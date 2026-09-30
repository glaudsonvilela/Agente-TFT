from __future__ import annotations

import asyncio
import json

import httpx

from core.remote_training import RemoteTrainingClient, RemoteTrainingConfig
from core.training_coordinator import (
    RemoteTrainingCoordinator,
    RemoteTrainingPhase,
)
from schemas.contracts import (
    DecisionPacket,
    GameState,
    HoldEconAction,
    MatchPhase,
    PlayerState,
)


def make_state() -> GameState:
    return GameState(
        revision=7,
        phase=MatchPhase.PLANNING,
        observed_at_ms=1000,
        player=PlayerState(),
        overall_confidence=0.95,
    )


def make_decision() -> DecisionPacket:
    return DecisionPacket(
        state_revision=7,
        action=HoldEconAction(),
        confidence=0.8,
    )


def test_matchmaking_trigger_starts_remote_training_session():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "session_id": "s1",
                "created_at_ms": 1000,
                "client_id": "local",
                "profile": "lab",
                "active": True,
            },
        )

    async def scenario():
        client = RemoteTrainingClient(
            RemoteTrainingConfig(
                base_url="https://trainer.example",
                client_id="local",
            ),
            transport=httpx.MockTransport(handler),
        )
        coordinator = RemoteTrainingCoordinator(client)
        try:
            await coordinator.on_matchmaking_requested(now_ms=1000)
            assert coordinator.phase == RemoteTrainingPhase.WAITING_FOR_MATCH
            assert coordinator.episode_id is not None
            coordinator.on_match_detected()
            assert coordinator.phase == RemoteTrainingPhase.MATCH_ACTIVE
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_remote_failure_degrades_without_blocking_local_mode():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "offline"})

    async def scenario():
        client = RemoteTrainingClient(
            RemoteTrainingConfig(base_url="https://trainer.example"),
            transport=httpx.MockTransport(handler),
        )
        coordinator = RemoteTrainingCoordinator(client)
        try:
            await coordinator.on_matchmaking_requested(now_ms=1000)
            assert coordinator.phase == RemoteTrainingPhase.DEGRADED_LOCAL_ONLY
            assert coordinator.last_error is not None
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_shadow_job_contains_no_remote_control_primitive():
    seen_payload = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_payload
        if request.url.path.endswith("/sessions"):
            return httpx.Response(
                201,
                json={
                    "session_id": "s1",
                    "created_at_ms": 1000,
                    "client_id": "local",
                    "profile": "lab",
                    "active": True,
                },
            )

        if request.url.path.endswith("/jobs"):
            seen_payload = json.loads(request.content)
            return httpx.Response(
                202,
                json={
                    "request": seen_payload,
                    "status": "accepted",
                    "accepted_at_ms": 1200,
                    "updated_at_ms": 1200,
                    "result": None,
                    "error": None,
                },
            )
        raise AssertionError(request.url)

    async def scenario():
        client = RemoteTrainingClient(
            RemoteTrainingConfig(
                base_url="https://trainer.example",
                client_id="local",
            ),
            transport=httpx.MockTransport(handler),
        )
        coordinator = RemoteTrainingCoordinator(client)
        try:
            await coordinator.on_matchmaking_requested(now_ms=1000)
            coordinator.on_match_detected()
            record = await coordinator.submit_shadow_decision(
                state=make_state(),
                decision=make_decision(),
                now_ms=1200,
                scripted_bots=("econ",),
            )
            assert record is not None
        finally:
            await client.aclose()

    asyncio.run(scenario())

    serialized = json.dumps(seen_payload).lower()
    for forbidden in ("mouse", "keyboard", "click", "desktop", "process_id"):
        assert forbidden not in serialized
