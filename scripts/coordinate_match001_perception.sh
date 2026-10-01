#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 1 ]] || { echo 'Uso: bash scripts/coordinate_match001_perception.sh <pasta HP5 ou run/report.json>' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Falta python3' >&2; exit 1; }
STORE="$ROOT/telemetry/data/perception-registry"
REGISTRY="$STORE/registry.sqlite3"
[[ -s "$REGISTRY" ]] || { echo 'Registry A1.4 ausente. Execute primeiro register_match001_perception.sh.' >&2; exit 1; }
OUT="$(mktemp -d "$ROOT/telemetry/data/a15-coordinator.XXXXXXXX")"
printf 'A15_EVIDENCE=%s\n' "$OUT"
# Hashing only; never execute or rebuild the preserved HP3 binary.
BIN="${TFT_HP5_PROBE:-$ROOT/rust/target/release/agente-tft-player-hp-fit-probe}"
python3 -m training.coordinate_hp5_perception --source "$1" \
  --evidence-root "$ROOT/telemetry/data" \
  --profile "$ROOT/configs/player-list/match001-self-badge-v1.json" --probe "$BIN" \
  --registry "$REGISTRY" --database "$STORE/coordinator.sqlite3" --output "$OUT/report.json"
