# 正式環境部署、備份與回退

[文件索引](README.md) · [返回專案首頁](../README.md)

正式路徑使用 immutable GHCR image、專用 Linux host 上的 Docker Compose，以及由 Caddy 管理的 HTTPS。主機需要：

- 對外 TCP 80、443；若使用 HTTP/3，再開 UDP 443
- Docker Engine 與 Compose v2
- 指向主機的 DNS record
- 標記為 `pokemon-production` 的 self-hosted GitHub Actions runner
- repository 外、只有 operator 可讀寫的 secrets、備份及 deploy state 目錄

## GitHub production Environment

建立受保護的 GitHub Environment `production`。若不只一個人可以觸發 release，建議要求人工 approval。

Environment variables：

| 名稱 | 範例 |
| --- | --- |
| `PUBLIC_DOMAIN` | `pokemon.example.com` |
| `ACME_EMAIL` | `operator@example.com` |
| `POSTGRES_DB` | `pokemon` |
| `POSTGRES_USER` | `pokemon` |
| `ALERTMANAGER_CONFIG_FILE` | `/etc/pokemon-recommender/alertmanager.yml` |
| `POKEMON_ARTWORK_BASE_URL` | `https://cdn.example.com/images/pokemon/artwork` |
| `POKEMON_BACKUP_DIR` | `/var/backups/pokemon-recommender` |
| `POKEMON_DEPLOY_STATE_DIR` | `/var/lib/pokemon-recommender/deploy-state` |
| `BACKUP_RETENTION_DAYS` | `30` |

Environment secrets：

- `POSTGRES_PASSWORD`
- 至少 32 個隨機字元的 `ADMIN_SESSION_SECRET`
- `GRAFANA_ADMIN_PASSWORD`
- `ADMIN_PASSWORD` 或 `ADMIN_ACCOUNTS_JSON`
- 選配的 `GEMINI_API_KEY`、`OPENAI_API_KEY`、`HF_TOKEN`

`POKEMON_ARTWORK_BASE_URL` 在 production 是必填值。請使用 operator 擁有或已明確核准的圖片目錄，不要讓 fork 在未告知的情況下消耗另一個專案的 CDN 流量。

Runner 帳號必須能執行 Docker，並可寫入 `POKEMON_BACKUP_DIR` 與 `POKEMON_DEPLOY_STATE_DIR`。兩者都要放在 Actions checkout 外，避免 checkout 清理未追蹤檔案時一併移除。

## Release 流程

推送 `v*` version tag，或手動執行 `Release production image`。Workflow 會：

1. 建立一份 image 並推到 GHCR；
2. 以 immutable digest 部署，不依賴 mutable tag；
3. migration 前備份正在運作的 PostgreSQL；
4. 執行 Alembic、可重跑的 seed import 與缺少的 embeddings；
5. 啟動 API、worker、monitoring 與 Caddy；
6. 驗證 HTTPS、HSTS、liveness、readiness 與公開 `/metrics` 封鎖；
7. smoke test 失敗時，自動切回上一個 application image。

Database migrations 必須與前一版 application image 向後相容。自動 rollback 只切換 image，不會逆向執行 database migration。

## 手動驗證

把 `.env.production.example` 複製到 repository 外的可信任檔案並填妥。該檔案必須是 shell-compatible `KEY=value` 格式。先載入目前 shell，確保 deployment、backup、rollback、restore scripts 使用相同設定：

```bash
set -a
. /secure/path/pokemon.env
set +a

docker compose -f compose.production.yml config --quiet

python scripts/production/smoke_test.py \
  --base-url https://pokemon.example.com
```

Prometheus、Grafana 與 Alertmanager 只綁 loopback，請透過 SSH tunnel 存取，不要公開其 ports。啟用付費 provider key 前，先依[費用護欄文件](cost-controls.md)設定通知與雲端預算。

## 網路與 proxy trust

Production Compose 分為四種網路用途：

- `edge`：Caddy 與 API；只有 Caddy 發布 80／443
- `data`：internal network，供 API、worker 與 PostgreSQL 使用
- `observability`：internal network，供 API、Prometheus、Grafana 與 Alertmanager 使用
- `model-egress`／`notification-egress`：只給需要下載模型或送通知的服務

Caddy 固定使用 edge IP `172.30.250.2`，Uvicorn 只信任該位址提供的 forwarded client headers。若 `/29` 與 host network 衝突，必須一起調整 edge subnet、Caddy `ipv4_address` 與 `--forwarded-allow-ips`。

公開 Caddy route 對 `/metrics` 回傳 `404`，Prometheus 則從 private observability network 直接 scrape API。每次 deploy 與 rollback 都會 render Compose JSON，再執行 `scripts/production/audit_compose_exposure.py`；只要 private service 多出 host port、operations port 離開 loopback、網路分區改變或 proxy trust 變寬，部署就會停止。

## 臨時 Cloudflare Quick Tunnel smoke test

Quick Tunnel 只適合短時間開發驗證，沒有 uptime 保證、固定 hostname 或 production access control。測試完成就關閉；長期環境使用前述 Caddy HTTPS 正式部署。

Repository 內的 overlay 固定走這條路徑：

```text
public HTTPS → cloudflared → tracked ops/caddy/Caddyfile → api:8000
```

不要把 `cloudflared` 直接指向 API service 或 API 的 loopback host port。Caddy 才是已驗證的公開邊界，負責封鎖 `/metrics` 與限制 16 KB request body。Overlay 也會強制清空 `GEMINI_API_KEY`、`OPENAI_API_KEY`、`HF_TOKEN`，即使目前 shell 另有設定也不會傳入。

在 PowerShell 7 啟動隔離 stack；若列出的 loopback ports 已被使用，請換成其他未使用值：

```powershell
$env:POSTGRES_PASSWORD = [Convert]::ToHexString(
  [Security.Cryptography.RandomNumberGenerator]::GetBytes(24)
)
$env:POSTGRES_PORT = "15432"
$env:API_PORT = "18000"
$env:TUNNEL_ORIGIN_PORT = "18080"

$compose = @(
  "--project-name", "pokemon-quick-tunnel",
  "-f", "docker-compose.yml",
  "-f", "compose.quick-tunnel.yml"
)
docker compose @compose config --quiet
docker compose @compose up --build --detach cloudflared
docker compose @compose logs --follow cloudflared
```

從 log 複製 `https://...trycloudflare.com`，再用 `Ctrl+C` 停止 follow；containers 仍會運行。cloudflared image 固定為 `2026.9.3`，manifest digest 為：

```text
sha256:072c067d25ccbe61d46e18f0d0723255f2bb5304f7317caa95b27031520ff92c
```

執行參數化 smoke test；指令不需要任何 API key：

```powershell
pwsh -File scripts/production/quick_tunnel_smoke.ps1 `
  -BaseUrl "https://replace-me.trycloudflare.com"
```

腳本會驗證：

- liveness、readiness 與首頁
- 非官方／非商業權利聲明
- 公開 `/metrics` 回傳 `404`
- 超過 16 KB 的 request 回傳 `413`
- Top 3 推薦與 grounded `local` fallback
- Top 1 HTTPS 圖片
- 輪換偽造 forwarded-address headers 仍會觸發 `429`

Overlay 把隔離環境的推薦上限降為每分鐘 4 次，讓最後一項能快速完成。重跑整套腳本前，先重啟隔離 API 或等待一分鐘。

檢查實際服務與 port：

```powershell
docker compose @compose ps
docker compose @compose config
```

安全停止，不刪 volumes：

```powershell
docker compose @compose down --remove-orphans
```

這會移除暫時 containers 與 network，但保留 database、model 與 Caddy named volumes，方便重跑。不要加 `--volumes` 或 `-v`，除非已確認資料可以刪除。

## 備份、rollback 與 restore

本節指令假設已依「手動驗證」載入 production environment file。只在單次 Compose command 傳 `--env-file`，不會把值 export 給之後執行的 shell scripts。

建立 PostgreSQL custom-format 備份：

```bash
sh scripts/production/backup_postgres.sh
```

腳本使用 private umask 寫入 temporary path，以 `pg_restore --list` 驗證後產生 checksum，最後才原子改名。Checksum 只包含 dump basename，因此搬到 off-host storage 後仍可驗證。`BACKUP_RETENTION_DAYS` 預設 30，只會清理 `POKEMON_BACKUP_DIR` 內符合 `pokemon-*.dump` 的過期檔案及 sidecar。

回退到上一個成功的 immutable image：

```bash
sh scripts/production/rollback.sh
```

Restore 會覆寫資料庫，必須提供明確確認參數。流程會先再做一份備份、停止 application writers、執行 restore，最後重新啟動服務：

```bash
sh scripts/production/restore_postgres.sh \
  /secure/backups/pokemon-YYYYMMDDTHHMMSSZ.dump \
  --confirm-database-overwrite
```

Restore 會拒絕缺少 `.sha256` sidecar 的 archive，並在停止 writers 前檢查 digest 與 archive table of contents。真正 restore 使用單一 database transaction；失敗時仍會重新啟動 API、worker 與 Caddy。

### 每日 maintenance timer

Repository 內的 systemd timer 每日執行已驗證備份與 90 天匿名 feedback purge。範例假設：

- checkout：`/srv/pokemon-recommender`
- service account：`pokemon`
- environment file：`/etc/pokemon-recommender/production.env`
- backup path：`/var/backups/pokemon-recommender`

若 host 版面不同，請一致修改 unit、environment file 與可寫目錄。

```bash
sudo install -d -o pokemon -g pokemon -m 0700 /var/backups/pokemon-recommender
sudo install -m 0644 ops/systemd/pokemon-maintenance.service /etc/systemd/system/
sudo install -m 0644 ops/systemd/pokemon-maintenance.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pokemon-maintenance.timer
sudo systemctl list-timers pokemon-maintenance.timer
```

依賴 timer 前，先人工執行一次並檢查：

```bash
sudo systemctl start pokemon-maintenance.service
sudo systemctl status pokemon-maintenance.service
sudo journalctl -u pokemon-maintenance.service --since today
```

本機 timer 不能防止整台 VPS 遺失。每份 `.dump` 與 `.sha256` 都應複製到獨立管理的 bucket 或 backup host，並至少每季在可丟棄環境做 restore drill。Caddy certificate state、Prometheus history 與 Grafana state 位於 named Docker volumes；需要保留歷史時也要納入 host-level backup policy。

## Feedback retention

匿名推薦收據應每日清理；預設保留 90 天：

```bash
docker compose -f compose.production.yml --profile maintenance \
  run --rm feedback-purge
```

若政策不同，可把 `FEEDBACK_RETENTION_DAYS` 設為 7–365；公開隱私聲明也必須同步更新。
