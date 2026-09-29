# 專案文件

[返回專案首頁](../README.md)

README 只保留專案介紹、快速啟動與常用入口；實作、維運及治理細節集中在這個目錄。

## 依需求選文件

| 我想要…… | 請閱讀 |
| --- | --- |
| 了解推薦、今日寶可夢、RAG 與資料流 | [系統架構與推薦流程](architecture.md) |
| 在本機啟動、查 log、操作資料庫或執行測試 | [本機操作指南](operations.md) |
| 暫時產生公開網址 | [正式部署文件的 Quick Tunnel 章節](production.md#臨時-cloudflare-quick-tunnel-smoke-test) |
| 用固定網域正式上線 | [正式環境部署、備份與回退](production.md) |
| 設定 Prometheus、Alertmanager 與雲端費用護欄 | [費用護欄與主動告警](cost-controls.md) |
| 稽核或更換 S3／CloudFront 圖片來源 | [AWS artwork 發送流程](aws-artwork.md) |
| 建立多人標註、仲裁與版本化資料集 | [多人標註與評估資料集流程](evaluation-workflow.md) |
| 了解匿名推薦回饋與 retention | [隱私最小化推薦回饋](recommendation-feedback.md) |
| 查看仍未完成的工作與驗收條件 | [Roadmap](roadmap.md) |

## 建議閱讀路徑

### 第一次在本機執行

1. 專案首頁的「快速開始」。
2. [本機操作指南](operations.md)的環境變數與 Docker Compose 章節。
3. 需要理解排序結果時，再閱讀[系統架構與推薦流程](architecture.md)。

### 暫時分享給其他人

1. 先完成本機啟動。
2. 使用[安全 Quick Tunnel 流程](production.md#臨時-cloudflare-quick-tunnel-smoke-test)。
3. 跑完 smoke test，分享產生的 `https://...trycloudflare.com`。
4. 測試結束就關閉 tunnel；Quick Tunnel 不是長期主機。

### 正式公開

1. 準備 Linux 主機、網域及受保護的 GitHub Environment。
2. 先完成[費用護欄](cost-controls.md)與自己可承擔流量的[圖片來源](aws-artwork.md)。
3. 依[正式部署文件](production.md)建立備份、告警、HTTPS 與回退流程。
4. 上線前執行 restore drill 與公開邊界 smoke test。

## 文件維護原則

- README 不硬編測試數量、migration head 或容易過期的執行結果。
- `.env`、帳號 ID、通知 webhook、API key 與帳務收件者不得寫入文件或 repository。
- 指令若會刪除 volume、覆寫資料庫或公開服務，必須明確標示影響與確認條件。
- 來源可追溯只代表資料鏈可稽核，不代表取得著作權或商業使用授權。
