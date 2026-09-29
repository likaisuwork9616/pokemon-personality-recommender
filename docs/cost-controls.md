# 費用護欄與主動告警

[文件索引](README.md) · [返回專案首頁](../README.md)

應用程式 rate limit 與 Prometheus 告警是第一層防護，但不能取代雲端帳號的預算設定。分散式攻擊、其他應用程式共用金鑰，或帳務資料延遲，都可能超出單一 API 程序能觀察的範圍。

## Runtime 告警

Prometheus 每 15 秒評估 `ops/prometheus/alerts.yml`，並把 firing alerts 送到 Alertmanager。規則涵蓋：

- API availability
- PostgreSQL 即時 readiness
- HTTP 5xx 比例
- p95 latency
- 重複 429
- 外部模型失敗
- Provider 流量突增
- 人格詞庫 snapshot 不健康

正式環境請把 `ops/alertmanager/alertmanager.example.yml` 複製到 repository 外，例如 `/etc/pokemon-recommender/alertmanager.yml`，再換成 operator 擁有的私密 webhook。設定 owner/group 為 `root:65534`、mode 為 `0640`，並讓 `ALERTMANAGER_CONFIG_FILE` 指向該檔案。

Prometheus、Grafana、Alertmanager 在 host 上只能綁 loopback；不要把 9090、3000 或 9093 發布到公開介面。

```bash
sudo install -d -m 0750 -o root -g 65534 /etc/pokemon-recommender
sudo install -m 0640 -o root -g 65534 \
  ops/alertmanager/alertmanager.example.yml \
  /etc/pokemon-recommender/alertmanager.yml
```

固定版本的 Alertmanager image 以 UID/GID `65534:65534` 執行。`0640` 讓 non-root container process 能讀取 bind mount，同時阻止其他 host 使用者讀取；每次修改後都要重新套用相同 owner 與 mode。

替換 webhook URL 後，部署前先驗證：

```bash
docker run --rm \
  --user 65534:65534 \
  --entrypoint amtool \
  -v /etc/pokemon-recommender/alertmanager.yml:/etc/alertmanager.yml:ro \
  prom/alertmanager:v0.28.1 \
  check-config /etc/alertmanager.yml
```

## AWS artwork 預算

`ops/aws/artwork-budget.yml` 會建立 CloudFront／S3 共用的帳號級月預算。預設為 USD 5，並在預測 50%、實際 80% 與實際 100% 時發送通知。

AWS Budgets 是告警，不會自動停用 CloudFront 或 S3。只有在確認收件者與可承擔金額後才部署：

```bash
aws sts get-caller-identity
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name pokemon-artwork-budget \
  --template-file ops/aws/artwork-budget.yml \
  --parameter-overrides AlertEmail=operator@example.com MonthlyBudgetUsd=5
```

收件者必須依 AWS 帳號要求確認通知。部署後要到 Billing and Cost Management 確認 budget，並在 `us-east-1` 的 CloudWatch 檢查 CloudFront `Requests` 與 `BytesDownloaded`。沒有通過 `aws sts get-caller-identity` 時，不應聲稱已確認實際流量或費用。

## OpenAI 與 Gemini

### OpenAI

- 使用專案專用 key，不與其他應用程式共用。
- 設定偏低的 project monthly budget 與通知。
- 除非帳號 Limits 頁面另有明確 hard limit，否則把 project budget 視為軟性警示；spend alert 不保證立即停止 API traffic。
- 即使帳號提供上限，仍保留應用程式的每來源與全程序 rate limit。

### Gemini

- 使用獨立的 AI Studio／Google Cloud project。
- 若帳號支援，設定 monthly project spend cap。
- Spend cap 功能可能不適用部分 invoiced accounts，帳務 enforcement 也可能延遲，因此仍須保留應用程式全域護欄並容許少量超額。

### Tunnel 測試

公開 Quick Tunnel 測試時，`compose.quick-tunnel.yml` 會強制把 `GEMINI_API_KEY`、`OPENAI_API_KEY` 與 `HF_TOKEN` 設成空字串，只驗證本機 fallback。除非刻意執行小額 paid-provider canary，否則不要在臨時公開網址中啟用付費 key。

## 上線檢查表

- [ ] Alertmanager 私密 receiver 已驗證，設定檔權限為 `root:65534`／`0640`
- [ ] AWS budget 已建立，收件者已確認
- [ ] CloudFront `Requests`／`BytesDownloaded` 有可追蹤 dashboard
- [ ] OpenAI／Gemini 使用專案專用 key 與低額通知
- [ ] 公開推薦與外部說明 rate limit 已啟用
- [ ] Provider failure／fallback 告警會送達值班人員
- [ ] 金鑰、帳號 ID、billing email 與 webhook 沒有提交到 repository

專案名稱、每月金額、收件者與最後驗證日期應記錄在私密 operator runbook，不要放進 Git。
