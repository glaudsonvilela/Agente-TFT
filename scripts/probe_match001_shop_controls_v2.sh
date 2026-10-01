#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 1 ]] || { echo 'Uso: bash scripts/probe_match001_shop_controls_v2.sh <pasta-S3>' >&2; exit 1; }
for tool in python3 ffmpeg tesseract; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
BIN="$ROOT/rust/target/shop-s3/release/agente-tft-shop-replay-probe"
[[ -x "$BIN" ]] || { echo 'Executável S3 ausente; não recompilar os leitores congelados automaticamente.' >&2; exit 1; }
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-shop-s4.XXXXXXXX")"
printf 'SHOP4_EVIDENCE=%s\n' "$OUT"
export OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  tesseract --version
  ffmpeg -version
} > "$OUT/environment.txt" 2>&1
python3 -m training.code_health_audit --root "$ROOT" --output "$OUT/code-review.json"
python3 -m training.shop_controls_patch_run --baseline "$1/run/report.json" \
  --manifest "$ROOT/training/annotations/match-001/prelabels.json" \
  --image-root "$ROOT/training/annotations/match-001" \
  --layout "$ROOT/configs/ui/match001-desktop-1920x1080-ptbr-v1.json" \
  --recovery-profile "$ROOT/configs/ui/match001-shop-recovery-v2.json" \
  --base-controls "$ROOT/configs/ui/match001-shop-controls-v1.json" \
  --patch "$ROOT/configs/ui/match001-shop-controls-v2-patch.json" \
  --probe "$BIN" --output "$OUT/evaluation"
