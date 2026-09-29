#!/usr/bin/env sh
set -eu

if [ "$#" -ne 2 ] || [ "$2" != "--confirm-database-overwrite" ]; then
    printf '%s\n' "Usage: $0 BACKUP.dump --confirm-database-overwrite" >&2
    exit 2
fi

backup_path=$1
if [ ! -f "${backup_path}" ]; then
    printf '%s\n' "Backup does not exist: ${backup_path}" >&2
    exit 2
fi

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="${repository_root}/compose.production.yml"

# Preserve the current state before the explicitly confirmed destructive restore.
sh "${repository_root}/scripts/production/backup_postgres.sh"
docker compose -f "${compose_file}" stop api worker
docker compose -f "${compose_file}" exec -T db \
    pg_restore \
    --username "${POSTGRES_USER:-pokemon}" \
    --dbname "${POSTGRES_DB:-pokemon}" \
    --clean \
    --if-exists \
    --exit-on-error \
    --no-owner < "${backup_path}"
docker compose -f "${compose_file}" up -d api worker caddy
