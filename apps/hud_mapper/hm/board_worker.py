"""Resident Rust board geometry process with paced trait-panel OCR."""

from __future__ import annotations

import os

from e1.protocol import NativeWorker


class BoardWorker:
    def __init__(self, binary, configs, log=None, tesseract='tesseract'):
        environment = dict(os.environ, AGENTE_TFT_BOARD_ONLY="1")
        self.worker = NativeWorker(binary, configs, tesseract=tesseract, log=log, env=environment)
        if self.worker.ready.get("board_only") is not True:
            self.close()
            raise ValueError(
                "Native reader lacks independent board capability; update the core"
            )

    def observe(self, frame, calibrate=False):
        header = dict(
            id=frame.id,
            source_ms=round(frame.pts_ms),
            width=frame.width,
            height=frame.height,
            bytes=len(frame.rgb),
        )
        if calibrate:
            result = self.worker.request(dict(header, op="reference"), frame.rgb)
            if result.get("reference_ready") is not True:
                raise ValueError("Board calibration failed")
        answer = self.worker.request(dict(header, op="frame"), frame.rgb)
        if answer.get("source_ms") != round(frame.pts_ms) or not isinstance(
            answer.get("board"), dict
        ):
            raise ValueError("Board result is not bound to the submitted frame")
        board = answer["board"]
        if isinstance(answer.get("trait_panel"), dict):
            board["trait_panel"] = answer["trait_panel"]
        if isinstance(answer.get("opponent_panel"), dict):
            board["opponent_panel"] = answer["opponent_panel"]
        return board

    def close(self):
        self.worker.close()


class FastMarkerWorker:
    """Independent Rust geometry tracker; never assigns champion names or ownership."""

    def __init__(self, binary, configs, log=None):
        environment = dict(os.environ, AGENTE_TFT_MARKERS_ONLY="1")
        self.worker = NativeWorker(binary, configs, log=log, env=environment)
        if self.worker.ready.get("fast_marker_tracking") is not True:
            self.close()
            raise ValueError("Native reader lacks fast marker tracking")

    def observe(self, frame):
        header = dict(op="markers", id=frame.id, epoch=frame.epoch,
                      source_ms=round(frame.pts_ms), width=frame.width,
                      height=frame.height, bytes=len(frame.rgb))
        answer = self.worker.request(header, frame.rgb, timeout=5)
        if (answer.get("source_ms") != header["source_ms"] or
                answer.get("origin") != "rust_fast_marker_tracker_v1" or
                not isinstance(answer.get("markers"), list)):
            raise ValueError("Marker result is not bound to the submitted frame")
        return answer

    def close(self):
        self.worker.close()
