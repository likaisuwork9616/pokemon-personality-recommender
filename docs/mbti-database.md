# MBTI SQL 資料來源與後台編輯

[文件索引](README.md) · [回到首頁](../README.md)

## 資料表與發布規則

`20261012_0011` 接在 `20260929_0010` 後新增 `mbti_profiles`、`mbti_weighted_terms`、`mbti_catalog_state`，不覆寫舊人格資料表、寶可夢文件或向量。Migration 只建結構，不自動 seed MBTI。

初始化必須是顯式命令。目標三表任一已有資料就拒絕；初始化、完整驗證與 ready 發布在同一交易內完成。並行初始化以 PostgreSQL transaction advisory lock 序列化。舊人格寫入端點保持停用。

所有寫入請使用新後台 API；不支援直接 SQL 編輯發布。Repository 會驗證 normalized_term、16 型完整性、所有文字與陣列、來源 URL、權重和 hash。外部 SQL 若破壞資料，provider 拒絕發布；不能只修改 state hash 來跳過驗證。

## 在已有資料庫啟用

先備份並試還原到獨立資料庫，再比對 revision。不要把正式庫設成 `TEST_DATABASE_URL`。

```powershell
. .\scripts\load_env.ps1
.venv\Scripts\alembic.exe current
.venv\Scripts\alembic.exe heads
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\python.exe -m scripts.mbti_catalog initialize
.venv\Scripts\python.exe -m scripts.mbti_catalog verify
```

`initialize` 第二次執行會拒絕覆寫，管理員修改不會因重啟消失。`verify` 使用唯讀 repeatable-read 交易，輸出來源、revision、16 型數量、關鍵詞總數與完整內容 hash。

先在獨立測試庫執行全部測試。PowerShell 設定如下；開新 shell 後需重新載入 `.env`：

```powershell
. .\scripts\load_env.ps1
$env:DATABASE_URL = $env:TEST_DATABASE_URL
$env:MBTI_CATALOG_SOURCE = "bundled"
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\python.exe -m unittest discover -s tests -v
# 恢復開發庫設定
. .\scripts\load_env.ps1
```

測試只建立隨機 schema，結束後清除該 schema，不刪除 public 裡的資料。CI 使用獨立 PostgreSQL 16/pgvector；本機驗證使用 PostgreSQL 17/pgvector。

驗證後把 `.env` 設為 `MBTI_CATALOG_SOURCE=database`，重新載入環境並重啟 API。Docker Compose 的 API、worker 也會取得這個設定；Docker 容器內的資料庫位址由 Compose 設定，不使用主機的 55432。

## 編輯與版本刷新

登入 `/admin` 後，database 來源的 editor/admin 可編輯完整介紹與行為詞。viewer 與 bundled 來源只顯示介紹。每行一個優勢、盲點、成長建議或 HTTPS 來源；行為詞採 `詞 | 權重`，至少 12 個且包含中英文。

`PUT /api/v1/admin/mbti/profiles/{code}` 接受 `expected_revision` 與完整 `profile`。需要登入、editor/admin 權限、正確 `X-CSRF-Token` 和同網站 `Origin`。API client 也必須明確提供正確 Origin。舊 revision 回傳 409；非法內容回傳 422；未登入 401；權限、CSRF 或 Origin 錯誤 403。修改、關鍵詞替換、revision 遞增與 Audit Log 同一交易提交；失敗全部 rollback。內容未變時不遞增 revision。

公開 API 與後台共用 provider，ETag 包含來源、版本、revision、hash。每個 worker 在推薦前檢查資料庫版本，用相同 embedding model 的完整描述重建 prototypes，再交換整個 immutable scorer；進行中的請求保留原 scorer，不混用 catalog。cache key 包含模型 id/name/version/dimensions/normalize 以及 revision/hash。編碼或資料驗證失敗保留上一份完整 scorer，readiness 會標示不健康；修復後下一次請求重試。

## Canonical hash

兩來源共用 loader：profiles 按 code 排序；詞按 NFKC、空白折疊、casefold 後的文字排序；權重先轉 finite float；日期採 ISO；物件鍵排序，UTF-8、無額外空白。hash 包含 version、catalog reviewed_at 與完整 profiles，排除來源標記、revision、DB timestamps、term id。revision 另行比對，因此純版本編號變動不改內容 hash。JSON→SQL→catalog 的 hash 與分數一致。

## 本機設定與啟停

本次新建的開發庫是 `127.0.0.1:55432/pokemon`，測試庫是 `pokemon_mbti_test`，僅監聽 loopback 並使用 SCRAM 密碼。連線密碼只存於被 Git 忽略的 `.env`；管理連線檔與 PostgreSQL cluster 在 `.local/`，同樣不進版控。原本 5432 的既有 PostgreSQL 無可用帳密，本次沒有存取、遷移或複製該庫。

```powershell
.\scripts\local_database.ps1 status
.\scripts\local_database.ps1 start
. .\scripts\load_env.ps1
.venv\Scripts\python.exe -m scripts.mbti_catalog verify
# 啟動應用（需要可用的寶可夢向量）
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 使用完才停止資料庫
.\scripts\local_database.ps1 stop
```

此 cluster 不是 Windows 自動啟動服務；重開機後請執行 start。此腳本針對本次 PostgreSQL 17 本機安裝；其他機器請使用自己的 PostgreSQL 或 Docker Compose。

## 回退

先把 `MBTI_CATALOG_SOURCE=bundled` 並重啟 API，公開介紹與計分即切回內建資料；保留 SQL 編輯內容，不需刪資料或重建寶可夢向量。修復後 verify，再設 database 重啟。

只有已備份且確定可丟棄新 MBTI 表資料時才 downgrade 到 `20260929_0010`。這會刪除三張新表；一般故障回退不需要 downgrade。

## 2026-10-12 本機驗證結果

- 新開發庫：1,025 隻 active/ready 寶可夢，4,684 個 ready vectors，待補或 hash 不符的 chunks 為 0。
- SQL catalog：16 型、256 個詞、revision 1、ready；migration `20261012_0011`。
- `database → bundled → database` 三次實際應用啟動都 ready，公開／後台 revision 一致，測試配對 Top 3 相同。
- 初始化後完整資料庫已 `pg_dump -Fc`、SHA-256 驗證，並成功還原到獨立 `pokemon_restore_populated`；核對寶可夢、向量、MBTI 與關鍵詞數量一致。備份在 `.local/backups/`，不是 off-host 備份。
- [真實模型比較報告](../evaluation/mbti_sql_validation.json)：20 題既有標註，兩來源 hash、指標、五組差異／衝突描述結果完全一致；重複查詢排序穩定，Top 1 document/chunk/hash lineage 核對成功。
- 既有標註上的 Top-3 Hit Rate 為 0.30，nDCG@10 為 0.097038。此驗證證明 SQL 切換不改變既有配對行為，不代表推薦已達高品質或心理測量有效。抽樣可見靈幽馬的「孤獨與寂靜」、呆呆王的「冷靜、智慧」與輸入有呼應，但部分候選仍偏重圖鑑題材／片段；資料與相關性改善應另立工作。
- 後台在瀏覽器確認 SQL 編輯表單、13 個欄位與類型切換；390px 手機 viewport 沒有水平溢出。儲存交易、登入、CSRF、Origin、非法資料與 revision 衝突由真實 PostgreSQL API 整合測試驗證。

可重跑比較（只讀取既有索引，不呼叫外部解說服務）：

```powershell
. .\scripts\load_env.ps1
.venv\Scripts\python.exe -m scripts.validate_mbti_database --output evaluation-report-mbti.json
```
