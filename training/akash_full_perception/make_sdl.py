#!/usr/bin/env python3
"""Render the wallet-signable Akash SDL and local transfer helper."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import secrets

import yaml


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--persistent", action="store_true",
                        help="Mount a provider persistent volume at /workspace")
    parser.add_argument("--storage-class", default="beta3")
    parser.add_argument("--gpu-model", action="append", choices=("rtx3090", "rtx4090"),
                        help="Repeat to accept bids for more than one GPU model")
    parser.add_argument("--max-bid-uact", type=int, default=500)
    args = parser.parse_args()
    if args.max_bid_uact <= 0:
        parser.error("--max-bid-uact must be positive")
    gpu_models = list(dict.fromkeys(args.gpu_model or ["rtx3090"]))
    folder = args.package.resolve()
    facts = json.loads((folder / "summary.json").read_text())
    token = secrets.token_urlsafe(32)
    receiver = base64.b64encode((Path(__file__).parent / "receiver.py").read_bytes()).decode("ascii")
    launch = ("set -eu\n"
              "python -m pip install --no-cache-dir onnxruntime==1.23.2\n"
              "mkdir -p /workspace\n"
              f"printf %s '{receiver}' | base64 -d > /workspace/receiver.py\n"
              "exec python -u /workspace/receiver.py\n")
    sdl = {
        "version": "2.0",
        "services": {"yoli-train": {
            "image": "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime",
            "command": ["/bin/bash", "-lc"], "args": [launch],
            "env": [f"AKASH_UPLOAD_TOKEN={token}",
                    f"AKASH_CORE_SHA256={facts['archives']['akash-core.tar.gz']['sha256']}",
                    f"AKASH_REPLAYS_SHA256={facts['archives']['akash-replays.tar.gz']['sha256']}"],
            "expose": [{"port": 8080, "as": 80, "to": [{"global": True}],
                        "http_options": {"max_body_size": 100000000, "read_timeout": 600000,
                                         "send_timeout": 600000}}],
        }},
        "profiles": {
            "compute": {"yoli-train": {"resources": {
                "cpu": {"units": 4}, "memory": {"size": "16Gi"},
                "storage": ([{"size": "10Gi"}, {"name": "training-data", "size": "20Gi",
                             "attributes": {"persistent": True, "class": args.storage_class}}]
                            if args.persistent else {"size": "30Gi"}),
                "gpu": {"units": 1, "attributes": {"vendor": {
                    "nvidia": [{"model": model} for model in gpu_models]}}},
            }}},
            "placement": {"akash": {"pricing": {"yoli-train": {"denom": "uact", "amount": args.max_bid_uact}}}},
        },
        "deployment": {"yoli-train": {"akash": {"profile": "yoli-train", "count": 1}}},
    }
    if args.persistent:
        sdl["services"]["yoli-train"]["params"] = {
            "storage": {"training-data": {"mount": "/workspace", "readOnly": False}}
        }
    (folder / "deploy.yml").write_text(yaml.safe_dump(sdl, sort_keys=False, allow_unicode=True))
    helper = f'''#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Uso: $0 https://URL-DA-LEASE" >&2
  exit 2
fi
endpoint="${{1%/}}"
curl --fail-with-body --retry 3 -X PUT -H 'X-Upload-Token: {token}' --data-binary '@{folder / 'akash-core.tar.gz'}' "$endpoint/core"
curl --fail-with-body --retry 3 -X PUT -H 'X-Upload-Token: {token}' --data-binary '@{folder / 'akash-replays.tar.gz'}' "$endpoint/replays"
curl --fail-with-body -H 'X-Upload-Token: {token}' "$endpoint/status"
'''
    upload = folder / "upload.sh"
    upload.write_text(helper)
    upload.chmod(0o700)
    (folder / "deploy.yml").chmod(0o600)
    print(json.dumps({"sdl": str(folder / "deploy.yml"), "upload": str(upload),
                      "persistent": args.persistent,
                      "gpu_models": gpu_models,
                      "max_bid_uact_per_block": args.max_bid_uact,
                      "max_bid_act_per_hour_at_6s_blocks": args.max_bid_uact * 0.0006,
                      "note": "Actual provider bid must be checked before lease acceptance."}, indent=2))


if __name__ == "__main__":
    main()
