#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 1 ]] || { echo 'Uso: bash scripts/probe_match001_shop_numbers.sh <pasta-S4>' >&2; exit 1; }
for tool in python3 cargo ffmpeg tesseract; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-shop-s5.XXXXXXXX")"
printf 'SHOP5_EVIDENCE=%s\n' "$OUT"
ARGS=(--baseline "$1/evaluation/report.json" --manifest "$ROOT/training/annotations/match-001/prelabels.json"
  --image-root "$ROOT/training/annotations/match-001" --layout "$ROOT/configs/ui/match001-desktop-1920x1080-ptbr-v1.json"
  --recovery-profile "$ROOT/configs/ui/match001-shop-recovery-v2.json"
  --numbers-profile "$ROOT/configs/ui/match001-shop-isolated-numbers-v1.json"
  --probe "$ROOT/rust/target/shop-s5/release/agente-tft-shop-replay-probe" --output "$OUT/evaluation")
python3 -m training.shop_numbers_run "${ARGS[@]}" --preflight-only
export OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  tesseract --version
  ffmpeg -version
} > "$OUT/environment.txt" 2>&1
cargo build --release --manifest-path rust/Cargo.toml --target-dir "$ROOT/rust/target/shop-s5" \
  -p agente-tft-shop-replay-probe
python3 -m training.code_health_audit --root "$ROOT" --output "$OUT/code-review.json"
python3 -m training.shop_numbers_run "${ARGS[@]}"
