#!/bin/sh
# Native Render buildCommand. Prefer the root Dockerfile if the Python runtime
# does not have Node.js.
set -eu
cd frontend
npm ci --legacy-peer-deps
NEXT_OUTPUT=export NEXT_PUBLIC_API_URL= npm run build
cd ..
python -m pip install -r requirements.txt
