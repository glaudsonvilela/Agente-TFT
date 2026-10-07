from __future__ import annotations

import json

import hm.neural_service as neural


class FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self, limit=None):
        return self.payload

    def getheader(self, name):
        return None


class FakeConnection:
    def __init__(self, factory):
        self.factory = factory
        self.request_args = None

    def request(self, method, path, body=None, headers=None):
        self.request_args = (method, path, body, headers)
        self.factory.requests.append(self.request_args)

    def getresponse(self):
        if not self.factory.responses:
            raise AssertionError("unexpected connection response request")
        status, payload = self.factory.responses.pop(0)
        return FakeResponse(status, payload)

    def close(self):
        return None


class FakeFactory:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, host, port, timeout=None):
        assert host == "tft.bigbanana.io"
        assert port == 443
        return FakeConnection(self)


def test_connect_reuses_cached_installation_token(monkeypatch):
    monkeypatch.setattr(neural, "installation_id", lambda: "cache-install")
    with neural._TOKEN_CACHE_LOCK:
        neural._TOKEN_CACHE.clear()

    factory = FakeFactory([
        (200, {"token": "x" * 64, "expires_at_ms": 9_999_999_999_999, "protocol_version": 1}),
    ])
    first = neural.NeuralServiceClient(
        "https://tft.bigbanana.io",
        connection_factory=factory,
    )
    value = first.connect()
    assert value["token"] == "x" * 64
    assert len(factory.requests) == 1

    second = neural.NeuralServiceClient(
        "https://tft.bigbanana.io",
        connection_factory=factory,
    )
    cached = second.connect()
    assert cached["cached"] is True
    assert second.token == "x" * 64
    assert len(factory.requests) == 1


def test_upload_401_refreshes_token_and_retries_same_frame(monkeypatch):
    monkeypatch.setattr(neural, "installation_id", lambda: "refresh-install")
    with neural._TOKEN_CACHE_LOCK:
        neural._TOKEN_CACHE.clear()

    factory = FakeFactory([
        (401, {"detail": "expired neural token"}),
        (200, {"token": "n" * 64, "expires_at_ms": 9_999_999_999_999, "protocol_version": 1}),
        (200, {
            "protocol_version": 1,
            "neural_session_id": "session-1",
            "frame_id": 7,
            "source_ms": 2000,
            "status": "queued",
            "observations": [],
        }),
    ])
    client = neural.NeuralServiceClient(
        "https://tft.bigbanana.io",
        connection_factory=factory,
    )
    client.token = "o" * 64
    client.expires_at_ms = 9_999_999_999_999

    result = client.upload_frame(
        "session-1",
        frame_id=7,
        source_ms=2000,
        width=1920,
        height=1080,
        image=b"jpeg-fixture",
        content_type="image/jpeg",
        capture_role="post_match_learning_evidence",
    )
    assert result["status"] == "queued"
    assert client.token == "n" * 64
    assert len(factory.requests) == 3

    first_upload = factory.requests[0]
    retry_upload = factory.requests[2]
    assert first_upload[0:2] == retry_upload[0:2]
    assert first_upload[2] == retry_upload[2] == b"jpeg-fixture"
    assert first_upload[3]["Authorization"] == "Bearer " + "o" * 64
    assert retry_upload[3]["Authorization"] == "Bearer " + "n" * 64
