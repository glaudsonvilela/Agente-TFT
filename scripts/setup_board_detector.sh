#!/usr/bin/env bash
# Isolated CPU laboratory; never installs into the agent's Python environment.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/telemetry/data/board3-runtime/venv"
mkdir -p "$(dirname "$VENV")"
exec 9>"$ROOT/telemetry/data/board3-runtime/setup.lock"
flock -w 1800 9 || { echo 'Outro setup B3 está em execução.' >&2; exit 2; }
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV" || { echo 'Não foi possível criar venv; verifique python3-venv. Nenhum pacote global foi alterado.' >&2; exit 2; }
fi
REQ="$ROOT/training/requirements-board-detector.txt"
KEY="$( { cat "$REQ"; printf '%s\n' 'torch==2.12.1+cpu'; } | sha256sum | cut -d' ' -f1)"
STAMP="$(dirname "$VENV")/requirements.sha256"
if [[ ! -f "$STAMP" || "$(cat "$STAMP")" != "$KEY" ]]; then
  echo 'BOARD3_SETUP=isolated_cpu_dependencies'
  "$VENV/bin/python" -m pip --disable-pip-version-check install --retries 2 --timeout 60 --only-binary=:all: \
    'torch==2.12.1+cpu' --index-url https://download.pytorch.org/whl/cpu
  "$VENV/bin/python" -m pip --disable-pip-version-check install --retries 2 --timeout 60 --only-binary=:all: -r "$REQ"
  "$VENV/bin/python" -m pip check
  printf '%s' "$KEY" > "$STAMP"
fi
"$VENV/bin/python" - "$REQ" <<'PY'
import importlib.metadata as m,sys
for line in ['torch==2.12.1+cpu']+open(sys.argv[1]).read().splitlines():
    if not line or line.startswith('#'): continue
    name,version=line.split('==')
    if m.version(name)!=version: raise SystemExit('B3 dependency changed: '+name)
print('BOARD3_ENVIRONMENT_OK=true')
PY
