#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for tool in cargo tesseract ffmpeg python3 sha256sum; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
ANN="training/annotations/match-001"
PROFILE="configs/player-list/match001-self-badge-v1.json"
[[ -f "$ANN/prelabels.json" && -d "$ANN/frames" ]] || { echo "Frames/manifest ausentes em $ANN" >&2; exit 1; }
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-player-hp1.XXXXXXXX")"
printf 'HP_PROBE_EVIDENCE=%s\n' "$OUT"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  tesseract --version
  ffmpeg -version
  sha256sum "$PROFILE" "$ANN/prelabels.json"
  find "$ANN/frames" -maxdepth 1 -type f -name '*.jpg' -print0 | sort -z | xargs -0 -r sha256sum
} > "$OUT/environment.txt" 2>&1
# Reuses only image paths and timestamps, never suggestions/expected HP.
set +e
cargo run --release --manifest-path rust/Cargo.toml -p agente-tft-player-hp-probe -- \
  "$ANN/prelabels.json" "$ANN" "$PROFILE" "$OUT/report.json" \
  > "$OUT/events.jsonl" 2> >(tee "$OUT/probe.stderr" >&2)
RC=$?
set -e
if [[ -s "$OUT/report.json" ]]; then
  python3 - "$OUT/report.json" <<'PY'
import json,sys
from pathlib import Path
r=json.loads(Path(sys.argv[1]).read_text());s=r['summary']
print('HP_PROBE_COMPLETE=',s['execution_complete'])
print('HP_SUMMARY=',json.dumps(s,sort_keys=True))
for item in r['records']:
    x=item['read'];c=x['location']['candidates']
    print('HP_READ=',json.dumps({'timestamp_ms':x['timestamp_ms'],'status':x['status'],
        'signed_hp':x['signed_hp'],'confidence':x['confidence'],
        'hp_roi':c[0]['hp_rect'] if len(c)==1 else None,'stable_current':item['freshness']['current']}))
    if x['status'] not in ('accepted','negative_display'):
        print('HP_PENDING_TRACE=',json.dumps(x,sort_keys=True))
PY
fi
printf 'HP_PROBE_REPORT=%s\nHP_PROBE_EVENTS=%s\nHP_PROBE_EXIT=%s\n' "$OUT/report.json" "$OUT/events.jsonl" "$RC"
exit "$RC"
