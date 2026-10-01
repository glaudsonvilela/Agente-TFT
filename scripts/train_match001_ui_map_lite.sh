#!/usr/bin/env bash
# U1 finite training and inference-only comparison. No model/profile is activated.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -le 1 ]] || { echo 'Uso: bash scripts/train_match001_ui_map_lite.sh [model.npz anterior]' >&2; exit 2; }
: "${TFT_BOARD3_STORAGE_ROOT:?Informe a pasta UI-Map no SSD}"
: "${TFT_BOARD3_STORAGE_MOUNT:?Informe a montagem do SSD}"
: "${TFT_BOARD3_STORAGE_UUID:?Informe o UUID do SSD}"
: "${TFT_UI_MAP_TRAIN_PYTHON:?Informe o Python do ambiente B3 existente}"
export PYTHONDONTWRITEBYTECODE=1
for tool in python3 timeout flock git; do command -v "$tool" >/dev/null || { echo "Falta: $tool" >&2; exit 2; }; done
# Reuse tested mount/UUID/cache/temp protections; do not modify that helper.
source "$ROOT/scripts/board_detector_storage.sh"
TRAIN_PY="$TFT_UI_MAP_TRAIN_PYTHON"
[[ -x "$TRAIN_PY" ]] || { echo 'Ambiente B3 existente não encontrado; não será reinstalado.' >&2; exit 2; }
"$TRAIN_PY" -B - <<'PY'
import importlib.metadata as m
from pathlib import Path
for k in ('torch','numpy','Pillow'):
    print('UIMAP1_TRAIN_DEPENDENCY='+k+'=='+m.version(k))
p=Path('/proc/meminfo')
if p.is_file():
    free=next(int(x.split()[1])*1024 for x in p.read_text().splitlines() if x.startswith('MemAvailable:'))
    if free<3*1024**3:raise SystemExit('U1 precisa de 3 GiB de RAM disponível durante o treino.')
PY
# The existing B3 training environment is read-only for this command.
[[ ! -L "$BOARD3_RUNTIME/uimap-run.lock" ]] || { echo "Lock U1 inválido." >&2; exit 2; }
exec 8>"$BOARD3_RUNTIME/uimap-run.lock"
flock -n 8 || { echo 'UI-Map Lite já está executando.' >&2; exit 2; }
OUT="$(mktemp -d "$BOARD3_STORAGE_ROOT/uimap-lite-u1.XXXXXXXX")"
printf 'UIMAP1_EVIDENCE=%s\n' "$OUT"
printf '%s\n' "$BOARD3_STORAGE_JSON" > "$OUT/storage.json"
INFER="$BOARD3_RUNTIME/uimap-inference-venv"
[[ ! -L "$INFER" ]] || { echo 'O venv de inferência não pode ser um link.' >&2; exit 2; }
if [[ ! -x "$INFER/bin/python" ]]; then python3 -m venv "$INFER"; fi
REQ="$ROOT/training/requirements-ui-map-runtime.txt"
KEY="$(sha256sum "$REQ" | cut -d' ' -f1)"
STAMP="$BOARD3_RUNTIME/uimap-requirements.sha256"
[[ ! -L "$STAMP" ]] || { echo "Stamp U1 inválido." >&2; exit 2; }
if [[ ! -f "$STAMP" || "$(cat "$STAMP")" != "$KEY" ]]; then
    timeout --signal=TERM --kill-after=10s 600 "$INFER/bin/python" -m pip install \
      --only-binary=:all: --retries 2 --timeout 60 --index-url https://pypi.org/simple -r "$REQ" 2>&1 | tee "$OUT/setup.log"
    "$INFER/bin/python" -m pip check
    printf '%s' "$KEY" > "$STAMP"
fi
"$INFER/bin/python" -B - "$REQ" <<'PY'
import importlib.metadata as m,importlib.util as u,sys
for line in open(sys.argv[1]):
    line=line.strip()
    if not line or line.startswith('#'):continue
    k,v=line.split('==')
    if m.version(k)!=v:raise SystemExit('Dependência U1 mudou: '+k)
if u.find_spec('torch') is not None:raise SystemExit('Venv de inferência contém torch inesperadamente.')
print('UIMAP1_INFERENCE_ENV_NO_TORCH=true')
PY
"$INFER/bin/python" -m pip freeze > "$OUT/inference-environment.txt"
"$TRAIN_PY" -m pip freeze > "$OUT/training-environment.txt"
git rev-parse HEAD > "$OUT/git-head.txt"
"$TRAIN_PY" -B -m training.code_health_audit --root "$ROOT" --output "$OUT/code-review.json"
ARGS=(--project "$ROOT" --spec "$ROOT/configs/vision/uimap-lite-u1.json"
      --image-root "$ROOT/training/annotations/match-001"
      --manifest "$ROOT/training/annotations/match-001/prelabels.json")
PARENT=()
if [[ $# -eq 1 ]]; then PARENT=(--parent "$1"); fi
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1
printf 'UIMAP1_PHASE=train_small_network\n'
timeout --signal=TERM --kill-after=10s 1800 "$TRAIN_PY" -B -u -m training.ui_map_lite.train \
  "${ARGS[@]}" --output "$OUT/training" "${PARENT[@]}" 2>&1 | tee "$OUT/train.log"
# No silent fallback to the full system partition after training.
source "$ROOT/scripts/board_detector_storage.sh"
printf 'UIMAP1_PHASE=inference_only_onnx_comparison\n'
set +e
timeout --signal=TERM --kill-after=10s 600 "$INFER/bin/python" -B -u -m training.ui_map_lite.runtime \
  "${ARGS[@]}" --train "$OUT/training" --output "$OUT/evaluation" 2>&1 | tee "$OUT/evaluation.log"
RC=${PIPESTATUS[0]}
set -e
printf 'UIMAP1_EXIT=%s\n' "$RC"
exit "$RC"
