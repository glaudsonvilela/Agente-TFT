#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 1 ]] || { echo "Uso: bash scripts/probe_match001_player_hp_fit.sh <pasta-HP2>" >&2; exit 1; }
SOURCE="$(realpath -- "$1")"
[[ -d "$SOURCE" ]] || { echo "Pasta HP2 ausente: $SOURCE" >&2; exit 1; }
for tool in cargo ffmpeg tesseract python3 sha256sum; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
ANN="$ROOT/training/annotations/match-001"
PROFILE="$ROOT/configs/player-list/match001-self-badge-v1.json"
[[ -f "$ANN/prelabels.json" && -f "$SOURCE/prepared.json" && -f "$SOURCE/plan.json" ]] || {
  echo "Manifesto esparso ou evidencias HP2 ausentes; nada foi alterado." >&2; exit 1;
}
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-player-hp3.XXXXXXXX")"
printf 'HP3_EVIDENCE=%s\n' "$OUT"
export OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  rustc --version
  tesseract --version
  ffmpeg -version
  printf 'OMP_THREAD_LIMIT=%s\n' "$OMP_THREAD_LIMIT"
  sha256sum "$PROFILE" "$ANN/prelabels.json" "$SOURCE/plan.json" "$SOURCE/prepared.json"
} > "$OUT/environment.txt" 2>&1
# Dedicated target path prevents reusing an unexpected external Cargo target.
cargo build --release --manifest-path rust/Cargo.toml --target-dir "$ROOT/rust/target" \
  -p agente-tft-player-hp-fit-probe 2>&1 | tee "$OUT/build.log"
set +e
python3 -m training.player_hp_text_fit \
  --source "$SOURCE" --output "$OUT" \
  --probe "$ROOT/rust/target/release/agente-tft-player-hp-fit-probe" \
  --profile "$PROFILE" --sparse-manifest "$ANN/prelabels.json" --sparse-root "$ANN" \
  2>&1 | tee "$OUT/run.log"
RC=${PIPESTATUS[0]}
set -e
printf 'HP3_REPORT=%s\nHP3_EVIDENCE=%s\nHP3_EXIT=%s\n' "$OUT/report.json" "$OUT" "$RC"
exit "$RC"
