"""Package the audited 1080p state experiment for a persistent Akash lease."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import secrets
import tarfile

from PIL import Image
import yaml

from training.experimental_video_state_supervisor import preflight


CHUNK_SIZE = 20_000_000
CODE_FILES = (
    "training/__init__.py",
    "training/akash_policy_supervisor.py",
    "training/experimental_video_state.py",
    "training/experimental_video_state_supervisor.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package(repo: Path, corpus: Path, index: Path, output: Path,
            branches: Path) -> dict:
    frames = corpus / "experimental-frames-15s"
    gate = preflight(index, frames, "2894958056", branches)
    if any(count < 10 for split in gate["comparable_heldout_readings"].values()
           for count in split.values()):
        raise ValueError("at least ten comparable readings per held-out field required")
    index_data = json.loads(index.read_text())
    corpus_facts = json.loads((corpus / "manifest.json").read_text())
    if index_data.get("target_patch") != "18.4B":
        raise ValueError("unexpected patch target")
    if {row["match_id"] for row in index_data["matches"]} != {
            row["match_id"] for row in corpus_facts["matches"]}:
        raise ValueError("state index and complete-match corpus disagree")
    referenced = []
    for match in index_data["matches"]:
        for row in match["observations"]:
            frame = frames / match["match_id"] / row["frame"]
            with Image.open(frame) as image:
                if image.size != (1920, 1080):
                    raise ValueError(f"non-1080p frame: {frame}")
            referenced.append(frame)
    if len(referenced) < 500:
        raise ValueError("too few verified complete-match frame observations")
    economy = json.loads(branches.read_text())
    if economy.get("full_match_simulator_ready") is not False or economy.get("synthetic_policy_labels_created") != 0:
        raise ValueError("economy branch report must remain separate from policy labels")
    output.mkdir(parents=True, exist_ok=True)
    if (output / "deploy.yml").exists():
        raise ValueError("package directory already has a deployment; use a fresh directory")
    for stale in output.glob("part-[0-9][0-9][0-9][0-9]"):
        stale.unlink()
    archive = output / "input.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(index, arcname="state-index.json")
        tar.add(corpus / "manifest.json", arcname="corpus-manifest.json")
        tar.add(branches, arcname="economy-branches.json")
        for relative in CODE_FILES:
            tar.add(repo / relative, arcname=f"code/{relative}")
        for frame in referenced:
            tar.add(frame, arcname="frames/" + str(frame.relative_to(frames)))
    part_hashes = []
    with archive.open("rb") as source:
        for i in range((archive.stat().st_size + CHUNK_SIZE - 1) // CHUNK_SIZE):
            path = output / f"part-{i:04d}"
            path.write_bytes(source.read(CHUNK_SIZE))
            part_hashes.append(sha256(path))
    token = secrets.token_urlsafe(32)
    receiver = base64.b64encode((repo / "training/experimental_video_state_receiver.py").read_bytes()).decode("ascii")
    launch = ("set -eu\n"
              "mkdir -p /workspace\n"
              f"printf %s '{receiver}' | base64 -d > /workspace/receiver.py\n"
              "exec python -u /workspace/receiver.py\n")
    service = "tft-study"
    sdl = {
        "version": "2.0", "services": {service: {
            "image": "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime",
            "command": ["/bin/bash", "-lc"], "args": [launch],
            "env": [f"TFT_UPLOAD_TOKEN={token}",
                    f"TFT_PART_SHA256_JSON={json.dumps(part_hashes, separators=(',', ':'))}",
                    f"TFT_BUNDLE_SHA256={sha256(archive)}"],
            "expose": [{"port": 8080, "as": 80, "to": [{"global": True}],
                        "http_options": {"max_body_size": 24000000,
                                         "read_timeout": 600000, "send_timeout": 600000}}],
            "params": {"storage": {"training-data": {"mount": "/workspace",
                                                     "readOnly": False}}},
        }},
        "profiles": {
            "compute": {service: {"resources": {
                "cpu": {"units": 4}, "memory": {"size": "16Gi"},
                "storage": [{"size": "10Gi"}, {"name": "training-data", "size": "20Gi",
                            "attributes": {"persistent": True, "class": "beta3"}}],
                "gpu": {"units": 1, "attributes": {"vendor": {
                    "nvidia": [{"model": "rtx3090"}]}}}}}},
            "placement": {"akash": {"pricing": {service: {"denom": "uact", "amount": 500}}}},
        },
        "deployment": {service: {"akash": {"profile": service, "count": 1}}},
    }
    (output / "deploy.yml").write_text(yaml.safe_dump(sdl, sort_keys=False,
                                                       allow_unicode=True))
    (output / "curl.conf").write_text(f'header = "X-Upload-Token: {token}"\n')
    upload = output / "upload.sh"
    upload.write_text('''#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Uso: upload.sh https://URL-DA-LEASE" >&2
  exit 2
fi
dir="$(cd "$(dirname "$0")" && pwd)"
endpoint="${1%/}"
for part in "$dir"/part-[0-9][0-9][0-9][0-9]; do
  number="${part##*-}"
  index="$((10#$number))"
  curl --fail-with-body --retry 3 --config "$dir/curl.conf" -X PUT --data-binary "@$part" "$endpoint/part/$index"
done
curl --fail-with-body --config "$dir/curl.conf" "$endpoint/status"
''')
    fetch = output / "fetch-results.sh"
    fetch.write_text('''#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Uso: fetch-results.sh https://URL-DA-LEASE" >&2
  exit 2
fi
dir="$(cd "$(dirname "$0")" && pwd)"
endpoint="${1%/}"
mkdir -p "$dir/results"
for name in report.json training.log checkpoint.json experimental-state-checkpoint.pt; do
  curl --fail-with-body --retry 3 --config "$dir/curl.conf" -o "$dir/results/$name" "$endpoint/download/$name"
done
for name in supervisor.log experimental-state-best.pt job.json; do
  curl --fail --silent --show-error --retry 3 --config "$dir/curl.conf" -o "$dir/results/$name" "$endpoint/download/$name" || true
done
python3 - "$dir/results" <<'PYTHON'
from pathlib import Path
import hashlib,json,sys
folder=Path(sys.argv[1]);seal=json.loads((folder/'checkpoint.json').read_text())
name=seal['path']
if Path(name).name!=name:raise SystemExit('unsafe checkpoint seal')
actual=hashlib.sha256((folder/name).read_bytes()).hexdigest()
if actual!=seal['sha256']:raise SystemExit('checkpoint hash mismatch')
report=json.loads((folder/'report.json').read_text())
print({'checkpoint_verified':True,'epoch':report.get('epoch'),
       'validation':report.get('best_validation_metrics'),
       'test':report.get('final_test_metrics')})
PYTHON
''')
    for path in (output / "deploy.yml", output / "curl.conf", upload, fetch):
        path.chmod(0o600)
    upload.chmod(0o700)
    fetch.chmod(0o700)
    summary = {"kind": "experimental_visible_state_forecast_10h",
               "not_player_policy": True, "matches": len(index_data["matches"]),
               "full_match_video_seconds": corpus_facts["total_video_seconds"],
               "native_resolution": [1920, 1080], "sampled_frames": len(referenced),
               "frame_interval_seconds": 15, "full_video_files_uploaded": False,
               "train_pairs": gate["training_pairs"],
               "validation_pairs": gate["validation_pairs"],
               "test_pairs": gate["test_pairs"],
               "comparable_heldout_readings": gate["comparable_heldout_readings"],
               "heldout_vod": "2894958056", "budget_seconds": 36000,
               "simulator_decisions": economy["simulated_decisions"],
               "simulator_policy_labels": 0, "archive_bytes": archive.stat().st_size,
               "archive_sha256": sha256(archive), "chunk_count": len(part_hashes),
               "gpu": "rtx3090", "persistent_storage": "20Gi beta3",
               "max_bid_uact_per_block": 500,
               "approximate_max_act_over_10h_at_6s_blocks": 3.0,
               "lease_created": False, "actual_bid_selected": None}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--branches", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.repo, args.corpus, args.index, args.output,
                             args.branches), indent=2))


if __name__ == "__main__":
    main()
