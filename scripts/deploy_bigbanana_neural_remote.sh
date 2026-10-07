#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE="$ROOT/trainer/neural-bundle"

: "\${BIGBANANA_SSH_TARGET:?set BIGBANANA_SSH_TARGET, e.g. user@server}"
: "\${BIGBANANA_REPO_DIR:?set BIGBANANA_REPO_DIR on the remote server}"

if [[ ! -f "$BUNDLE/bundle.json" ]]; then
  echo "BIGBANANA_REMOTE_DEPLOY_ERROR=local_neural_bundle_missing" >&2
  echo "Run scripts/prepare_bigbanana_neural_bundle.py first." >&2
  exit 1
fi

for command in ssh rsync git; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "BIGBANANA_REMOTE_DEPLOY_ERROR=\${command}_missing" >&2
    exit 1
  }
done

branch="$(git -C "$ROOT" branch --show-current)"
head="$(git -C "$ROOT" rev-parse HEAD)"
if [[ -z "$branch" ]]; then
  echo "BIGBANANA_REMOTE_DEPLOY_ERROR=detached_head" >&2
  exit 1
fi
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]; then
  echo "BIGBANANA_REMOTE_DEPLOY_ERROR=tracked_worktree_dirty" >&2
  exit 1
fi

remote_q="$(printf '%q' "$BIGBANANA_REPO_DIR")"
branch_q="$(printf '%q' "$branch")"
head_q="$(printf '%q' "$head")"

ssh "$BIGBANANA_SSH_TARGET" "
  set -euo pipefail
  cd $remote_q
  test -d .git
  git fetch origin $branch_q
  git checkout $branch_q
  git pull --ff-only origin $branch_q
  test \"\$(git rev-parse HEAD)\" = $head_q
  mkdir -p trainer/neural-bundle
"

rsync -a --delete \
  --chmod=Du=rwx,Dgo=,Fu=rw,Fgo= \
  "$BUNDLE/" \
  "$BIGBANANA_SSH_TARGET:$BIGBANANA_REPO_DIR/trainer/neural-bundle/"

ssh "$BIGBANANA_SSH_TARGET" "
  set -euo pipefail
  cd $remote_q
  test -f trainer/neural-bundle/bundle.json
  test -x trainer/scripts/deploy_bigbanana_neural.sh || chmod 755 trainer/scripts/deploy_bigbanana_neural.sh
  trainer/scripts/deploy_bigbanana_neural.sh
"

echo "BIGBANANA_REMOTE_NEURAL_DEPLOY_OK=true"
echo "REMOTE=$BIGBANANA_SSH_TARGET"
echo "COMMIT=$head"
echo "BUNDLE=trainer/neural-bundle"
