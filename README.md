# iMuseLLC 案件 進捗信号ダッシュボード

「iMuseLLC 案件管理表」のスプレッドシートをそのまま読み取り、各案件の進捗を **赤／黄／青／灰** の信号で一目で把握できる Web ダッシュボードです。

## 特徴

- スプレッドシートの **F列「状況」** と **D列「投稿（公開予定日）」** だけを使う、シンプルで安定した信号判定
- 信号の意味（既定値）:
  - **赤**: 公開予定日を過ぎているのに「完了」になっていない（パルスで強調）
  - **黄**: 公開予定日まで残り 4 日以内（要注意）
  - **青**: 公開予定日まで残り 5 日以上（順調）
  - **灰**: 公開予定日が未設定で判定不能（情報不足）
- **公開済み案件は一覧から除外**（F列「完了」または A列「済」、`EXCLUDE_COMPLETED=False` で表示にも切替可）
- タイトルが「未入力」「未撮影」「未定」など下書き行は自動でスキップ
- 画面構成（上から）
  1. **信号別の件数サマリ**（赤・黄・青・灰）
  2. **赤・黄案件のテーブル**（モバイルはカードリスト）
  3. **情報不足（灰）案件**（折りたたみ）
- 月／日 のみで書かれた日付（例: `10/19` / `1/06`）を **自動で年補完**
- 「今日」は **常に JST（Asia/Tokyo）の暦日**で判定（サーバが UTC でも納期判定が1日ズレない）
- `APScheduler` で定期的に最新データを再取得
- 取得失敗時は **画面上部に赤いバナーで明示**（既定ではサンプルへ静かにフォールバックしない）
- `/healthz` でデータ鮮度・最終エラーを返す（古ければ 503）
- `USE_SAMPLE_DATA=True` で **シート連携なしでもサンプルで動作**

## 想定するシート構造

| 列 | ヘッダー（行2） | 内容 |
| --- | --- | --- |
| A | 投稿 | 「済」or 空 |
| B | クライアント | DEP / 1sec / そうぞう など |
| C | # | 案件番号 |
| D | 投稿 | **公開予定日**（年なしOK） |
| E | 動画 | タイトル |
| F | 状況 | 完了 / サムネ待ち / 編集中 / 未着手 / リンク共有待ち / CL確認中 など |
| G | 編集 | 編集者名 |
| H | BO | BO担当 |
| I 以降 | 工程記録（ガントチャート的） | 信号判定には使用しない |

> 行1 はガントチャート用の日付ラベル、行2 が実ヘッダー、行3 以降がデータという前提です。
> **行2 の見出し**は `app/config.py` の `EXPECTED_HEADER_KEYWORDS` で軽く検証され、想定キーワード（「クライアント」「動画」「状況」「投稿」）が見当たらない場合は取得時にエラーとなり、画面に赤バナーが出ます。
> 列の対応は [`app/config.py`](app/config.py) の `ColumnIndex` で変更できます。

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
WORKSHEET_GID=<対象タブのgid（URLの gid= の値）>
GOOGLE_APPLICATION_CREDENTIALS=./service_account.json
USE_SAMPLE_DATA=False
REFRESH_INTERVAL_MINUTES=60
TIMEZONE=Asia/Tokyo
```

`uvicorn app.main:app --reload --port 8000` で再起動するとシートのデータが反映されます。

## 信号閾値の調整

[`app/config.py`](app/config.py) の以下を変更します。

```python
SIGNAL_BLUE_MIN_DAYS = 5   # 残り5日以上 → 青
SIGNAL_YELLOW_MIN_DAYS = 0 # 残り0〜4日 → 黄、マイナス → 赤
```

例: 「残り3日以上を青、残り0〜2日を黄」にしたいなら
`SIGNAL_BLUE_MIN_DAYS = 3`, `SIGNAL_YELLOW_MIN_DAYS = 0`。

## 列構成が変わったら

実シートで列順が変わっても、[`app/config.py`](app/config.py) の `ColumnIndex` を編集するだけで対応できます。

```python
@dataclass(frozen=True)
class ColumnIndex:
    posted_flag: int = 0   # A
    client: int = 1        # B
    no: int = 2            # C
    publish_date: int = 3  # D
    title: int = 4         # E
    status: int = 5        # F
    editor: int = 6        # G
    bo: int = 7            # H
```

「完了」と判定する状況の語彙も同ファイルの `COMPLETED_STATUSES` で増減できます。
ヘッダー検証で見るキーワードは `EXPECTED_HEADER_KEYWORDS` で調整できます。

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
  --set-env-vars SHEET_ID=...,WORKSHEET_GID=1402673414,USE_SAMPLE_DATA=False,REFRESH_INTERVAL_MINUTES=60,TIMEZONE=Asia/Tokyo,GOOGLE_APPLICATION_CREDENTIALS=
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
  --set-env-vars SHEET_ID=...,WORKSHEET_GID=1402673414,USE_SAMPLE_DATA=False,REFRESH_INTERVAL_MINUTES=60,TIMEZONE=Asia/Tokyo,GOOGLE_APPLICATION_CREDENTIALS=/secrets/service_account.json
```

### アクセス制御

このアプリは認証なし（URLを知っている人なら誰でも閲覧可）の前提で動作します。
社内限定にする場合は **IAP（Identity-Aware Proxy）** を併用するか、
`gcloud run deploy --no-allow-unauthenticated` で IAM 限定公開にしてください。

## ファイル構成

```
app/
  main.py             FastAPI ルート（/, /refresh, /healthz）
  config.py           列インデックス・状況語彙・信号閾値・タイムゾーン・フォールバック制御
  models.py           Video / VideoSignal データクラス
  sheets.py           gspread でシート取得 + ヘッダー検証 + ADC フォールバック + 年補完 + サンプルデータ
  schedule.py         年補完ユーティリティ
  signal.py           赤/黄/青/灰 判定
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
