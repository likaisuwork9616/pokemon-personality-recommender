# Pokémon Personality Recommender

> 以 PostgreSQL、pgvector、Hybrid Retrieval 與 Grounded RAG，從使用者的自然語言描述中推薦 Top 3 人格相契的寶可夢。

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![pgvector](https://img.shields.io/badge/pgvector-384d-336791)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Status](https://img.shields.io/badge/MVP-complete-success)

這不是單純依照屬性或關鍵字配對的測驗。系統會把使用者描述轉為語意向量，結合中文全文搜尋、SQL 人格詞彙、可追蹤的圖鑑知識 chunks 與分數融合，最後產生三個可驗證的推薦結果。使用者可選擇是否呼叫 Gemini 或 OpenAI；模型只能根據本次檢索證據解釋契合原因。

## 目前完成的功能

- 輸入個性、興趣或生活習慣，固定取得 Top 3 寶可夢推薦
- 顯示語意分數、人格分數、總分及匹配證據
- 將圖鑑資料版本化為可追蹤的 knowledge documents 與 chunks
- 使用 pgvector Dense Search 與 jieba／PostgreSQL FTS 進行 Hybrid Retrieval
- 以 Reciprocal Rank Fusion（RRF，`k=60`）融合兩條檢索分支
- 將人格特質與中英文同義詞存入 PostgreSQL，由 SQL 搜尋匹配
- 使用 Gemini 或 OpenAI 產生有 citation allowlist 的 Grounded RAG 解釋
- 外部模型失敗、逾時、格式錯誤或引用越界時，自動使用本地證據式解釋
- 預設不永久保存使用者原始描述與 query vector
- 提供圖鑑列表、中英文名稱搜尋、分頁、屬性、世代、傳說與幻之篩選
- 提供單一管理員後台，可新增、查看、修改、停用及恢復寶可夢
- 提供人格詞庫管理介面，可修改 16 維特質名稱，新增、編輯、加權、停用與恢復中英文同義詞
- 詞彙以 NFKC／case-fold 正規化防止重複加權，revision 讓多個 API process 在下次推薦前自動刷新人格向量
- 修改敘述後建立新版文件，透過 PostgreSQL 背景佇列重建 embedding，支援即時進度、失敗重試與安全切換
- 1,025 筆寶可夢關聯資料存入 PostgreSQL
- 384 維知識 chunk embeddings 存入 pgvector
- 官方寶可夢 PNG 存放於 Amazon S3，透過 CloudFront 交付；PostgreSQL 只保存 URL
- FastAPI 自動產生 Swagger／OpenAPI 文件
- Alembic 管理 PostgreSQL schema 版本
- Docker Compose 一次完成 migration、seed、embedding 初始化與 API 啟動

### MVP 資料成果

| 項目 | 數量／狀態 |
| --- | ---: |
| 寶可夢主資料 | 1,025 筆 |
| 圖鑑描述 | 3,075 筆 |
| 圖片 URL | 2,050 筆 |
| 可追蹤知識文件 | 4,100 筆 |
| 知識 chunks | 4,684 筆 |
| pgvector embeddings | 4,684 筆 |
| 人格維度 | 16 種 |
| 中英文人格同義詞 | 230 筆 |
| 自動化測試 | 125 項 |
| 官方 artwork | 1,025 張，S3 與 CloudFront 內容雜湊驗證完成 |

## 系統架構

```mermaid
flowchart LR
    U[使用者瀏覽器] --> WEB[FastAPI + Jinja2]
    A[管理員後台] --> WEB

    WEB --> API[REST API /api/v1]
    API --> QE[Query Encoder<br/>request scope]
    QE --> D[pgvector Dense Top 50]
    API --> L[jieba + PostgreSQL FTS Top 50]
    D --> RRF[RRF Fusion]
    L --> RRF
    RRF --> PS[SQL 人格詞彙與分數融合]
    PS --> TOP3[Top 3 + 分數 + 證據]

    TOP3 -->|使用者勾選 AI 解釋| RAG[Grounded RAG]
    RAG --> LLM[Gemini 或 OpenAI]
    RAG --> FALLBACK[本地 evidence fallback]

    API <--> PG[(PostgreSQL + pgvector)]
    WEB --> CDN[CloudFront]
    CDN --> S3[(Amazon S3 Artwork)]
```

## 推薦流程

1. 驗證使用者輸入，且不在錯誤內容中回傳原文。
2. 使用 `paraphrase-multilingual-MiniLM-L12-v2` 建立 384 維 query vector。
3. 分別執行 pgvector exact cosine search 與中文斷詞全文搜尋，各取 Top 50 chunks。
4. 以 RRF 合併同一 chunk 的兩條排名，再限制每隻寶可夢最多三段證據，避免 chunks 數量灌票。
5. 從 PostgreSQL 人格字典比對輸入中的特質與同義詞，建立 16 維人格向量。
6. 合併語意與人格分數，以穩定 tie-break 規則選出唯一 Top 3。
7. 若使用者開啟 AI 解釋，將本次證據包交給指定模型；否則不呼叫任何外部 LLM。

最終分數概念如下：

```text
total = α × personality + (1 - α) × semantic
```

`α` 會依輸入中可辨識的人格訊號調整，範圍為 `0.35–0.80`。語意分數來自 Hybrid Retrieval，人格分數則是使用者與寶可夢人格向量的 cosine similarity。

## Grounded RAG 設計

推薦排名在呼叫 LLM 前就已確定，模型不參與排序，只負責說明結果。

- 每段證據都具有 `document_id`、`chunk_id`、`content_hash` 與 `evidence_id`
- 模型輸出必須符合結構化 schema
- 每個理由只能引用該推薦結果自己的 evidence ID
- 提示詞將使用者文字與檢索內容標記為不可信資料，降低 prompt injection 影響
- 英文原始檢索文字不會直接成為使用者看到的推薦理由
- 無 API key、逾時、輸出格式錯誤或 citation 無效時，改用繁體中文本地解釋
- `LLM_PROVIDER=gemini|openai` 明確選擇供應商，不會在兩家付費模型間自動轉送

## 隱私與安全

- 使用者原始描述與 query vector 只存在單次 request scope，預設不寫入 PostgreSQL
- 推薦成功、驗證失敗與例外路徑都不記錄原始輸入或向量
- 未勾選 AI 解釋時，不建立任何外部 LLM 請求
- 勾選 AI 解釋時，使用者文字與證據會傳送到所選 provider，但不寫入本專案資料庫
- 管理後台使用簽章且有期限的 HttpOnly cookie、`SameSite=Strict` 與 CSRF token
- 公開 API 與推薦流程只讀取 active、current、ready 的資料
- 圖片二進位檔、上傳 manifest、AWS 憑證、`.env` 與資料庫備份均不進 Git

## 技術棧

| 分層 | 技術 | 用途 |
| --- | --- | --- |
| Web／API | FastAPI、Uvicorn、Jinja2、原生 JavaScript | 頁面、REST API、Swagger 與管理後台 |
| Database | PostgreSQL 16、SQLAlchemy 2、psycopg | 關聯資料、交易與 repository layer |
| Vector Search | pgvector、sentence-transformers | 384 維 embeddings 與 exact cosine search |
| Text Retrieval | jieba、PostgreSQL Full Text Search | 中文斷詞與 lexical search |
| Ranking | RRF、NumPy、scikit-learn | Hybrid Retrieval 與人格分數融合 |
| RAG | Google Gen AI、OpenAI Responses API | 結構化、受證據限制的推薦解釋 |
| Migration | Alembic | schema 與種子字典版本管理 |
| Image Delivery | Amazon S3、CloudFront、boto3 | 官方 artwork 儲存、完整性驗證與 CDN 交付 |
| Deployment | Docker、Docker Compose | DB、migration、seed、embedding、背景 worker、API 編排 |
| Test | Python `unittest` | API、資料庫、檢索、隱私、RAG 與圖片流程測試 |

## 快速啟動

### 1. 需求

- Docker Desktop，並已啟用 Docker Compose v2
- 首次啟動可連線下載 Python packages 與 Hugging Face embedding model
- 至少約 4 GB 可用記憶體供 PostgreSQL、模型與 API 使用

Gemini／OpenAI API key 都是選配。未設定 key 時，推薦與本地證據式解釋仍可使用。

### 2. 建立環境設定

Windows PowerShell：

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

macOS／Linux：

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

編輯 `.env`，至少更換資料庫密碼；若要啟用管理後台，再設定管理密碼與剛產生的 session secret：

```env
POSTGRES_PASSWORD=replace-with-a-strong-password
DATABASE_URL=postgresql+psycopg://pokemon:replace-with-a-strong-password@db:5432/pokemon

ADMIN_PASSWORD=replace-with-a-strong-admin-password
ADMIN_SESSION_SECRET=replace-with-generated-random-secret
ADMIN_COOKIE_SECURE=false
```

若網站由 HTTPS 提供，請將 `ADMIN_COOKIE_SECURE=true`。

### 3. 啟動完整服務

```bash
docker compose up --build
```

Compose 會依序執行：

```text
PostgreSQL → Alembic migration → CSV seed → pgvector embedding → FastAPI + reindex worker
```

第一次啟動需要建立 1,025 筆資料與 embeddings，時間會比後續啟動長。當 readiness 回傳 `ready` 後即可使用：

| 頁面 | URL |
| --- | --- |
| Top 3 人格推薦 | <http://localhost:8000/> |
| 寶可夢圖鑑 | <http://localhost:8000/pokemon> |
| 管理後台 | <http://localhost:8000/admin> |
| Swagger UI | <http://localhost:8000/docs> |
| OpenAPI JSON | <http://localhost:8000/openapi.json> |
| Liveness | <http://localhost:8000/health/live> |
| Readiness | <http://localhost:8000/health/ready> |

背景啟動與停止：

```bash
docker compose up --build -d
docker compose down
```

`docker compose down` 不會刪除 PostgreSQL 與模型 volumes；除非確定不需要資料，請勿加入 `-v`。

## 環境變數

| 變數 | 預設值 | 說明 |
| --- | --- | --- |
| `DATABASE_URL` | Docker Compose 產生 | PostgreSQL SQLAlchemy URL |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | query 與 chunk embedding model |
| `EMBEDDING_MODEL_VERSION` | `default` | embedding lineage 版本 |
| `PGVECTOR_SEARCH_MODE` | `hnsw` | `hnsw` 近似搜尋或 `exact` 精確基準模式 |
| `HNSW_EF_SEARCH` | `100` | HNSW 查詢候選數，範圍 `1–1000` |
| `HNSW_ITERATIVE_SCAN` | `strict_order` | filtered HNSW 的迭代掃描排序模式 |
| `REINDEX_WORKER_POLL_SECONDS` | `2` | 背景 worker 查詢 PostgreSQL 佇列的間隔秒數 |
| `LLM_PROVIDER` | `gemini` | `gemini` 或 `openai` |
| `GEMINI_API_KEY` | 空白 | Gemini 選配金鑰 |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model 名稱 |
| `OPENAI_API_KEY` | 空白 | OpenAI 選配金鑰 |
| `OPENAI_MODEL` | `gpt-5-mini` | OpenAI model 名稱 |
| `RAG_TIMEOUT_SECONDS` | `20` | 外部解釋逾時秒數 |
| `POKEMON_ARTWORK_BASE_URL` | 空白 | CDN artwork 目錄；設定後 importer 產生四位數 PNG URL |
| `ADMIN_PASSWORD` | 空白 | 單一管理員密碼；空白時後台登入停用 |
| `ADMIN_SESSION_SECRET` | 空白 | 至少 32 字元的 session 簽章 secret |
| `ADMIN_COOKIE_SECURE` | `false` | HTTPS 環境應設為 `true` |
| `HF_TOKEN` | 空白 | Hugging Face 下載模型的選配 token |

## API

主要公開介面：

| Method | Path | 說明 |
| --- | --- | --- |
| `POST` | `/api/v1/recommendations` | 取得固定三筆推薦、分數、證據與選配解釋 |
| `GET` | `/api/v1/pokemon` | 搜尋、篩選、排序與分頁 |
| `GET` | `/api/v1/pokemon/{id}` | 取得寶可夢詳細資料 |
| `POST` | `/api/v1/admin/session` | 管理員登入 |
| `GET/POST/PATCH` | `/api/v1/admin/pokemon...` | 管理資料、狀態與排程重建索引 |
| `GET` | `/api/v1/admin/reindex-jobs/{job_id}` | 讀取背景 reindex 進度與結果 |
| `GET/PATCH` | `/api/v1/admin/personality/traits...` | 管理固定 16 維人格特質名稱 |
| `POST/PATCH` | `/api/v1/admin/personality/traits/{code}/synonyms...` | 新增、修改、加權、停用或恢復同義詞 |
| `GET` | `/health/live` | 程序存活檢查 |
| `GET` | `/health/ready` | DB、pgvector 與推薦引擎就緒檢查 |

推薦請求範例：

```bash
curl -X POST http://localhost:8000/api/v1/recommendations \
  -H "Content-Type: application/json" \
  -d '{
    "text": "我慢熟但重承諾，也喜歡和別人分享自己喜歡的事物。",
    "generate_explanation": false
  }'
```

每筆推薦結果包含：

```text
rank
pokemon: id、圖鑑編號、中英文名稱、屬性、圖片 URL
scores: semantic、personality、total
evidence: 文件與 chunk lineage、檢索排名、RRF 分數、匹配特質
explanation: 繁中分析、citation、provider、fallback 狀態（選配）
```

完整 request／response schema 請直接查看 `/docs`。

## 資料匯入與 Embedding

Importer 可重跑且不會建立重複寶可夢：

```bash
python scripts/import_pokemon.py --dry-run
python scripts/import_pokemon.py
```

使用 CDN 圖片目錄覆寫 artwork URL：

```bash
python scripts/import_pokemon.py \
  --artwork-base-url https://cdn.example.com/images/pokemon/artwork
```

只建立缺少、過期、失敗或 hash 不一致的 embeddings：

```bash
python scripts/rebuild_embeddings.py --batch-size 64
```

比較 exact 與 HNSW 的延遲、QPS 與 recall@K：

```bash
python scripts/benchmark_vector_search.py \
  --sample-size 50 \
  --top-k 50 \
  --ef-search 100 \
  --output benchmarks/vector-search.json
```

報告會記錄實際 corpus 大小、exact／HNSW 的 mean、p50、p95、QPS，以及以 exact Top-K 為 ground truth 的平均與最低 recall。大型資料集驗收可加上 `--minimum-corpus-size`，避免誤用小型資料庫結果作為效能結論。

目前 4,684 個 vectors、50 次 Top-50 查詢的本機基準如下；數值會受硬體、PostgreSQL cache 與資料量影響，因此應視為開發環境 baseline，而不是大型正式環境的保證值：

| 模式 | Mean | p50 | p95 | QPS |
| --- | ---: | ---: | ---: | ---: |
| Exact | 5.11 ms | 4.69 ms | 6.92 ms | 195.51 |
| HNSW | 1.99 ms | 1.88 ms | 3.19 ms | 503.45 |

HNSW 平均 recall@50 為 `99.64%`，最低單次 recall@50 為 `92%`。正式大型資料集應在目標硬體上以 `--minimum-corpus-size`、不同 `ef_search` 與代表性查詢集重新量測。

Alembic migration：

```bash
alembic upgrade head
alembic downgrade -1
```

## 查看 PostgreSQL 資料

Docker Compose 啟動後，可直接進入 PostgreSQL：

```bash
docker compose exec db psql -U pokemon -d pokemon
```

進入 `pokemon=#` 後，可使用以下指令：

```sql
-- 列出 public schema 的全部 tables
\dt

-- 查看 table 結構
\d pokemon
\d pokemon_knowledge_chunks
\d pokemon_chunk_embeddings

-- 查看寶可夢主資料
SELECT pokedex_number, name_zh, name_en
FROM pokemon
ORDER BY pokedex_number
LIMIT 10;

-- 查看目前 artwork URL
SELECT p.pokedex_number, p.name_zh, pi.image_url
FROM pokemon AS p
JOIN pokemon_images AS pi ON pi.pokemon_id = p.id
WHERE pi.image_kind = 'artwork'
ORDER BY p.pokedex_number
LIMIT 10;

-- 查看 SQL 人格同義詞
SELECT pt.name_zh, pts.term, pts.weight
FROM personality_traits AS pt
JOIN personality_trait_synonyms AS pts
  ON pts.trait_code = pt.code
ORDER BY pt.vector_index, pts.term
LIMIT 30;

-- 離開 psql
\q
```

也可使用 pgAdmin 或 DBeaver 連線：

| 設定 | 值 |
| --- | --- |
| Host | `localhost` |
| Port | `.env` 的 `POSTGRES_PORT`，預設 `5432` |
| Database | `.env` 的 `POSTGRES_DB`，預設 `pokemon` |
| Username | `.env` 的 `POSTGRES_USER`，預設 `pokemon` |
| Password | `.env` 的 `POSTGRES_PASSWORD` |

### 如何確認執行期查詢 SQL，而不是 CSV

CSV 是可重跑的初始資料來源，只在 `seed` 階段匯入 PostgreSQL；正式 API 不會在每次推薦時掃描 CSV。可從以下路徑驗證：

1. API 啟動時由 [`PokemonRepository`](app/main.py#L36-L49) 讀取 PostgreSQL；若資料庫沒有資料會直接 readiness 失敗。
2. 每次推薦都在新的 DB session 中執行 [Hybrid Retrieval 與人格 SQL 查詢](app/services/recommendation.py#L119-L137)。
3. Dense 分支透過 [pgvector cosine distance](app/repositories/vector.py#L245-L295) 搜尋 384 維 chunk embeddings。
4. Lexical 分支透過 [PostgreSQL `tsvector`、`plainto_tsquery` 與 `ts_rank_cd`](app/repositories/retrieval.py#L35-L86) 搜尋知識 chunks。
5. 人格文字透過 [`personality_traits` 與 `personality_trait_synonyms`](app/repositories/personality.py#L78-L109) 產生 16 維向量。
6. [`seed` service](docker-compose.yml#L84-L97) 完成 CSV 匯入後即結束，持續運行的只有 `api` 與 `db`。

可用以下指令確認服務生命週期：

```bash
docker compose ps -a
```

正常狀態會看到 `seed`、`migrate`、`embed` 為 `Exited (0)`，`api` 與 `db` 則保持 `Up`／`healthy`。CSV 仍應保留在專案中，因為建立全新資料庫或重新 seed 時會再次使用。

## AWS 圖片交付流程

圖片不寫入 PostgreSQL，也不提交 GitHub。資料庫只保存 CloudFront URL，S3 object key 使用可預測的四位圖鑑編號：

```text
images/pokemon/artwork/0001.png
images/pokemon/artwork/0002.png
...
images/pokemon/artwork/1025.png
```

安裝選配 AWS 依賴：

```bash
pip install -r requirements-aws.txt
```

建立含檔名、繁中名稱、尺寸、SHA-256、object key 與 delivery URL 的 manifest：

```bash
python scripts/build_pokemon_image_manifest.py \
  --bucket <your-bucket> \
  --region <your-region> \
  --delivery-base-url https://cdn.example.com
```

上傳器預設只執行本機 dry-run，不會連線 AWS：

```bash
python scripts/pokemon_s3_image_uploader.py \
  --bucket <your-bucket> \
  --region <your-region> \
  --delivery-base-url https://cdn.example.com \
  --profile <your-aws-profile>
```

先上傳一張 canary 並驗證 CloudFront，再續傳全部圖片：

```bash
python scripts/pokemon_s3_image_uploader.py \
  --bucket <your-bucket> \
  --region <your-region> \
  --delivery-base-url https://cdn.example.com \
  --profile <your-aws-profile> \
  --limit 1 --execute --verify-delivery

python scripts/pokemon_s3_image_uploader.py \
  --bucket <your-bucket> \
  --region <your-region> \
  --delivery-base-url https://cdn.example.com \
  --profile <your-aws-profile> \
  --resume --execute --verify-delivery
```

既有 S3 物件只有在大小、Content-Type 與 SHA-256 metadata 全部一致時才略過；內容衝突時停止，不會自動覆寫。

## 測試

安裝完整依賴後執行：

```bash
python -m unittest discover -s tests -v
```

目前測試涵蓋：

- FastAPI contract、422 驗證、Swagger 與健康檢查
- PostgreSQL schema、migration、import transaction 與 idempotency
- knowledge documents／chunks 的版本、hash 與 lineage
- pgvector embedding 狀態與 exact search
- jieba／FTS、RRF 與候選聚合
- 人格 SQL 字典、同義詞與分數
- 人格詞庫管理、正規化唯一性、跨 process revision refresh 與最後啟用詞保護
- Top 3 穩定排序、證據與 response schema
- 查詢隱私與例外路徑
- Grounded RAG、provider 切換、prompt injection 與 fallback
- 管理後台、cookie、CSRF、停用與恢復
- stale／ready／failed／retry embedding lifecycle
- PostgreSQL 背景 reindex queue、`SKIP LOCKED` worker 與前端進度通知
- 不含 request body 的結構化 request log、request ID 與 Prometheus metrics
- 版本化離線評估集、Recall@K、MRR、nDCG、Hit Rate 與 Precision
- AWS manifest、dry-run、resume、衝突與內容驗證
- 響應式推薦頁與圖鑑頁

PostgreSQL importer 整合測試必須指向可丟棄的測試資料庫：

```bash
TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost/test_db \
  python -m unittest discover -s tests -p test_csv_importer.py -v
```

## 專案結構

```text
.
├── app/
│   ├── api/                 # 公開與管理 API
│   ├── db/                  # SQLAlchemy models 與 session
│   ├── repositories/        # PostgreSQL／pgvector 資料存取
│   ├── schemas/             # Pydantic request／response contracts
│   ├── services/            # retrieval、scoring、RAG、import、reindex
│   ├── static/              # 原生 JavaScript 與 CSS
│   ├── templates/           # Jinja2 頁面
│   └── main.py              # FastAPI application factory
├── alembic/                 # schema migrations
├── pokemon_descript/        # 1,025 筆來源資料集
├── evaluation/              # 版本化離線推薦標註集
├── scripts/                 # import、embedding、evaluation 與 S3 圖片工具
├── tests/                   # 單元／整合測試
├── legacy/                  # 舊版 Gradio 介面
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── requirements.txt
└── requirements-aws.txt
```

## MVP 邊界與後續方向

目前版本已提供 pgvector HNSW 與 exact 基準模式；HNSW 使用 cosine operator class、filtered iterative scan 與可調整的 `ef_search`，並以 recall／延遲 benchmark 驗證品質與效能取捨。

### 可觀測性與離線品質評估

每個 HTTP response 都包含 `X-Request-ID`。`/metrics` 以 Prometheus text format 輸出低基數的 route-template 請求量與耗時；結構化 log 只記錄 request ID、method、route、status 與 duration，不讀取或記錄使用者 request body。

執行版本化的離線標註集：

```bash
python scripts/evaluate_recommendations.py --retrieval-k 10
python scripts/evaluate_recommendations.py --min-recall 0.50 --min-hit-rate 0.60 --output evaluation-report.json
```

報告包含 retrieval Recall@K／MRR／nDCG、Top‑3 Hit Rate／Precision／MRR 與延遲統計。輸出只包含 case ID 與指標，不回寫資料庫，也不輸出 query 文字；門檻未達時 CLI 以非零狀態結束，可直接接入 CI。

目前 5 筆初始人工標註集的 baseline（2026-09-07、4,684 個 ready vectors）為 Recall@10 `0.20`、MRR@10 `0.15`、nDCG@10 `0.1391`、Top‑3 Hit Rate `0.20`，平均單次延遲約 `287.63 ms`。這組低基準值被保留為後續調整詞庫、標註與 ranking 的可量化起點，不宣稱已達正式推薦品質門檻。

後續可擴充：

- 公開環境部署、HTTPS 與自動化 CI/CD
- 人格詞庫變更審核、操作歷程與角色權限分級

## 免責聲明

本專案為非商業、教育與作品集用途。Pokémon、寶可夢名稱及相關圖像之商標與著作權均屬其各自權利人所有，本專案與 Nintendo、Creatures Inc.、GAME FREAK Inc. 或 The Pokémon Company 無官方關聯。
