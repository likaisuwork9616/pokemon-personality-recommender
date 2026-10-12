# MBTI SQL 待辦完成記錄

2026-10-12 已在本機新開發庫完成。實作與操作細節見 [MBTI SQL 操作](docs/mbti-database.md)。

本次範圍是 `127.0.0.1:55432/pokemon`；`pokemon_mbti_test` 為獨立測試庫。原本 5432 的資料庫沒有可用帳密，沒有存取、複製或遷移它。新開發庫由本專案 1,025 筆 seed 建立，不代表已搬移原資料庫裡的管理員修改。

## 已完成

- [x] 核對版本與 revision：main 整合基準 `84ed50b`；新 migration `20261012_0011` 接在 `20260929_0010` 後，開發庫與測試庫均完成 upgrade。
- [x] 備份與試還原：初始化前備份；初始化、seed 與向量完成後再建立完整 custom-format archive 與 SHA-256，還原到獨立庫核對 1,025 隻、4,684 個向量、16 型、256 詞及 catalog state。檔案保存於 Git 忽略的 `.local/backups/`。
- [x] 新增三張 MBTI 表及 ORM：完整 NOT NULL、合法代碼、非空文字／陣列、唯一正規化詞、外鍵、有限權重、單列 state、正 revision、合法 hash/status 約束；保留所有舊人格與寶可夢資料表。
- [x] 一次性顯式初始化：`python -m scripts.mbti_catalog initialize`。只接受三表皆空；第二次拒絕覆寫，並行只會成功一次；中途失敗全部 rollback；應用啟動不 seed/upsert。
- [x] SQL provider 與來源切換：`MBTI_CATALOG_SOURCE=bundled|database`，版本庫預設 bundled，本機 `.env` 已切 database。公開 API、後台、推薦與評估共用 provider。
- [x] 跨來源 canonical hash：日期 ISO、finite float 權重、profiles 與詞固定排序、UTF-8 canonical JSON；排除 storage metadata 與 revision，revision 另行比對。JSON→SQL→catalog hash 與分數相同。
- [x] 後台完整編輯：新 `PUT /api/v1/admin/mbti/profiles/{code}` 與表單，涵蓋完整介紹、優勢／盲點／壓力／成長、來源／日期與詞權重。只允許 database 來源的 editor/admin；保留舊人格寫入端點停用。
- [x] 安全與交易：登入、權限、X-CSRF-Token、同來源 Origin；非法資料 422，舊 revision 409；內容／詞／revision／Audit Log 同交易，錯誤 rollback，沒有變更則不遞增 revision。
- [x] 多程序一致性：每次推薦檢查 SQL snapshot，模型完整身分＋revision/hash 快取；原子交換完整 scorer/prototypes/catalog，進行中的請求保持原快照。新編碼失敗保留上一完整版本並標記 readiness，下一次可恢復；不快取使用者原文／query vector。
- [x] 完整性只讀檢查：`python -m scripts.mbti_catalog verify` 使用 repeatable-read/read-only；驗證完整內容、normalization、16 型、來源與 hash，拒絕缺型、損壞或半份資料。
- [x] 真實 PostgreSQL 整合：初始化、SQL 約束、rollback、並行初始化／編輯／刷新、兩個 worker、舊 session revision、單次請求一致性、API 權限／CSRF／Origin、ETag；migration downgrade/upgrade 保留舊表資料；原匯入整合測試也執行。
- [x] 真實模型品質與覆蓋：4,684 個向量全部 ready，1,025 隻 ready，pending/hash mismatch 為 0；20 題與五組差異／衝突輸入的兩來源結果一致，重跑排序穩定，Top 1 證據 lineage 已核對。報告見 [mbti_sql_validation.json](evaluation/mbti_sql_validation.json)。
- [x] 切換與回退：實際啟動驗證 database→bundled→database，三次 `/health/ready` 都 ready，公開與後台 revision 相同、配對相同；最後本機 `.env` 保持 database。一般回退只切 bundled 並重啟，不刪新表、不重建寶可夢索引。
- [x] 文件與環境：README、operations、專用 SQL 指南、Compose 與 env 範例同步；新增 PowerShell 環境載入及本機資料庫 start/status/stop 指令。密碼、cluster、備份不進 Git。

## 驗證界線

- 本機使用 PostgreSQL 17/pgvector；CI 沿用獨立 PostgreSQL 16/pgvector。
- 真實模型比較使用 seed 建立的新開發庫，不是原本 5432 資料庫的快照；未呼叫 Gemini/OpenAI。
- 既有 20 題標註 Top-3 Hit Rate 0.30、nDCG@10 0.097038；這是目前配對品質基準，不能當作心理測量準確率。資料／候選改善是後續工作，SQL 接線不調整原有公式。
- 本機已切換；外部正式主機與原本 5432 的庫不在本次已驗證範圍。若要使用那些環境，須依 [SQL 操作指南](docs/mbti-database.md) 對各自資料庫備份、migrate、initialize、verify 後切換。

## 最終驗證

- `python -m unittest discover -s tests -v`：333 項全數通過，無略過。
- JavaScript 語法、Python compileall、Git whitespace 檢查通過。
- 本機 PostgreSQL stop/start 後 SQL catalog 仍為 revision 1、16 型、256 詞，hash 相同，連線驗證成功。
