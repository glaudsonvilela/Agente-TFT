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



def test_coordinator_runs_shadow_and_swarm_in_parallel():
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)

        if request.url.path == "/v1/training/sessions":
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

        if request.url.path == "/v1/shadow/sessions":
            return httpx.Response(
                201,
                json={
                    "shadow_id": "shadow-1",
                    "training_session_id": "s1",
                    "episode_id": "episode-1",
                    "status": "active",
                    "created_at_ms": 1100,
                    "updated_at_ms": 1100,
                    "real_revision": 7,
                    "simulated_revision": 7,
                    "last_divergence": None,
                    "last_step": None,
                    "error": None,
                },
            )

        if request.url.path == "/v1/shadow/sessions/shadow-1/step":
            return httpx.Response(
                200,
                json={
                    "shadow_id": "shadow-1",
                    "training_session_id": "s1",
                    "episode_id": "episode-1",
                    "status": "active",
                    "created_at_ms": 1100,
                    "updated_at_ms": 1200,
                    "real_revision": 7,
                    "simulated_revision": 8,
                    "last_divergence": None,
                    "last_step": {
                        "simulated_revision": 8,
                        "reward": 0.25,
                    },
                    "error": None,
                },
            )

        if request.url.path == "/v1/training/jobs":
            payload = json.loads(request.content)
            return httpx.Response(
                202,
                json={
                    "request": payload,
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

            # Fix the deterministic episode id expected by the mock response.
            coordinator.episode_id = "episode-1"

            assert await coordinator.start_realtime_shadow(
                state=make_state(),
                now_ms=1100,
            )

            shadow_step = await coordinator.step_realtime_shadow(
                decision=make_decision(),
                now_ms=1200,
            )
            assert shadow_step is not None
            assert shadow_step["reward"] == 0.25

            swarm_job = await coordinator.submit_counterfactual_job(
                state=make_state(),
                decision=make_decision(),
                now_ms=1200,
                rollout_count=128,
            )
            assert swarm_job is not None
            assert swarm_job.status == "accepted"
        finally:
            await client.aclose()

    asyncio.run(scenario())

    assert "/v1/shadow/sessions" in seen_paths
    assert "/v1/shadow/sessions/shadow-1/step" in seen_paths
    assert "/v1/training/jobs" in seen_paths
