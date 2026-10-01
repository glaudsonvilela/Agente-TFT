#!/usr/bin/env bash
set -euo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 1 ]] || { echo 'Uso: bash scripts/register_match001_perception.sh <pasta HP5 ou run/report.json>' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Falta instalar: python3' >&2; exit 1; }
BIN="${TFT_HP5_PROBE:-$ROOT/rust/target/release/agente-tft-player-hp-fit-probe}"
PROFILE="$ROOT/configs/player-list/match001-self-badge-v1.json"
# Persistent laboratory control state, not another disposable probe directory.
DEST="$ROOT/telemetry/data/perception-registry"
[[ ! -L "$DEST" ]] || { echo 'Destino do registry não pode ser symlink.' >&2; exit 1; }
mkdir -p "$DEST"
python3 -m training.register_hp5_profiles --source "$1" \
  --evidence-root "$ROOT/telemetry/data" --profile "$PROFILE" --probe "$BIN" \
  --registry "$DEST/registry.sqlite3"
