# iMuseLLC 案件 進捗信号ダッシュボード

「iMuseLLC 案件管理表」のスプレッドシートをそのまま読み取り、各案件の進捗を **赤／黄／青／灰** の信号で一目で把握できる Web ダッシュボードです。

## 特徴

- スプレッドシートの **「ダッシュボード」シート（判定済みの表）をそのまま読み取って表示**する。判定（赤/黄/青/灰）はスプレッドシート側の数式で行われ、アプリは判定し直さない
- 信号の意味（判定基準はスプレッドシート「ダッシュボード」シートに記載）:
  - **赤（要対応）**: 公開まで 2 日以内、または いずれかの工程が締切超過（パルスで強調）
  - **黄（もうすぐ）**: 公開まで 5 日以内、または 制作締切の 1 日前
  - **青（順調）**: 上記以外
  - **灰（情報不足）**: タイトル・投稿予定日・担当のいずれかが未入力
- 判定ルールを変えたいときは **コードではなくスプレッドシートを編集**すればよい（再デプロイ不要）
- 画面構成（上から）
  1. **信号別の件数サマリ**（要対応・もうすぐ・順調・情報不足）
  2. **要対応・もうすぐ案件のテーブル**（モバイルはカードリスト）
  3. **情報不足（灰）案件**（折りたたみ。クライアント／タイトル／投稿予定／不足項目）
- 月／日 のみで書かれた日付（例: `10/19` / `1/06`）を **自動で年補完**
- 「今日」は **常に JST（Asia/Tokyo）の暦日**で判定（サーバが UTC でも 1 日ズレない）
- `APScheduler` で定期的に最新データを再取得
- 取得失敗時は **画面上部に赤いバナーで明示**（既定ではサンプルへ静かにフォールバックしない）
- `/healthz` でデータ鮮度・最終エラーを返す（古ければ 503）
- `USE_SAMPLE_DATA=True` で **シート連携なしでもサンプルで動作**

## 想定するシート構造（「ダッシュボード」シート）

アプリは「ダッシュボード」シートの中から、見出しのキーワードを手がかりに以下を読み取ります（行・列の位置が多少ずれても動きます）。

- **件数表**: `要対応` / `もうすぐ` / `順調` / `情報不足` / `合計` の見出し行と、その直下の数値行
- **判定基準**: `判定基準：…` で始まるセル（画面の説明文にそのまま表示）
- **要対応リスト**: `信号` / `クライアント` / `タイトル` / `公開予定` / `残り(日)` / `状況` / `編集` / `BO` を含む見出し行と、その下に続く `赤` / `黄` の行
- **情報不足リスト**: `不足項目` を含む見出し行（`クライアント` / `タイトル` / `投稿予定` / `不足項目`）と、その下の行
> 件数・要対応リスト・情報不足リストを **どれも読み取れなかった場合**は取得時にエラーとなり、画面に赤バナーが出ます。
> 検索キーワードは [`app/sheets.py`](app/sheets.py) の `parse_dashboard` で調整できます。

## クイックスタート（サンプルデータで試す）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env はそのままでOK（USE_SAMPLE_DATA=True）

# CSS は git にコミット済みなので通常は不要だが、テンプレートを編集したらビルド
# scripts/build_css.sh build

uvicorn app.main:app --reload --port 8000
```

ブラウザで http://localhost:8000 を開きます。

### CSS のビルド

このアプリは **Tailwind CSS v4 のスタンドアロン CLI** でビルド済み CSS を `app/static/tailwind.css` に置く方式です（CDN 不要、Node.js 不要）。

```bash
# テンプレートを編集してクラスを追加・削除した後はビルドし直す
scripts/build_css.sh build

# 編集中はファイル変更を監視して自動ビルド
scripts/build_css.sh watch
```

スクリプトは初回実行時に `bin/tailwindcss` をプラットフォーム自動判定でダウンロードします（macOS arm64/x64、Linux arm64/x64）。
Docker ビルド時は `Dockerfile` の `css-builder` ステージが Linux 用バイナリで自動ビルドします。

## 実シートへの接続

### 1. サービスアカウントを作成

1. Google Cloud Console でプロジェクトを作成（既存でも可）
2. 「APIとサービス」→「ライブラリ」で **Google Sheets API** と **Google Drive API** を有効化
3. 「IAM と管理」→「サービスアカウント」で作成し、JSON キーをダウンロード
4. ダウンロードした JSON をプロジェクト直下に `service_account.json` として配置（`.gitignore` 済み）

### 2. スプレッドシートを共有

対象シートを開き、サービスアカウントのメールアドレス（`xxx@xxx.iam.gserviceaccount.com`）を **閲覧者** として共有します。

### 3. `.env` を設定

```env
SHEET_ID=<対象スプレッドシートのID>
WORKSHEET_NAME=ダッシュボード
GOOGLE_APPLICATION_CREDENTIALS=./service_account.json
USE_SAMPLE_DATA=False
REFRESH_INTERVAL_MINUTES=60
TIMEZONE=Asia/Tokyo
```

`uvicorn app.main:app --reload --port 8000` で再起動するとシートのデータが反映されます。

## 判定ルールの変更

判定（赤/黄/青/灰）は **スプレッドシート「ダッシュボード」シート側で完結**しています。
ルールを変えたいときは **スプレッドシートの数式を編集**してください。アプリの再デプロイは不要です
（アプリは「ダッシュボード」シートの結果をそのまま表示するだけ）。

## シートの見出しが変わったら

アプリは固定の列番号ではなく **見出しのキーワード**でセクションを探します
（[`app/sheets.py`](app/sheets.py) の `parse_dashboard`）。たとえば要対応リストは
`信号` / `クライアント` / `タイトル` を含む見出し行、情報不足リストは `不足項目` を含む見出し行を探します。
見出しの文言を大きく変える場合は、`parse_dashboard` 内の検索キーワードを合わせて調整してください。

## 環境変数一覧

| 変数 | 既定 | 説明 |
| --- | --- | --- |
| `SHEET_ID` | （空） | 対象スプレッドシートID。未設定だとシート取得時にエラー |
| `WORKSHEET_NAME` | （空） | タブ名で指定する場合 |
| `WORKSHEET_GID` | （空） | タブを `gid` で指定。`WORKSHEET_NAME` 未指定時に使用 |
| `GOOGLE_APPLICATION_CREDENTIALS` | `./service_account.json` | サービスアカウントJSONのパス |
| `USE_SAMPLE_DATA` | `True` | True ならサンプルで動作（シート不要） |
| `FALLBACK_TO_SAMPLE_ON_ERROR` | `False` | True にするとシート取得失敗時にサンプルへ静かにフォールバック（本番非推奨） |
| `FALLBACK_TO_FIRST_SHEET` | `False` | True にすると `WORKSHEET_GID` 不一致時に先頭シートへフォールバック |
| `REFRESH_INTERVAL_MINUTES` | `60` | 自動更新間隔（分）。0 で無効 |
| `TIMEZONE` | `Asia/Tokyo` | 「今日」の判定とスケジューラのタイムゾーン |
| `PORT` | `8000` | 待ち受けポート |

## ヘルスチェック

```
GET /healthz
```

`{ ok, last_updated, last_attempted, last_error, data_age_seconds, is_stale }` を返します。
最終取得がエラー、または最終更新から「更新間隔の3倍」以上経過していたら **HTTP 503**。

## テスト

```bash
.venv/bin/pytest
```

## Discord 朝の進捗通知（GitHub Actions）

- ワークフロー **「Discord 朝の進捗通知」**（[.github/workflows/discord_morning.yml](.github/workflows/discord_morning.yml)）が **毎日 UTC 21:30**（日本時間では **朝 6:30 前後**。GitHub の遅延で **7 時台までずれる**ことがあります）にスプレッドシートを読み、Discord Webhook に投稿します。
- GitHub の **Settings → Secrets and variables → Actions** に、`DISCORD_WEBHOOK_URL` / `SHEET_ID` / `WORKSHEET_NAME`（既定「ダッシュボード」なら省略可）/ `GOOGLE_SERVICE_ACCOUNT_JSON` などが入っている必要があります（手動実行で届くなら設定済みです）。
- **Actions** でワークフローが **無効**になっていないか確認してください。黄色い帯で「60 日間活動がないためスケジュールが無効」などと出ていたら **Enable workflow** が必要です。
- 公開リポジトリでは長期間コミットが無いとスケジュールが止まりやすいため、週 1 回だけタイムスタンプをコミットする **「Schedule keepalive」**（[.github/workflows/schedule_keepalive.yml](.github/workflows/schedule_keepalive.yml)）を入れています。`main` に **ブランチ保護で bot の push を禁止**している場合は、このワークフローが失敗するので保護ルールを調整するか、keepalive を無効化してください。

## デプロイ（Google Cloud Run の例）

サービスアカウントの認証情報の渡し方は **2通り**あります。
推奨は **(A) ランタイムサービスアカウント＋シート共有**で、JSON キーを発行・配布しなくて済みます。

### (A) ランタイムサービスアカウントを使う（推奨）

1. Cloud Run サービスにアタッチするサービスアカウントを作成し、**対象スプレッドシートに「閲覧者」として共有**
2. プロジェクトで Google Sheets API / Google Drive API を有効化
3. デプロイ時に `--service-account` で指定し、`GOOGLE_APPLICATION_CREDENTIALS` 環境変数は **設定しない**（または存在しないパスを指定）

```bash
gcloud run deploy video-progress-dashboard \
  --source . \
  --region asia-northeast1 \
  --service-account=ytdash-runner@<PROJECT_ID>.iam.gserviceaccount.com \
  --set-env-vars SHEET_ID=...,WORKSHEET_NAME=ダッシュボード,USE_SAMPLE_DATA=False,REFRESH_INTERVAL_MINUTES=60,TIMEZONE=Asia/Tokyo,GOOGLE_APPLICATION_CREDENTIALS=
```

`app/sheets.py` は **JSON ファイルがあればそれを優先、無ければ Application Default Credentials (ADC) にフォールバック** します。
そのため Cloud Run のランタイム SA に切り替えるだけで認証が通り、JSON キーの発行・配布は不要です。

### (B) JSON キーを Secret Manager 経由でマウント

1. Secret Manager に `service-account-json` という名前で JSON を保存
2. デプロイ時にファイルとしてマウントし、`GOOGLE_APPLICATION_CREDENTIALS` で参照

```bash
gcloud run deploy video-progress-dashboard \
  --source . \
  --region asia-northeast1 \
  --update-secrets=/secrets/service_account.json=service-account-json:latest \
  --set-env-vars SHEET_ID=...,WORKSHEET_NAME=ダッシュボード,USE_SAMPLE_DATA=False,REFRESH_INTERVAL_MINUTES=60,TIMEZONE=Asia/Tokyo,GOOGLE_APPLICATION_CREDENTIALS=/secrets/service_account.json
```

### アクセス制御

このアプリは認証なし（URLを知っている人なら誰でも閲覧可）の前提で動作します。
社内限定にする場合は **IAP（Identity-Aware Proxy）** を併用するか、
`gcloud run deploy --no-allow-unauthenticated` で IAM 限定公開にしてください。

## ファイル構成

```
.github/
  workflows/          discord_morning / film_monday / schedule_keepalive 等
  schedule-keepalive.log  keepalive ワークフローが週1で更新
app/
  main.py             FastAPI ルート（/, /refresh, /healthz）
  config.py           接続情報・タイムゾーン・フォールバック制御
  models.py           Video / VideoSignal / DashboardSnapshot データクラス
  sheets.py           「ダッシュボード」シートを取得・解析（parse_dashboard）+ ADC フォールバック + 年補完 + サンプルデータ
  schedule.py         年補完ユーティリティ
  signal.py           信号ラベル（赤→red 等）の変換
  scheduler.py        APScheduler によるキャッシュ更新（last_error も保持）
  static/
    src.css           Tailwind v4 のソース（@import "tailwindcss"）
    tailwind.css      ビルド済み CSS（git にコミット済み）
  templates/dashboard.html
tests/
  test_signal.py
  test_sheets.py
  test_schedule.py
scripts/
  build_css.sh        Tailwind CLI のダウンロード＋CSS ビルド
bin/
  tailwindcss         CLI バイナリ（.gitignore 済み・初回ビルド時に自動取得）
Dockerfile            マルチステージ（CSS ビルド → 本体）
requirements.txt
.env.example
```

## アクセシビリティ

主要な配慮:

- 全ての色付き信号アイコンに `role="img"` と `aria-label`（「赤信号（遅延中）」など）を付与し、色だけでなく**スクリーンリーダー読み上げでも識別**できる
- ページ最上部に「本文へスキップ」リンクをキーボードフォーカス時のみ可視化
- テーブルヘッダーに `scope="col"`、テーブルに `<caption>`（sr-only）
- 日付は `<time datetime="...">` で機械可読
- 取得失敗バナーは `role="alert" aria-live="assertive"`
- フォーカスリングを強めに上書き（`:focus-visible` ルール）
- テキストコントラストを `text-slate-900 / 800 / 700` 中心に底上げ
