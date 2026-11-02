# Windows 本機環境

本機採用原生 Windows 程序：Python 3.12、PostgreSQL 16／pgvector、API、reindex worker、Prometheus、Grafana、Alertmanager。無須先安裝 Docker；原有 Docker Compose 仍可依 README 使用。

這份文件記錄 2026-11-02 已建置電腦的環境。Git 會同步腳本與文件；`.env`、`.venv/`、PostgreSQL binaries／資料、模型及監控工具都不在 Git 中。另一台電腦第一次使用時，須先依 README 的 Docker 流程，或依下方初次安裝順序建立環境，完成後才能使用啟停腳本。

## 日常啟停

在專案根目錄使用 PowerShell：

```powershell
.\scripts\local_stack.ps1 start
.\scripts\local_stack.ps1 status
.\scripts\local_stack.ps1 stop
```

`start` 載入 `.env`、啟動資料庫與五個背景程序，並等待 API readiness。`stop` 只停止本腳本記錄且 PID、啟動時間、執行檔均吻合的程序，再停止本專案資料庫；資料與快取會保留。重開機後重新執行 `start`。

| 功能 | 本機網址 |
| --- | --- |
| 人格推薦 | <http://127.0.0.1:8000/> |
| 今日寶可夢 | <http://127.0.0.1:8000/today> |
| 圖鑑 | <http://127.0.0.1:8000/pokemon> |
| 管理後台 | <http://127.0.0.1:8000/admin> |
| Swagger | <http://127.0.0.1:8000/docs> |
| Prometheus | <http://127.0.0.1:9090/> |
| Grafana | <http://127.0.0.1:3000/> |
| Alertmanager | <http://127.0.0.1:9093/> |

全部服務只監聽 loopback。管理後台登入使用 `.env` 的 `ADMIN_PASSWORD`；Grafana 帳號使用 `GRAFANA_ADMIN_USER`，密碼使用 `GRAFANA_ADMIN_PASSWORD`。隨機密碼、session secret、資料庫連線均只存於 Git 忽略的 `.env`，不寫入文件。

## 安裝位置與設定

| 位置 | 內容 |
| --- | --- |
| `.venv/` | `requirements.txt`、`requirements-aws.txt` 與 CPU PyTorch |
| `.local/pgsql/` | EDB PostgreSQL 16.15；pgvector 0.8.7 由官方 source tag 編譯 |
| `.local/postgres/data/` | 本專案的 PostgreSQL cluster |
| `.local/huggingface/` | `paraphrase-multilingual-MiniLM-L12-v2` 模型快取 |
| `.local/tools/` | Prometheus 3.14.0、Grafana 13.2.1、Alertmanager 0.28.1 |
| `.local/monitoring/` | 原生程序適用的監控設定、Grafana data 與監控歷史 |
| `.local/services/` | 五個背景程序的 log 與啟停記錄 |
| `.local/downloads/` | 安裝來源 archives |

PostgreSQL 對含中文的 Windows 執行路徑有初始化限制，資料庫腳本會在暫存目錄建立 `pokemon-runtime-<專案路徑雜湊>` junction。它指向本專案 `.local/`，實際資料仍在專案內；若 junction 被清除，腳本會重新建立。切勿手動修改 junction 目標。

開發庫：`127.0.0.1:55432/pokemon`；獨立測試庫：`pokemon_test`。腳本也接受 `.env` 的 `LOCAL_POSTGRES_BIN`、`LOCAL_POSTGRES_DATA` 覆寫，並保留舊 PostgreSQL 17 cluster 的相容路徑。

目前 MBTI SQL catalog 已初始化。`.env` 使用 `MBTI_CATALOG_SOURCE=database`，可從後台編輯；切回 `bundled` 並重啟 API 可使用內建資料。

模型已完整快取，`.env` 設定 `HF_HUB_OFFLINE=1`，啟動與檢索不需連線 Hugging Face。要下載新模型時，先暫時改成 `0`，下載完成後再恢復。Gemini／OpenAI keys 留空，目前使用本機圖鑑證據產生解說；圖片仍使用專案既有 CDN。

## Python 與資料庫工具

不必啟用虛擬環境，直接指定 Python 路徑即可：

```powershell
. .\scripts\load_env.ps1
.\.venv\Scripts\python.exe -m scripts.mbti_catalog verify
.\.venv\Scripts\alembic.exe current
```

完整測試固定使用獨立測試庫：

```powershell
. .\scripts\load_env.ps1
$env:DATABASE_URL = $env:TEST_DATABASE_URL
$env:MBTI_CATALOG_SOURCE = 'bundled'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
. .\scripts\load_env.ps1
```

初次安裝流程為：建立 Python venv、安裝鎖定套件與 CPU PyTorch、下載官方 PostgreSQL archive、用 Visual Studio C++ 編譯 pgvector、`local_database.ps1 initialize`、建立開發／測試 database、兩庫執行 Alembic migration、匯入 seed、初始化 MBTI SQL catalog、建立 embeddings，最後下載三項監控工具。已初始化的環境不需重跑這些步驟。

原生監控沿用 `ops/` 的 alert rules 與 dashboard；啟動時只將 Docker service hostname 改成本機位址。Alertmanager 使用既有的 local receiver，不會傳送外部通知。本機建置不包含網域、HTTPS、遠端主機與雲端帳號設定；相關操作見 [正式部署](production.md)。

下載來源：[PostgreSQL Windows](https://www.postgresql.org/download/windows/)、[EDB binaries](https://www.enterprisedb.com/download-postgresql-binaries)、[pgvector](https://github.com/pgvector/pgvector/tree/v0.8.7)、[Prometheus](https://github.com/prometheus/prometheus/releases/tag/v3.14.0)、[Alertmanager](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1)、[Grafana 13.2.1](https://grafana.com/grafana/download/13.2.1?edition=oss&platform=windows)。Grafana archive 已核對下載頁提供的 SHA-256。
