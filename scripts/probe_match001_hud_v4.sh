#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for tool in cargo tesseract ffmpeg python3 sha256sum; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
ANN="training/annotations/match-001"
LAYOUT="configs/hud/tft-1920x1080-match001-v3-gray.json"
RECOVERY="configs/hud/tft-1920x1080-match001-v4-stage-recovery.json"
[[ -f "$ANN/prelabels.json" && -d "$ANN/frames" ]] || { echo "Prelabels/frames ausentes em $ANN" >&2; exit 1; }
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-hud-v4.XXXXXXXX")"
printf 'HUD_PROBE_EVIDENCE=%s\n' "$OUT"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  tesseract --version
  ffmpeg -version
  sha256sum "$LAYOUT" "$RECOVERY" "$ANN/prelabels.json"
  find "$ANN/frames" -maxdepth 1 -type f -name '*.jpg' -print0 | sort -z | xargs -0 -r sha256sum
} > "$OUT/environment.txt" 2>&1
# Same numeric v3 path; only an unknown Stage is eligible for recovery.
set +e
cargo run --manifest-path rust/Cargo.toml -p agente-tft-hud-replay-probe -- \
  telemetry/replays/match-001/TFT_MATCH_001.mp4 "$LAYOUT" "$ANN/prelabels.json" \
  --prelabels --numeric-gray --stage-recovery "$RECOVERY" \
  --image-root "$ANN" --output "$OUT/report.json" \
  > "$OUT/events.jsonl" 2> >(tee "$OUT/probe.stderr" >&2)
RC=$?
set -e
if [[ -s "$OUT/report.json" ]]; then
  python3 - "$OUT/report.json" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
r = json.loads(p.read_text(encoding="utf-8")); s = r["summary"]
print("HUD_PROBE_COMPLETE=", s["execution_complete"])
print("FRAME_SELECTION=", s["frames_selected"], "/", s["frames_in_labels"])
print("OCR_PROFILE=", s["ocr_profile"])
print("METRIC=", s["metric_kind"], "| PROMOTION=", s["promotion_gate"])
for field, metrics in s["fields"].items():
    print(field, json.dumps(metrics, sort_keys=True))
    rows = [x for x in r["records"] if x["field"] == field]
    print(field.upper()+" WRONG=", [(x["timestamp_ms"], x["expected"], x["recognized"], x.get("confidence"))
        for x in rows if x["recognized"] is not None and not x["correct"]])
    print(field.upper()+" UNKNOWN=", [x["timestamp_ms"] for x in rows if x["recognized"] is None])
    for x in rows:
        if x.get("recovery_applied"):
            print("STAGE_RECOVERED=", json.dumps({k: x.get(k) for k in ("timestamp_ms", "recognized", "confidence", "selected_candidate", "ocr_attempts_total")}))
        if x["recognized"] is None or not x["correct"]:
            print("HUD_PENDING_TRACE=", json.dumps(x, sort_keys=True))
print("STAGE_RECOVERED_COUNT=", s.get("stage_recovered", 0))
PY
fi
printf 'HUD_PROBE_REPORT=%s\nHUD_PROBE_EVENTS=%s\nHUD_PROBE_EXIT=%s\n' "$OUT/report.json" "$OUT/events.jsonl" "$RC"
exit "$RC"
