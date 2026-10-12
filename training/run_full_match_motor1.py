"""Read one complete replay through the same Motor 1 -> Rust Motor 2 runtime.

This records observations and unresolved candidates. It does not label player
actions or claim that a policy learned from the match.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/hud_mapper"), str(ROOT / "apps/e1_replay")]

from hm.runtime_app import runtime_paths  # noqa: E402
from hm.runtime_session import HM4RuntimeSession  # noqa: E402
from hm.session import Options  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.video.is_file():
        parser.error("Complete replay does not exist")
    # The runtime's high-cadence item and bar lanes are opt-in. A full-match
    # review must opt in explicitly or its viewer silently reports zero events.
    os.environ["AGENTE_TFT_UBUNTU_MVP"] = "1"
    paths = runtime_paths()
    paths.update(ffmpeg="ffmpeg", ffprobe="ffprobe")
    options = Options(**paths, video=str(args.video),
                      output=str(args.output), model="", seconds=2221,
                      map_hz=2, reader_hz=2, sample_hz=.2,
                      max_samples=600, max_bytes=2 * 1024**3,
                      dataset_only=True, replay_review=True,
                      board_hub_enabled=True)
    session = HM4RuntimeSession(options)
    # A whole match emits far more structured evidence than a short live run.
    # The default 128 MiB log cap would silently truncate late-game readings.
    session.store.max_log_bytes = 2 * 1024**3
    session.start()
    print(json.dumps({"event": "started", "session": session.id,
                      "output": str(args.output)}), flush=True)
    while not session.done.wait(5):
        print(json.dumps({"event": "progress", "phase": session.phase,
                          "counts": dict(session.counts), "error": session.error}), flush=True)
    result = session.finish()
    print(json.dumps({"event": "finished", "result": result},
                     ensure_ascii=False), flush=True)
    if result.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
