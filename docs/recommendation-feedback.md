# 隱私最小化推薦回饋

推薦頁面的每張 Top 3 卡片都可回報「符合」或「不符合」。這個功能用來觀察真實排序品質，但不會把原始人格描述轉存成訓練資料。

## 保存內容

每次成功推薦只建立一個隨機 UUID 收據，保存：

- 演算法版本。
- Top 3 的 Pokémon 資料庫 ID 與原始名次。
- 使用者針對單一結果選擇的 `match`／`not_match`。
- 可選的固定原因：`personality_mismatch`、`ranking`、`unfamiliar`；不接受自由文字。
- 建立與更新時間。

不保存原始描述、query vector、evidence、LLM 說明、IP、User-Agent、Cookie ID 或帳號識別。瀏覽器端也不使用 `localStorage`／`sessionStorage` 保存回饋。

## 防止錯誤綁定

公開 API 為 `POST /api/v1/recommendation-feedback`。伺服器會確認：

1. recommendation UUID 存在。
2. Pokémon 確實屬於該次 Top 3。
3. 名次與原始推薦一致。
4. verdict 與 reason 都來自固定列舉。

同一個 recommendation UUID 與 Pokémon 只有一筆回饋；重送會更新原值，不會重複灌票。UUID 無法取代正式身分驗證，因此這些資料適合做產品訊號與離線實驗參考，不應視為防作弊問卷。

## 管理彙總

登入 `/admin` 後可查看：

- 收據數、已回饋收據數與回應率。
- 整體及各 Rank 的符合率。
- 固定原因分布。
- 各演算法版本的回饋數與符合率。

API 為 `GET /api/v1/admin/feedback/summary`，需要任一管理角色。回應只有 aggregate，不回傳個別收據或任何 query。

## Retention

預設建議只保留 90 天；可由排程器每日執行：

```bash
python scripts/purge_recommendation_feedback.py --retention-days 90
```

正式主機也可使用 production Compose 的 maintenance profile：

```bash
docker compose -f compose.production.yml --profile maintenance \
  run --rm feedback-purge
```

刪除 impression 時，Top 3 items 與 feedback 會透過外鍵 cascade 一併刪除。若需改變 retention，應同步更新隱私聲明與實際排程。
