# 本機操作指南

這份文件集中整理環境變數、Docker 生命週期、PostgreSQL 查驗、reindex worker、測試與量測方式。第一次使用請先看 [README 的快速開始](../README.md#快速開始)。

## 環境變數

以 [`.env.example`](../.env.example) 建立本機 `.env`。`.env` 已由 `.gitignore` 排除，不應提交 API key、管理密碼或資料庫密碼。

| 變數 | 預設或範例 | 用途 |
| --- | --- | --- |
| `POSTGRES_DB` | `pokemon` | Compose 建立的 database |
| `POSTGRES_USER` | `pokemon` | Compose 建立的 database user |
| `POSTGRES_PASSWORD` | 空白、必填 | PostgreSQL 密碼；Compose 在未設定時拒絕啟動 |
| `POSTGRES_PORT` | `5432` | PostgreSQL 對外 port |
| `API_PORT` | `8000` | FastAPI 對外 port |
| `DATABASE_URL` | 依執行環境 | Alembic、CLI 與 application 的 SQLAlchemy URL |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | query 與 chunk encoder |
| `EMBEDDING_MODEL_VERSION` | `default` | embedding lineage 版本 |
| `PGVECTOR_SEARCH_MODE` | `hnsw` | `hnsw` 線上搜尋或 `exact` 基準模式 |
| `HNSW_EF_SEARCH` | `100` | HNSW 候選數，允許範圍 1–1000 |
| `HNSW_ITERATIVE_SCAN` | `strict_order` | `strict_order` 或 `relaxed_order` |
| `CROSS_ENCODER_ENABLED` | `false` | 是否啟用實驗性多語 Cross-Encoder 重排 |
| `CROSS_ENCODER_MODEL` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | Cross-Encoder model ID |
| `CROSS_ENCODER_CANDIDATE_LIMIT` | `10` | 只重排基礎排名最前面的候選，範圍 3–50 |
| `CROSS_ENCODER_WEIGHT` | `0.25` | 重排分數權重，範圍 `(0, 0.5]` |
| `CROSS_ENCODER_LATENCY_BUDGET_MS` | `250` | 單次推論接受預算；超過時沿用基礎排名 |
| `CROSS_ENCODER_BATCH_SIZE` | `10` | Cross-Encoder 推論 batch size |
| `CROSS_ENCODER_MAX_LENGTH` | `256` | query／evidence pair 的 token 上限 |
| `REINDEX_WORKER_POLL_SECONDS` | `2` | worker 沒有工作時的輪詢間隔 |
| `GEMINI_API_KEY` | 空白 | 第一順位 Gemini 契合分析的選配 key |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model ID |
| `OPENAI_API_KEY` | 空白 | Gemini 失敗時使用的 OpenAI 備援 key |
| `OPENAI_MODEL` | `gpt-5-mini` | OpenAI model ID |
| `RAG_TIMEOUT_SECONDS` | `20` | 每個外部 provider 的 timeout |
| `ADMIN_PASSWORD` | 空白 | 單一管理員密碼；空白時登入停用 |
| `ADMIN_SESSION_SECRET` | 空白 | cookie 簽章 secret，至少 32 字元 |
| `ADMIN_SESSION_TTL_SECONDS` | `28800` | 管理 session 有效秒數 |
| `ADMIN_COOKIE_SECURE` | `false` | HTTPS 環境設為 `true` |
| `POKEMON_ARTWORK_BASE_URL` | 專案 CloudFront 目錄 | importer 產生 artwork URL 時使用的 CDN 目錄 |
| `HF_TOKEN` | 空白 | 下載 Hugging Face 模型的選配 token |

Compose 會從 `POSTGRES_*` 組出容器內的 `DATABASE_URL`。從主機直接執行 Alembic 或 scripts 時，hostname 應使用 `localhost`，不能沿用容器內的 `db`。

## Docker Compose

### 啟動

~~~bash
docker compose up --build -d
docker compose ps -a
~~~

啟動依賴如下：

~~~text
db → migrate → seed → embed → api
                           └→ worker
~~~

- `migrate`：執行 `alembic upgrade head`。
- `seed`：將 CSV upsert 至 PostgreSQL，重跑不會重複建立寶可夢。
- `embed`：補齊目前 model version 尚未建立的 chunk embeddings。
- `api`：等待 embeddings 初始化成功後才啟動。
- `worker`：處理管理後台排入的 reindex jobs。

正常狀態下，`migrate`、`seed`、`embed` 是 `Exited (0)`；`db`、`api`、`worker` 保持運行。

### Log 與狀態

~~~bash
docker compose logs --tail 100 api
docker compose logs --tail 100 worker
docker compose logs --follow api worker
~~~

檢查程序與推薦引擎：

~~~bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/metrics
~~~

HTTP response 會包含 `X-Request-ID`。Request log 記錄 method、route template、status 與 duration，不讀取 request body。`/metrics` 是 process-local 記憶體統計，application restart 後會歸零。

人格詞庫異動已寫入 PostgreSQL、但目前程序無法刷新記憶體快照時，管理 API 會回傳 `202` 與 `X-Personality-Refresh-Status: pending`，`/health/ready` 同時回傳 `503`。下一次刷新成功後 readiness 會自動恢復；失敗次數與目前狀態可從 `/metrics` 查驗。

### 停止與重建

~~~bash
docker compose down
~~~

這會保留 `postgres_data` 與 `model_cache` volumes。只有在確認資料可刪除時才執行：

~~~bash
docker compose down --volumes
~~~

該指令會刪除本專案 Compose 管理的 PostgreSQL 與模型 volumes，無法靠重新啟動還原其中的本機修改。

## 從主機執行 Python 工具

### 建立環境

Windows PowerShell：

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch==2.14.0+cpu --index-url https://download.pytorch.org/whl/cpu
python -m pip install --requirement requirements.txt
~~~

macOS／Linux：

~~~bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch==2.14.0+cpu --index-url https://download.pytorch.org/whl/cpu
python -m pip install --requirement requirements.txt
~~~

### 連線設定

PowerShell：

~~~powershell
$env:DATABASE_URL = "postgresql+psycopg://pokemon:your-password@localhost:5432/pokemon"
~~~

Bash：

~~~bash
export DATABASE_URL="postgresql+psycopg://pokemon:your-password@localhost:5432/pokemon"
~~~

Python scripts 直接讀取 process environment，不會自動載入 `.env`。

## Migration、匯入與 embeddings

~~~bash
alembic current
alembic history
alembic upgrade head
python scripts/import_pokemon.py --dry-run
python scripts/import_pokemon.py
python scripts/rebuild_embeddings.py --batch-size 64
~~~

目前 migration head 是 `20260907_0007`。Importer 會驗證完整 CSV header、編號與欄位內容，可用 `--csv` 指定其他來源，也可用 `--artwork-base-url` 覆寫 artwork URL。

若要改用另一個 embedding lineage，應讓 API、worker 與重建工具使用相同的 `EMBEDDING_MODEL` 和 `EMBEDDING_MODEL_VERSION`。API 在啟動時會拒絕與 active model metadata 不一致的 encoder。

## PostgreSQL 查驗

進入 Compose database：

~~~bash
docker compose exec db psql -U pokemon -d pokemon
~~~

若修改過 `POSTGRES_USER` 或 `POSTGRES_DB`，請替換指令中的值。

列出 schema 與主要資料量：

~~~sql
\dt
\d pokemon
\d pokemon_knowledge_chunks
\d pokemon_chunk_embeddings

SELECT count(*) AS pokemon_count FROM pokemon;
SELECT count(*) AS document_count FROM pokemon_knowledge_documents;
SELECT count(*) AS chunk_count FROM pokemon_knowledge_chunks;
SELECT count(*) AS embedding_count FROM pokemon_chunk_embeddings;
~~~

檢查圖鑑與人格詞庫：

~~~sql
SELECT pokedex_number, name_zh, name_en, is_active
FROM pokemon
ORDER BY pokedex_number
LIMIT 10;

SELECT pt.vector_index, pt.name_zh, pts.term, pts.weight
FROM personality_traits AS pt
JOIN personality_trait_synonyms AS pts
  ON pts.trait_code = pt.code
WHERE pts.is_active = true
ORDER BY pt.vector_index, pts.term
LIMIT 30;
~~~

CSV 只參與 seed。Runtime 的 catalog、Dense、Lexical 與人格查詢分別走 `app/repositories/pokemon.py`、`vector.py`、`retrieval.py` 與 `personality.py`。

## Reindex worker

管理員修改圖鑑敘述後，系統建立新版 staged documents／chunks，並將工作寫入 `pokemon_reindex_jobs`。Worker 透過 `FOR UPDATE SKIP LOCKED` claim job；全部 embeddings 成功後才在交易內切換 current index。

查看佇列：

~~~sql
SELECT id, pokemon_id, status,
       progress_current, progress_total, embedded, failed,
       message, queued_at, started_at, completed_at
FROM pokemon_reindex_jobs
ORDER BY queued_at DESC
LIMIT 20;
~~~

狀態只有 `queued`、`running`、`succeeded`、`failed`。失敗不會讓未完成的 staged index 取代上一版 ready index，管理員可從後台重新排程。

Worker 維護：

~~~bash
docker compose logs --follow worker
docker compose restart worker
~~~

從主機單獨執行時，先設定 `DATABASE_URL`、model name 與 model version：

~~~bash
python scripts/reindex_worker.py
~~~

## 測試

一般本機測試：

~~~bash
python -m unittest discover -s tests -v
~~~

未設定 `TEST_DATABASE_URL` 時，PostgreSQL importer integration test 會略過。若要執行目前全部 186 個案例，請建立可丟棄的 pgvector database、啟用 `vector` extension，再設定：

PowerShell：

~~~powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://user:password@localhost/test_database"
python -m unittest discover -s tests -v
Remove-Item Env:TEST_DATABASE_URL
~~~

Bash：

~~~bash
export TEST_DATABASE_URL="postgresql+psycopg://user:password@localhost/test_database"
python -m unittest discover -s tests -v
unset TEST_DATABASE_URL
~~~

測試會在指定 database 中建立並移除獨立 schema，但該 URL 仍不可指向正式環境或含有個人資料的 database。GitHub Actions 使用一次性 PostgreSQL service 執行完整測試。

## Vector benchmark

Database 必須已有 active embedding model 與 ready vectors：

~~~bash
python scripts/benchmark_vector_search.py \
  --sample-size 50 \
  --top-k 50 \
  --warmup 5 \
  --ef-search 100 \
  --minimum-corpus-size 1000 \
  --output benchmarks/vector-search.json
~~~

工具會先用 exact search 建立 ground truth，再量測 HNSW latency、QPS 與 Recall@K。可用 `--iterative-scan strict_order` 或 `relaxed_order` 比較 filtered HNSW 行為。不同硬體、cache 狀態與 corpus 大小的結果不能直接互相比較。

## 離線推薦評估

預設資料集是 `evaluation/recommendation_cases.jsonl`，目前包含 20 種人格情境。每個候選使用三級人工相關性：`1` 為部分相關、`2` 為高度相關、`3` 為核心標註。報表同時輸出 binary recall／MRR、graded nDCG、高相關召回率與加權 Top-3 precision：

~~~bash
python scripts/evaluate_recommendations.py \
  --retrieval-k 10 \
  --output evaluation/latest-report.json
~~~

可在 CI 或調參流程設定最低門檻：

~~~bash
python scripts/evaluate_recommendations.py \
  --retrieval-k 10 \
  --min-recall 0.20 \
  --min-hit-rate 0.20
~~~

未達 `--min-recall` 或 `--min-hit-rate` 時，程式會回傳非零 exit code。這 20 筆標註適合做回歸與調參基準；正式品質判定仍應加入多位標註者、分歧紀錄與交叉覆核。

### Cross-Encoder A/B

資料庫與 ready vectors 準備完成後，可比較同一套 20 題標註的 baseline 與多語 Cross-Encoder：

~~~bash
python scripts/evaluate_cross_encoder.py \
  --candidate-limit 10 \
  --weight 0.25 \
  --min-ndcg-improvement 0.001 \
  --max-added-p95-ms 250 \
  --output evaluation/cross_encoder_benchmark.json
~~~

程式只有在 graded nDCG 達到最低改善且額外 p95 未超過預算時才回傳 `0`。版本化 CPU 報表的結果為 nDCG `0.095655 → 0.095588`（`-0.000067`），額外 p95 `993.1806 ms`，兩項門檻皆未通過，因此 `CROSS_ENCODER_ENABLED` 保持 `false`。延遲預算是在推論完成後決定是否採用結果，不能回收已花費的推論時間；正式啟用前應改用更小模型、量化、GPU 或獨立 inference service 重新測量。
