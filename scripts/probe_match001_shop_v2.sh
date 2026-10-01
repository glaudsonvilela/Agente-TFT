#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# == 1 ]] || { echo 'Uso: probe_match001_shop_v2.sh <diretorio-S1-ou-report.json>' >&2; exit 1; }
BASE="$1"
[[ ! -d "$BASE" ]] || BASE="$BASE/run/report.json"
[[ -f "$BASE" ]] || { echo 'Relatorio completo S1 ausente.' >&2; exit 1; }
for tool in cargo python3 ffmpeg tesseract; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
ANN="$ROOT/training/annotations/match-001"
UI="$ROOT/configs/ui/match001-desktop-1920x1080-ptbr-v1.json"
RECOVERY="$ROOT/configs/ui/match001-shop-recovery-v2.json"
python3 -m training.shop_recovery_compare "$BASE" --manifest "$ANN/prelabels.json" --image-root "$ANN" --layout "$UI"
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-shop-s2.XXXXXXXX")"
printf 'SHOP2_EVIDENCE=%s\n' "$OUT"
export OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  tesseract --version
  ffmpeg -version
} > "$OUT/environment.txt" 2>&1
# Separate build output preserves the S1 shop and frozen HP3 executables.
TARGET="$ROOT/rust/target/shop-s2"
cargo build --release --manifest-path rust/Cargo.toml --target-dir "$TARGET" -p agente-tft-shop-replay-probe
python3 -m training.code_health_audit --root "$ROOT" --output "$OUT/code-review.json"
python3 -m training.shop_replay_observe --manifest "$ANN/prelabels.json" --image-root "$ANN" \
  --layout "$UI" --recovery-profile "$RECOVERY" --probe "$TARGET/release/agente-tft-shop-replay-probe" --output "$OUT/run"
python3 -m training.shop_recovery_compare "$BASE" --candidate "$OUT/run/report.json" --output "$OUT/comparison.json"
printf 'SHOP2_REPORT=%s\n' "$OUT/run/report.json"
