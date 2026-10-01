#!/usr/bin/env bash
# Opt-in v3; v2 runner, labels and earlier reports remain unchanged.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for tool in cargo ffmpeg tesseract python3 sha256sum; do
  command -v "$tool" >/dev/null || { printf 'Falta instalar: %s\n' "$tool" >&2; exit 1; }
done
LABELS="$ROOT/training/annotations/match-001/prelabels.json"
IMAGES="$ROOT/training/annotations/match-001"
LAYOUT="$ROOT/configs/hud/tft-1920x1080-match001-v3.json"
[[ -s "$LABELS" && -d "$IMAGES/frames" && -s "$LAYOUT" ]] || {
  printf 'Faltam layout/prelabels/frames locais. Nenhuma anotação foi alterada.\n' >&2; exit 1;
}
mkdir -p "$ROOT/telemetry/data"
RUN="$(mktemp -d "$ROOT/telemetry/data/match-001-hud-v3.XXXXXXXX")"
{
  git rev-parse HEAD
  cargo --version
  tesseract --version 2>&1
  ffmpeg -version 2>&1
  sha256sum "$LABELS" "$LAYOUT"
} > "$RUN/environment.txt"
printf 'HUD v3: concordância com IA, NÃO ground truth.\nSaída: %s\n' "$RUN"
status=0
cargo run --manifest-path rust/Cargo.toml -p agente-tft-hud-replay-probe -- \
  "$ROOT/telemetry/replays/match-001/TFT_MATCH_001.mp4" "$LAYOUT" "$LABELS" \
  --prelabels --image-root "$IMAGES" --output "$RUN/report.json" \
  > "$RUN/events.jsonl" || status=$?
if [[ -s "$RUN/report.json" ]]; then
  python3 - "$RUN/report.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    s=json.load(f)["summary"]
print("HUD_PROBE_COMPLETE=", s["execution_complete"])
print("FRAME_SELECTION=", s["frames_selected"], "/", s["frames_in_labels"])
print("METRIC=", s["metric_kind"], "| PROMOTION=", s["promotion_gate"])
for field, result in s["fields"].items():
    print(field, json.dumps(result, sort_keys=True))
PY
fi
printf 'HUD_PROBE_REPORT=%s/report.json\nHUD_PROBE_EVENTS=%s/events.jsonl\n' "$RUN" "$RUN"
exit "$status"
