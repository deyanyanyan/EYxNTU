#!/usr/bin/env sh
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -f "$repo_root/.env" ]; then
    echo '.env already exists; keeping its credentials. Continue with sh scripts/compose.sh up --build --wait.'
    exit 0
fi
docker info >/dev/null
docker run --rm --user "$(id -u):$(id -g)" --mount "type=bind,source=$repo_root,target=/workspace" \
    python:3.12-slim python /workspace/scripts/gen_env.py
