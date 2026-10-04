"""Exercise the Windows-side VM client against the real Linux core in Docker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from hm45_vm_client import VMCore, RemoteBoardHub, RemoteNativeWorker, RemoteObserver


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--output", type=Path, default=Path("hm45-vm-e2e.json"))
    args = parser.parse_args()
    if args.sample:
        with Image.open(args.sample) as source:
            image = source.convert("RGB")
            if image.size != (1920, 1080):
                raise ValueError("O teste exige um quadro 1920×1080.")
            rgb = image.tobytes()
    else:
        rgb = bytes(1920 * 1080 * 3)
    frame = SimpleNamespace(id=1, width=1920, height=1080, rgb=rgb, pts_ms=0)
    command = ["docker", "run", "--rm", "--network=host", "--memory=768m", "--cpus=2",
               "-i", "agente-tft-hm45-core:0.6.1", "serve"]
    core = VMCore("unused", args.output.with_suffix(".stderr.log"), command=command)
    try:
        model = RemoteObserver(core, "build/hm4-live-assets/models/deployment-candidate.json").observe(frame)
        request = dict(op="frame", id=frame.id, source_ms=0, width=frame.width, height=frame.height)
        reader = RemoteNativeWorker(core, "reader").request(request, rgb)
        hp = RemoteNativeWorker(core, "hp").request(request, rgb)
        hub = RemoteBoardHub(core).observe(frame, reader.get("board"))
        assert model["frame_id"] == reader["id"] == hp["id"] == frame.id
        assert len(model["regions"]) == 2 and "snapshot" in hub and "regions" in hub
        assert all(value["vm_transport"]["codec"] == "rgb8" for value in (reader, hp, hub))
        result = {"sample": str(args.sample) if args.sample else "synthetic_black",
                  "image_size": [frame.width, frame.height],
                  "model": model["vm_transport"], "reader": reader["vm_transport"],
                  "hp": hp["vm_transport"], "hub": hub["vm_transport"],
                  "board_read_present": bool(reader.get("board")),
                  "health": "L3/OCR/HP/B4 frame identity and lossless TCP OK"}
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("HM45_VM_E2E=" + json.dumps(result))
    finally:
        core.close()


if __name__ == "__main__":
    main()
