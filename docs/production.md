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
| `ALERTMANAGER_CONFIG_FILE` | `/etc/pokemon-recommender/alertmanager.yml` |

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

Prometheus, Grafana and Alertmanager bind only to loopback. Reach them through an SSH tunnel instead of exposing their ports publicly. Configure the receiver and cloud-account budgets using `docs/cost-controls.md` before enabling paid provider keys.

The production Compose network is segmented: PostgreSQL is reachable only on
the internal `data` network, monitoring uses the internal `observability`
network, and only Caddy publishes public ports. Caddy has the fixed edge IP
`172.30.250.2`, which is the only proxy Uvicorn trusts for forwarded client
addresses. If that `/29` conflicts with a host network, change the edge subnet,
Caddy `ipv4_address`, and `--forwarded-allow-ips` together before deployment.
The public Caddy route returns `404` for `/metrics` while Prometheus continues
to scrape it directly over the private observability network.
Every deploy and rollback renders the final Compose JSON and runs
`scripts/production/audit_compose_exposure.py`; deployment stops if a private
service gains a host port, an operations port leaves loopback, network
segmentation changes, or proxy trust becomes broad.

## Backup, rollback and restore

Create an on-demand PostgreSQL custom-format backup:

```bash
sh scripts/production/backup_postgres.sh
```

The backup is written with a private umask to a temporary path, validated with
`pg_restore --list`, checksummed, and then atomically renamed. The checksum
contains only the dump basename, so the pair remains verifiable after an
off-host copy. `BACKUP_RETENTION_DAYS` defaults to 30 and only matching
`pokemon-*.dump` files inside `POKEMON_BACKUP_DIR` are pruned.

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

Restore refuses archives without a matching `.sha256` sidecar, checks the
digest and archive table of contents before stopping writers, and uses one
database transaction. A failed restore still restarts API, worker and Caddy.

### Daily maintenance timer

The checked-in systemd timer runs the verified backup and the 90-day anonymous
feedback purge once per day. The sample unit assumes the checkout is
`/srv/pokemon-recommender`, runs as the `pokemon` account, reads secrets from
`/etc/pokemon-recommender/production.env`, and writes backups to
`/var/backups/pokemon-recommender`. Change all four paths consistently when the
host uses a different layout.

```bash
sudo install -d -o pokemon -g pokemon -m 0700 /var/backups/pokemon-recommender
sudo install -m 0644 ops/systemd/pokemon-maintenance.service /etc/systemd/system/
sudo install -m 0644 ops/systemd/pokemon-maintenance.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pokemon-maintenance.timer
sudo systemctl list-timers pokemon-maintenance.timer
```

Run one supervised backup and verify the timer before relying on it:

```bash
sudo systemctl start pokemon-maintenance.service
sudo systemctl status pokemon-maintenance.service
sudo journalctl -u pokemon-maintenance.service --since today
```

The local timer does not protect against loss of the VPS. Copy each `.dump` and
`.sha256` pair to a separately administered bucket or backup host, then run a
quarterly restore drill on a disposable environment. Caddy certificate state,
Prometheus history and Grafana state reside in named Docker volumes; include
them in the host-level backup policy when their history matters.

## Feedback retention

Anonymous recommendation receipts should be purged daily. The default policy keeps 90 days:

```bash
docker compose -f compose.production.yml --profile maintenance \
  run --rm feedback-purge
```

Set `FEEDBACK_RETENTION_DAYS` to a value from 7 through 365 when a different policy is required, and keep the public privacy notice in sync with that policy.
