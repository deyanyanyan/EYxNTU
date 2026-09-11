#!/usr/bin/env sh
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -f "$repo_root/.env" ]; then echo 'Run sh scripts/setup.sh first.' >&2; exit 1; fi
exec docker compose --env-file "$repo_root/.env" -f "$repo_root/infra/docker-compose.yml" "$@"
