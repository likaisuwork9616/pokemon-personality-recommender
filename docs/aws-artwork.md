# AWS artwork 發送流程

這套工具將本機整理好的官方 artwork 驗證後上傳至 Amazon S3，再透過 CloudFront 提供公開 URL。圖片二進位不寫入 PostgreSQL；application 只保存 URL。

[返回 README](../README.md)

## 資料流

~~~text
pk_pic/*.png
    │
    ├─ build_pokemon_image_manifest.py
    │      └─ 本機 manifest：名稱、尺寸、SHA-256、object key、URL
    │
    └─ pokemon_s3_image_uploader.py
           ├─ Amazon S3：PNG + SHA-256 metadata
           └─ CloudFront：公開 artwork URL
                         │
                         └─ PostgreSQL pokemon_images.image_url
~~~

`pk_pic/`、manifest、上傳結果、資料庫 URL 備份與 `.env` 均由 `.gitignore` 排除。AWS access key、SSO token、account 資訊或實際密碼不得寫入這些檔案。

工具只檢查現有 bucket 與 CloudFront delivery，不會修改 bucket policy、CloudFront distribution 或 Origin Access Control。

目前公開設定預設使用本專案的 CloudFront artwork 目錄，因此 fork 或 clone 後啟動的環境也會向該 distribution 請求圖片。若不打算承擔第三方流量，公開前應改成自己的 CDN URL 或空白設定，並在 AWS 設定費用預算與告警。

## 命名契約

每個全國圖鑑編號只保留一張 artwork，不包含 Mega 等共用圖鑑敘述的形態：

~~~text
本機檔名：0001_妙蛙種子.png
Object key：images/pokemon/artwork/0001.png
Delivery URL：https://cdn.example.com/images/pokemon/artwork/0001.png
~~~

Manifest 必須與 `pokemon_descript/pokedex_final.csv` 的 1,025 筆編號和繁中名稱逐筆相符，並滿足：

- 0 缺圖、0 重複編號、0 重複 object key
- PNG signature 與寬高可解析
- 本機重新計算的 SHA-256 與來源 manifest 相同
- 每個 object key 都位於 `images/pokemon/artwork/`

## 準備工作

安裝 AWS 選配套件：

~~~bash
python -m pip install --requirement requirements-aws.txt
~~~

若使用 AWS IAM Identity Center：

~~~bash
aws configure sso --profile your-profile
aws sso login --profile your-profile
aws sts get-caller-identity --profile your-profile
~~~

`pk_pic/_manifest.csv` 至少要有下列來源欄位：

~~~text
pokedex_number,name_zh,filename,source_url,sha256
~~~

對應 PNG 放在 `pk_pic/`。不要把 AWS credentials 填進來源 manifest。

後續範例使用：

| 參數 | 範例 |
| --- | --- |
| Bucket | `your-bucket` |
| Region | `your-region` |
| CloudFront base | `https://cdn.example.com` |
| AWS profile | `your-profile` |

`--delivery-base-url` 使用 CloudFront domain 根目錄；manifest builder 會自行附加完整 object key。

## 建立 manifest

~~~bash
python scripts/build_pokemon_image_manifest.py \
  --bucket "your-bucket" \
  --region "your-region" \
  --delivery-base-url "https://cdn.example.com"
~~~

預設輸出：

~~~text
pk_pic/manifests/pokemon_image_upload_manifest.csv
~~~

內容包括圖鑑編號、繁中名稱、本機相對路徑、來源 URL、檔案大小、PNG 寬高、SHA-256、object key、S3 URI、S3 HTTPS URL 與 CloudFront URL。

Manifest 驗證失敗時不要開始上傳。先修正缺圖、錯名、損壞檔案或 hash 差異，再重新產生。

## 上傳前 dry-run

Uploader 沒有 `--execute` 時只做本機驗證，不建立 AWS client：

~~~bash
python scripts/pokemon_s3_image_uploader.py \
  --bucket "your-bucket" \
  --region "your-region" \
  --delivery-base-url "https://cdn.example.com" \
  --profile "your-profile"
~~~

預設結果檔是：

~~~text
pk_pic/manifests/pokemon_image_upload_result.csv
~~~

正式執行時每 50 筆原子寫入 checkpoint。若結果檔已存在，工具會要求使用 `--resume`，不會靜默覆蓋既有紀錄。

## Canary

先處理一張圖片：

~~~bash
python scripts/pokemon_s3_image_uploader.py \
  --bucket "your-bucket" \
  --region "your-region" \
  --delivery-base-url "https://cdn.example.com" \
  --profile "your-profile" \
  --limit 1 \
  --execute \
  --verify-delivery
~~~

Canary 需同時通過：

- S3 object 存在
- `Content-Type` 是 `image/png`
- object size 與 SHA-256 metadata 相符
- CloudFront 回傳 PNG，實際內容 SHA-256 相符

若 CloudFront 驗證失敗，先檢查 distribution origin、cache behavior 與 S3 存取設定，不要直接開始全量上傳。

## 續傳全部圖片

Canary 成功後，從結果檔繼續：

~~~bash
python scripts/pokemon_s3_image_uploader.py \
  --bucket "your-bucket" \
  --region "your-region" \
  --delivery-base-url "https://cdn.example.com" \
  --profile "your-profile" \
  --resume \
  --execute \
  --verify-delivery
~~~

可用 `--workers`、`--checkpoint-every` 與 `--timeout` 調整並行驗證和 checkpoint 頻率。

已有 object 時，只有檔案大小、`Content-Type` 與 `sha256` metadata 都相同才標記為 `already_exists`。任一項不同會回報 conflict，工具不會自動覆蓋。上傳時使用：

~~~text
Content-Type: image/png
Cache-Control: public, max-age=86400
Metadata: sha256=<local SHA-256>
~~~

批次結束後，結果檔應有 1,025 筆成功或 `already_exists`，而且 S3 與 CloudFront 驗證狀態都是 `verified`。

## 切換 PostgreSQL artwork URL

### 1. 備份目前 URL

Compose 使用預設 database 名稱時：

~~~powershell
docker compose exec -T db psql -U pokemon -d pokemon --csv --command "SELECT p.pokedex_number, p.name_zh, pi.image_url FROM pokemon AS p JOIN pokemon_images AS pi ON pi.pokemon_id = p.id WHERE pi.image_kind = 'artwork' ORDER BY p.pokedex_number" > pk_pic/manifests/pokemon_artwork_url_backup.csv
~~~

若 `POSTGRES_USER` 或 `POSTGRES_DB` 不同，請替換指令中的值。備份留在 `pk_pic/`，不要提交 repository。

### 2. 設定 importer URL 目錄

在 `.env` 設定 object 所在的目錄，而不是只有 CloudFront domain：

~~~env
POKEMON_ARTWORK_BASE_URL=https://cdn.example.com/images/pokemon/artwork
~~~

Importer 會產生固定四位數 URL，例如：

~~~text
https://cdn.example.com/images/pokemon/artwork/0001.png
~~~

### 3. 重新匯入並重啟 API

~~~bash
docker compose run --rm seed
docker compose restart api
~~~

Importer 在單一交易中 upsert 圖片 URL。Sprite URL 不會受到 `POKEMON_ARTWORK_BASE_URL` 影響。API restart 會重新載入推薦結果使用的圖片資料。

### 4. 驗證 database

~~~sql
SELECT
  count(*) FILTER (WHERE image_kind = 'artwork') AS artwork_rows,
  count(*) FILTER (
    WHERE image_kind = 'artwork'
      AND image_url LIKE 'https://cdn.example.com/images/pokemon/artwork/%'
  ) AS cdn_artwork_rows,
  count(*) FILTER (WHERE image_kind = 'sprite') AS sprite_rows
FROM pokemon_images;
~~~

預期 `artwork_rows`、`cdn_artwork_rows` 與 `sprite_rows` 都是 1,025。接著檢查推薦頁、圖鑑列表與詳細頁的圖片是否能正常載入。

## 回復 CSV 原始 URL

目前 Compose 設定以專案 CloudFront 目錄作為 seed 預設值。若要讓這次匯入改用 CSV 原始 URL，需在執行時明確傳入空值：

~~~bash
docker compose run --rm -e POKEMON_ARTWORK_BASE_URL= seed
docker compose restart api
~~~

Importer 會依 `pokemon_descript/pokedex_final.csv` 恢復 artwork URL。日後若再次執行未覆寫環境變數的 Compose seed，CloudFront URL 會重新套用。這個回復只改 PostgreSQL URL，不會刪除 S3 objects、CloudFront cache 或本機圖片。
