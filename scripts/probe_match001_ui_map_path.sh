#!/usr/bin/env bash
# Complete, finite L3 experiment; prior experiments and user data remain immutable.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPYCACHEPREFIX
export TFT_BOARD3_STORAGE_ROOT="${UI_MAP_L3_STORAGE_ROOT:-/mnt/sherlock-ssd/Agente-TFT/ui-map-path-l3}"
export TFT_BOARD3_STORAGE_MOUNT="${UI_MAP_STORAGE_MOUNT:-/mnt/sherlock-ssd}"
export TFT_BOARD3_STORAGE_UUID="${UI_MAP_STORAGE_UUID:-497aeb76-c1f7-4991-a6c6-5446694f5b18}"
[[ "$(git hash-object training/board_detector_storage.py)" == 00624c77d5de340bfc37771b26492209e4210dbb ]] || { echo 'Storage helper changed; stop.' >&2; exit 2; }
source "$ROOT/scripts/board_detector_storage.sh"
for tool in flock timeout; do command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 2; }; done
[[ ! -L "$BOARD3_RUNTIME/uimap-l3.lock" ]] || exit 2
exec 9>"$BOARD3_RUNTIME/uimap-l3.lock"
flock -n 9 || { echo 'L3 already running.' >&2; exit 2; }
TRAIN_PY="${UI_MAP_TRAIN_PYTHON:-/mnt/sherlock-ssd/Agente-TFT/board3/board3-runtime/venv/bin/python}"
RUNTIME_PY="${UI_MAP_RUNTIME_PYTHON:-/mnt/sherlock-ssd/Agente-TFT/ui-map-lite/board3-runtime/venv/bin/python}"
[[ -x "$TRAIN_PY" && -x "$RUNTIME_PY" ]] || { echo 'B3/L1 environments missing; nothing installed.' >&2; exit 2; }
[[ "$("$TRAIN_PY" -B -c 'import sys;print(sys.version_info[:2])')" == "$("$RUNTIME_PY" -B -c 'import sys;print(sys.version_info[:2])')" ]] || { echo 'Python ABI mismatch.' >&2; exit 2; }
EXTRAS="$("$RUNTIME_PY" -B -c 'import sysconfig;print(sysconfig.get_path("purelib"))')"
export PYTHONPATH="$ROOT:$EXTRAS"
BASE="$("$TRAIN_PY" -B - "${UI_MAP_L2_HOME:-/mnt/sherlock-ssd/Agente-TFT/ui-map-lite-l2}" "${UI_MAP_L2_RUN:-}" <<'PY'
from pathlib import Path
import sys
from training.uimap_path_l3.evidence import locate,baseline
p=baseline(Path(sys.argv[2]))[0] if sys.argv[2] else locate(Path(sys.argv[1]))
print(p)
PY
)"
printf 'LITE3_BASELINE=%s\n' "$BASE"
"$TRAIN_PY" -B - <<'PY'
from pathlib import Path
import torch,onnx,onnxruntime
from training.uimap_path_l3.evidence import validate_plan
from training.uimap_path_l3 import legacy
from uimap_lite_l2.common import load
from uimap_lite_l2.data import source_manifest
p=load('configs/vision/uimap-path-l3.json');b=validate_plan(p,legacy.L2/'configs/plan.json')
source_manifest(Path('training/annotations/match-001'),b,Path('training/annotations/match-001/prelabels.json'))
av=next(int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
if av<3*1024**3:raise SystemExit('L3 needs 3 GiB available RAM; no training started.')
print('LITE3_PREFLIGHT_OK=true')
PY
OUT="$(mktemp -d "$BOARD3_STORAGE_ROOT/match-001-ui-map-l3.XXXXXXXX")"
printf 'LITE3_EVIDENCE=%s\n' "$OUT"
trap 'rc=$?; if [[ $rc -ne 0 ]]; then printf "LITE3_EXIT=%s\nLITE3_FAILED_EVIDENCE=%s\n" "$rc" "$OUT" >&2; fi' EXIT
printf '%s\n' "$BOARD3_STORAGE_JSON" > "$OUT/storage.json"
git rev-parse HEAD > "$OUT/git-revision.txt"
"$TRAIN_PY" -B -m pip freeze > "$OUT/train-environment.txt"
"$RUNTIME_PY" -B -m pip freeze > "$OUT/runtime-environment.txt"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=2 UIMAP_PATH_REQUIRE_ONNX=1
"$TRAIN_PY" -B -m unittest discover -s tests/uimap_path_l3 -v > "$OUT/tests.log" 2>&1 || { cat "$OUT/tests.log"; exit 2; }
"$TRAIN_PY" -B -m training.code_health_audit --root "$ROOT" --output "$OUT/code-review.json"
source "$ROOT/scripts/board_detector_storage.sh"
set +e
timeout --signal=TERM --kill-after=15s 1800 "$TRAIN_PY" -B -u -m training.uimap_path_l3.run \
 --image-root "$ROOT/training/annotations/match-001" \
 --manifest "$ROOT/training/annotations/match-001/prelabels.json" \
 --plan "$ROOT/configs/vision/uimap-path-l3.json" --baseline "$BASE" --output "$OUT/run" --require-onnx \
 2>&1 | tee "$OUT/console.log"
RC=${PIPESTATUS[0]}
set -e
[[ $RC -eq 0 ]] || exit "$RC"
PYTHONPATH="$ROOT" timeout --signal=TERM --kill-after=10s 240 "$RUNTIME_PY" -B -m training.uimap_path_l3.runtime \
 --bundle "$OUT/run" --image-root "$ROOT/training/annotations/match-001" --output "$OUT/runtime.json" | tee "$OUT/runtime.log"
"$RUNTIME_PY" -B scripts/uimap_path_viewer.py "$OUT/run/original-frames.json" "$ROOT/training/annotations/match-001" "$OUT/viewer.html"
"$RUNTIME_PY" -B - "$OUT" <<'PY'
from pathlib import Path
import json,sys
from training.uimap_path_l3.evidence import seal_output
p=Path(sys.argv[1])
lines=['LITE3_SUMMARY='+json.dumps(json.loads((p/'run/report.json').read_text())['summary']),
       'LITE3_RUNTIME_SUMMARY='+json.dumps(json.loads((p/'runtime.json').read_text())['summary'])]
with (p/'comparison.txt').open('x') as f:f.write('\n'.join(lines)+'\n')
seal_output(p)
PY
printf 'LITE3_COMPARISON=%s\nLITE3_VIEWER=%s\nLITE3_EXIT=0\n' "$OUT/comparison.txt" "$OUT/viewer.html"
