# 多人標註與評估資料集流程

[文件索引](README.md) · [返回專案首頁](../README.md)

這套流程把「案例建立、獨立評分、衝突仲裁、品質檢查、離線匯出」分開，避免單一人員直接修改正式評估答案。管理操作沿用 `/admin` 的同源 Session、CSRF、角色權限與 Audit Log。

## 資料與角色

- `viewer`：查看案例、標註狀態、一致性與 slice 報表。
- `editor`：建立草稿，並以自己的帳號提交 0–3 級獨立評分。
- `admin`：具有 editor 能力，另可提交最終仲裁、啟用或退役案例。
- 0 表示不相關，1 表示部分相關，2 表示高度相關，3 表示核心標註。
- 案例從 `draft` 轉為 `active` 前，每個候選都必須有至少兩位標註者及一筆仲裁，且至少一個候選的最終分數大於 0。

系統只保存人工建立的評估 query。公開推薦流量、原始個性描述與 query vector 不會自動寫入標註資料表。

## API 流程

登入後取得 `csrf_token`，所有寫入都要帶 `X-CSRF-Token`。以下省略 Cookie 參數：

```bash
curl -X POST http://localhost:8000/api/v1/admin/evaluation/cases \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF_TOKEN" \
  -d '{
    "case_key": "patient_listener_v2",
    "query": "我習慣先聽完大家的想法，再慢慢整理出適合團隊的方向。",
    "segment": "social_empathy",
    "dataset_version": "2026.10",
    "pokemon_ids": [25, 39, 52, 94]
  }'
```

每位 editor 使用自己的帳號提交同一候選集的完整評分：

```bash
curl -X PUT http://localhost:8000/api/v1/admin/evaluation/cases/CASE_UUID/annotations \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF_TOKEN" \
  -d '{"judgments":[
    {"pokemon_id":25,"grade":3},
    {"pokemon_id":39,"grade":1},
    {"pokemon_id":52,"grade":0},
    {"pokemon_id":94,"grade":2}
  ]}'
```

admin 檢視分歧後，呼叫 `/adjudications` 寫入最終標籤，再以 `PATCH /cases/{id}/status` 送出 `{"status":"active"}`。所有 mutation 都會產生 `evaluation.*` Audit Log。

## 品質閘門

`GET /api/v1/admin/evaluation/quality` 提供：

- 候選項目的雙人標註覆蓋率、衝突率及仲裁覆蓋率。
- 每組標註者共同評分數與 quadratic weighted Cohen's kappa。
- `segment` 與 query 長度（short／medium／long）切片。

建議在發布資料集前確認雙人標註與仲裁覆蓋率皆為 1，並針對低一致性的標註者組合重新校準標準。Kappa 是診斷指標，不應單獨取代實際衝突審查。

## 版本化匯出

只有 `active` 且最終分數大於 0 的標籤會進入離線資料集：

```bash
python scripts/export_evaluation_dataset.py \
  --dataset-version 2026.10 \
  --output evaluation/recommendation_cases_2026.10.jsonl

python scripts/evaluate_recommendations.py \
  --dataset evaluation/recommendation_cases_2026.10.jsonl
```

匯出採同目錄暫存檔後原子取代，並保留 `segment`、`dataset_version` 與 1–3 級相關性。輸出格式相容既有離線評估器；0 分只用於一致性與仲裁紀錄，不會輸出成正相關答案。
