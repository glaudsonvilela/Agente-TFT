#!/usr/bin/env bash
# Offline diagnostic only; never modifies annotations or the running game.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for tool in cargo ffmpeg tesseract python3; do
  command -v "$tool" >/dev/null || { printf 'Falta instalar: %s\n' "$tool" >&2; exit 1; }
done
LABELS="$ROOT/training/annotations/match-001/prelabels.json"
IMAGES="$ROOT/training/annotations/match-001"
[[ -s "$LABELS" && -d "$IMAGES/frames" ]] || {
  printf 'Faltam os prelabels/frames locais em %s. Nenhuma anotação foi alterada.\n' "$IMAGES" >&2
  exit 1
}
mkdir -p "$ROOT/telemetry/data"
RUN="$(mktemp -d "$ROOT/telemetry/data/match-001-hud-v2.XXXXXXXX")"
printf 'HUD v2: diagnóstico contra sugestões de IA, NÃO ground truth.\nSaída: %s\n' "$RUN"
status=0
cargo run --manifest-path rust/Cargo.toml -p agente-tft-hud-replay-probe -- \
  "$ROOT/telemetry/replays/match-001/TFT_MATCH_001.mp4" \
  configs/hud/tft-1920x1080-match001-v2.json "$LABELS" \
  --prelabels --image-root "$IMAGES" --output "$RUN/report.json" \
  > "$RUN/events.jsonl" || status=$?
if [[ -s "$RUN/report.json" ]]; then
  python3 - "$RUN/report.json" <<'PY'
import json,sys
with open(sys.argv[1], encoding="utf-8") as stream:
    s=json.load(stream)["summary"]
print("HUD_PROBE_COMPLETE=", s["execution_complete"])
print("FRAME_SELECTION=", s["frames_selected"], "/", s["frames_in_labels"])
print("METRIC=", s["metric_kind"], "| PROMOTION=", s["promotion_gate"])
for field, result in s["fields"].items():
    print(field, json.dumps(result, sort_keys=True))
PY
fi
printf 'HUD_PROBE_REPORT=%s/report.json\nHUD_PROBE_EVENTS=%s/events.jsonl\n' "$RUN" "$RUN"
exit "$status"
