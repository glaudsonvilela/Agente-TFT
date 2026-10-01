#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 1 ]] || { echo 'Uso: bash scripts/probe_match001_board_detector.sh <pasta B1>' >&2; exit 2; }
for tool in python3 ffmpeg timeout flock sha256sum; do command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 2; }; done
BASELINE="$1"
ANN="$ROOT/training/annotations/match-001"
MODEL="$ROOT/telemetry/data/board3-models"
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-board-b3.XXXXXXXX")"
printf 'BOARD3_EVIDENCE=%s\n' "$OUT"
ARGS=(--baseline "$BASELINE" --manifest "$ANN/prelabels.json" --image-root "$ANN"
  --profile "$ROOT/configs/ui/match001-board-bench-v1.json"
  --board-topology "$ROOT/configs/topology/board-standard-4x7-v1.json"
  --bench-topology "$ROOT/configs/topology/bench-nine-v1.json"
  --probe "$ROOT/rust/target/board-b1/release/agente-tft-board-replay-probe"
  --detector-policy "$ROOT/configs/vision/board-open-vocabulary-v1.json"
  --model-cache "$MODEL" --output "$OUT/run")
python3 -m training.board_detector_run "${ARGS[@]}" --preflight-only
python3 - "$ROOT" <<'PY'
import pathlib,shutil,sys
if shutil.disk_usage(sys.argv[1]).free < 4*1024**3: raise SystemExit('B3 precisa de 4 GiB livres para dependências/modelo/evidências.')
p=pathlib.Path('/proc/meminfo')
if p.is_file():
    available=next(int(x.split()[1])*1024 for x in p.read_text().splitlines() if x.startswith('MemAvailable:'))
    if available<3*1024**3: raise SystemExit('B3 precisa de pelo menos 3 GiB de memória disponível; feche outros programas.')
PY
# One run holds the environment lock through setup and inference.
mkdir -p "$ROOT/telemetry/data/board3-runtime"
exec 8>"$ROOT/telemetry/data/board3-runtime/run.lock"
flock -n 8 || { echo 'B3 já está em execução; nenhuma segunda inferência foi iniciada.' >&2; exit 2; }
# Dependency and model downloads have a time bound and remain outside production.
timeout --signal=TERM --kill-after=10s 1800 bash scripts/setup_board_detector.sh 2>&1 | tee "$OUT/setup.log"
PYTHON="$ROOT/telemetry/data/board3-runtime/venv/bin/python"
"$PYTHON" -m pip freeze > "$OUT/environment.txt"
ffmpeg -version >> "$OUT/environment.txt"
git rev-parse HEAD >> "$OUT/environment.txt"
# Existing structural review, not a claim of complete semantic review.
"$PYTHON" -m training.code_health_audit --root "$ROOT" --output "$OUT/code-review.json"
"$PYTHON" -m unittest training.tests.test_board_detector -v > "$OUT/contracts.log" 2>&1
export HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_HUB_DISABLE_XET=1 TOKENIZERS_PARALLELISM=false
set +e
timeout --signal=TERM --kill-after=15s 3600 "$PYTHON" -u -m training.board_detector_run "${ARGS[@]}" 2>&1 | tee "$OUT/console.log"
RC=${PIPESTATUS[0]}
set -e
printf 'BOARD3_EXIT=%s\n' "$RC"
exit "$RC"
