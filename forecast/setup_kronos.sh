#!/usr/bin/env bash
# Clones Kronos at a pinned commit into forecast/vendor/Kronos (gitignored).
set -euo pipefail

KRONOS_COMMIT="67b630e67f6a18c9e9be918d9b4337c960db1e9a"
DEST="$(cd "$(dirname "$0")" && pwd)/vendor/Kronos"

if [ ! -d "$DEST/.git" ]; then
    git clone https://github.com/shiyu-coder/Kronos "$DEST"
fi
git -C "$DEST" fetch --quiet origin "$KRONOS_COMMIT"
git -C "$DEST" checkout --quiet "$KRONOS_COMMIT"
echo "Kronos ready at $DEST ($KRONOS_COMMIT)"
