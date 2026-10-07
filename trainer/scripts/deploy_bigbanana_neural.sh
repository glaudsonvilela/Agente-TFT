#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "\${BASH_SOURCE[0]}")/../.." && pwd)"
TRAINER="$ROOT/trainer"
COMPOSE="$TRAINER/compose.example.yml"
BUNDLE="$TRAINER/neural-bundle/bundle.json"
DATA="$TRAINER/data"

if ! command -v docker >/dev/null 2>&1; then
  echo "BIGBANANA_NEURAL_DEPLOY_ERROR=docker_missing" >&2
  exit 1
fi
docker compose version >/dev/null

if [[ ! -f "$COMPOSE" ]]; then
  echo "BIGBANANA_NEURAL_DEPLOY_ERROR=compose_missing" >&2
  exit 1
fi
if [[ ! -f "$BUNDLE" ]]; then
  echo "BIGBANANA_NEURAL_DEPLOY_ERROR=neural_bundle_missing" >&2
  echo "Run scripts/prepare_bigbanana_neural_bundle.py before deploy." >&2
  exit 1
fi
if [[ -z "\${TRAINER_API_TOKEN:-}" ]]; then
  echo "BIGBANANA_NEURAL_DEPLOY_ERROR=TRAINER_API_TOKEN_missing" >&2
  exit 1
fi

mkdir -p "$DATA"
chmod 700 "$DATA"

cd "$TRAINER"
docker compose -f "$COMPOSE" build trainer neural-worker
docker compose -f "$COMPOSE" up -d trainer neural-worker

ok=0
for _ in $(seq 1 45); do
  if body="$(curl -fsS --max-time 3 http://127.0.0.1:8801/v1/training/health 2>/dev/null)"; then
    if python3 - "$body" <<'PY'
import json,sys
doc=json.loads(sys.argv[1])
central=doc.get("central_neural") or {}
assert doc.get("ok") is True
assert doc.get("neural_backend_ready") is True
assert central.get("learning_backend") == "file_queue_worker"
assert isinstance(central.get("stable_generation"), int)
PY
    then
      ok=1
      break
    fi
  fi
  sleep 2
done

if [[ "$ok" != "1" ]]; then
  echo "BIGBANANA_NEURAL_DEPLOY_ERROR=health_or_initial_champion_failed" >&2
  docker compose -f "$COMPOSE" ps >&2 || true
  exit 1
fi

edge_id="$(
  docker ps -q \
    --filter 'label=com.docker.compose.service=tft-voice-edge' \
    | head -n1
)"
edge_reloaded=false
if [[ -n "$edge_id" ]]; then
  docker exec "$edge_id" nginx -t -c /etc/nginx/tft.conf >/dev/null
  docker exec "$edge_id" nginx -s reload
  edge_reloaded=true
fi

health="$(curl -fsS http://127.0.0.1:8801/v1/training/health)"
python3 - "$health" "$edge_reloaded" <<'PY'
import json,sys
doc=json.loads(sys.argv[1])
central=doc["central_neural"]
print("BIGBANANA_NEURAL_DEPLOY_OK=true")
print("NEURAL_BACKEND_READY="+str(doc["neural_backend_ready"]).lower())
print("LEARNING_BACKEND="+str(central["learning_backend"]))
print("STABLE_GENERATION="+str(central["stable_generation"]))
print("STABLE_VERSION="+str(central["stable_version"]))
print("EDGE_RELOADED="+sys.argv[2])
print("TRAINING_LOCATION=BigBANANA")
print("CLIENT_COMPUTE_REQUIRED=false")
PY
