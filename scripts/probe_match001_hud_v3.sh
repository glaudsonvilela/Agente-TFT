#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for tool in cargo tesseract ffmpeg python3 sha256sum; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
ANN="training/annotations/match-001"
LAYOUT="configs/hud/tft-1920x1080-match001-v3-gray.json"
[[ -f "$ANN/prelabels.json" && -d "$ANN/frames" ]] || { echo "Prelabels/frames ausentes em $ANN" >&2; exit 1; }
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-hud-v3.XXXXXXXX")"
printf 'HUD_PROBE_EVIDENCE=%s\n' "$OUT"
{
  git rev-parse HEAD
  tesseract --version
  sha256sum "$LAYOUT" "$ANN/prelabels.json"
} > "$OUT/environment.txt" 2>&1
# This is the same sparse Rust probe. No labels or prior reports are overwritten.
set +e
cargo run --manifest-path rust/Cargo.toml -p agente-tft-hud-replay-probe -- \
  telemetry/replays/match-001/TFT_MATCH_001.mp4 "$LAYOUT" "$ANN/prelabels.json" \
  --prelabels --numeric-gray --image-root "$ANN" --output "$OUT/report.json" \
  > "$OUT/events.jsonl" 2> >(tee "$OUT/probe.stderr" >&2)
RC=$?
set -e
if [[ -s "$OUT/report.json" ]]; then
  python3 - "$OUT/report.json" <<'PY'
import json, sys
r=json.load(open(sys.argv[1], encoding="utf-8")); s=r["summary"]
print("HUD_PROBE_COMPLETE=", s["execution_complete"])
print("FRAME_SELECTION=", s["frames_selected"], "/", s["frames_in_labels"])
print("OCR_PROFILE=", s["ocr_profile"])
print("METRIC=", s["metric_kind"], "| PROMOTION=", s["promotion_gate"])
for f,v in s["fields"].items():
    print(f, json.dumps(v, sort_keys=True))
    bad=[(x["timestamp_ms"],x["expected"],x["recognized"],x.get("confidence"))
         for x in r["records"] if x["field"]==f and x["recognized"] is not None and not x["correct"]]
    print(f.upper()+" WRONG=",bad)
PY
fi
printf 'HUD_PROBE_REPORT=%s\nHUD_PROBE_EVENTS=%s\nHUD_PROBE_EXIT=%s\n' "$OUT/report.json" "$OUT/events.jsonl" "$RC"
exit "$RC"
