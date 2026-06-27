"""アプリ全体の設定値。

このアプリは、スプレッドシートの「ダッシュボード」シート（判定済みの表）を
そのまま読み取って表示する。判定ルールはスプレッドシート側にあるので、
ルールを変えたいときはコードではなくスプレッドシートを編集する。
"""

from __future__ import annotations

import os
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


# 接続情報 -------------------------------------------------------------------
# 実 ID を直接デフォルトに置くと、設定漏れで本番に意図せず触れる可能性があるため
# デフォルトは空にしておき、必ず .env / 環境変数経由で指定する設計にする。
SHEET_ID: str = os.getenv("SHEET_ID", "")
GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS", "./service_account.json"
)
# 読み取り対象タブ。WORKSHEET_NAME が最優先。新スプレッドシートでは
# 判定済みの「ダッシュボード」シートを読むので、既定をその名前にしておく。
# `or` で結合しているのは、CI（GitHub Actions）が未設定シークレットを
# 空文字列として環境変数に流し込むケースでも、既定名にフォールバックさせるため。
WORKSHEET_NAME: str = os.getenv("WORKSHEET_NAME") or "ダッシュボード"
WORKSHEET_GID: str = os.getenv("WORKSHEET_GID") or ""


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

# WORKSHEET_NAME / WORKSHEET_GID が一致するシートが無いとき、先頭シートに
# フォールバックするか。既定 False（誤ったシートを読む事故を防ぐ）。
FALLBACK_TO_FIRST_SHEET: bool = _env_bool("FALLBACK_TO_FIRST_SHEET", False)

REFRESH_INTERVAL_MINUTES: int = int(os.getenv("REFRESH_INTERVAL_MINUTES", "60"))
PORT: int = int(os.getenv("PORT", "8000"))


# 元スプレッドシートへのリンク。明示指定が無ければ SHEET_ID から組み立てる。
def _default_sheet_url() -> str:
    if SHEET_ID:
        return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
    return ""


SHEET_URL: str = os.getenv("SHEET_URL", "").strip() or _default_sheet_url()


# 表示用の補助 ---------------------------------------------------------------
APP_TITLE: str = "iMuseLLC 案件 進捗信号ダッシュボード"
