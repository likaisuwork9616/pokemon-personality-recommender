# Pokémon Personality Recommender

> 輸入一段個性、興趣或生活方式描述，系統會從 1,025 隻寶可夢中找出三個契合對象，並附上分數、圖鑑依據與繁中契合分析。

[![CI](https://github.com/likaisuwork9616/pokemon-personality-recommender/actions/workflows/ci.yml/badge.svg)](https://github.com/likaisuwork9616/pokemon-personality-recommender/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141.1-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![pgvector](https://img.shields.io/badge/pgvector-HNSW%20%7C%20exact-336791)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)

這個專案把語意搜尋、中文全文搜尋與 SQL 人格詞庫放在同一條推薦流程中。排名先由可重現的檢索與計分完成，LLM 只負責把人格訊號和圖鑑內容整理成說明；即使沒有外部 API key，核心推薦仍可運作。

## 功能亮點

- 固定回傳 Top 3，包含語意分數、人格分數、總分與最多三段可追蹤證據。
- Dense Retrieval 預設使用 pgvector HNSW，另保留 exact search 作為 recall 與延遲基準。
- jieba 斷詞搭配 PostgreSQL Full Text Search，兩路結果以 RRF（`k=60`）融合。
- 圖鑑內容拆成版本化 documents 與 chunks，保存來源、雜湊、語言及 current／ready 狀態。
- 人格特質與中英文同義詞存入 PostgreSQL，可從管理後台調整權重、啟用狀態與顯示名稱。
- 敘述修改後由 PostgreSQL 工作佇列排程 reindex；新索引完整建立後才切換，失敗時沿用舊版。
- 公開端提供推薦頁與可搜尋圖鑑；管理端支援寶可夢維護、停用、詞庫管理和索引進度。
- 圖片可選擇交由 S3 儲存、CloudFront 發送，PostgreSQL 只保存 URL。

## 系統架構

~~~mermaid
flowchart TB
    U[使用者] --> WEB[FastAPI + Jinja2]
    A[管理員] --> WEB
    WEB --> API[REST API /api/v1]

    API --> ENC[384d Query Encoder]
    ENC --> DENSE[Dense Top 50<br/>pgvector HNSW / exact]
    API --> LEX[jieba + PostgreSQL FTS<br/>Lexical Top 50]
    DENSE --> RRF[RRF k=60]
    LEX --> RRF
    RRF --> SCORE[人格向量融合與穩定排序]
    SCORE --> TOP3[Top 3 + 分數 + 證據]

    TOP3 -->|產生契合分析| RAG[Grounded RAG]
    RAG -->|已設定 provider| LLM[Gemini 或 OpenAI]
    RAG -->|無 key、逾時或驗證失敗| LOCAL[本地 evidence fallback]

    API <--> DB[(PostgreSQL 16 + pgvector)]
    API --> JOBS[(Reindex jobs)]
    WORKER[Background worker] -->|FOR UPDATE SKIP LOCKED| JOBS
    WORKER --> STAGED[Staged documents / chunks / embeddings]
    STAGED -->|成功後原子切換| DB

    API --> OBS[X-Request-ID<br/>Structured logs<br/>Prometheus metrics]
    WEB -->|選配| CDN[CloudFront]
    CDN --> S3[(Amazon S3 artwork)]
~~~

CSV 是建立空資料庫時的 seed 來源。API 啟動後，寶可夢資料、人格詞庫、檢索 chunks 與 embeddings 都從 PostgreSQL 讀取。

## 推薦資料流與隱私

1. FastAPI 驗證輸入長度與 request schema。
2. SentenceTransformer 將描述編碼成正規化的 384 維 query vector。
3. pgvector 與中文全文搜尋各取 Top 50 chunks，再以 RRF 融合。
4. 系統按寶可夢聚合結果，每隻最多保留三段證據，避免 chunk 數量造成灌票。
5. SQL 人格詞庫將描述映射到 16 維人格訊號，並與寶可夢人格向量一起計分。
6. 固定 tie-break 完成 Top 3 後，才進入選配的契合分析。

總分公式：

~~~text
total = α × personality + (1 - α) × semantic
~~~

`α` 依辨識到的人格訊號調整，範圍為 `0.35–0.80`。每段證據都帶有 `document_id`、`chunk_id`、`content_hash` 與 `evidence_id`，可以追溯到當次使用的知識版本。

### 契合分析

- Web 介面預設產生契合分析；API 的 `generate_explanation` 預設為 `false`，呼叫端可明確決定是否啟用。
- `LLM_PROVIDER` 預設為 `gemini`，也可明確設成 `openai`；系統不會在兩個付費 provider 之間自動轉送。
- 外部 provider 已設定且使用者要求分析時，原始描述與當次證據會送往該服務。
- 原始描述與 query vector 不寫入 PostgreSQL、request log 或瀏覽器儲存空間。
- Provider 缺少 key、逾時、格式錯誤或引用不合法時，會改用本地繁中 fallback。
- LLM 回應只能引用該推薦結果的 evidence allowlist，也不會改變既有排名。

## 快速開始

### 執行需求

- Docker Desktop 與 Docker Compose v2
- 約 4 GB 可用記憶體
- 首次啟動時可連線下載 Python packages 與 Hugging Face embedding model

Gemini／OpenAI key 是選配。沒有 key 時，Top 3、分數、證據與本地契合分析仍可使用。

### 1. 取得專案

~~~bash
git clone https://github.com/likaisuwork9616/pokemon-personality-recommender.git
cd pokemon-personality-recommender
~~~

建立本機環境檔：

~~~bash
cp .env.example .env
~~~

Windows PowerShell 請改用：

~~~powershell
Copy-Item .env.example .env
~~~

### 2. 設定必要值

至少更換 `POSTGRES_PASSWORD`。若要登入管理後台，還要設定管理密碼與至少 32 字元的 session secret：

~~~env
POSTGRES_PASSWORD=replace-with-a-strong-password
ADMIN_PASSWORD=replace-with-a-strong-admin-password
ADMIN_SESSION_SECRET=replace-with-a-random-secret-of-at-least-32-characters
ADMIN_COOKIE_SECURE=false
~~~

HTTPS 環境請將 `ADMIN_COOKIE_SECURE` 設成 `true`。

### 3. 啟動服務

~~~bash
docker compose up --build -d
docker compose ps -a
~~~

第一次啟動會依序套用 Alembic migrations、匯入 1,025 筆 seed 資料並建立 embeddings，因此會比後續啟動久。`migrate`、`seed`、`embed` 成功後會顯示 `Exited (0)`；`db`、`api`、`worker` 會持續運行。

| 功能 | URL |
| --- | --- |
| Top 3 人格推薦 | <http://localhost:8000/> |
| 寶可夢圖鑑 | <http://localhost:8000/pokemon> |
| 管理後台 | <http://localhost:8000/admin> |
| Swagger UI | <http://localhost:8000/docs> |

停止服務：

~~~bash
docker compose down
~~~

這個指令會保留 PostgreSQL 與模型 volumes。完整的環境變數、資料庫操作、worker 維護和量測指令請看 [本機操作指南](docs/operations.md)；圖片上傳與 CDN URL 切換另見 [AWS artwork 發送流程](docs/aws-artwork.md)。

## API

### 公開介面

| Method | Path | 說明 |
| --- | --- | --- |
| `POST` | `/api/v1/recommendations` | 回傳三筆推薦、分數、證據與選配解釋 |
| `GET` | `/api/v1/pokemon` | 中英文搜尋、分頁、屬性與世代等篩選 |
| `GET` | `/api/v1/pokemon/{pokemon_id}` | 寶可夢詳細資料 |

~~~bash
curl --request POST http://localhost:8000/api/v1/recommendations \
  --header "Content-Type: application/json" \
  --data '{"text":"我慢熟但重視承諾，也喜歡和別人分享自己喜歡的事物。","generate_explanation":false}'
~~~

每筆結果包含 Pokémon 基本資料、圖片 URL、`semantic`／`personality`／`total` 分數、證據 lineage 與選配的繁中契合分析。完整 schema 以 Swagger UI 為準。

### 管理介面

管理 API 位於 `/api/v1/admin/*`，提供：

- 管理 session 登入與登出
- 寶可夢新增、查看、修改、停用與恢復
- index status、reindex 排程與工作進度
- 人格特質及同義詞的新增、修改、加權、停用與恢復

管理 session 使用簽章 HttpOnly cookie、`SameSite=Strict` 與 CSRF token。公開圖鑑排除 inactive Pokémon；推薦查詢還會限制 current、ready 的知識與 embeddings。

## 測試與評估

GitHub Actions 會使用 Python 3.12 與暫時的 pgvector PostgreSQL 執行 migrations 和完整測試：

~~~bash
python -m unittest discover -s tests -v
~~~

目前共有 157 個測試案例。本機未設定可丟棄的 `TEST_DATABASE_URL` 時，結果為 156 通過、1 略過；CI 會啟用 PostgreSQL importer 整合測試，執行全部 157 個案例。

### pgvector 查詢基準

以下是 2026-09-07 的單一本機開發環境快照：4,684 個 ready vectors、50 次 Top-50 查詢、`ef_search=100`。

| 模式 | Mean | p50 | p95 | QPS |
| --- | ---: | ---: | ---: | ---: |
| Exact | 5.11 ms | 4.69 ms | 6.92 ms | 195.51 |
| HNSW | 1.99 ms | 1.88 ms | 3.19 ms | 503.45 |

HNSW 平均 Recall@50 為 99.64%，最低單次 Recall@50 為 92%。數字會受到硬體、資料量與 PostgreSQL cache 影響，不代表正式環境的效能保證。

### 離線推薦基準

目前評估集只有 5 筆人工標註，作用是確認 evaluation pipeline 與追蹤改動，不能用來推論正式推薦品質。

| 指標 | 結果 |
| --- | ---: |
| Retrieval Recall@10 | 0.20 |
| MRR@10 | 0.15 |
| nDCG@10 | 0.1391 |
| Top-3 Hit Rate | 0.20 |
| Precision@3 | 0.0667 |
| 平均延遲 | 287.63 ms |

重跑 benchmark、設定品質門檻及使用可丟棄整合資料庫的方法，請見 [本機操作指南](docs/operations.md)。

## 專案結構

~~~text
.
├── .github/workflows/       # GitHub Actions CI
├── app/
│   ├── api/                 # 公開與管理 API
│   ├── db/                  # SQLAlchemy models 與 session
│   ├── repositories/        # PostgreSQL／pgvector 資料存取
│   ├── schemas/             # Pydantic request／response contracts
│   ├── services/            # retrieval、scoring、RAG、reindex、observability
│   ├── static/              # 原生 JavaScript 與 CSS
│   ├── templates/           # Jinja2 頁面
│   └── main.py              # FastAPI application factory
├── alembic/                 # schema migrations
├── docs/                    # 操作與 AWS 圖片流程
├── evaluation/              # 版本化離線推薦標註集
├── pokemon_descript/        # 1,025 筆 seed 資料
├── scripts/                 # import、embedding、worker、evaluation、AWS 工具
├── tests/                   # 單元與 PostgreSQL 整合測試
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── requirements.txt
└── requirements-aws.txt
~~~

## 已知限制

- 目前以本機 Docker Compose 為主要執行環境，尚未提供公開 HTTPS 部署。
- 離線評估集只有 5 筆標註，應先增加案例與相關性標籤，再根據指標調整排名。
- 管理後台採單一密碼，沒有多使用者角色、操作審核或 audit log。
- `/health/ready` 會檢查推薦引擎與執行期人格詞庫快照，但尚未在每次探測時查詢 DB 連線。
- `/metrics` 是 process-local 記憶體統計，程序重啟後歸零，也尚未接上 Prometheus／Grafana。
- 目前沒有 Cross-Encoder reranker；是否加入應由擴充後的評估集與延遲量測決定。

## 資料與權利聲明

- 選配的 AWS pipeline 使用本機整理自 [寶可夢官方圖鑑](https://tw.portal-pokemon.com/play/pokedex/) 的 artwork；圖片檔與上傳 manifest 不納入 repository。
- 本 repository 目前未附開源授權條款；若要允許他人使用、修改或散布，應先新增合適的 `LICENSE`。

本專案供非商業、教育與作品集展示使用。Pokémon、寶可夢名稱及相關圖像的商標與著作權屬其各自權利人所有；本專案與 Nintendo、Creatures Inc.、GAME FREAK Inc. 或 The Pokémon Company 無官方關聯。
