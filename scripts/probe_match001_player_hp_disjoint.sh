#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 1 ]] || { echo 'Uso: bash scripts/probe_match001_player_hp_disjoint.sh <pasta HP4 ou audit/report.json>' >&2; exit 1; }
for tool in python3 ffmpeg ffprobe tesseract sha256sum; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
AUDIT="$1"
if [[ -d "$AUDIT" ]]; then
  if [[ -f "$AUDIT/audit/report.json" ]]; then AUDIT="$AUDIT/audit/report.json"; else AUDIT="$AUDIT/report.json"; fi
fi
BIN="${TFT_HP5_PROBE:-$ROOT/rust/target/release/agente-tft-player-hp-fit-probe}"
PROFILE="$ROOT/configs/player-list/match001-self-badge-v1.json"
VIDEO="$ROOT/telemetry/replays/match-001/TFT_MATCH_001.mp4"
[[ -f "$AUDIT" && -s "$VIDEO" && -x "$BIN" ]] || {
  echo 'HP4, vídeo ou binário HP3 preservado ausente. HP5 não recompila nem troca o leitor silenciosamente.' >&2; exit 1;
}
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-player-hp5.XXXXXXXX")"
printf 'HP5_EVIDENCE=%s\n' "$OUT"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  command -v tesseract ffmpeg ffprobe
  tesseract --version
  ffmpeg -version
  sha256sum "$PROFILE" "$BIN"
} > "$OUT/environment.txt" 2>&1
# No Cargo build: equality with the HP3 executable hash is required by the planner.
set +e
python3 -m training.player_hp_disjoint_shadow --audit "$AUDIT" \
  --evidence-root "$ROOT/telemetry/data" --video "$VIDEO" --profile "$PROFILE" \
  --probe "$BIN" --output "$OUT/run" \
  > >(tee "$OUT/run.stdout") 2> >(tee "$OUT/run.stderr" >&2)
RC=$?
set -e
printf 'HP5_REPORT=%s\nHP5_EVIDENCE=%s\nHP5_EXIT=%s\n' "$OUT/run/report.json" "$OUT" "$RC"
exit "$RC"
