#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -le 1 ]] || { echo "Uso: $0 [relatorio-HP1.json]" >&2; exit 1; }
for tool in cargo tesseract ffmpeg ffprobe python3 sha256sum timeout; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
if [[ $# -eq 1 ]]; then
  SOURCE="$1"
else
  SOURCE="$(python3 - <<'PY'
from pathlib import Path
files=[p for p in Path('telemetry/data').glob('match-001-player-hp1.*/report.json') if p.is_file() and p.stat().st_size]
if not files:
    raise SystemExit('Relatorio HP1 ausente; execute primeiro probe_match001_player_hp.sh')
print(max(files,key=lambda p:p.stat().st_mtime_ns).resolve())
PY
)"
fi
VIDEO="$ROOT/telemetry/replays/match-001/TFT_MATCH_001.mp4"
PROFILE="$ROOT/configs/player-list/match001-self-badge-v1.json"
[[ -s "$SOURCE" && -s "$VIDEO" && -s "$PROFILE" ]] || { echo "Relatorio, video ou perfil ausente." >&2; exit 1; }
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-player-hp2.XXXXXXXX")"
trap 'rc=$?; printf "HP2_EVIDENCE=%s\nHP2_EXIT=%s\n" "$OUT" "$rc"' EXIT
printf 'HP2_SOURCE=%s\nHP2_EVIDENCE=%s\n' "$SOURCE" "$OUT"
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  cargo --version
  tesseract --version
  ffmpeg -version
  ffprobe -version
  sha256sum "$SOURCE" "$PROFILE" training/player_hp_dense.py
} > "$OUT/environment.txt" 2>&1
python3 -m training.player_hp_dense prepare "$SOURCE" "$VIDEO" "$OUT" \
  > >(tee "$OUT/extract.stdout") 2> >(tee "$OUT/extract.stderr" >&2)
echo 'HP2_BUILD=compilando o mesmo leitor HP1, sem alterar OCR'
cargo build --release --manifest-path rust/Cargo.toml -p agente-tft-player-hp-probe \
  2> >(tee "$OUT/build.stderr" >&2)
TARGET="$(cargo metadata --manifest-path rust/Cargo.toml --no-deps --format-version 1 | python3 -c 'import json,sys;print(json.load(sys.stdin)["target_directory"])')"
BIN="$TARGET/release/agente-tft-player-hp-probe"
[[ -x "$BIN" ]] || { echo "Binario HP1 nao encontrado: $BIN" >&2; exit 1; }
sha256sum "$BIN" >> "$OUT/environment.txt"
RC=0
for DIR in "$OUT"/window-*; do
  [[ -d "$DIR" && -s "$DIR/manifest.json" ]] || { echo "Janela incompleta: $DIR" >&2; exit 1; }
  printf 'HP2_RUNNING=%s\n' "$(basename "$DIR")"
  # A NEW native process per clip prevents carrying state across unrelated gaps.
  set +e
  timeout --signal=TERM --kill-after=5s 180s "$BIN" \
    "$DIR/manifest.json" "$DIR" "$PROFILE" "$DIR/report.json" \
    > "$DIR/events.jsonl" 2> >(tee "$DIR/probe.stderr" >&2)
  CUR=$?
  set -e
  printf '%s\n' "$CUR" > "$DIR/exit-code.txt"
  [[ $CUR -eq 0 ]] || RC=2
  [[ -s "$DIR/report.json" ]] || { echo "HP2_FAIL=janela sem relatorio; veja $DIR/probe.stderr" >&2; exit 2; }
done
python3 -m training.player_hp_dense summarize "$OUT" | tee "$OUT/summary.txt"
printf 'HP2_REPORT=%s\n' "$OUT/report.json"
exit "$RC"
