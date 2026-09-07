# Pokémon Personality Recommender

> 以 FastAPI、PostgreSQL／pgvector 與可選 Grounded RAG 實作的繁中寶可夢人格推薦系統。輸入一段自然語言描述後，系統會回傳三筆推薦、分數與可追蹤的檢索證據。

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141.1-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![pgvector](https://img.shields.io/badge/pgvector-HNSW%20%7C%20exact-336791)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)

系統把語意檢索、中文全文搜尋與 SQL 人格詞庫合併計分，再從版本化的圖鑑知識中整理推薦證據。使用者可選擇是否產生 AI 解釋；實際 provider 由伺服器設定，呼叫失敗時自動改用本地 fallback。

## 目錄

- [專案重點](#專案重點)
- [系統架構](#系統架構)
- [推薦如何運作](#推薦如何運作)
- [資料模型](#資料模型)
- [已驗證成果](#已驗證成果)
- [快速啟動](#快速啟動)
- [API](#api)
- [開發與驗證](#開發與驗證)
- [專案結構](#專案結構)
- [已知限制與下一步](#已知限制與下一步)

## 專案重點

- 固定回傳 Top 3，包含語意分數、人格分數、總分與匹配證據。
- Dense Retrieval 預設使用 pgvector HNSW，並保留 exact 模式作為品質與效能基準。
- Lexical Retrieval 使用 jieba 斷詞與 PostgreSQL Full Text Search，再以 RRF 融合兩路排名。
- 圖鑑內容拆成可追蹤的 documents／chunks，保留來源、版本、雜湊與 current 狀態。
- PostgreSQL 背景工作佇列負責 reindex；新版索引成功後才原子切換，失敗不影響既有推薦。
- 16 維人格特質與中英文同義詞由管理後台維護，API process 依 revision 自動刷新。
- 原始個性文字與 query vector 預設不持久化；request log 不讀取 request body。

## 系統架構

~~~mermaid
flowchart LR
    U[使用者] --> UI[FastAPI + Jinja2 UI]
    ADM[管理員] --> UI
    UI --> API[REST API /api/v1]

    API --> ENC[384d Query Encoder]
    ENC --> D[Dense Top 50<br/>pgvector HNSW / exact]
    API --> L[jieba + PostgreSQL FTS<br/>Lexical Top 50]
    D --> RRF[RRF k=60]
    L --> RRF
    RRF --> P[SQL 人格向量融合]
    P --> T[Top 3 + 分數 + 證據]

    T -->|使用者選擇 AI 解釋| RAG[Grounded RAG]
    RAG --> PROVIDER[Gemini 或 OpenAI]
    RAG -->|無 key、逾時或驗證失敗| FB[本地 evidence fallback]

    API <--> DB[(PostgreSQL 16 + pgvector)]
    API --> Q[(Reindex Job Queue)]
    W[Background Worker] -->|SKIP LOCKED| Q
    W --> S[建立 staged documents / chunks / embeddings]
    S -->|成功後原子切換| DB

    API --> O[X-Request-ID<br/>Structured Logs<br/>Prometheus Metrics]
    UI -->|設定 CDN artwork 時| CDN[CloudFront]
    CDN --> S3[(Amazon S3 Artwork)]
~~~

## 推薦如何運作

1. FastAPI 先驗證輸入，再交由推薦服務處理。
2. SentenceTransformer 將文字編碼成 384 維向量。
3. pgvector Dense Search 與 jieba／PostgreSQL FTS 各取 Top 50 chunks。
4. RRF（<code>k=60</code>）融合排名，並限制每隻寶可夢最多保留三段證據，降低 chunk 數量造成的偏差。
5. SQL 人格詞庫將輸入映射為 16 維人格向量，與寶可夢人格向量計算相似度。
6. 系統依固定 tie-break 規則完成 Top 3 排名，再視使用者選擇產生解釋。

總分公式：

~~~text
total = α × personality + (1 - α) × semantic
~~~

<code>α</code> 會依輸入中辨識到的人格訊號調整，範圍為 <code>0.35–0.80</code>。語意分數來自 Hybrid Retrieval，人格分數則使用 cosine similarity。

### Grounded RAG 與隱私界線

- 排名在 LLM 呼叫前完成，切換 provider 或關閉 AI 解釋不會改變 Top 3。
- 每段證據都有 <code>document_id</code>、<code>chunk_id</code>、<code>content_hash</code> 與 <code>evidence_id</code>。
- 模型回應必須符合結構化 schema，citation 只能引用該結果的 allowlist。
- 無 API key、逾時、格式錯誤或 citation 無效時，回傳 deterministic 本地繁中解釋。
- 未勾選 AI 解釋時，不會建立任何外部 LLM 請求。
- 勾選後，文字與證據會送往所選 provider，但不寫入本專案的 PostgreSQL。
- 成功、驗證失敗與例外路徑都不記錄原始描述或 query vector。

## 資料模型

| 資料表 | 用途 |
| --- | --- |
| <code>pokemon</code> | 寶可夢主資料、狀態與基本分類 |
| <code>pokemon_descriptions</code>、<code>pokemon_images</code> | 多來源描述與圖片 URL |
| <code>pokemon_knowledge_documents</code> | 版本化知識文件、來源與內容雜湊 |
| <code>pokemon_knowledge_chunks</code> | 可引用的檢索片段與 lineage |
| <code>embedding_models</code>、<code>pokemon_chunk_embeddings</code> | 384 維模型 metadata 與 pgvector embeddings |
| <code>personality_traits</code>、<code>personality_trait_synonyms</code> | 16 維人格定義、同義詞與權重 |
| <code>personality_vocabulary_state</code> | 跨 process 詞庫 revision |
| <code>pokemon_reindex_jobs</code> | durable 背景工作、進度、錯誤與重試狀態 |

## 關鍵工程決策

| 決策 | 原因 |
| --- | --- |
| LLM 只負責解釋 | 排名可重現，也能在沒有付費模型時完整運作 |
| HNSW 作為線上預設、exact 作為基準 | 兼顧查詢速度與可量測的 recall |
| 使用 PostgreSQL durable queue | 不額外引入 Redis，工作狀態與產品資料共用交易邊界 |
| 版本化文件後再切換 current index | reindex 失敗時繼續使用上一版 ready 索引 |
| 人格詞庫存入 SQL | 同義詞、權重與啟用狀態可由後台調整，不必修改程式碼 |
| 查詢資料不持久化 | 降低保存個人描述與向量帶來的隱私風險 |

## 已驗證成果

### 初始資料規模

| 項目 | 數量 |
| --- | ---: |
| 寶可夢主資料 | 1,025 |
| 圖鑑描述 | 3,075 |
| 圖片 URL | 2,050 |
| 知識文件 | 4,100 |
| 知識 chunks／embeddings | 4,684 |
| 人格維度 | 16 |

本機圖片與 manifest 位於 <code>pk_pic/</code>，連同 <code>.env</code> 都由 <code>.gitignore</code> 排除。AWS 憑證與資料庫備份不應放入 repository。

### pgvector 查詢基準

以下是 2026-09-07 的單一本機開發環境快照：4,684 個 ready vectors、50 次 Top-50 查詢、<code>ef_search=100</code>。結果會受到硬體、資料量與 PostgreSQL cache 影響，不代表正式環境的效能保證。

| 模式 | Mean | p50 | p95 | QPS |
| --- | ---: | ---: | ---: | ---: |
| Exact | 5.11 ms | 4.69 ms | 6.92 ms | 195.51 |
| HNSW | 1.99 ms | 1.88 ms | 3.19 ms | 503.45 |

HNSW 平均 Recall@50 為 99.64%，最低單次 Recall@50 為 92%。

### 離線推薦基準

目前版本化評估集只有 5 筆人工標註，適合用來確認 evaluation pipeline 與追蹤改動方向，不能視為正式推薦品質結論。

| 指標 | 結果 |
| --- | ---: |
| Retrieval Recall@10 | 0.20 |
| MRR@10 | 0.15 |
| nDCG@10 | 0.1391 |
| Top-3 Hit Rate | 0.20 |
| Precision@3 | 0.0667 |
| 平均延遲 | 287.63 ms |

這組低基準會作為後續擴充標註集、調整詞庫與 ranking 的比較起點。

## 快速啟動

### 需求

- Docker Desktop 與 Docker Compose v2
- 首次啟動可連線下載 Python packages 與 Hugging Face embedding model
- 約 4 GB 可用記憶體

Gemini／OpenAI API key 為選配；未設定時，推薦與本地證據式解釋仍可使用。

### 1. 建立環境設定

Windows PowerShell：

~~~powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
~~~

macOS／Linux：

~~~bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
~~~

編輯 <code>.env</code>，至少更換 PostgreSQL 密碼。若要啟用管理後台，<code>ADMIN_PASSWORD</code> 與至少 32 字元的 <code>ADMIN_SESSION_SECRET</code> 必須同時設定：

~~~env
POSTGRES_PASSWORD=replace-with-a-strong-password

ADMIN_PASSWORD=replace-with-a-strong-admin-password
ADMIN_SESSION_SECRET=replace-with-generated-random-secret
ADMIN_COOKIE_SECURE=false
~~~

HTTPS 環境請將 <code>ADMIN_COOKIE_SECURE</code> 設為 <code>true</code>。

### 2. 啟動完整服務

~~~bash
docker compose up --build -d
docker compose ps -a
~~~

Compose 會依序執行：

~~~text
PostgreSQL → Alembic migration → CSV seed → pgvector embedding
                                      └→ FastAPI API + reindex worker
~~~

<code>migrate</code>、<code>seed</code>、<code>embed</code> 成功後會顯示 <code>Exited (0)</code>；<code>db</code>、<code>api</code>、<code>worker</code> 則持續運行。第一次初始化模型與 embeddings 會比後續啟動久。

### 3. 開啟服務

| 功能 | URL |
| --- | --- |
| Top 3 人格推薦 | <http://localhost:8000/> |
| 寶可夢圖鑑 | <http://localhost:8000/pokemon> |
| 管理後台 | <http://localhost:8000/admin> |
| Swagger UI | <http://localhost:8000/docs> |
| OpenAPI JSON | <http://localhost:8000/openapi.json> |
| Liveness／Readiness | <http://localhost:8000/health/live> ／ <http://localhost:8000/health/ready> |
| Prometheus metrics | <http://localhost:8000/metrics> |

停止服務：

~~~bash
docker compose down
~~~

此指令不會刪除 PostgreSQL 與模型 volumes。只有在確定資料可移除時才使用 <code>docker compose down -v</code>。

## 常用環境變數

基礎範例請看 [.env.example](.env.example)。

| 變數 | 預設值 | 說明 |
| --- | --- | --- |
| <code>POSTGRES_DB／POSTGRES_USER</code> | <code>pokemon／pokemon</code> | Compose 建立的 database 與使用者 |
| <code>POSTGRES_PASSWORD</code> | 必須更換 | Compose 的 PostgreSQL 密碼 |
| <code>POSTGRES_PORT</code> | <code>5432</code> | PostgreSQL 對外 port |
| <code>API_PORT</code> | <code>8000</code> | API 對外 port |
| <code>DATABASE_URL</code> | 依環境 | 本機 CLI／測試使用；Compose 服務會由 <code>POSTGRES_*</code> 組出容器內 URL |
| <code>EMBEDDING_MODEL</code> | <code>paraphrase-multilingual-MiniLM-L12-v2</code> | query 與 chunk encoder |
| <code>EMBEDDING_MODEL_VERSION</code> | <code>default</code> | embedding lineage 版本 |
| <code>PGVECTOR_SEARCH_MODE</code> | <code>hnsw</code> | <code>hnsw</code> 線上搜尋或 <code>exact</code> 基準模式 |
| <code>HNSW_EF_SEARCH</code> | <code>100</code> | HNSW 候選數，範圍 1–1000 |
| <code>HNSW_ITERATIVE_SCAN</code> | <code>strict_order</code> | filtered HNSW 掃描模式 |
| <code>REINDEX_WORKER_POLL_SECONDS</code> | <code>2</code> | worker 輪詢工作佇列的間隔 |
| <code>LLM_PROVIDER</code> | <code>gemini</code> | <code>gemini</code> 或 <code>openai</code> |
| <code>GEMINI_API_KEY／OPENAI_API_KEY</code> | 空白 | 外部解釋的選配金鑰 |
| <code>RAG_TIMEOUT_SECONDS</code> | <code>20</code> | 外部解釋逾時秒數 |
| <code>ADMIN_PASSWORD</code> | 空白 | 單一管理員密碼；空白時登入停用 |
| <code>ADMIN_SESSION_SECRET</code> | 空白 | 至少 32 字元的 cookie 簽章 secret |
| <code>ADMIN_SESSION_TTL_SECONDS</code> | <code>28800</code> | 管理 session 有效秒數 |
| <code>ADMIN_COOKIE_SECURE</code> | <code>false</code> | HTTPS 環境設為 <code>true</code> |
| <code>POKEMON_ARTWORK_BASE_URL</code> | 空白 | importer 產生四位數 artwork URL 的 CDN 目錄 |
| <code>HF_TOKEN</code> | 空白 | 下載 Hugging Face 模型的選配 token |

## API

### 公開介面

| Method | Path | 說明 |
| --- | --- | --- |
| <code>POST</code> | <code>/api/v1/recommendations</code> | 固定三筆推薦、分數、證據與選配解釋 |
| <code>GET</code> | <code>/api/v1/pokemon</code> | 搜尋、篩選、固定穩定排序與分頁 |
| <code>GET</code> | <code>/api/v1/pokemon/{pokemon_id}</code> | 寶可夢詳細資料 |
| <code>GET</code> | <code>/health/live</code> | 程序存活檢查 |
| <code>GET</code> | <code>/health/ready</code> | 啟動階段是否已建立推薦引擎 |
| <code>GET</code> | <code>/metrics</code> | Prometheus text format；不列入 OpenAPI schema |

<code>POST /recommend</code> 仍保留為 deprecated 相容端點，新整合應使用 <code>/api/v1/recommendations</code>。

PowerShell 請求範例：

~~~powershell
$body = @{
    text = "我慢熟但重承諾，也喜歡和別人分享自己喜歡的事物。"
    generate_explanation = $false
} | ConvertTo-Json

$request = @{
    Method = "Post"
    Uri = "http://localhost:8000/api/v1/recommendations"
    ContentType = "application/json"
    Body = $body
}
Invoke-RestMethod @request
~~~

每筆結果包含 Pokémon 基本資料與圖片 URL、<code>semantic</code>／<code>personality</code>／<code>total</code> 分數、document／chunk lineage、evidence IDs，以及選配的繁中解釋。完整 request／response schema 請查看 Swagger UI。

### 管理介面

| 範圍 | 主要能力 |
| --- | --- |
| <code>/api/v1/admin/session</code> | 登入、確認 session、登出 |
| <code>/api/v1/admin/pokemon</code> | 新增、查看、修改、停用與恢復 Pokémon |
| <code>.../index-status</code>、<code>.../reindex</code> | 讀取索引狀態與排程重建 |
| <code>/api/v1/admin/reindex-jobs/{job_id}</code> | 查詢背景工作進度與結果 |
| <code>/api/v1/admin/personality/traits</code> | 修改 16 維特質顯示名稱 |
| <code>.../traits/{trait_code}/synonyms</code> | 新增、修改、加權、停用與恢復同義詞 |

管理 API 使用簽章 HttpOnly cookie、<code>SameSite=Strict</code> 與 CSRF token。圖鑑列表排除 inactive Pokémon；推薦檢索會再限制 current、ready 的知識與 embeddings。

## 開發與驗證

### 本機 Python 環境

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
~~~

### Migration、匯入與 embedding

從主機直接執行 CLI 時，請先使用 <code>localhost</code> 設定連線；Python scripts 不會自動載入 <code>.env</code>：

~~~powershell
$env:DATABASE_URL = "postgresql+psycopg://pokemon:replace-with-a-strong-password@localhost:5432/pokemon"
alembic upgrade head
python scripts/import_pokemon.py --dry-run
python scripts/import_pokemon.py
python scripts/rebuild_embeddings.py --batch-size 64
~~~

目前 Alembic head 為 <code>20260907_0007</code>。Importer 可用 <code>--csv</code> 指定來源且可重跑，正式 API 的執行期資料來源仍是 PostgreSQL。

### 測試

~~~powershell
python -m unittest discover -s tests -v
~~~

測試套件共有 146 個案例；未設定可丟棄的整合測試資料庫時，預期 145 通過、1 略過。涵蓋 API contract、migration／import、Hybrid Retrieval、人格詞庫、隱私、Grounded RAG、後台安全、reindex queue、可觀測性、離線評估與 S3 圖片工具。

需要執行 PostgreSQL importer 整合測試時：

~~~powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://user:password@localhost/test_db"
python -m unittest discover -s tests -p test_csv_importer.py -v
Remove-Item Env:TEST_DATABASE_URL
~~~

測試資料庫必須可丟棄，請勿指向正式或個人資料庫。

### 效能與品質量測

~~~powershell
python scripts/benchmark_vector_search.py --sample-size 50 --top-k 50 --ef-search 100 --output benchmarks/vector-search.json
python scripts/evaluate_recommendations.py --retrieval-k 10 --output evaluation-report.json
~~~

Benchmark 可加上 <code>--minimum-corpus-size</code>，避免把小型語料結果當成大型資料集結論。Evaluation 可使用 <code>--min-recall</code> 與 <code>--min-hit-rate</code> 設定門檻；未達門檻時會回傳非零 exit code。

<details>
<summary><strong>查看 PostgreSQL tables，並確認 API 不是直接搜尋 CSV</strong></summary>

Compose 啟動後進入 PostgreSQL：

~~~powershell
docker compose exec db psql -U pokemon -d pokemon
~~~

常用查詢：

~~~sql
\dt
\d pokemon
\d pokemon_knowledge_chunks
\d pokemon_chunk_embeddings

SELECT pokedex_number, name_zh, name_en
FROM pokemon
ORDER BY pokedex_number
LIMIT 10;

SELECT pt.name_zh, pts.term, pts.weight
FROM personality_traits AS pt
JOIN personality_trait_synonyms AS pts
  ON pts.trait_code = pt.code
WHERE pts.is_active = true
ORDER BY pt.vector_index, pts.term
LIMIT 30;
~~~

CSV 只在一次性的 <code>seed</code> 階段匯入資料。API 透過 [repositories](app/repositories/) 查詢 PostgreSQL；Dense 分支使用 [pgvector repository](app/repositories/vector.py)，Lexical 分支使用 [PostgreSQL FTS repository](app/repositories/retrieval.py)，人格比對則讀取 [SQL personality repository](app/repositories/personality.py)。

執行 <code>docker compose ps -a</code> 時，正常狀態是 <code>migrate</code>、<code>seed</code>、<code>embed</code> 已 <code>Exited (0)</code>，<code>db</code>、<code>api</code>、<code>worker</code> 保持運行。CSV 需要留在 repository，因為建立空資料庫時仍會用它 seed。

也可用 pgAdmin 或 DBeaver 連至 <code>localhost</code>、<code>POSTGRES_PORT</code>，並使用 <code>POSTGRES_DB／USER／PASSWORD</code> 中的設定。
</details>

<details>
<summary><strong>AWS artwork manifest、上傳與 CloudFront 驗證</strong></summary>

圖片不寫入 PostgreSQL，也不提交 GitHub；資料庫只保存 URL。Fresh clone 不含被忽略的圖片輸入，執行前需自行準備 <code>pk_pic/</code> 內的 1,025 張 PNG 與 <code>pk_pic/_manifest.csv</code>。Object key 採固定格式：

~~~text
images/pokemon/artwork/0001.png
...
images/pokemon/artwork/1025.png
~~~

安裝選配套件並建立 manifest：

~~~powershell
python -m pip install -r requirements-aws.txt
python scripts/build_pokemon_image_manifest.py --bucket "your-bucket" --region "your-region" --delivery-base-url "https://cdn.example.com"
~~~

上傳器預設為 dry-run，不連 AWS。正式執行前先上傳一張 canary，確認 CloudFront 的 HTTP status、Content-Type 與 SHA-256，再使用 resume：

~~~powershell
python scripts/pokemon_s3_image_uploader.py --bucket "your-bucket" --region "your-region" --delivery-base-url "https://cdn.example.com" --profile "your-profile"
python scripts/pokemon_s3_image_uploader.py --bucket "your-bucket" --region "your-region" --delivery-base-url "https://cdn.example.com" --profile "your-profile" --limit 1 --execute --verify-delivery
python scripts/pokemon_s3_image_uploader.py --bucket "your-bucket" --region "your-region" --delivery-base-url "https://cdn.example.com" --profile "your-profile" --resume --execute --verify-delivery
~~~

既有 object 只有在大小、Content-Type 與 SHA-256 metadata 相符時才略過；內容衝突會停止，不會自動覆蓋。產生的 manifest 與結果檔只留在本機。
</details>

## 專案結構

~~~text
.
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
├── evaluation/              # 版本化離線推薦標註集
├── pokemon_descript/        # 1,025 筆 seed 資料
├── scripts/                 # import、embedding、worker、evaluation、AWS 工具
├── tests/                   # 單元與整合測試
├── legacy/                  # 舊版 Gradio 介面
├── pokedex_online.py        # 目前推薦引擎的組裝與相容層
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── requirements.txt
└── requirements-aws.txt
~~~

## 已知限制與下一步

- 目前以本機 Docker Compose 為主，尚未提供公開 HTTPS 環境與 CI/CD pipeline。
- 離線評估集僅 5 筆標註，需先擴充案例與相關性標籤，再進行排名調參。
- 管理後台是單一密碼模式，尚無多使用者角色、操作審核與 audit log。
- <code>/health/ready</code> 反映啟動時的推薦引擎狀態，尚未持續探測執行中的 DB 連線。
- <code>/metrics</code> 為 process-local、記憶體內統計，程序重啟後會歸零；正式環境可接 Prometheus／Grafana。
- 目前沒有 Cross-Encoder reranker，可在評估集擴充後比較品質與延遲成本。

## 資料與權利聲明

- 初始資料由專案整理的 [pokemon_descript/pokedex_final.csv](pokemon_descript/pokedex_final.csv) 匯入；目前尚未附每個欄位的來源與授權 metadata，公開散布資料集前應先補齊 provenance。
- Seed CSV 的 artwork URL 指向 52Poké Wiki，sprite URL 指向 PokeAPI GitHub assets。設定 <code>POKEMON_ARTWORK_BASE_URL</code> 後，importer 會將 artwork 改為指定 CDN URL。
- 選配的 AWS pipeline 使用本機整理自 [寶可夢官方圖鑑](https://tw.portal-pokemon.com/play/pokedex/) 的 artwork；圖片檔與上傳 manifest 不納入 repository。
- 本 repository 目前未附開源授權條款；若要允許他人使用、修改或散布，應先新增合適的 <code>LICENSE</code>。

本專案供非商業、教育與作品集展示使用。Pokémon、寶可夢名稱及相關圖像的商標與著作權屬其各自權利人所有；本專案與 Nintendo、Creatures Inc.、GAME FREAK Inc. 或 The Pokémon Company 無官方關聯。
