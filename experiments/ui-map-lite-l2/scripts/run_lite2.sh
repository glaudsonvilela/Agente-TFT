#!/usr/bin/env bash
# Explicit bounded experiment, with existing L1/B3 environments read-only.
set -euo pipefail
if [[ "${1:-}" == --help ]]; then
  printf 'Uso: bash run_lite2.sh [diretorio Agente-TFT]\nReutiliza ambientes L1/B3; nao instala pacotes.\n'
  exit 0
fi
ROOT="$(cd -- "${1:-$HOME/Agente-TFT}" && pwd)"
PACKAGE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPYCACHEPREFIX
export TFT_BOARD3_STORAGE_ROOT="${UI_MAP_L2_STORAGE_ROOT:-/mnt/sherlock-ssd/Agente-TFT/ui-map-lite-l2}"
export TFT_BOARD3_STORAGE_MOUNT="${UI_MAP_STORAGE_MOUNT:-/mnt/sherlock-ssd}"
export TFT_BOARD3_STORAGE_UUID="${UI_MAP_STORAGE_UUID:-497aeb76-c1f7-4991-a6c6-5446694f5b18}"
[[ "$(git -C "$ROOT" hash-object training/board_detector_storage.py)" == 00624c77d5de340bfc37771b26492209e4210dbb ]] || { echo 'Helper de armazenamento diferente/ausente; nada instalado.' >&2; exit 2; }
[[ "$(git -C "$ROOT" hash-object scripts/board_detector_storage.sh)" == 5a92c1552dd69b01afd6b9fdae1461e76f433a5c ]] || { echo 'Helper shell diferente/ausente.' >&2; exit 2; }
source "$ROOT/scripts/board_detector_storage.sh"
for tool in flock timeout sha256sum; do command -v "$tool" >/dev/null || { echo "Falta: $tool" >&2; exit 2; }; done
[[ ! -L "$BOARD3_RUNTIME/uimap-l2.lock" ]] || exit 2
exec 9>"$BOARD3_RUNTIME/uimap-l2.lock"
flock -n 9 || { echo 'Outro L2 em execucao.' >&2; exit 2; }
TRAIN_PY="${UI_MAP_TRAIN_PYTHON:-/mnt/sherlock-ssd/Agente-TFT/board3/board3-runtime/venv/bin/python}"
BASE_HOME="${UI_MAP_L1_HOME:-/mnt/sherlock-ssd/Agente-TFT/ui-map-lite}"
RUNTIME_PY="${UI_MAP_RUNTIME_PYTHON:-$BASE_HOME/board3-runtime/venv/bin/python}"
[[ -x "$TRAIN_PY" && -x "$RUNTIME_PY" ]] || { echo 'Ambientes B3/L1 nao encontrados. Nenhum download iniciado.' >&2; exit 2; }
[[ "$("$RUNTIME_PY" -B -c 'import sys;print(sys.version_info[:2])')" == "$("$TRAIN_PY" -B -c 'import sys;print(sys.version_info[:2])')" ]] || { echo 'ABIs Python diferentes.' >&2; exit 2; }
EXTRAS="$("$RUNTIME_PY" -B -c 'import sysconfig;print(sysconfig.get_path("purelib"))')"
export PYTHONPATH="$PACKAGE/training:$EXTRAS"
BASE="$("$TRAIN_PY" -B - "$BASE_HOME" "${UI_MAP_L1_RUN:-}" <<'PY'
import sys
from pathlib import Path
from uimap_lite_l2.baseline import locate,validate_baseline
p=validate_baseline(Path(sys.argv[2]))[0] if sys.argv[2] else locate(Path(sys.argv[1]))
print(p)
PY
)"
printf 'LITE2_BASELINE=%s\n' "$BASE"
"$TRAIN_PY" -B - "$ROOT" "$PACKAGE" <<'PY'
from pathlib import Path
import sys,torch,onnx,onnxruntime,numpy,PIL
from uimap_lite_l2.common import load
from uimap_lite_l2.data import source_manifest
r,p=map(Path,sys.argv[1:]);source_manifest(r/'training/annotations/match-001',load(p/'configs/plan.json'),r/'training/annotations/match-001/prelabels.json')
av=next(int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
if av<3*1024**3:raise SystemExit('L2 requer 3 GiB de RAM disponivel; treino nao iniciado.')
print('LITE2_PREFLIGHT_OK=true')
print('LITE2_ENVIRONMENT='+str({'torch':torch.__version__,'onnx':onnx.__version__,'onnxruntime':onnxruntime.__version__}))
PY
OUT="$(mktemp -d "$BOARD3_STORAGE_ROOT/match-001-ui-map-l2.XXXXXXXX")"
printf 'LITE2_EVIDENCE=%s\n' "$OUT"
trap 'rc=$?; if [[ $rc -ne 0 ]]; then printf "LITE2_EXIT=%s\nLITE2_FAILED_EVIDENCE=%s\n" "$rc" "$OUT" >&2; fi' EXIT
printf '%s\n' "$BOARD3_STORAGE_JSON" > "$OUT/storage.json"
"$TRAIN_PY" -B -m pip freeze > "$OUT/training-environment.txt"
"$RUNTIME_PY" -B -m pip freeze > "$OUT/runtime-environment.txt"
# Preserve existing whole-repository structural review; it is not a full semantic audit.
(cd "$ROOT" && PYTHONPATH="$ROOT" "$TRAIN_PY" -B -m training.code_health_audit --root "$ROOT" --output "$OUT/code-review.json")
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 LITE2_REQUIRE_ONNX=1
"$TRAIN_PY" -B -m unittest discover -s "$PACKAGE/tests" -v > "$OUT/tests.log" 2>&1 || { cat "$OUT/tests.log"; exit 2; }
source "$ROOT/scripts/board_detector_storage.sh"
set +e
timeout --signal=TERM --kill-after=15s 1800 "$TRAIN_PY" -B -u -m uimap_lite_l2.train \
  --image-root "$ROOT/training/annotations/match-001" \
  --manifest "$ROOT/training/annotations/match-001/prelabels.json" \
  --plan "$PACKAGE/configs/plan.json" --baseline "$BASE" --output "$OUT/run" --require-onnx \
  2>&1 | tee "$OUT/console.log"
RC=${PIPESTATUS[0]}
set -e
[[ $RC -eq 0 ]] || exit "$RC"
# Separate inference process; Torch/trainer must remain unloaded.
PYTHONPATH="$PACKAGE/training" timeout --signal=TERM --kill-after=10s 180 \
 "$RUNTIME_PY" -B -m uimap_lite_l2.runtime --bundle "$OUT/run" \
 --image-root "$ROOT/training/annotations/match-001" --output "$OUT/runtime-isolation.json" \
 | tee "$OUT/runtime.log"
cat "$OUT/run/comparison.txt" "$OUT/runtime.log" > "$OUT/comparison.txt"
"$RUNTIME_PY" -B - "$OUT" <<'PY'
from pathlib import Path
import sys
from uimap_lite_l2.common import save,sha
p=Path(sys.argv[1]);save(p/'COMPLETE.json',{str(f.relative_to(p)):sha(f) for f in p.rglob('*') if f.is_file() and f.name!='COMPLETE.json'})
PY
printf 'LITE2_COMPARISON=%s\nLITE2_VIEWER=%s\nLITE2_EXIT=0\n' "$OUT/comparison.txt" "$OUT/run/viewer.html"
