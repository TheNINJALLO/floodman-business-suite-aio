#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(tr -d '\r\n' < "$ROOT/vendor/roomflow/REPOSITORY")"
COMMIT="$(tr -d '\r\n' < "$ROOT/vendor/roomflow/PINNED_COMMIT")"
DEST="${1:-$ROOT/vendor/roomflow/source}"

if [[ -d "$DEST/.git" ]]; then
  git -C "$DEST" fetch --depth 1 origin "$COMMIT"
else
  rm -rf "$DEST"
  git clone --filter=blob:none --no-checkout "$REPO" "$DEST"
  git -C "$DEST" fetch --depth 1 origin "$COMMIT"
fi
git -C "$DEST" checkout --detach "$COMMIT"
actual="$(git -C "$DEST" rev-parse HEAD)"
[[ "$actual" == "$COMMIT" ]] || { echo "Expected $COMMIT but checked out $actual" >&2; exit 1; }
printf 'RoomFlow ready at %s (%s)\n' "$DEST" "$actual"
