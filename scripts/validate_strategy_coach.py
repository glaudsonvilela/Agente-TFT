"""Probe the shipped decision/text/voice contract on held-out structured states.

Does not contact ElevenLabs, observe pixels, play audio, or validate Windows.
Uses only the standard library and the packaged coach modules.
"""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/hud_mapper")]

from hm.replay_coach import coach_prompt
from hm.replay_decision import ReplayDecisionEngine


def probe(dataset, limit=100):
    engine = ReplayDecisionEngine(str(ROOT / "configs"))
    if engine.strategic_coach.model is None:
        raise ValueError("no evaluated ranker loaded")
    times, examples, families = [], {}, Counter()
    counts = Counter()
    with gzip.open(dataset, "rt") as stream:
        for line in stream:
            episode = json.loads(line)
            if episode["split"] != "test":
                continue
            state = episode["state"]
            # Exercise the pixel-reader contract with explicitly synthetic values.
            answer = dict(
                origin="observed_pixels",
                source_ms=1000,
                hud=[
                    dict(
                        field="gold",
                        value=state["gold"],
                        confidence=0.99,
                        status="single_frame_observation",
                    )
                ],
            )
            start = time.perf_counter()
            result = engine.evaluate(answer, strategy_state=state)
            tip = coach_prompt(result)
            times.append((time.perf_counter() - start) * 1000)
            for row in result["strategic_coaching"]["recommendations"]:
                families[row["family"]] += 1
                examples.setdefault(row["family"], row["text"])
            counts["actionable"] += int(tip["actionable"])
            counts["speech_payloads"] += int(bool(tip.get("speech_text")))
            if len(times) >= limit:
                break
    if not times:
        raise ValueError("no held-out states")
    return dict(
        schema_version=1,
        scope="synthetic_structured_state_to_text_and_voice_payload",
        states=len(times),
        counts=dict(counts),
        families=dict(families),
        example_text=examples,
        model_identity=engine.strategic_coach.model.identity,
        latency_ms=dict(
            p50=statistics.median(times),
            p95=sorted(times)[int((len(times) - 1) * 0.95)],
            max=max(times),
        ),
        torch_imported="torch" in sys.modules,
        numpy_imported="numpy" in sys.modules,
        neural_ranker_loaded=True,
        live_vision_connected=False,
        physical_audio_tested=False,
        windows_field_test=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = probe(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
