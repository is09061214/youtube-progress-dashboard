"""Google スプレッドシートからの動画データ取得。

実シート（iMuseLLC 案件管理表）の構造:
- 行1: ガントチャート用の日付ラベル（無視）
- 行2: ヘッダー（A:投稿 B:クライアント C:# D:投稿 E:動画 F:状況 G:編集 H:BO ...）
- 行3〜: 案件データ
- D列「投稿」は公開予定日。年が省略された "10/19" などの形式が混在する。

`USE_SAMPLE_DATA=True` の間はサンプルデータで動作するので、
シート連携が未設定でもダッシュボードを試せます。
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional

from .config import (
    COLUMNS,
    DATA_START_ROW,
    EXPECTED_HEADER_KEYWORDS,
    FALLBACK_TO_FIRST_SHEET,
    FALLBACK_TO_SAMPLE_ON_ERROR,
    GOOGLE_APPLICATION_CREDENTIALS,
    HEADER_ROW,
    PLACEHOLDER_TITLES,
    SHEET_ID,
    USE_SAMPLE_DATA,
    WORKSHEET_GID,
    WORKSHEET_NAME,
    today_local,
)
from .models import Video
from .schedule import infer_year

logger = logging.getLogger(__name__)


class SheetSchemaError(RuntimeError):
    """シート構造（ヘッダー・タブ）が想定と違うときに投げる例外。"""


_DATE_PATTERNS_FULL = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y")
_DATE_RE_MONTH_DAY = re.compile(r"^\s*(\d{1,2})[/\-.](\d{1,2})\s*$")


def parse_date(value: object, today: Optional[date] = None) -> Optional[date]:
    """シートのセル値を date に変換する。

    - "2026/01/15" 等 完全な日付 → そのまま
    - "1/15" 等 月/日 のみ → infer_year で年を補完
    - 空文字や認識できない値 → None
    """
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()

    s = str(value).strip()
    if not s:
        return None

    for fmt in _DATE_PATTERNS_FULL:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    m = _DATE_RE_MONTH_DAY.match(s)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            t = today or today_local()
            year = infer_year(month, day, t)
            try:
                return date(year, month, day)
            except ValueError:
                return None

    return None


def _safe_get(row: list, idx: int) -> str:
    if idx < len(row):
        return str(row[idx]).strip()
    return ""


def row_to_video(row: list, today: Optional[date] = None) -> Optional[Video]:
    client = _safe_get(row, COLUMNS.client)
    title = _safe_get(row, COLUMNS.title)
    if not client and not title:
        return None
    if title in PLACEHOLDER_TITLES or not title:
        return None
    no = _safe_get(row, COLUMNS.no)
    publish_date = parse_date(_safe_get(row, COLUMNS.publish_date), today=today)
    status = _safe_get(row, COLUMNS.status)
    editor = _safe_get(row, COLUMNS.editor)
    bo = _safe_get(row, COLUMNS.bo)
    posted_flag = _safe_get(row, COLUMNS.posted_flag)
    return Video(
        no=no,
        client=client or "(未設定)",
        title=title,
        publish_date=publish_date,
        status=status,
        editor=editor,
        bo=bo,
        posted=posted_flag == "済",
    )


def validate_header(header_row: list) -> list[str]:
    """行2のヘッダーが想定列と整合しているかチェックし、警告メッセージのリストを返す。

    完全一致ではなく、「想定列のキーワードがヘッダーセルに含まれているか」で判定する。
    例: COLUMNS.client=1 のセルに「クライアント」が含まれていればOK。
    """
    issues: list[str] = []
    for idx, keyword in EXPECTED_HEADER_KEYWORDS.items():
        cell = _safe_get(header_row, idx)
        if keyword not in cell:
            col_letter = chr(ord("A") + idx)
            issues.append(
                f"列 {col_letter}（index {idx}）のヘッダーに『{keyword}』が見当たりません: 実際=「{cell}」"
            )
    return issues


def _select_worksheet(spreadsheet):
    """設定に従って対象ワークシートを取り出す。
    `WORKSHEET_NAME` が最優先、次に `WORKSHEET_GID`。
    GID 不一致時は既定で例外（FALLBACK_TO_FIRST_SHEET=True なら sheet1 にフォールバック）。
    """
    if WORKSHEET_NAME:
        try:
            return spreadsheet.worksheet(WORKSHEET_NAME)
        except Exception as e:
            raise SheetSchemaError(
                f"WORKSHEET_NAME='{WORKSHEET_NAME}' のタブが見つかりません: {e}"
            ) from e

    if WORKSHEET_GID:
        for ws in spreadsheet.worksheets():
            if str(ws.id) == str(WORKSHEET_GID):
                return ws
        if FALLBACK_TO_FIRST_SHEET:
            logger.warning(
                "WORKSHEET_GID=%s が見つからないため先頭シートにフォールバックします",
                WORKSHEET_GID,
            )
            return spreadsheet.sheet1
        available = ", ".join(f"{ws.title}(gid={ws.id})" for ws in spreadsheet.worksheets())
        raise SheetSchemaError(
            f"WORKSHEET_GID={WORKSHEET_GID} のタブが見つかりません。利用可能: {available}"
        )

    return spreadsheet.sheet1


def _build_credentials(scopes: list[str]):
    """Google API 用のクレデンシャルを取得する。

    優先順位:
      1. `GOOGLE_APPLICATION_CREDENTIALS` で指定された JSON ファイルが存在すればそれを使用
         （ローカル開発・Secret Manager マウント方式）
      2. 上記が無ければ Application Default Credentials (ADC) にフォールバック
         （Cloud Run のランタイムサービスアカウント、`gcloud auth application-default login` 等）
    """
    import os

    from google.oauth2.service_account import Credentials as SACredentials

    if GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
        logger.info("認証: サービスアカウント JSON を使用 (%s)", GOOGLE_APPLICATION_CREDENTIALS)
        return SACredentials.from_service_account_file(
            GOOGLE_APPLICATION_CREDENTIALS, scopes=scopes
        )

    import google.auth

    creds, project = google.auth.default(scopes=scopes)
    logger.info("認証: Application Default Credentials を使用 (project=%s)", project)
    return creds


def fetch_from_google_sheets() -> list[Video]:
    if not SHEET_ID:
        raise RuntimeError("SHEET_ID が未設定です。.env を確認してください。")

    import gspread

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = _build_credentials(scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SHEET_ID)

    worksheet = _select_worksheet(spreadsheet)

    all_values = worksheet.get_all_values()
    if len(all_values) < HEADER_ROW:
        raise SheetSchemaError(
            f"シートの行数が想定より少なすぎます（行数={len(all_values)}, HEADER_ROW={HEADER_ROW}）"
        )

    header = all_values[HEADER_ROW - 1]
    issues = validate_header(header)
    if issues:
        raise SheetSchemaError(
            "シートのヘッダーが想定と異なります。app/config.py の ColumnIndex を確認してください:\n  - "
            + "\n  - ".join(issues)
        )

    today = today_local()
    videos: list[Video] = []
    for row in all_values[DATA_START_ROW - 1 :]:
        v = row_to_video(row, today=today)
        if v:
            videos.append(v)
    return videos


def sample_videos(today: Optional[date] = None) -> list[Video]:
    """実シートからピックした典型データを使ったサンプル。"""
    today = today or today_local()

    def d(month_day: str) -> Optional[date]:
        return parse_date(month_day, today=today)

    return [
        Video(no="116", client="DEP", title="【10分骨盤調整】姿勢改善・代謝爆上がり！立ったままできる骨盤調整ストレッチ",
              publish_date=d("5/10"), status="完了", editor="GS", bo="増田", posted=False),
        Video(no="36", client="1sec", title="総会密着 いつ投稿か？",
              publish_date=d("5/12"), status="編集中", editor="砂田", bo="増田", posted=False),
        Video(no="47", client="1sec", title="未撮影",
              publish_date=d("7/7"), status="未着手", editor="", bo="増田", posted=False),
        Video(no="38", client="1sec", title="【永久保存版】飼い主は絶対知っておきたい。死亡のリスクが高い犬猫の皮膚病について",
              publish_date=d("4/28"), status="完了", editor="GS", bo="増田", posted=True),
        Video(no="84", client="DEP", title="コメントアンサー回",
              publish_date=d("2/15"), status="リンク共有待ち", editor="GS", bo="増田", posted=True),
        Video(no="80", client="DEP", title="岩崎先生_栄養コンシェルジュ食生活について",
              publish_date=d("3/8"), status="リンク共有待ち", editor="安里", bo="増田", posted=True),
        Video(no="9", client="バイオテック", title="苦しい時期の乗り越え方",
              publish_date=d("3/6"), status="リンク共有待ち", editor="GS", bo="増田", posted=True),
        Video(no="40", client="1sec", title="犬のおすすめサプリメント5選",
              publish_date=d("2/10"), status="リンク共有待ち", editor="GS", bo="増田", posted=True),
        Video(no="7", client="バイオテック", title="バイオテックで働いて人生どう変わった？",
              publish_date=d("2/20"), status="完了", editor="かずあき", bo="増田", posted=True),
        Video(no="22", client="mug", title="🌿よもトーク【わたなべさん】",
              publish_date=d("3/18"), status="完了", editor="砂田", bo="岩渕", posted=True),
        Video(no="98", client="そうぞう", title="新作未定の企画",
              publish_date=None, status="企画中", editor="", bo="岩渕", posted=False),
    ]


def fetch_videos() -> list[Video]:
    """シートから取得。USE_SAMPLE_DATA=True ならサンプル。

    取得失敗時は基本的に例外を伝播させる（VideoStore 側で last_error を保持）。
    `FALLBACK_TO_SAMPLE_ON_ERROR=True` を設定したときだけサンプルへフォールバックする
    （ローカル開発時の利便性向け。本番では推奨しない）。
    """
    if USE_SAMPLE_DATA:
        logger.info("USE_SAMPLE_DATA=True のためサンプルデータを返します")
        return sample_videos()
    try:
        return fetch_from_google_sheets()
    except Exception as e:
        if FALLBACK_TO_SAMPLE_ON_ERROR:
            logger.exception(
                "Google Sheets 取得失敗。FALLBACK_TO_SAMPLE_ON_ERROR=True のためサンプルにフォールバックします: %s",
                e,
            )
            return sample_videos()
        raise
