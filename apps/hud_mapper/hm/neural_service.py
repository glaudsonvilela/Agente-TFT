"""HTTPS client for the server-resident TFT neural service.

No model weights or administrative server secrets are stored in the Windows
application. The client obtains a short-lived installation token, uploads
bounded evidence, and receives structured neural results.
"""
from __future__ import annotations

import hashlib
import http.client
import json
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlencode, urlsplit

from .voice_service import installation_id


class NeuralServiceError(RuntimeError):
    pass


_TOKEN_CACHE_LOCK = threading.Lock()
_TOKEN_CACHE: dict[tuple[str, int, str], tuple[str, int]] = {}


def _cached_token(host: str, port: int, installation: str) -> tuple[str, int] | None:
    now_ms = time.time_ns() // 1_000_000
    key = (host, port, installation)
    with _TOKEN_CACHE_LOCK:
        value = _TOKEN_CACHE.get(key)
        if value is None:
            return None
        token, expires_at_ms = value
        if expires_at_ms <= now_ms + 60_000:
            _TOKEN_CACHE.pop(key, None)
            return None
        return token, expires_at_ms


def _store_token(host: str, port: int, installation: str, token: str, expires_at_ms: int) -> None:
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE[(host, port, installation)] = (token, expires_at_ms)


def _service_url(value: str | None = None) -> str:
    if value is not None:
        return value
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    try:
        doc = json.loads((root / "configs/services/neural.json").read_text(encoding="utf-8"))
        return str(doc["service_url"])
    except (OSError, ValueError, KeyError):
        raise NeuralServiceError("Serviço neural remoto ainda não configurado.") from None


def service_address(value: str | None = None) -> tuple[str, int]:
    url = urlsplit(_service_url(value))
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
    ):
        raise NeuralServiceError("Endereço HTTPS do serviço neural inválido.")
    return url.hostname, url.port or 443


class NeuralServiceClient:
    def __init__(
        self,
        service_url: str | None = None,
        *,
        connection_factory=http.client.HTTPSConnection,
    ):
        self.host, self.port = service_address(service_url)
        self.connection_factory = connection_factory
        self.installation_id = installation_id()
        self.token: str | None = None
        self.expires_at_ms: int | None = None

    def _json_request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        auth: bool = True,
        timeout: float = 8,
        _retry_auth: bool = True,
    ) -> dict:
        connection = self.connection_factory(self.host, self.port, timeout=timeout)
        try:
            body = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if auth:
                if not self.token:
                    raise NeuralServiceError("Sessão neural não conectada.")
                headers["Authorization"] = "Bearer " + self.token
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise NeuralServiceError("Resposta neural excedeu o limite.")
            if response.status == 401 and auth and _retry_auth:
                self.connect(force_refresh=True)
                return self._json_request(
                    method,
                    path,
                    payload,
                    auth=auth,
                    timeout=timeout,
                    _retry_auth=False,
                )
            if response.status not in (200, 201, 202):
                raise NeuralServiceError(f"Servidor neural indisponível (HTTP {response.status}).")
            value = json.loads(raw or b"{}")
            if not isinstance(value, dict):
                raise NeuralServiceError("Resposta neural inválida.")
            return value
        except NeuralServiceError:
            raise
        except Exception:
            raise NeuralServiceError("Falha de conexão com o servidor neural.") from None
        finally:
            connection.close()

    def connect(self, *, force_refresh: bool = False) -> dict:
        if not force_refresh:
            cached = _cached_token(self.host, self.port, self.installation_id)
            if cached is not None:
                self.token, self.expires_at_ms = cached
                return {
                    "token": self.token,
                    "expires_at_ms": self.expires_at_ms,
                    "protocol_version": 1,
                    "cached": True,
                }

        value = self._json_request(
            "POST",
            "/v1/neural/client-session",
            {"installation_id": self.installation_id},
            auth=False,
        )
        token = value.get("token")
        expires = value.get("expires_at_ms")
        if not isinstance(token, str) or len(token) < 32 or not isinstance(expires, int):
            raise NeuralServiceError("Servidor neural devolveu sessão inválida.")
        self.token = token
        self.expires_at_ms = expires
        _store_token(self.host, self.port, self.installation_id, token, expires)
        return value

    def create_session(
        self,
        *,
        match_id: str,
        created_at_ms: int,
        patch: str | None,
        set_key: str | None,
        capture_policy: str,
        metadata: dict | None = None,
    ) -> dict:
        return self._json_request(
            "POST",
            "/v1/neural/sessions",
            {
                "client_id": self.installation_id,
                "match_id": match_id,
                "created_at_ms": created_at_ms,
                "patch": patch,
                "set_key": set_key,
                "capture_policy": capture_policy,
                "metadata": metadata or {},
            },
        )

    def upload_frame(
        self,
        neural_session_id: str,
        *,
        frame_id: int,
        source_ms: int,
        width: int,
        height: int,
        image: bytes,
        content_type: str,
        capture_role: str,
        capture_event: str | None = None,
        _retry_auth: bool = True,
    ) -> dict:
        if not self.token:
            raise NeuralServiceError("Sessão neural não conectada.")
        digest = hashlib.sha256(image).hexdigest()
        query = urlencode(
            {
                "frame_id": frame_id,
                "source_ms": source_ms,
                "width": width,
                "height": height,
                "image_sha256": digest,
                "capture_role": capture_role,
                **({"capture_event": capture_event} if capture_event else {}),
            }
        )
        connection = self.connection_factory(self.host, self.port, timeout=12)
        try:
            connection.request(
                "POST",
                f"/v1/neural/sessions/{neural_session_id}/frames?{query}",
                image,
                {
                    "Authorization": "Bearer " + self.token,
                    "Content-Type": content_type,
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise NeuralServiceError("Resposta de inferência excedeu o limite.")
            if response.status == 401 and _retry_auth:
                self.connect(force_refresh=True)
                return self.upload_frame(
                    neural_session_id,
                    frame_id=frame_id,
                    source_ms=source_ms,
                    width=width,
                    height=height,
                    image=image,
                    content_type=content_type,
                    capture_role=capture_role,
                    capture_event=capture_event,
                    _retry_auth=False,
                )
            if response.status not in (200, 201, 202):
                raise NeuralServiceError(f"Upload neural recusado (HTTP {response.status}).")
            value = json.loads(raw or b"{}")
            if not isinstance(value, dict):
                raise NeuralServiceError("Resposta de inferência inválida.")
            return value
        except NeuralServiceError:
            raise
        except Exception:
            raise NeuralServiceError("Falha ao enviar evidência ao servidor neural.") from None
        finally:
            connection.close()

    def seal(
        self,
        neural_session_id: str,
        *,
        sealed_at_ms: int,
        match_end_reason: str,
        capture_manifest_sha256: str,
        frame_count: int,
        metadata: dict | None = None,
    ) -> dict:
        return self._json_request(
            "POST",
            f"/v1/neural/sessions/{neural_session_id}/seal",
            {
                "sealed_at_ms": sealed_at_ms,
                "match_end_reason": match_end_reason,
                "capture_manifest_sha256": capture_manifest_sha256,
                "frame_count": frame_count,
                "metadata": metadata or {},
            },
        )

    def learning_status(self, neural_session_id: str) -> dict:
        return self._json_request(
            "GET",
            f"/v1/neural/sessions/{neural_session_id}/learning",
            {},
        )


    def champion_manifest(self, channel: str = "stable") -> dict:
        if channel not in {"stable", "shadow"}:
            raise NeuralServiceError("Canal de modelo neural inválido.")
        return self._json_request(
            "GET",
            f"/v1/neural/champion?channel={channel}",
            {},
        )

    def download_champion_package(
        self,
        channel: str,
        generation: int,
        destination: Path,
        *,
        max_bytes: int = 512 * 1024 * 1024,
        _retry_auth: bool = True,
    ) -> dict:
        if not self.token:
            raise NeuralServiceError("Sessão neural não conectada.")
        connection = self.connection_factory(self.host, self.port, timeout=30)
        path = f"/v1/neural/champion/package/{channel}/{generation}"
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Accept": "application/zip",
                },
            )
            response = connection.getresponse()
            if response.status == 401 and _retry_auth:
                self.connect(force_refresh=True)
                return self.download_champion_package(
                    channel,
                    generation,
                    destination,
                    max_bytes=max_bytes,
                    _retry_auth=False,
                )
            if response.status != 200:
                raise NeuralServiceError(
                    f"Download da rede neural recusado (HTTP {response.status})."
                )
            expected = response.getheader("X-TFT-Package-SHA256")
            if not isinstance(expected, str) or len(expected) != 64:
                raise NeuralServiceError("Servidor não informou hash do pacote neural.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".partial")
            total = 0
            h = hashlib.sha256()
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise NeuralServiceError("Pacote neural excedeu o limite local.")
                    h.update(chunk)
                    handle.write(chunk)
                handle.flush()
            digest = h.hexdigest()
            if digest != expected:
                temporary.unlink(missing_ok=True)
                raise NeuralServiceError("Hash do pacote neural não confere.")
            temporary.replace(destination)
            return {
                "sha256": digest,
                "bytes": total,
                "path": str(destination),
            }
        except NeuralServiceError:
            raise
        except Exception:
            raise NeuralServiceError("Falha ao baixar atualização neural.") from None
        finally:
            connection.close()
