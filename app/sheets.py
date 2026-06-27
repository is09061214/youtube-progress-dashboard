"""スプレッドシート「ダッシュボード」シートの読み取り。

このシートは、判定（赤/黄/青/灰）がスプレッドシート側で済んでいる「完成済みの表」。
アプリは判定をやり直さず、シートの内容をそのまま読み取って表示する。

「ダッシュボード」シートの構成（おおよそ）:
  - 上部: 件数の表（要対応 / もうすぐ / 順調 / 情報不足 / 合計）
  - 「判定基準：…」の説明行
  - 「いますぐ確認が必要な案件」の見出し
  - 表: 信号 | クライアント | タイトル | 公開予定 | 残り(日) | 状況 | 編集 | BO
  - 表: クライアント | タイトル | 投稿予定 | 不足項目  （情報不足の一覧）

位置が多少ずれても動くよう、固定の行番号ではなく「見出しのキーワード」を
手がかりに各セクションを探して読む方式にしている。

`USE_SAMPLE_DATA=True` の間はサンプルデータで動作するので、
シート連携が未設定でもダッシュボードを試せます。
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional

from .config import (
    FALLBACK_TO_FIRST_SHEET,
    FALLBACK_TO_SAMPLE_ON_ERROR,
    GOOGLE_APPLICATION_CREDENTIALS,
    SHEET_ID,
    USE_SAMPLE_DATA,
    WORKSHEET_GID,
    WORKSHEET_NAME,
    today_local,
)
from .models import DashboardSnapshot, Video, VideoSignal
from .schedule import infer_year
from .signal import GRAY, signal_from_label

logger = logging.getLogger(__name__)


class SheetSchemaError(RuntimeError):
    """シート構造（タブ・見出し）が想定と違うときに投げる例外。"""


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


# --- グリッド読み取りの小道具 ------------------------------------------------
def _cell(row: list, idx: int) -> str:
    if idx is not None and 0 <= idx < len(row):
        return str(row[idx]).strip()
    return ""


def _find_col(header: list, *keywords: str) -> Optional[int]:
    """見出し行の中で、いずれかのキーワードを含む最初の列インデックスを返す。"""
    for i, cell in enumerate(header):
        text = str(cell).strip()
        for kw in keywords:
            if kw in text:
                return i
    return None


_SIGNAL_EMOJI_RE = re.compile(r"^[\s🔴🟡🔵⚪🟠🟢🟣🔵⬜◯●▲△]+")


def _clean_status(value: str) -> str:
    """状況テキスト先頭の信号絵文字（🔴 等）を取り除く。

    画面側に信号ドットがあるので、状況に絵文字が重複すると見づらいため。
    """
    return _SIGNAL_EMOJI_RE.sub("", str(value)).strip()


def _to_int(value: str) -> Optional[int]:
    s = str(value).strip().replace(",", "")
    if not s:
        return None
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else None


def parse_dashboard(grid: list[list], today: date) -> DashboardSnapshot:
    """「ダッシュボード」シートのグリッド（get_all_values の結果）を読み解く。"""
    counts = {"red": 0, "yellow": 0, "blue": 0, "gray": 0, "total": 0}
    criteria_text = ""
    urgent: list[VideoSignal] = []
    gray_items: list[VideoSignal] = []

    # 1) 件数の表（要対応 / もうすぐ / 順調 / 情報不足 / 合計）-----------------
    for i, row in enumerate(grid[:20]):
        joined = "".join(str(c) for c in row)
        if "要対応" in joined and "もうすぐ" in joined and "順調" in joined:
            label_row = row
            num_row = grid[i + 1] if i + 1 < len(grid) else []
            for key, kw in (
                ("red", "要対応"),
                ("yellow", "もうすぐ"),
                ("blue", "順調"),
                ("gray", "情報不足"),
                ("total", "合計"),
            ):
                col = _find_col(label_row, kw)
                if col is not None:
                    n = _to_int(_cell(num_row, col))
                    if n is not None:
                        counts[key] = n
            break
    if not counts.get("total"):
        counts["total"] = counts["red"] + counts["yellow"] + counts["blue"] + counts["gray"]

    # 2) 「判定基準：…」の文言 -----------------------------------------------
    for row in grid[:20]:
        for cell in row:
            text = str(cell).strip()
            if "判定基準" in text:
                criteria_text = text
                break
        if criteria_text:
            break

    # 3) 要対応（赤・黄）の表 -------------------------------------------------
    hdr_idx = None
    for i, row in enumerate(grid):
        joined = "".join(str(c) for c in row)
        if "信号" in joined and "クライアント" in joined and "タイトル" in joined:
            hdr_idx = i
            break
    if hdr_idx is not None:
        h = grid[hdr_idx]
        c_sig = _find_col(h, "信号")
        c_client = _find_col(h, "クライアント")
        c_title = _find_col(h, "タイトル")
        c_pub = _find_col(h, "公開予定", "投稿予定", "公開")
        c_days = _find_col(h, "残り")
        c_status = _find_col(h, "状況", "ステータス")
        c_editor = _find_col(h, "編集", "制作担当")
        c_bo = _find_col(h, "BO")
        for row in grid[hdr_idx + 1:]:
            sig = signal_from_label(_cell(row, c_sig))
            if sig not in ("red", "yellow"):
                break  # 赤・黄の連続が途切れたら表の終わり
            title = _cell(row, c_title)
            status = _clean_status(_cell(row, c_status))
            video = Video(
                no="",
                client=_cell(row, c_client) or "(未設定)",
                title=title or "(タイトル未入力)",
                publish_date=parse_date(_cell(row, c_pub), today=today),
                status=status,
                editor=_cell(row, c_editor),
                bo=_cell(row, c_bo),
                posted=False,
            )
            urgent.append(
                VideoSignal(
                    video=video,
                    signal=sig,
                    days_remaining=_to_int(_cell(row, c_days)),
                    reason=status,
                )
            )

    # 4) 情報不足（灰）の表 --------------------------------------------------
    # 「不足項目」列を持つ見出し行を探す。上部カウント表の「情報不足」セルに
    # 誤マッチしないよう、列見出し（不足項目）でピンポイントに判定する。
    g_idx = None
    for i, row in enumerate(grid):
        if any("不足項目" in str(c) for c in row):
            g_idx = i
            break
    if g_idx is not None:
        h = grid[g_idx]
        c_client = _find_col(h, "クライアント", "クラアント", "ライアント")
        c_title = _find_col(h, "タイトル")
        c_pub = _find_col(h, "投稿予定", "公開予定", "投稿")
        c_missing = _find_col(h, "不足")
        for row in grid[g_idx + 1:]:
            client = _cell(row, c_client)
            title = _cell(row, c_title)
            missing = _cell(row, c_missing)
            if not client and not title and not missing:
                break  # 空行で表の終わり
            video = Video(
                no="",
                client=client or "(未設定)",
                title=title or "(タイトル未入力)",
                publish_date=parse_date(_cell(row, c_pub), today=today),
                status="",
                editor="",
                bo="",
                posted=False,
            )
            gray_items.append(
                VideoSignal(
                    video=video,
                    signal=GRAY,
                    days_remaining=None,
                    reason=missing or "情報不足",
                )
            )

    return DashboardSnapshot(
        counts=counts,
        urgent=urgent,
        gray_items=gray_items,
        criteria_text=criteria_text,
    )


def _select_worksheet(spreadsheet):
    """設定に従って対象ワークシートを取り出す。
    `WORKSHEET_NAME` が最優先、次に `WORKSHEET_GID`。
    見つからないときは既定で例外（FALLBACK_TO_FIRST_SHEET=True なら sheet1）。
    """
    if WORKSHEET_NAME:
        try:
            return spreadsheet.worksheet(WORKSHEET_NAME)
        except Exception as e:
            if WORKSHEET_GID:
                pass  # 名前で見つからなければ gid を試す
            else:
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
            f"WORKSHEET_NAME='{WORKSHEET_NAME}' / WORKSHEET_GID={WORKSHEET_GID} のタブが"
            f"見つかりません。利用可能: {available}"
        )

    if FALLBACK_TO_FIRST_SHEET:
        return spreadsheet.sheet1
    raise SheetSchemaError("読み取り対象のタブが指定されていません（WORKSHEET_NAME を設定してください）")


def _build_credentials(scopes: list[str]):
    """Google API 用のクレデンシャルを取得する。

    優先順位:
      1. `GOOGLE_APPLICATION_CREDENTIALS` で指定された JSON ファイルが存在すればそれを使用
      2. 無ければ Application Default Credentials (ADC) にフォールバック
         （Cloud Run のランタイムサービスアカウント等）
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


def fetch_dashboard_from_sheets() -> DashboardSnapshot:
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
    grid = worksheet.get_all_values()

    snapshot = parse_dashboard(grid, today_local())
    if not snapshot.urgent and not snapshot.gray_items and snapshot.counts["total"] == 0:
        raise SheetSchemaError(
            f"「{WORKSHEET_NAME or worksheet.title}」シートから案件を1件も読み取れませんでした。"
            "シートの見出し（信号 / クライアント / タイトル / 不足項目 など）をご確認ください。"
        )
    return snapshot


def _sample_grid() -> list[list[str]]:
    """実シート「ダッシュボード」の典型レイアウトを再現したサンプルグリッド。

    本番と同じ parse_dashboard() を通すので、サンプルモードでも
    パーサーの動作確認ができる。
    """
    return [
        ["🔴 要対応", "🟡 もうすぐ", "🔵 順調", "⚪ 情報不足", "合計", "", "", ""],
        ["5", "6", "80", "28", "94", "", "", ""],
        [
            "判定基準：🔴要対応＝公開まで2日以内 または いずれかの工程が締切超過　／　"
            "🟡もうすぐ＝公開まで5日以内 または 制作締切1日前　／　🔵順調＝上記以外　／　"
            "⚪情報不足＝タイトル・投稿予定日・担当のいずれか未入力",
            "", "", "", "", "", "", "",
        ],
        ["いますぐ確認が必要な案件（赤＝要対応 → 黄＝もうすぐ の順）", "", "", "", "", "", "", ""],
        ["信号", "クライアント", "タイトル", "公開予定", "残り(日)", "状況", "編集", "BO"],
        ["赤", "empowerx", "転職エージェントの闇", "6/29", "2", "CL提出待ち（超過）", "安里", "岩渕"],
        ["赤", "角川春樹", "5本目", "6/29", "2", "修正中", "ゆうさく", "岩渕"],
        ["赤", "mug_m", "よもぎ蒸しのコンロの選び方", "7/3", "6", "サムネ待ち（超過）", "ゆき", "岩渕"],
        ["赤", "バイオテック_m", "組織を崩壊させる幹部", "7/3", "6", "サムネ待ち（超過）", "GS", "増田"],
        ["赤", "角川春樹", "6本目", "7/6", "9", "制作待ち（超過）", "ゆうさく", "岩渕"],
        ["黄", "四国物産_m", "田中密着_密着", "6/30", "3", "公開設定・納品待ち", "イカラシ", "岩渕"],
        ["黄", "アーバンガレージ_m", "ベンツ_切り抜き", "6/30", "3", "公開設定・納品待ち", "GS", "岩渕"],
        ["黄", "ハイテクノ_m", "ホワイトカラーからブルーカラーに転職する人について", "7/2", "5", "修正中", "GS", "増田"],
        ["", "", "", "", "", "", "", ""],
        ["クライアント", "タイトル", "投稿予定", "不足項目", "", "", "", ""],
        ["ハイテクノ_m", "", "7/16", "タイトル 制作担当", "", "", "", ""],
        ["そうぞう_m", "", "7/21", "タイトル", "", "", "", ""],
        ["1sec._m", "7/7涙やけについて_ショート", "", "投稿予定日", "", "", "", ""],
    ]


def sample_dashboard(today: Optional[date] = None) -> DashboardSnapshot:
    """サンプルの DashboardSnapshot（本番と同じパーサーを通す）。"""
    return parse_dashboard(_sample_grid(), today or today_local())


def fetch_dashboard() -> DashboardSnapshot:
    """ダッシュボードシートを取得。USE_SAMPLE_DATA=True ならサンプル。

    取得失敗時は基本的に例外を伝播させる（VideoStore 側で last_error を保持）。
    `FALLBACK_TO_SAMPLE_ON_ERROR=True` のときだけサンプルにフォールバックする。
    """
    if USE_SAMPLE_DATA:
        logger.info("USE_SAMPLE_DATA=True のためサンプルデータを返します")
        return sample_dashboard()
    try:
        return fetch_dashboard_from_sheets()
    except Exception as e:
        if FALLBACK_TO_SAMPLE_ON_ERROR:
            logger.exception(
                "ダッシュボード取得失敗。FALLBACK_TO_SAMPLE_ON_ERROR=True のため"
                "サンプルにフォールバックします: %s",
                e,
            )
            return sample_dashboard()
        raise
