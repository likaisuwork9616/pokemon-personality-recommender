# 系統架構與推薦流程

[文件索引](README.md) · [返回專案首頁](../README.md)

本文件說明推薦排名、Grounded RAG、今日寶可夢、資料版本與服務邊界。操作指令請看[本機操作指南](operations.md)。

## 設計原則

1. 排名由可重現的檢索與評分流程決定，外部 LLM 不能改名次或分數。
2. 所有解說只能引用當次推薦結果的 evidence allowlist。
3. Gemini、OpenAI 都不可用時，核心推薦仍以本機 evidence-only fallback 完成。
4. CSV 只負責空資料庫初始化；runtime 查詢都從 PostgreSQL 取得。
5. 新索引全部 ready 後才原子切換，不讓半套 embeddings 進入正式查詢。

## 系統概觀

```mermaid
flowchart TB
    USER[使用者] --> WEB[Web UI]
    ADMIN[管理員] --> ADMIN_UI[RBAC 管理後台]
    WEB --> API[FastAPI /api/v1]
    ADMIN_UI --> API

    API --> DENSE[pgvector Dense Retrieval]
    API --> FTS[PostgreSQL FTS + jieba]
    DENSE --> RRF[RRF 融合]
    FTS --> RRF
    RRF --> SCORE[人格與屬性加權]
    SCORE --> TOP3[穩定 Top 3]

    TOP3 --> PACKET[Evidence Packet]
    PACKET --> GEMINI[Gemini]
    GEMINI -->|失敗| OPENAI[OpenAI]
    OPENAI -->|失敗| LOCAL[本機證據分析]

    API <--> DB[(PostgreSQL 16 + pgvector)]
    WORKER[Reindex Worker] --> STAGED[Staged documents / chunks / embeddings]
    STAGED -->|原子切換| DB

    API --> METRICS[/metrics]
    METRICS --> PROM[Prometheus]
    PROM --> GRAFANA[Grafana]
    PROM --> ALERT[Alertmanager]
    WEB --> CDN[Artwork CDN]
```

## 初始化與執行期資料

空資料庫第一次啟動的順序為：

```text
PostgreSQL → Alembic migration → 匯入 1,025 筆 seed → 建立 embeddings → API / worker
```

服務啟動後，下列內容直接從 PostgreSQL 讀取：

- 寶可夢與繁中圖鑑資料
- 16 維人格特質、同義詞與權重
- knowledge documents、chunks 與 embeddings
- current／staged index 狀態
- 管理 Audit Log
- 多人評估標註與仲裁結果
- 隱私最小化推薦收據與 bounded feedback

CSV 移除或更名不影響已完成初始化的資料庫，但會讓新的空環境無法重新 seed。

## 推薦流程

1. FastAPI 依 schema 驗證輸入與長度。
2. SentenceTransformer 將描述轉成正規化 384 維向量。
3. pgvector Dense Retrieval 與中文全文搜尋各取候選 chunks。
4. RRF（`k=60`）融合 Dense 與 Lexical 排名。
5. 結果按寶可夢聚合，每隻最多保留三段證據，避免 chunk 數量灌票。
6. SQL 人格詞庫把描述映射成 16 維訊號，再加入主、副屬性參考權重。
7. 以寶可夢 ID 作最終 tie-break，產生可重現的 Top 3。
8. 只有 Top 1 進入 Grounded RAG；說明生成不能改變排名。

### 分數融合

```text
total = α × personality + (1 - α) × semantic
```

`α` 依辨識到的人格訊號調整，範圍為 `0.35–0.80`。Cross-Encoder 位於融合後的選配實驗路徑；目前版本化 CPU benchmark 未同時通過品質與延遲門檻，因此預設關閉。

### Evidence lineage

每段推薦證據都保存：

```text
document_id
chunk_id
content_hash
evidence_id
```

這些欄位可追溯當次使用的知識版本。外部模型只能引用該結果的 `evidence_id` allowlist；格式、語言或引用驗證失敗時，輸出會被捨棄並進入下一層 fallback。

### Grounded RAG 備援順序

```text
Gemini → OpenAI → 本機 evidence-only fallback
```

- API 的 `generate_explanation` 預設為 `false`。
- Web 推薦頁會要求 Top 1 說明，因此設定付費 provider key 後可能產生費用。
- OpenAI 請求設定 `store=false`。
- prompt、原始人格描述與 provider exception 不寫入應用程式 log。
- 任何說明失敗都不會改變已完成的 Top 3。

## 今日寶可夢

「今日寶可夢」以 `Asia/Taipei` 擷取一次完整時間快照，並在本機換算國曆、農曆、節氣與傳統時辰。十二星座的元素、模式與特質，以及節氣、月相區間和時辰五行，都會映射至同一套人格及屬性訊號。

系統先用 Hybrid Retrieval 取得十隻相關候選，再以 `90%` 正規化相關性與 `10%` 日期／時辰穩定雜湊選出代表寶可夢。同一星座在同一日期與時辰內會得到相同結果；四面向運勢與行動提醒由本機版本化規則產生，定位為娛樂內容。

## Reindex 與一致性

管理端修改圖鑑內容後會建立 staged documents、chunks 與 embeddings。Worker 使用 PostgreSQL job queue claim 工作，只有在所有新 embeddings ready 時，才在單一交易中切換 current index。失敗工作會保留狀態供重試，舊 current index 繼續服務。

## 隱私與可觀測性

- 原始人格描述與 query vector 只存在 request scope。
- 匿名回饋不保存自由文字、IP、User-Agent 或帳號識別。
- `/health/live` 只檢查程序；`/health/ready` 另外執行 bounded database round-trip。
- `/metrics` 使用固定 route labels，避免把使用者輸入變成 metric label。
- 正式環境由 Caddy 封鎖公開 `/metrics`，Prometheus 只從內部網路 scrape。
- Rate limit 的來源識別以程序內隨機金鑰雜湊，不寫入資料庫或 log。

## 正式環境網路邊界

```text
Internet → Caddy :80/:443 → API
                         ├→ internal data network → PostgreSQL
                         └→ internal observability network → Prometheus
```

- PostgreSQL 與 API 不發布 host port。
- Prometheus、Grafana、Alertmanager 只綁 host loopback。
- Caddy 是唯一公開服務，並封鎖 `/metrics`、限制 request body。
- Uvicorn 只信任固定 Caddy 位址帶來的 forwarded headers。
- 模型下載與通知各自使用獨立 egress network。

實際部署、備份與回退方式見[正式環境部署文件](production.md)。
