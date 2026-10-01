#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 0 ]] || { echo 'Uso: bash scripts/work_match001_perception.sh' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Falta python3' >&2; exit 1; }
STORE="$ROOT/telemetry/data/perception-registry"
[[ -s "$STORE/registry.sqlite3" && -s "$STORE/coordinator.sqlite3" ]] || {
  echo 'A14/A15 ausentes. O worker não cria reservas ou registros de aprovação.' >&2; exit 1;
}
OUT="$(mktemp -d "$ROOT/telemetry/data/a16-worker.XXXXXXXX")"
printf 'A16_EVIDENCE=%s\n' "$OUT"
BIN="${TFT_HP5_PROBE:-$ROOT/rust/target/release/agente-tft-player-hp-fit-probe}"
python3 -m training.run_perception_worker --registry "$STORE/registry.sqlite3" \
  --coordinator "$STORE/coordinator.sqlite3" --evidence-root "$ROOT/telemetry/data" \
  --probe "$BIN" --profile "$ROOT/configs/player-list/match001-self-badge-v1.json" \
  --output "$OUT/report.json"
