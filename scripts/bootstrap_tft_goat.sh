#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/training/upstream/TFT_GOAT"
REPO="https://github.com/MielPopsssssss/TFT_GOAT.git"
COMMIT="d5358e9402569f745bea81b61c5aed0500c57d66"

if ! command -v git >/dev/null 2>&1; then
  echo "git não está instalado." >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"

if [ ! -d "$DEST/.git" ]; then
  git clone --filter=blob:none --no-checkout "$REPO" "$DEST"
fi

git -C "$DEST" remote set-url origin "$REPO"
git -C "$DEST" fetch --depth=1 origin "$COMMIT"
git -C "$DEST" checkout --detach "$COMMIT"

ACTUAL="$(git -C "$DEST" rev-parse HEAD)"
if [ "$ACTUAL" != "$COMMIT" ]; then
  echo "Commit inesperado: $ACTUAL" >&2
  exit 1
fi

if ! grep -q "MIT License" "$DEST/LICENSE"; then
  echo "Licença MIT esperada não foi encontrada." >&2
  exit 1
fi

echo "TFT_GOAT_PIN_OK=$ACTUAL"
echo "PATH=$DEST"
