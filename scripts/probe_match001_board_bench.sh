#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -eq 0 ]] || { echo 'Uso: bash scripts/probe_match001_board_bench.sh' >&2; exit 1; }
for tool in python3 cargo ffmpeg; do
  command -v "$tool" >/dev/null || { echo "Falta instalar: $tool" >&2; exit 1; }
done
mkdir -p telemetry/data
OUT="$(mktemp -d "$ROOT/telemetry/data/match-001-board-b1.XXXXXXXX")"
printf 'BOARD1_EVIDENCE=%s\n' "$OUT"
ARGS=(--manifest "$ROOT/training/annotations/match-001/prelabels.json"
  --image-root "$ROOT/training/annotations/match-001"
  --profile "$ROOT/configs/ui/match001-board-bench-v1.json"
  --board-topology "$ROOT/configs/topology/board-standard-4x7-v1.json"
  --bench-topology "$ROOT/configs/topology/bench-nine-v1.json"
  --probe "$ROOT/rust/target/board-b1/release/agente-tft-board-replay-probe"
  --output "$OUT/run")
python3 -m training.board_spatial_run "${ARGS[@]}" --preflight-only
{
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  cargo --version
  ffmpeg -version
} > "$OUT/environment.txt" 2>&1
cargo build --release --manifest-path rust/Cargo.toml --target-dir "$ROOT/rust/target/board-b1" \
  -p agente-tft-board-replay-probe
python3 -m training.code_health_audit --root "$ROOT" --output "$OUT/code-review.json"
python3 -m training.board_spatial_run "${ARGS[@]}"
