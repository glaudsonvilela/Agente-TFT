"""Causal sequence imitation from Motor 2 observations and video actions.

Every observation in a complete match advances the recurrent state. Only an
action established from the *subsequent* video transition supplies an action
target. Future HUD values train an auxiliary forecast, never a claim that the
demonstrated action caused the match result. Missing actions/candidates stay
missing; the Rust-selected option is never used as an expert label.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F


STATE_START = "gold"
STATE_END = "phase_late"


@dataclass(frozen=True)
class Decision:
    match_id: str
    source_ms: int
    state: list[float]
    candidates: list[list[float]]
    candidate_keys: list[str]
    chosen: int | None
    future_hp_delta: float | None
    future_gold_delta: float | None


def _number(value: Any) -> float | None:
    if type(value) in (int, float) and -300 <= value <= 300:
        return float(value)
    return None


def align_video_actions(frames: list[dict], labels: list[dict], *,
                        max_before_ms: int = 2000) -> dict[int, dict]:
    """Bind an independently observed action to the latest earlier Motor 2 frame.

    Video evidence must carry a real action time and source hash. A label after
    a camera cut, with no earlier state, or absent from Rust candidates cannot
    silently become a training example.
    """
    if max_before_ms < 1:
        raise ValueError("positive alignment limit required")
    ordered = sorted(frames, key=lambda row: row["source_ms"])
    if any(a["source_ms"] >= b["source_ms"] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("Motor 2 time must be unique and increasing")
    times = [row["source_ms"] for row in ordered]
    aligned: dict[int, dict] = {}
    for label in labels:
        action_ms = label.get("action_ms")
        if type(action_ms) is not int or not isinstance(label.get("source_sha256"), str) \
                or len(label["source_sha256"]) != 64 or not label.get("evidence_id"):
            raise ValueError("action time, source hash and video evidence required")
        position = bisect_left(times, action_ms) - 1
        if position < 0 or action_ms - times[position] > max_before_ms:
            raise ValueError(f"no causal Motor 2 state before {action_ms}")
        frame = ordered[position]
        if frame.get("match_id") != label.get("match_id") or \
                frame.get("source_video_sha256") != label["source_sha256"]:
            raise ValueError("video action and Motor 2 source differ")
        if frame.get("scene_status") != "stable_planning":
            raise ValueError("camera/scene is not a verified planning view")
        options = frame.get("candidates") or []
        chosen_key = label.get("chosen_decision_key")
        keys = [option.get("decision_key") for option in options]
        if chosen_key not in keys or len(set(keys)) != len(keys):
            raise ValueError(f"observed action absent or ambiguous in Motor 2: {chosen_key}")
        frame_id = frame.get("frame_id")
        if type(frame_id) is not int or frame_id in aligned:
            raise ValueError("multiple actions need separately captured pre-action states")
        aligned[frame_id] = label
    return aligned


def _state_indices(feature_names: list[str]) -> list[int]:
    if STATE_START not in feature_names or STATE_END not in feature_names:
        raise ValueError("Motor 2 state fields missing")
    first, last = feature_names.index(STATE_START), feature_names.index(STATE_END)
    if first > last or len(set(feature_names)) != len(feature_names):
        raise ValueError("invalid Motor 2 feature schema")
    return list(range(first, last + 1))


def make_decisions(frames: list[dict], labels: list[dict], *,
                   future_horizon_ms: int = 60000) -> list[Decision]:
    if not frames or future_horizon_ms < 1:
        raise ValueError("nonempty episode and positive horizon required")
    ordered = sorted(frames, key=lambda row: row["source_ms"])
    feature_names = ordered[0].get("feature_names")
    if not isinstance(feature_names, list):
        raise ValueError("Motor 2 feature schema required")
    state_at = _state_indices(feature_names)
    aligned = align_video_actions(ordered, labels) if labels else {}
    times = [row["source_ms"] for row in ordered]
    match_id = ordered[0].get("match_id")
    if any(row.get("match_id") != match_id or row.get("feature_names") != feature_names
           for row in ordered):
        raise ValueError("one complete match and one feature schema required")
    output = []
    for index, frame in enumerate(ordered):
        options = frame.get("candidates") or []
        if not options:
            raise ValueError("Motor 2 must supply candidates at each decision state")
        vectors = [row.get("features") for row in options]
        if any(not isinstance(vector, list) or len(vector) != len(feature_names)
               or any(_number(value) is None for value in vector) for vector in vectors):
            raise ValueError("invalid candidate feature vector")
        state = [float(vectors[0][column]) for column in state_at]
        if any([float(vector[column]) for column in state_at] != state for vector in vectors[1:]):
            raise ValueError("candidate state changed within the same observation")
        keys = [row.get("decision_key") for row in options]
        if any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys):
            raise ValueError("ambiguous candidate identities")
        label = aligned.get(frame.get("frame_id"))
        chosen = keys.index(label["chosen_decision_key"]) if label else None
        future_index = bisect_left(times, frame["source_ms"] + future_horizon_ms,
                                   lo=index + 1)
        future = ordered[future_index] if future_index < len(ordered) else None
        current_state = frame.get("whole_state") or {}
        later_state = (future or {}).get("whole_state") or {}
        hp0, hp1 = _number(current_state.get("hp")), _number(later_state.get("hp"))
        gold0, gold1 = _number(current_state.get("gold")), _number(later_state.get("gold"))
        output.append(Decision(match_id, frame["source_ms"], state,
                               [[float(value) for value in vector] for vector in vectors],
                               keys, chosen, hp1 - hp0 if hp0 is not None and hp1 is not None else None,
                               gold1 - gold0 if gold0 is not None and gold1 is not None else None))
    if len(aligned) != sum(row.chosen is not None for row in output):
        raise AssertionError("a video label was lost")
    return output


class SequencePolicy(nn.Module):
    """A recurrent match memory, candidate scorer and future-state forecast."""

    def __init__(self, state_size: int, candidate_size: int, hidden: int = 64):
        super().__init__()
        self.memory = nn.GRUCell(state_size, hidden)
        self.score = nn.Sequential(nn.Linear(hidden + candidate_size, hidden),
                                   nn.ReLU(), nn.Linear(hidden, 1))
        self.forecast = nn.Linear(hidden, 2)
        self.hidden = hidden

    def step(self, state: torch.Tensor, candidates: torch.Tensor,
             memory: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        memory = self.memory(state, memory)
        repeated = memory.expand(candidates.shape[0], -1)
        logits = self.score(torch.cat((repeated, candidates), dim=1)).squeeze(-1)
        return logits, self.forecast(memory).squeeze(0), memory


def train_episode(decisions: list[Decision], model: SequencePolicy, optimizer,
                  *, chunk_size: int = 128) -> dict:
    """Train in chronological chunks; unlabelled frames still update memory."""
    if not decisions or chunk_size < 1:
        raise ValueError("nonempty chronological episode required")
    if not any(row.chosen is not None for row in decisions):
        raise ValueError("video action labels required; future HUD prediction is not imitation")
    if any(a.source_ms >= b.source_ms for a, b in zip(decisions, decisions[1:])):
        raise ValueError("episode time must increase")
    model.train()
    memory = torch.zeros(1, model.hidden)
    actions, forecasts, chunks = 0, 0, 0
    for offset in range(0, len(decisions), chunk_size):
        losses = []
        for row in decisions[offset:offset + chunk_size]:
            state = torch.tensor(row.state, dtype=torch.float32).unsqueeze(0)
            candidates = torch.tensor(row.candidates, dtype=torch.float32)
            logits, forecast, memory = model.step(state, candidates, memory)
            if row.chosen is not None:
                losses.append(F.cross_entropy(logits.unsqueeze(0),
                                              torch.tensor([row.chosen])))
                actions += 1
            for position, value in enumerate((row.future_hp_delta, row.future_gold_delta)):
                if value is not None:
                    losses.append(0.01 * F.smooth_l1_loss(forecast[position],
                                                            torch.tensor(value / 100.0)))
                    forecasts += 1
        if losses:
            optimizer.zero_grad()
            torch.stack(losses).mean().backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            chunks += 1
        memory = memory.detach()
    return {"matched_video_actions": actions, "future_hud_targets": forecasts,
            "optimizer_chunks": chunks, "macro_target_is_forecast_not_causal_reward": True}


def save_checkpoint(model: SequencePolicy, path: Path, metadata: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save({"state_dict": model.state_dict(), "metadata": metadata}, temporary)
    temporary.replace(path)
