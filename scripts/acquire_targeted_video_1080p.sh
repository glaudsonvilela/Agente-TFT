#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Uso:
  scripts/acquire_targeted_video_1080p.sh URL DEST_DIR

Exemplo:
  scripts/acquire_targeted_video_1080p.sh \
    "https://www.youtube.com/watch?v=Ot358nhRJl0" \
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/elder-dragon-shurkou"

Requisitos:
  yt-dlp
  ffmpeg / ffprobe
EOF
}

[[ $# -eq 2 ]] || { usage >&2; exit 2; }

URL="$1"
DEST="$2"
VIDEO="$DEST/source.mp4"
META="$DEST/source-metadata.json"
URL_FILE="$DEST/source-url.txt"

command -v yt-dlp >/dev/null 2>&1 || {
  echo "TARGETED_ACQUIRE_ERROR=yt-dlp_not_found" >&2
  exit 1
}
command -v ffmpeg >/dev/null 2>&1 || {
  echo "TARGETED_ACQUIRE_ERROR=ffmpeg_not_found" >&2
  exit 1
}
command -v ffprobe >/dev/null 2>&1 || {
  echo "TARGETED_ACQUIRE_ERROR=ffprobe_not_found" >&2
  exit 1
}

if [[ -e "$VIDEO" || -e "$META" || -e "$URL_FILE" ]]; then
  echo "TARGETED_ACQUIRE_ERROR=destination_already_contains_source_artifacts" >&2
  exit 1
fi

mkdir -p "$DEST"

TMP_TEMPLATE="$DEST/.download.%(ext)s"
yt-dlp \
  --no-playlist \
  --no-overwrites \
  -f 'bestvideo[height=1080]+bestaudio/best[height=1080]' \
  --merge-output-format mp4 \
  -o "$TMP_TEMPLATE" \
  "$URL"

TMP_FILE="$(find "$DEST" -maxdepth 1 -type f -name '.download.*' | head -n 1 || true)"
[[ -n "$TMP_FILE" && -f "$TMP_FILE" ]] || {
  echo "TARGETED_ACQUIRE_ERROR=download_output_missing" >&2
  exit 1
}

ffmpeg -nostdin -loglevel error -y -i "$TMP_FILE" -map 0:v:0 -map 0:a? -c copy "$VIDEO"
rm -f "$TMP_FILE"

PROBE="$(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height:format=duration \
  -of json "$VIDEO")"

WIDTH="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["streams"][0]["width"])' <<<"$PROBE")"
HEIGHT="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["streams"][0]["height"])' <<<"$PROBE")"
DURATION="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["format"]["duration"])' <<<"$PROBE")"

if [[ "$WIDTH" != "1920" || "$HEIGHT" != "1080" ]]; then
  echo "TARGETED_ACQUIRE_ERROR=expected_1920x1080" >&2
  exit 1
fi

SHA="$(sha256sum "$VIDEO" | awk '{print $1}')"
BYTES="$(stat -c '%s' "$VIDEO")"
printf '%s\n' "$URL" > "$URL_FILE"

python3 - "$META" "$URL" "$VIDEO" "$SHA" "$BYTES" "$WIDTH" "$HEIGHT" "$DURATION" <<'PY'
import json, sys
from pathlib import Path
out, url, video, sha, size, width, height, duration = sys.argv[1:]
doc = {
    "schema_version": 1,
    "kind": "targeted_authorized_source_acquisition",
    "source_url": url,
    "video": video,
    "video_sha256": sha,
    "bytes": int(size),
    "width": int(width),
    "height": int(height),
    "duration_seconds": float(duration),
    "training_performed": False,
    "runtime_approved": False,
}
Path(out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "TARGETED_ACQUIRE_OK=true"
echo "VIDEO=$VIDEO"
echo "SHA256=$SHA"
echo "RESOLUTION=$WIDTH"x"$HEIGHT"
echo "DURATION_SECONDS=$DURATION"
echo "TRAINING_PERFORMED=false"
echo "RUNTIME_APPROVED=false"
