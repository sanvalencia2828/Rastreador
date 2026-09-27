#!/bin/sh
# Rebuild the committed static snapshot used by the native Render runtime.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT/frontend"
npm ci --legacy-peer-deps
NEXT_OUTPUT=export NEXT_PUBLIC_API_URL= npm run build
rm -rf "$ROOT/static"
mkdir -p "$ROOT/static"
cp -a out/. "$ROOT/static/"
test -f "$ROOT/static/index.html"
test -f "$ROOT/static/routes/index.html"
echo "static snapshot updated"
