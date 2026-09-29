#!/usr/bin/env sh
set -eu
umask 077

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="${repository_root}/compose.production.yml"
backup_root="${POKEMON_BACKUP_DIR:-${HOME}/pokemon-backups}"
retention_days="${BACKUP_RETENTION_DAYS:-30}"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
output_path="${backup_root}/pokemon-${timestamp}.dump"
temporary_path="${output_path}.tmp"
checksum_path="${output_path}.sha256"
checksum_temporary_path="${checksum_path}.tmp"

case "${backup_root}" in
    ""|/|/.|"${HOME}"|"${HOME}/")
        printf '%s\n' "Refusing unsafe POKEMON_BACKUP_DIR: ${backup_root}" >&2
        exit 2
        ;;
esac
case "${retention_days}" in
    *[!0-9]*|"")
        printf '%s\n' "BACKUP_RETENTION_DAYS must be an integer from 1 through 3650." >&2
        exit 2
        ;;
esac
if [ "${retention_days}" -lt 1 ] || [ "${retention_days}" -gt 3650 ]; then
    printf '%s\n' "BACKUP_RETENTION_DAYS must be an integer from 1 through 3650." >&2
    exit 2
fi

cleanup() {
    rm -f "${temporary_path}" "${checksum_temporary_path}"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "${backup_root}"
docker compose -f "${compose_file}" exec -T db \
    pg_dump \
    --username "${POSTGRES_USER:-pokemon}" \
    --dbname "${POSTGRES_DB:-pokemon}" \
    --format custom \
    --no-owner \
    --file - > "${temporary_path}"

# A successful pg_dump process is not enough: verify that pg_restore can read
# the custom-format archive before publishing it as a completed backup.
docker compose -f "${compose_file}" exec -T db \
    pg_restore --list < "${temporary_path}" > /dev/null

checksum_line=$(sha256sum "${temporary_path}")
checksum_value=${checksum_line%% *}
output_name=${output_path##*/}
printf '%s  %s\n' "${checksum_value}" "${output_name}" \
    > "${checksum_temporary_path}"
mv "${temporary_path}" "${output_path}"
mv "${checksum_temporary_path}" "${checksum_path}"

# Remove only this application's expired dump/checksum pairs inside the
# explicitly validated backup directory.
find "${backup_root}" -type f -name 'pokemon-*.dump' \
    -mtime "+${retention_days}" -print | while IFS= read -r expired_path; do
    rm -f "${expired_path}" "${expired_path}.sha256"
done

trap - EXIT HUP INT TERM
printf '%s\n' "${output_path}"
