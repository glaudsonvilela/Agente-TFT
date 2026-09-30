from __future__ import annotations

import json

import httpx
import pytest

from core.remote_training import RemoteTrainingClient, RemoteTrainingConfig
from schemas.contracts import (
    DecisionPacket,
    GameState,
    HoldEconAction,
    MatchPhase,
    PlayerState,
)


def state(revision: int = 7) -> GameState:
    return GameState(
        revision=revision,
        phase=MatchPhase.PLANNING,
        observed_at_ms=1000,
        player=PlayerState(),
        overall_confidence=0.95,
    )


def decision(revision: int = 7) -> DecisionPacket:
    return DecisionPacket(
        state_revision=revision,
        action=HoldEconAction(),
        confidence=0.80,
    )


@pytest.mark.asyncio
async def test_client_creates_session_and_submits_structured_job():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/sessions"):
            return httpx.Response(
                201,
                json={
                    "session_id": "session-1",
                    "created_at_ms": 1000,
                    "client_id": "local",
                    "profile": "lab",
                    "active": True,
                },
            )

        if request.url.path.endswith("/jobs"):
            payload = json.loads(request.content)
            return httpx.Response(
                202,
                json={
                    "request": payload,
                    "status": "accepted",
                    "accepted_at_ms": 1100,
                    "updated_at_ms": 1100,
                    "result": None,
                    "error": None,
                },
            )

        raise AssertionError(request.url)

    client = RemoteTrainingClient(
        RemoteTrainingConfig(
            base_url="https://trainer.example",
            client_id="local",
        ),
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.create_session(requested_at_ms=1000)
        record = await client.submit_decision_job(
            state=state(),
            decision=decision(),
            created_at_ms=1100,
            job_id="job-1",
            episode_id="episode-1",
            scripted_bots=("econ", "aggressive"),
        )
    finally:
        await client.aclose()

    assert record.status == "accepted"
    payload = record.request
    assert payload["state"]["revision"] == 7
    assert payload["decision"]["state_revision"] == 7
    assert payload["opponent_pool"]["scripted_bots"] == ["econ", "aggressive"]
    assert "mouse" not in json.dumps(payload).lower()
    assert "keyboard" not in json.dumps(payload).lower()


@pytest.mark.asyncio
async def test_revision_mismatch_is_rejected_before_network():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            201,
            json={
                "session_id": "session-1",
                "created_at_ms": 1000,
                "client_id": "local",
                "profile": "lab",
                "active": True,
            },
        )

    client = RemoteTrainingClient(
        RemoteTrainingConfig(base_url="https://trainer.example"),
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.create_session(requested_at_ms=1000)
        with pytest.raises(ValueError):
            await client.submit_decision_job(
                state=state(8),
                decision=decision(7),
                created_at_ms=1100,
            )
    finally:
        await client.aclose()

    assert calls == 1
