#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    printf '%s\n' "Usage: $0 IMAGE@sha256:DIGEST" >&2
    exit 2
fi

new_image=$1
case "${new_image}" in
    *@sha256:*) ;;
    *)
        printf '%s\n' "Production deployments require an immutable @sha256 image." >&2
        exit 2
        ;;
esac

: "${PUBLIC_DOMAIN:?Set PUBLIC_DOMAIN}"
: "${ACME_EMAIL:?Set ACME_EMAIL}"
: "${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}"
: "${ADMIN_SESSION_SECRET:?Set ADMIN_SESSION_SECRET}"
: "${GRAFANA_ADMIN_PASSWORD:?Set GRAFANA_ADMIN_PASSWORD}"
: "${ALERTMANAGER_CONFIG_FILE:?Set ALERTMANAGER_CONFIG_FILE}"

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file="${repository_root}/compose.production.yml"
state_root="${POKEMON_DEPLOY_STATE_DIR:-${HOME}/.local/state/pokemon-recommender}"
current_file="${state_root}/current-image"
previous_file="${state_root}/previous-image"
mkdir -p "${state_root}"

previous_image=""
if [ -s "${current_file}" ]; then
    previous_image=$(tr -d '\r\n' < "${current_file}")
fi

export APP_IMAGE="${new_image}"
docker compose -f "${compose_file}" config --quiet
docker compose -f "${compose_file}" config --format json \
    | python "${repository_root}/scripts/production/audit_compose_exposure.py"

if [ -n "$(docker compose -f "${compose_file}" ps --status running --quiet db)" ]; then
    sh "${repository_root}/scripts/production/backup_postgres.sh"
fi

docker compose -f "${compose_file}" pull api worker migrate seed embed
docker compose -f "${compose_file}" up -d db
docker compose -f "${compose_file}" run --rm migrate
docker compose -f "${compose_file}" run --rm seed
docker compose -f "${compose_file}" run --rm embed
docker compose -f "${compose_file}" up -d api worker alertmanager prometheus grafana caddy

if ! python "${repository_root}/scripts/production/smoke_test.py" \
    --base-url "https://${PUBLIC_DOMAIN}"; then
    if [ -n "${previous_image}" ]; then
        printf '%s\n' "Deployment smoke test failed; rolling back application image." >&2
        sh "${repository_root}/scripts/production/rollback.sh" "${previous_image}"
    fi
    exit 1
fi

if [ -n "${previous_image}" ] && [ "${previous_image}" != "${new_image}" ]; then
    printf '%s\n' "${previous_image}" > "${previous_file}"
fi
printf '%s\n' "${new_image}" > "${current_file}"
printf '%s\n' "Production deployment completed: ${new_image}"
