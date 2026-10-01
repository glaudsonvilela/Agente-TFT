#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 1 ]] || { echo 'Uso: bash scripts/probe_match001_shop_controls.sh <pasta-S2>' >&2; exit 1; }
for tool in cargo python3 ffmpeg tesseract; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
BASE="$1/run/report.json"
ANN="$ROOT/training/annotations/match-001"
UI="$ROOT/configs/ui/match001-desktop-1920x1080-ptbr-v1.json"
RECOVERY="$ROOT/configs/ui/match001-shop-recovery-v2.json"
CONTROLS="$ROOT/configs/ui/match001-shop-controls-v1.json"
python3 -m training.shop_controls_evidence "$BASE" --manifest "$ANN/prelabels.json" \
  --image-root "$ANN" --layout "$UI" --recovery "$RECOVERY"
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-shop-s3.XXXXXXXX")"
printf 'SHOP3_EVIDENCE=%s\n' "$OUT"
export OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  tesseract --version
  ffmpeg -version
} > "$OUT/environment.txt" 2>&1
# Isolated build: never overwrite the frozen S1/S2/HP3 binaries.
cargo build --release --manifest-path rust/Cargo.toml --target-dir "$ROOT/rust/target/shop-s3" \
  -p agente-tft-shop-replay-probe
python3 -m training.code_health_audit --root "$ROOT" --output "$OUT/code-review.json"
python3 -m training.shop_replay_observe --manifest "$ANN/prelabels.json" --image-root "$ANN" \
  --layout "$UI" --recovery-profile "$RECOVERY" --controls-profile "$CONTROLS" \
  --probe "$ROOT/rust/target/shop-s3/release/agente-tft-shop-replay-probe" --output "$OUT/run"
python3 -m training.shop_controls_evidence "$BASE" --candidate "$OUT/run/report.json" --output "$OUT/regression.json"
printf 'SHOP3_REPORT=%s\n' "$OUT/run/report.json"
