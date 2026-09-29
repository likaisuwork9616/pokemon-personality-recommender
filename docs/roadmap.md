# Roadmap 與現況限制

[文件索引](README.md) · [返回專案首頁](../README.md)

這份清單只保留尚未完成、需要外部帳號或必須累積真實資料才能驗收的工作。已完成能力請看專案首頁與[系統架構](architecture.md)。

## 優先工作

| 優先級 | 現況 | 完成條件 |
| --- | --- | --- |
| P0 | 正式交付骨架已包含 immutable image、Caddy TLS、備份、migration、smoke test 與 image rollback，但尚未部署至持久公開主機。 | 準備網域與 Linux 主機，設定受保護的 GitHub `production` Environment／runner，執行首次 release，並完成異地主機 restore drill。 |
| P1 | 多人標註、仲裁、weighted kappa、slice metrics 與版本化匯出已完成；正式資料集仍只有 20 題。 | 由至少兩位真人標註者擴充至 100 題以上，完成衝突校準並發布新版 JSONL；不以合成標籤灌水。 |
| P1 | 匿名 bounded feedback 與 aggregate 已完成，但尚無足夠真實流量，觀察值也不代表因果效果。 | 累積至少 500 份有效回饋收據，按 Rank／版本檢查偏差，預先定義 A/B 指標與停止條件後再調整排序。 |
| P1 | availability、p95、5xx、readiness、429 與 provider 告警規則已建立。 | 在正式主機設定私密通知接收端，依實際流量校準門檻，再補長期 retention 與 dashboard runbook 連結。 |
| P1 | 管理帳號仍由環境變數提供。 | 串接 OIDC／企業 IdP，支援停權、角色變更、session 撤銷與相關 Audit Log。 |
| P2 | Gemini／OpenAI attempt、failure、fallback 指標與 rate limit 已完成。 | 補 token／實際金額指標與 circuit breaker，並以正式帳務報表校準費用門檻。 |
| P2 | 現有多語 Cross-Encoder 未通過 `+0.001 nDCG／≤250 ms` 門檻。 | 測試輕量模型、特徵權重或 query expansion；只有品質與延遲同時通過才進入 runtime。 |
| P2 | 已有功能與單點故障驗證，尚未建立持續容量基準。 | 加入固定資料量的 load test、容量門檻、備份還原計時及定期故障演練。 |
| P2 | 今日寶可夢 v1 已有固定選角、圖鑑依據與四面向娛樂運勢，尚無獨立滿意度資料。 | 加入不保存生日的 bounded feedback，累積至少 500 筆後按星座／時辰切片評估。 |
| P3 | 今日體驗固定台北時區，結果分享以網址為主。 | 在保留預設規則下加入可選時區、瀏覽器端星座換算、分享圖卡與跨程序快取。 |

## 外部前置條件

下列項目不能只靠 repository 內的程式碼宣告完成：

- AWS 帳號內的 CloudFront `Requests`、`BytesDownloaded` 與實際費用確認
- AWS Budgets 通知收件者確認
- OpenAI／Gemini 專案預算與可用的帳號級限制
- 正式網域、DNS、Linux 主機與 GitHub self-hosted runner
- Alertmanager 的私密通知 webhook
- 異地主機或獨立帳號管理的備份位置

這些設定應記錄在私密 operator runbook，不應把帳號 ID、收件者、key 或 webhook 寫進 repository。
