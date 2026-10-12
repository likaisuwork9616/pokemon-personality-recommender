# MBTI SQL 與程式修改代辦清單

本次以程式內建、版本化 JSON 提供 MBTI 配對；不執行本文件的 SQL，不修改資料庫、seed、索引或既有寶可夢文件。回家接續時逐項勾選，完成前請保留未勾選狀態。原有需要 `TEST_DATABASE_URL` 的匯入整合測試，這次本機仍略過。

## 本次已完成

- [x] **建立接續清單**（順序 1）。目的：記錄資料庫與程式的接續工作。SQL／migration：無。程式：本文件。驗證：逐項包含目的、變更、執行順序、驗證及回退。回退：還原本文件的 Git 版本。

> 下列本次工作待實際完成與驗證後，再同步勾選並補上實際檔名。

- [ ] **建立內建 MBTI 資料與來源**（順序 2）。目的：不依賴舊人格資料表即可取得 16 型完整描述。SQL／migration：無。程式：`docs/mbti-research.md`、`app/data/mbti_zh_hant.json`、`app/services/mbti_catalog.py`。驗證：16 型唯一性、必要描述、合法關鍵詞權重、來源與版本測試。回退：還原此功能分支的資料與 loader。
- [ ] **完成共用配對與 API**（順序 3）。目的：文字必填、MBTI 選填，使用同一份人格快照計分。SQL／migration：僅讀取現有 current／ready 文件與同模型向量，不建表、不寫入。程式：`app/services/mbti_scoring.py`、`app/repositories/mbti_profiles.py`、`app/services/personality_profile.py`、`app/services/recommendation.py`、`app/main.py`、`app/api/v1.py`、`app/api/personality.py`、相關 schemas。驗證：替代 session／encoder 測試、計分與排序案例、無寫入斷言。回退：部署原功能版本；既有資料與索引不需還原。
- [ ] **完成前台、唯讀後台與契合分析**（順序 4）。目的：顯示 16 型細節，停用舊人格寫入，說明只引用該寶可夢證據。SQL／migration：無。程式：`app/templates/`、`app/static/`、`app/api/admin.py`、`app/services/rag.py`。驗證：前台／後台／RAG 測試、舊寫入 API 在 commit 前拒絕。回退：還原應用版本。
- [ ] **完成驗證與文件同步**（順序 5）。目的：交付可追溯版本。SQL／migration：無。程式：`tests/`、`evaluation/`、`README.md`、本文件、CI。驗證：完整本機測試（資料庫整合項目略過）、功能分支 CI；小步中文 commit 與 push。回退：Git 還原；不修改資料庫。

## 回家後待完成

### 1. 確認環境與備份

- [ ] **核對版本與資料庫 revision**。目的：避免在錯誤分支或資料庫遷移。順序：先核對 Git commit／PR，再設定家中資料庫，最後讀取 revision。SQL／migration：只讀 `SELECT version_num FROM alembic_version;`；本次程式的 migration head 為 `20260907_0007`，執行 `alembic heads`、`alembic current` 比對，若已不同先檢查新 migration，不直接套用本文 revision。程式：檢查 `alembic/versions/`、`app/core/config.py` 及 `.env` 的連線目的地（不可提交密碼）。驗證：revision 與備份時間記錄在執行筆記。回退：尚未變更；發現不同即停止遷移。
- [ ] **建立可還原備份與獨立測試資料庫**。目的：保留舊人格、寶可夢、文件與向量。順序：備份→在另一資料庫試還原→執行測試。SQL／migration：以 `pg_dump`／`pg_restore` 保存並還原至獨立資料庫，啟用所需 pgvector extension；不可將正式資料庫 URL 填入 `TEST_DATABASE_URL`。程式：為本機整合測試設定獨立 `TEST_DATABASE_URL`；`DATABASE_URL` 仍指向預期開發資料庫。驗證：測試庫名稱與 host 明確不同，備份可還原，`python -m unittest discover -s tests -v` 在測試庫執行。回退：移除一次性測試庫；正式庫不受影響。

### 2. 建立 MBTI 資料表與一次性初始化

- [ ] **新增 migration（接在實際 head 後）**。目的：可編輯且可驗證的 MBTI 資料，不覆寫舊人格表。順序：測試庫 migration→約束測試→正式開發庫 migration。SQL／migration：建議新增下列三表，實際檔案需由 Alembic 產生並人工檢查；不要修改舊 migration。

  | 表 | 欄位與約束 |
  | --- | --- |
  | `mbti_profiles` | `code varchar(4)` 主鍵，限制為 16 個合法代碼；`name_zh`、`summary`、`information_style`、`decision_style`、`interaction_style`、`action_style`、`stress_pattern` 必填且非空；`strengths`、`blind_spots`、`growth_tips`、`source_urls` JSONB 陣列且非空；`reviewed_at date`、`created_at`、`updated_at` 必填。 |
  | `mbti_weighted_terms` | `id bigint` 主鍵；`profile_code` 外鍵→`mbti_profiles.code`；`term varchar(80)`、`normalized_term varchar(80)` 必填非空；`weight numeric` 且 `0 < weight <= 5`；`UNIQUE(profile_code, normalized_term)`；`created_at`、`updated_at`。程式與資料庫同採 NFKC／大小寫正規化。 |
  | `mbti_catalog_state` | 單列 `id smallint` 主鍵且 `CHECK(id = 1)`；`revision bigint > 0`；`source_version`、`content_hash` 必填；`status` 限 `ready`／`editing`；`initialized_at`、`updated_at`。只有全部 16 型驗證通過後才設為 ready；每次有效編輯同交易遞增 revision。 |

  對應程式：新增 ORM models／repository，不動 `PersonalityTrait`、舊關鍵詞或舊 revision 資料。驗證：非法 code、重複詞、空描述、NaN／無限／超界權重、孤兒外鍵均拒絕；16 型完整性由初始化及發布驗證檢查（列級 CHECK 不會保證有 16 筆）。回退：先切回內建來源，再 downgrade 新 migration；保留備份與舊人格表。
- [ ] **從本次 JSON 一次性初始化 16 型**。目的：SQL 與已驗證內建資料一致，保留管理員修改。順序：新表→執行顯式初始化命令→驗證→ready。SQL／migration：以交易載入 `app/data/mbti_zh_hant.json`，記錄版本與 canonical hash；僅在尚未初始化且目標表為空時執行，已有資料則拒絕並提示，不能啟動時 upsert 覆蓋內容。程式：新增顯式初始化 service／CLI，重用 `app/services/mbti_catalog.py` 驗證；禁止塞入應用啟動 seed。驗證：首跑 16 型與所有詞一致，第二次執行不覆寫；編輯後重啟應用內容仍保留。回退：切回 bundled；若要清空新表，先備份管理員改動且只處理新 MBTI 表。

### 3. 接回共用計分與後台

- [ ] **新增 SQL catalog provider 與來源切換**。目的：計分不依賴資料儲存方式。順序：先實作 provider 與快照測試，再加設定，最後試切換。SQL／migration：只讀 ready catalog；在單一一致性交易讀取 state、16 型及全部關鍵詞，讀取前後 revision 必須一致。程式：`app/services/mbti_catalog.py` 保留 immutable catalog 介面；新增 SQL repository／provider；`app/core/config.py` 新增 `MBTI_CATALOG_SOURCE=bundled|database`（預設 bundled）；`app/main.py`、公開 API、唯讀後台都注入同一 provider；`app/services/mbti_scoring.py` 的公式不變。驗證：同一資料源產生相同分數；SQL 損壞／缺型時不發布半份資料；單次推薦固定 catalog、prototype 與 revision，並行編輯不混用。回退：設定 bundled 並重啟；不需刪資料或重建寶可夢向量。
- [ ] **恢復 MBTI 後台編輯與安全驗證**。目的：編輯完整描述、優勢／盲點／壓力／成長與加權詞。順序：provider→表單／API→CSRF／驗證→版本刷新→開放操作。SQL／migration：更新 profile／terms 與 revision 必須同交易；使用 optimistic concurrency 防止覆蓋，衝突回傳 409；任何錯誤 rollback。程式：`app/api/admin.py`、`app/templates/admin.html`、`app/static/js/admin.js`、schemas；保留管理員登入、CSRF token／Origin 驗證，不能直接恢復舊人格詞庫寫入 endpoint；編輯的是新 MBTI catalog。驗證：未登入 401、錯誤 CSRF 403、非法欄位 422、舊 revision 409；成功後公開 API ETag／介紹與新推薦快照更新，進行中的推薦仍使用舊完整快照。回退：關閉編輯／來源切回 bundled；DB 修改留存供修復。
- [ ] **完成版本刷新與多程序一致性**。目的：避免各 worker 使用不同或部分更新的人格。順序：實作 revision 檢查→新快照編碼→原子交換→並行測試。SQL／migration：更新只遞增單列 revision；讀取時採 repeatable-read snapshot 或等價一致性機制。程式：provider cache 以 revision／hash 為鍵，16 個描述 prototype 只在 catalog 變動時重建；`recommendation.py` 一次請求先取得快照；不得快取使用者原文或查詢向量。驗證：並行編輯、回滾、兩個 worker、編碼失敗時仍保留上一完整快照。回退：停用刷新、切回 bundled 並重啟。

### 4. 完整性檢查、整合驗證與切換

- [ ] **執行資料完整性只讀查詢**。目的：確認切換前資料完整。順序：初始化／編輯後→測試→切換。SQL：下列為新表建好後才可執行的檢查，不在本次執行。

  ```sql
  SELECT count(*) AS profile_count, count(DISTINCT code) AS unique_codes
  FROM mbti_profiles; -- 兩者必須都是 16
  SELECT code FROM mbti_profiles
  WHERE code NOT IN ('ENFJ','ENFP','ENTJ','ENTP','ESFJ','ESFP','ESTJ','ESTP',
                     'INFJ','INFP','INTJ','INTP','ISFJ','ISFP','ISTJ','ISTP');
  SELECT p.code FROM mbti_profiles p LEFT JOIN mbti_weighted_terms t
    ON t.profile_code = p.code GROUP BY p.code HAVING count(t.id) = 0;
  SELECT profile_code, normalized_term, count(*) FROM mbti_weighted_terms
    GROUP BY profile_code, normalized_term HAVING count(*) > 1;
  SELECT * FROM mbti_weighted_terms WHERE weight <= 0 OR weight > 5;
  SELECT id, revision, source_version, content_hash, status FROM mbti_catalog_state;
  ```

  程式：加上 loader 全欄位驗證、來源 URL／JSON 陣列形狀、canonical hash 與恰好 16 型檢查，不能只看 count。驗證：異常查詢應無結果、state 恰一列 ready、hash 與讀出內容一致。回退：保持 bundled，修復新表後重驗。
- [ ] **在一次性測試庫補足 SQL 整合測試**。目的：驗證真實交易、初始化、編輯與快照。順序：獨立 TEST_DATABASE_URL→migration→測試→人工前後台。SQL／migration：只對測試庫執行 `alembic upgrade head`；執行前確認 `DATABASE_URL` 同樣指向該測試庫（Alembic 使用它）。程式：新增 DB provider／初始化／後台／並行刷新整合測試，執行 `python -m unittest discover -s tests -v`；原匯入整合測試此時應不略過。驗證：全套通過，故意錯誤初始化可 rollback，啟動不覆寫，推薦沒有 insert／update／commit；CI 繼續只用一次性 PostgreSQL。回退：移除測試庫；修復後重跑，不以正式庫試錯。
- [ ] **驗證真實配對品質與索引覆蓋**。目的：確認目前 ready 文件足夠表達寶可夢行為。順序：SQL provider 測試後→抽樣評估→決定是否另開文件改善工作。SQL／migration：只讀 current／ready 與 embedding model／hash 覆蓋率，不直接重建索引。程式：以 `evaluation/` 案例比較文字／同型異描述／同描述異型／衝突描述；檢查 Top 3 穩定性及 Top 1 證據；實際模型與資料庫品質仍待此步。驗證：記錄資料版本、模型版本、命中與人工判斷；不要把工程權重當心理測量準確率。回退：來源切回 bundled 或應用回前版；若日後需更新索引，另行備份與規劃。
- [ ] **正式切換與回退演練**。目的：可控啟用家中 SQL 資料源。順序：備份→完整性→整合測試→少量查詢→設定 database→觀察→紀錄 revision。SQL／migration：無額外寫入；保留原人格表。程式：預設仍 bundled，只有家中驗證後才改設定；README／operations 文件記錄實際新 revision、命令、設定與故障處理。驗證：前台及後台版本相同、編輯刷新、錯誤可回復，確認設定 bundled 後恢復。回退：先 bundled 並重啟，再視需要還原應用；通常不需 downgrade 或刪新表。只有確定資料可丟且有備份才 downgrade。

## 計分基準與交付限制

每型訊號 = 80% 詳細正向描述語意 + 20% 加權關鍵詞涵蓋率；使用者與寶可夢共用。文字契合 = 75% 文字檢索 + 25% 16 維行為相似度（缺少訊號時用文字檢索）。選填 MBTI 後總分 = 75% 文字契合 + 25% 指定型契合。這些是初始工程設定，不是心理測量準確率。

本次不執行 SQL、不恢復人格編輯、不補跑本機資料庫整合、不執行 `docker compose up`。交付前依實際實作同步上方完成狀態；家中工作不得預先勾選。
