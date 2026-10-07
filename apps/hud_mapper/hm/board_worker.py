"""Resident Rust geometry process with OCR explicitly disabled."""

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
        return board

    def close(self):
        self.worker.close()
