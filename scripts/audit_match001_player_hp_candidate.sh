#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 1 ]] || { echo "Uso: bash scripts/audit_match001_player_hp_candidate.sh <pasta-HP3>" >&2; exit 2; }
command -v python3 >/dev/null || { echo "Falta instalar: python3" >&2; exit 1; }
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-player-hp4.XXXXXXXX")"
printf 'HP4_EVIDENCE=%s\n' "$OUT"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  python3 --version
} > "$OUT/environment.txt" 2>&1
# Reports only: no Cargo, FFmpeg, Tesseract, image decoding or label entry.
set +e
python3 -m training.player_hp_candidate_audit --source "$1" --output "$OUT/audit" \
  2> >(tee "$OUT/audit.stderr" >&2) | tee "$OUT/console.txt"
RC=${PIPESTATUS[0]}
set -e
printf 'HP4_REPORT=%s\nHP4_CASES=%s\nHP4_EXIT=%s\n' "$OUT/audit/report.json" "$OUT/audit/cases.jsonl" "$RC"
exit "$RC"
