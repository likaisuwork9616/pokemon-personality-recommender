# Production deployment

The production path uses an immutable GHCR image, Docker Compose on a dedicated Linux host, and Caddy-managed HTTPS. The host needs public TCP ports 80 and 443, Docker Engine with Compose v2, a DNS record pointing at the host, and a self-hosted GitHub Actions runner labelled `pokemon-production`.

## GitHub production environment

Create a protected GitHub Environment named `production`. Require approval if more than one person can trigger releases.

Environment variables:

| Name | Example |
| --- | --- |
| `PUBLIC_DOMAIN` | `pokemon.example.com` |
| `ACME_EMAIL` | `operator@example.com` |
| `POSTGRES_DB` | `pokemon` |
| `POSTGRES_USER` | `pokemon` |

Environment secrets:

- `POSTGRES_PASSWORD`
- `ADMIN_SESSION_SECRET` with at least 32 random characters
- `GRAFANA_ADMIN_PASSWORD`
- either `ADMIN_PASSWORD` or `ADMIN_ACCOUNTS_JSON`
- optional `GEMINI_API_KEY`, `OPENAI_API_KEY`, and `HF_TOKEN`

The runner account must be able to run Docker and write to the chosen `POKEMON_BACKUP_DIR` and `POKEMON_DEPLOY_STATE_DIR`. Keep both locations outside the Actions checkout because checkout cleanup removes untracked files.

## Release

Push an annotated version tag or manually run `Release production image`. The workflow:

1. builds one image and pushes it to GHCR;
2. deploys the immutable digest rather than a mutable tag;
3. backs up a running PostgreSQL database before migration;
4. runs Alembic, idempotent seed import and missing-embedding generation;
5. starts API, worker, monitoring and Caddy;
6. verifies HTTPS, HSTS, liveness and readiness;
7. restores the previous application image automatically if the smoke test fails.

Database migrations must remain backward-compatible with the immediately previous application image. Automatic rollback changes the application image; it deliberately does not reverse database migrations.

## Manual validation

Copy `.env.production.example` to a secret file outside the repository, fill it, then run:

```bash
docker compose --env-file /secure/path/pokemon.env \
  -f compose.production.yml config --quiet

python scripts/production/smoke_test.py \
  --base-url https://pokemon.example.com
```

Prometheus and Grafana bind only to loopback. Reach them through an SSH tunnel instead of exposing their ports publicly.

## Backup, rollback and restore

Create an on-demand PostgreSQL custom-format backup:

```bash
sh scripts/production/backup_postgres.sh
```

Roll back to the last successful immutable image:

```bash
sh scripts/production/rollback.sh
```

Restore is destructive and requires an explicit confirmation argument. It first creates another backup, stops API writes, restores, and restarts the application:

```bash
sh scripts/production/restore_postgres.sh \
  /secure/backups/pokemon-YYYYMMDDTHHMMSSZ.dump \
  --confirm-database-overwrite
```

Regularly copy database backups off the host and test restoration on a disposable environment. Caddy certificate state, Prometheus history and Grafana state reside in named Docker volumes; include them in the host-level backup policy when their history matters.
