#!/usr/bin/env bash
# One explicit, bounded run; no background daemon, model download or production activation.
set -euo pipefail
if [[ "${1:-}" == "--help" ]]; then
  printf 'Uso: bash run_lite.sh [caminho do Agente-TFT]\n'
  exit 0
fi
ROOT="$(cd -- "${1:-$HOME/Agente-TFT}" && pwd)"
PACKAGE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export TFT_BOARD3_STORAGE_ROOT="${UI_MAP_STORAGE_ROOT:-/mnt/sherlock-ssd/Agente-TFT/ui-map-lite}"
export TFT_BOARD3_STORAGE_MOUNT="${UI_MAP_STORAGE_MOUNT:-/mnt/sherlock-ssd}"
export TFT_BOARD3_STORAGE_UUID="${UI_MAP_STORAGE_UUID:-497aeb76-c1f7-4991-a6c6-5446694f5b18}"
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPYCACHEPREFIX
# Fail rather than executing a locally edited storage helper unnoticed.
[[ "$(git -C "$ROOT" hash-object training/board_detector_storage.py)" == "00624c77d5de340bfc37771b26492209e4210dbb" ]] || { echo 'Helper de armazenamento diferente da base revisada.' >&2; exit 2; }
[[ "$(git -C "$ROOT" hash-object scripts/board_detector_storage.sh)" == "5a92c1552dd69b01afd6b9fdae1461e76f433a5c" ]] || { echo 'Helper shell diferente da base revisada.' >&2; exit 2; }
source "$ROOT/scripts/board_detector_storage.sh"
for tool in flock timeout; do command -v "$tool" >/dev/null || { echo "Falta: $tool" >&2; exit 2; }; done
[[ ! -L "$BOARD3_RUNTIME/uimap.lock" ]] || exit 2
exec 9>"$BOARD3_RUNTIME/uimap.lock"
flock -n 9 || { echo 'UI-Map Lite já está em execução.' >&2; exit 2; }
TRAIN_PY="${UI_MAP_TRAIN_PYTHON:-/mnt/sherlock-ssd/Agente-TFT/board3/board3-runtime/venv/bin/python}"
[[ -x "$TRAIN_PY" ]] || { echo 'Python B3 não encontrado; nenhum pacote grande foi instalado. Configure UI_MAP_TRAIN_PYTHON.' >&2; exit 2; }
PYTHONPATH="$PACKAGE/training" "$TRAIN_PY" -B - "$ROOT" "$PACKAGE" <<'PY'
from pathlib import Path
import torch, PIL, numpy, sys
from uimap_lite.common import load
from uimap_lite.data import source_manifest
root,package=map(Path,sys.argv[1:])
source_manifest(root/"training/annotations/match-001", load(package/"configs/seed_plan.json"),
                root/"training/annotations/match-001/prelabels.json")
print("LITE1_SOURCE_PREFLIGHT_OK=true")
available=next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
if available < 3*1024**3: raise SystemExit('L1 requer 3 GiB de RAM disponível para o treinamento limitado.')
print('LITE1_TRAIN_ENV='+torch.__version__)
PY
# Fresh small environment for export/deployment only. B3 environment is never changed.
VENV="$BOARD3_RUNTIME/venv"
if [[ ! -x "$VENV/bin/python" ]]; then "$TRAIN_PY" -B -m venv "$VENV"; fi
REQ="$PACKAGE/configs/requirements-export.txt"
REQ_HASH="$(sha256sum "$REQ" | cut -d' ' -f1)"
STAMP="$BOARD3_RUNTIME/lite-export-requirements.sha256"
[[ ! -L "$STAMP" ]] || exit 2
if [[ ! -f "$STAMP" || "$(cat "$STAMP")" != "$REQ_HASH" ]]; then
  echo 'LITE1_PHASE=prepare_small_onnx_runtime'
  timeout --signal=TERM --kill-after=10s 900 "$VENV/bin/python" -B -m pip install \
    --disable-pip-version-check --retries 2 --timeout 45 --only-binary=:all: -r "$REQ"
  "$VENV/bin/python" -B -m pip check
  printf '%s' "$REQ_HASH" > "$STAMP"
fi
EXTRAS="$("$VENV/bin/python" -B -c 'import sysconfig;print(sysconfig.get_path("purelib"))')"
export PYTHONPATH="$PACKAGE/training:$EXTRAS"
# Both interpreters must have the same Python ABI before using the small export packages.
[[ "$("$VENV/bin/python" -B -c 'import sys;print(sys.version_info[:2])')" == "$("$TRAIN_PY" -B -c 'import sys;print(sys.version_info[:2])')" ]] || { echo 'Python ABI incompatível.' >&2; exit 2; }
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=2
OUT="$(mktemp -d "$BOARD3_STORAGE_ROOT/match-001-ui-map-l1.XXXXXXXX")"
printf 'LITE1_EVIDENCE=%s\n' "$OUT"
printf '%s\n' "$BOARD3_STORAGE_JSON" > "$OUT/storage.json"
"$TRAIN_PY" -B -m pip freeze > "$OUT/training-environment.txt"
"$VENV/bin/python" -B -m pip freeze > "$OUT/export-environment.txt"
"$TRAIN_PY" -B -m unittest discover -s "$PACKAGE/tests" -v > "$OUT/tests.log" 2>&1 || { cat "$OUT/tests.log"; exit 2; }
# The native ONNX forward test is mandatory with this environment, not an optional skip.
"$TRAIN_PY" -B -c 'import onnx, onnxruntime; print("LITE1_EXPORT_DEPS_OK=true")'
# Recheck mount/UUID before the bounded training run. Never spill to /.
source "$ROOT/scripts/board_detector_storage.sh"
set +e
timeout --signal=TERM --kill-after=15s 900 "$TRAIN_PY" -B -u -m uimap_lite.train \
  --image-root "$ROOT/training/annotations/match-001" \
  --manifest "$ROOT/training/annotations/match-001/prelabels.json" \
  --plan "$PACKAGE/configs/seed_plan.json" --output "$OUT/run" --steps 600 --require-onnx \
  2>&1 | tee "$OUT/console.log"
RC=${PIPESTATUS[0]}
set -e
if [[ "$RC" -eq 0 ]]; then
  # A second process demonstrates inference without loading Torch/trainer.
  PYTHONPATH="$PACKAGE/training" timeout --signal=TERM --kill-after=10s 120 \
    "$VENV/bin/python" -B -m uimap_lite.runtime --bundle "$OUT/run" \
    --image "$ROOT/training/annotations/match-001/frames/0006_000250000ms.jpg" \
    --output "$OUT/runtime-isolation.json" | tee "$OUT/runtime.log"
  cat "$OUT/run/comparison.txt" "$OUT/runtime.log" > "$OUT/comparison.txt"
  printf 'LITE1_COMPARISON=%s\n' "$OUT/comparison.txt"
fi
printf 'LITE1_EXIT=%s\n' "$RC"
exit "$RC"
