#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="${repository_root}/compose.production.yml"
state_root="${POKEMON_DEPLOY_STATE_DIR:-${HOME}/.local/state/pokemon-recommender}"
previous_file="${state_root}/previous-image"
current_file="${state_root}/current-image"
rollback_image="${1:-}"

if [ -z "${rollback_image}" ]; then
    if [ ! -s "${previous_file}" ]; then
        printf '%s\n' "No previous immutable image is recorded." >&2
        exit 2
    fi
    rollback_image=$(tr -d '\r\n' < "${previous_file}")
fi

case "${rollback_image}" in
    *@sha256:*) ;;
    *)
        printf '%s\n' "Rollback image must use an immutable @sha256 digest." >&2
        exit 2
        ;;
esac

mkdir -p "${state_root}"
current_image=""
if [ -s "${current_file}" ]; then
    current_image=$(tr -d '\r\n' < "${current_file}")
fi

export APP_IMAGE="${rollback_image}"
docker compose -f "${compose_file}" pull api worker
docker compose -f "${compose_file}" up -d api worker caddy
python "${repository_root}/scripts/production/smoke_test.py" \
    --base-url "https://${PUBLIC_DOMAIN}"

if [ -n "${current_image}" ]; then
    printf '%s\n' "${current_image}" > "${previous_file}"
fi
printf '%s\n' "${rollback_image}" > "${current_file}"
printf '%s\n' "Rolled back to ${rollback_image}."
