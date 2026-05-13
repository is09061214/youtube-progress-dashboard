"""アプリ全体の設定値。

実シート（iMuseLLC 案件管理表）の構造に合わせて設計しています。
シート構造が変わったらここを書き換えてください。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


# タイムゾーン ----------------------------------------------------------------
# 「今日」の判定はサーバの OS ロケールに依存させず、JST に固定する。
# Cloud Run などホストが UTC のとき、深夜帯に日付が1日ズレる事故を防ぐため。
TIMEZONE_NAME: str = os.getenv("TIMEZONE", "Asia/Tokyo")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)


def today_local() -> date:
    """設定タイムゾーンでの「今日」を返す。"""
    return datetime.now(TIMEZONE).date()


def now_local() -> datetime:
    """設定タイムゾーンでの現在時刻（tz付き）。"""
    return datetime.now(TIMEZONE)


# シートのレイアウト ----------------------------------------------------------
# 実シートは行1がガントチャートの日付ラベル、行2が本当のヘッダーになっている。
HEADER_ROW: int = 2
DATA_START_ROW: int = 3


@dataclass(frozen=True)
class ColumnIndex:
    """0-based の列インデックス（A=0, B=1, ...）。"""

    posted_flag: int = 0   # A: 投稿（"済"が公開済み）
    client: int = 1        # B: クライアント
    no: int = 2            # C: # （案件番号）
    publish_date: int = 3  # D: 投稿（公開予定日）
    title: int = 4         # E: 動画
    status: int = 5        # F: 状況
    editor: int = 6        # G: 編集
    bo: int = 7            # H: BO


COLUMNS = ColumnIndex()


# ヘッダー検証 ---------------------------------------------------------------
# 行2のヘッダー文字列に「以下のキーワードが含まれているか」を緩めに検証する。
# 完全一致ではなく `in` 判定なので、小さな表記ゆれ（"投稿日" 等）には耐える。
EXPECTED_HEADER_KEYWORDS: dict[int, str] = {
    COLUMNS.posted_flag: "投稿",
    COLUMNS.client: "クライアント",
    COLUMNS.publish_date: "投稿",
    COLUMNS.title: "動画",
    COLUMNS.status: "状況",
}


# 状況の語彙 ------------------------------------------------------------------
COMPLETED_STATUSES: set[str] = {
    "完了",
    "済",
}


# このタイトルが入っている行は「下書き / プレースホルダ」と見なし、ダッシュボードに含めない
PLACEHOLDER_TITLES: set[str] = {
    "未入力",
    "未撮影",
    "未定",
    "未設定",
    "(無題)",
    "（無題）",
    "TBD",
    "tbd",
}


# 「公開済み」案件をダッシュボードから除外するか
EXCLUDE_COMPLETED: bool = True

# F列に登場する代表的な状況。並び順は「公開に近い順」のイメージで定義。
KNOWN_STATUSES: list[str] = [
    "未着手",
    "企画中",
    "撮影予定",
    "撮影済",
    "編集中",
    "サムネ待ち",
    "MUSUBI待ち",
    "BO待ち",
    "CL確認中",
    "CL提出済",
    "リンク共有待ち",
    "完了",
]


# 信号判定の閾値（公開予定日までの残り日数）-------------------------------
SIGNAL_BLUE_MIN_DAYS = 5   # 残り5日以上 → 青（順調）
SIGNAL_YELLOW_MIN_DAYS = 0 # 残り0〜4日 → 黄（要注意）、マイナス → 赤（遅延中）


# 接続情報 -------------------------------------------------------------------
# 実 ID を直接デフォルトに置くと、設定漏れで本番に意図せず触れる可能性があるため
# デフォルトは空にしておき、必ず .env 経由で指定する設計にする。
SHEET_ID: str = os.getenv("SHEET_ID", "")
GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS", "./service_account.json"
)
WORKSHEET_NAME: str = os.getenv("WORKSHEET_NAME", "")
WORKSHEET_GID: str = os.getenv("WORKSHEET_GID", "")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


USE_SAMPLE_DATA: bool = _env_bool("USE_SAMPLE_DATA", True)

# シート取得失敗時にサンプルへ自動フォールバックするか。
# 本番（USE_SAMPLE_DATA=False）では既定で False。
# True にすると実環境でも障害時に静かにサンプル表示してしまうので注意。
FALLBACK_TO_SAMPLE_ON_ERROR: bool = _env_bool("FALLBACK_TO_SAMPLE_ON_ERROR", False)

# WORKSHEET_GID が一致するシートが無いとき、先頭シートにフォールバックするか。
# 既定 False（誤った先頭シートを読む事故を防ぐ）。
FALLBACK_TO_FIRST_SHEET: bool = _env_bool("FALLBACK_TO_FIRST_SHEET", False)

REFRESH_INTERVAL_MINUTES: int = int(os.getenv("REFRESH_INTERVAL_MINUTES", "60"))
PORT: int = int(os.getenv("PORT", "8000"))


# 表示用の補助 ---------------------------------------------------------------
APP_TITLE: str = "iMuseLLC 案件 進捗信号ダッシュボード"
