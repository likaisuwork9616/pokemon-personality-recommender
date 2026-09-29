#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="${repository_root}/compose.production.yml"
backup_root="${POKEMON_BACKUP_DIR:-${HOME}/pokemon-backups}"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
output_path="${backup_root}/pokemon-${timestamp}.dump"

mkdir -p "${backup_root}"
docker compose -f "${compose_file}" exec -T db \
    pg_dump \
    --username "${POSTGRES_USER:-pokemon}" \
    --dbname "${POSTGRES_DB:-pokemon}" \
    --format custom \
    --no-owner \
    --file - > "${output_path}"

sha256sum "${output_path}" > "${output_path}.sha256"
printf '%s\n' "${output_path}"
