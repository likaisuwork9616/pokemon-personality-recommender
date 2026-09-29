#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="${repository_root}/compose.production.yml"

sh "${repository_root}/scripts/production/backup_postgres.sh"
docker compose -f "${compose_file}" --profile maintenance \
    run --rm feedback-purge
