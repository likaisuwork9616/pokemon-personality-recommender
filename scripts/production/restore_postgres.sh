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
checksum_path="${backup_path}.sha256"
if [ ! -f "${checksum_path}" ]; then
    printf '%s\n' "Backup checksum does not exist: ${checksum_path}" >&2
    exit 2
fi

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="${repository_root}/compose.production.yml"

backup_directory=$(CDPATH= cd -- "$(dirname -- "${backup_path}")" && pwd)
backup_name=$(basename -- "${backup_path}")
checksum_name=$(basename -- "${checksum_path}")
(
    cd "${backup_directory}"
    sha256sum -c "${checksum_name}"
)
docker compose -f "${compose_file}" exec -T db \
    pg_restore --list < "${backup_path}" > /dev/null

# Preserve the current state before the explicitly confirmed destructive restore.
sh "${repository_root}/scripts/production/backup_postgres.sh"
docker compose -f "${compose_file}" stop api worker

restart_services() {
    docker compose -f "${compose_file}" up -d api worker caddy
}
trap restart_services EXIT HUP INT TERM

docker compose -f "${compose_file}" exec -T db \
    pg_restore \
    --username "${POSTGRES_USER:-pokemon}" \
    --dbname "${POSTGRES_DB:-pokemon}" \
    --clean \
    --if-exists \
    --exit-on-error \
    --single-transaction \
    --no-owner < "${backup_path}"
restart_services
trap - EXIT HUP INT TERM
