#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for tool in cargo python3 ffmpeg tesseract sha256sum; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
ANN="$ROOT/training/annotations/match-001"
[[ -f "$ANN/prelabels.json" && -d "$ANN/frames" ]] || { echo 'Manifesto/frames Match001 ausentes' >&2; exit 1; }
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-shop-s1.XXXXXXXX")"
printf 'SHOP1_EVIDENCE=%s\n' "$OUT"
export OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  tesseract --version
  ffmpeg -version
} > "$OUT/environment.txt" 2>&1
# Build only this new executable. Do not rebuild/overwrite the frozen HP3 binary.
cargo build --release --manifest-path rust/Cargo.toml -p agente-tft-shop-replay-probe
EXTRA=()
if [[ -n "${TFT_SHOP_RELEASE:-}" ]]; then
  [[ -n "${TFT_SHOP_CONTEXT:-}" ]] || { echo 'TFT_SHOP_RELEASE exige TFT_SHOP_CONTEXT explícito' >&2; exit 1; }
  EXTRA=(--release "$TFT_SHOP_RELEASE" --context "$TFT_SHOP_CONTEXT")
fi
python3 -m training.code_health_audit --root "$ROOT" --output "$OUT/code-review.json"
python3 -m training.shop_replay_observe --manifest "$ANN/prelabels.json" --image-root "$ANN" \
  --layout "$ROOT/configs/ui/match001-desktop-1920x1080-ptbr-v1.json" \
  --probe "$ROOT/rust/target/release/agente-tft-shop-replay-probe" --output "$OUT/run" "${EXTRA[@]}"
