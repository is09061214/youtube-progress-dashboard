"""毎週月曜 朝に「今後 14 日間の撮影予定」を Discord に通知するスクリプト。

GitHub Actions の cron から呼び出される想定。
動作:
  1. Google カレンダーから今後 14 日間のイベントを取得
  2. タイトルに「撮影」を含むものだけ抽出
  3. リスト画像（1200x630 PNG）を Pillow で生成
  4. Discord Webhook に画像 + テキストを POST

必要な環境変数:
  DISCORD_WEBHOOK_URL          Discord のチャンネル Webhook URL（必須）
  CALENDAR_ID                  対象の Google カレンダー ID（既定 primary）
  GOOGLE_SERVICE_ACCOUNT_JSON  サービスアカウント JSON の中身（文字列）
                               または GOOGLE_APPLICATION_CREDENTIALS にファイルパス
  TIMEZONE                     既定 Asia/Tokyo
  LOOKAHEAD_DAYS               何日先まで見るか（既定 14）
  FILMING_KEYWORD              タイトルに含まれていれば撮影とみなすキーワード（既定 "撮影"）
  MENTION_EVERYONE             True なら @everyone（既定 True）
  BOT_NAME                     既定「ミュー」
  BOT_AVATAR_URL               既定 raw.githubusercontent.com 経由
"""

from __future__ import annotations

import io
import json
import logging
import os
import random
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_credentials_from_env() -> None:
    """GOOGLE_SERVICE_ACCOUNT_JSON が文字列で渡されていたら一時ファイルに書き出す。"""
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and os.path.exists(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    ):
        return
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        return
    fd, path = tempfile.mkstemp(prefix="sa-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        f.write(sa_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path


_setup_credentials_from_env()

logger = logging.getLogger("film_notify")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


# === Google Calendar からの取得 =======================================
from google.oauth2 import service_account  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def fetch_filming_events(
    calendar_id: str, tz: ZoneInfo, lookahead_days: int, keyword: str
) -> list[dict]:
    """カレンダーから「タイトルにキーワードを含む」イベントを取得して返す。

    返却フォーマット:
        [
          {"start": datetime, "end": datetime, "all_day": bool, "title": str, "location": str},
          ...
        ]
    """
    sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not sa_path or not os.path.exists(sa_path):
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS が指定されていません。"
            "サービスアカウント JSON のパスか、GOOGLE_SERVICE_ACCOUNT_JSON を設定してください。"
        )
    creds = service_account.Credentials.from_service_account_file(
        sa_path, scopes=CALENDAR_SCOPES
    )
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    now = datetime.now(tz)
    end = now + timedelta(days=lookahead_days)
    logger.info(
        "カレンダー取得: id=%s 範囲=%s 〜 %s キーワード=%r",
        calendar_id, now.isoformat(), end.isoformat(), keyword,
    )

    resp = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
    )
    items = resp.get("items", [])
    logger.info("取得イベント数（フィルタ前）: %d", len(items))

    results: list[dict] = []
    for ev in items:
        title = (ev.get("summary") or "").strip()
        if keyword not in title:
            continue
        start_raw = ev.get("start", {})
        end_raw = ev.get("end", {})
        if "dateTime" in start_raw:
            start = datetime.fromisoformat(start_raw["dateTime"]).astimezone(tz)
            end_dt = datetime.fromisoformat(end_raw["dateTime"]).astimezone(tz)
            all_day = False
        elif "date" in start_raw:
            start = datetime.fromisoformat(start_raw["date"]).replace(tzinfo=tz)
            end_dt = datetime.fromisoformat(end_raw["date"]).replace(tzinfo=tz)
            all_day = True
        else:
            continue
        results.append({
            "start": start,
            "end": end_dt,
            "all_day": all_day,
            "title": title,
            "location": (ev.get("location") or "").strip(),
        })
    logger.info("フィルタ後の撮影イベント数: %d", len(results))
    return results


# === 画像生成 =========================================================
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

CANVAS_W, CANVAS_H = 1200, 630

COLOR_BG_TOP = (15, 23, 42)       # dark navy
COLOR_BG_BOTTOM = (30, 41, 59)     # slate
COLOR_HEADER_BG = (10, 15, 30)
COLOR_TEXT_PRIMARY = (241, 245, 249)
COLOR_TEXT_SECONDARY = (148, 163, 184)
COLOR_ACCENT = (34, 211, 238)      # cyan
COLOR_DIVIDER = (51, 65, 85)
COLOR_CARD_BG = (30, 41, 59)
COLOR_BADGE_BG = (8, 145, 178)
WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    os.getenv("FONT_PATH", ""),
]


def _find_font_path() -> str:
    for p in FONT_CANDIDATES:
        if p and os.path.exists(p):
            return p
    raise RuntimeError("日本語フォントが見つかりませんでした。")


def _truncate(text: str, font: ImageFont.FreeTypeFont, max_w: int, draw: ImageDraw.ImageDraw) -> str:
    if draw.textbbox((0, 0), text, font=font)[2] <= max_w:
        return text
    ellipsis = "…"
    for i in range(len(text), 0, -1):
        candidate = text[:i] + ellipsis
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_w:
            return candidate
    return ellipsis


def _event_date_range(ev: dict) -> tuple[date, date, bool]:
    """イベントの表示用の (開始日, 終了日, 複数日かどうか) を返す。

    Google Calendar の終日イベントは end が exclusive（最終日の翌日 00:00）
    なので、実際の最終日は end - 1 日として扱う。
    """
    start_d = ev["start"].date()
    if ev["all_day"]:
        end_d = (ev["end"] - timedelta(days=1)).date()
    else:
        end_d = ev["end"].date()
    if end_d < start_d:
        end_d = start_d
    return start_d, end_d, end_d > start_d


def _format_date_pair(start_d: date, end_d: date) -> tuple[str, str]:
    """日付と曜日の表示文字列を、単日 / 複数日に応じて生成する。

    Returns:
        (date_text, weekday_text)
        単日:    "5/19", "(火)"
        複数日:  "5/19→5/20", "(火→水)"
    """
    s_wd = WEEKDAY_JP[start_d.weekday()]
    e_wd = WEEKDAY_JP[end_d.weekday()]
    if end_d == start_d:
        return f"{start_d.month}/{start_d.day}", f"({s_wd})"
    return (
        f"{start_d.month}/{start_d.day}→{end_d.month}/{end_d.day}",
        f"({s_wd}→{e_wd})",
    )


def generate_summary_image(events: list[dict], today: date, lookahead_days: int) -> bytes:
    font_path = _find_font_path()
    title_font = ImageFont.truetype(font_path, 44)
    subtitle_font = ImageFont.truetype(font_path, 22)
    date_font = ImageFont.truetype(font_path, 36)
    weekday_font = ImageFont.truetype(font_path, 24)
    event_font = ImageFont.truetype(font_path, 28)
    time_font = ImageFont.truetype(font_path, 20)
    empty_font = ImageFont.truetype(font_path, 32)

    # 縦方向グラデの背景
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), COLOR_BG_TOP)
    pix = img.load()
    for y in range(CANVAS_H):
        t = y / (CANVAS_H - 1)
        r = int(COLOR_BG_TOP[0] * (1 - t) + COLOR_BG_BOTTOM[0] * t)
        g = int(COLOR_BG_TOP[1] * (1 - t) + COLOR_BG_BOTTOM[1] * t)
        b = int(COLOR_BG_TOP[2] * (1 - t) + COLOR_BG_BOTTOM[2] * t)
        for x in range(CANVAS_W):
            pix[x, y] = (r, g, b)

    draw = ImageDraw.Draw(img)

    # 微細グリッド（テック感）
    grid_color = (40, 55, 80)
    for x in range(0, CANVAS_W, 60):
        draw.line([(x, 0), (x, CANVAS_H)], fill=grid_color, width=1)
    for y in range(0, CANVAS_H, 60):
        draw.line([(0, y), (CANVAS_W, y)], fill=grid_color, width=1)

    # ヘッダー帯
    header_h = 110
    draw.rectangle([0, 0, CANVAS_W, header_h], fill=COLOR_HEADER_BG)
    draw.line([0, header_h, CANVAS_W, header_h], fill=COLOR_ACCENT, width=3)

    title_text = "📸 撮影予定 / Filming Schedule"
    draw.text((40, 25), title_text, font=title_font, fill=COLOR_TEXT_PRIMARY)
    range_start = today
    range_end = today + timedelta(days=lookahead_days - 1)
    subtitle_text = f"{range_start.strftime('%Y/%m/%d')} 〜 {range_end.strftime('%Y/%m/%d')}（今後{lookahead_days}日間）"
    draw.text((42, 76), subtitle_text, font=subtitle_font, fill=COLOR_TEXT_SECONDARY)

    if not events:
        msg = "今後14日間に撮影予定はありません"
        bbox = draw.textbbox((0, 0), msg, font=empty_font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text(
            ((CANVAS_W - w) // 2, (CANVAS_H - h) // 2 + 40),
            msg, font=empty_font, fill=COLOR_TEXT_SECONDARY,
        )
        sub_msg = "新しい撮影予定が入ったらここに表示されます"
        bbox2 = draw.textbbox((0, 0), sub_msg, font=subtitle_font)
        w2 = bbox2[2] - bbox2[0]
        draw.text(
            ((CANVAS_W - w2) // 2, (CANVAS_H - h) // 2 + 95),
            sub_msg, font=subtitle_font, fill=COLOR_TEXT_SECONDARY,
        )
    else:
        max_show = 8
        shown = events[:max_show]
        card_y = header_h + 25
        card_h = 56
        card_gap = 8
        for ev in shown:
            start_d, end_d, is_multi = _event_date_range(ev)
            date_str, wd_str = _format_date_pair(start_d, end_d)

            # カード背景（複数日なら少し縁の色を変えて目立たせる）
            draw.rounded_rectangle(
                [30, card_y, CANVAS_W - 30, card_y + card_h],
                radius=8, fill=COLOR_CARD_BG,
            )
            # 左端の縦線：複数日は明るめのシアン、単日は通常
            draw.rectangle(
                [30, card_y, 36, card_y + card_h],
                fill=COLOR_ACCENT,
            )
            # 日付
            draw.text((54, card_y + 8), date_str, font=date_font, fill=COLOR_TEXT_PRIMARY)
            date_w = draw.textbbox((0, 0), date_str, font=date_font)[2]
            # 曜日バッジ（複数日は幅可変）
            badge_pad_x = 12
            badge_x = 54 + date_w + 10
            wd_bbox = draw.textbbox((0, 0), wd_str, font=weekday_font)
            wd_w = wd_bbox[2] - wd_bbox[0]
            badge_w = max(56, wd_w + badge_pad_x * 2)
            badge_h = 28
            badge_y = card_y + 14
            draw.rounded_rectangle(
                [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                radius=14, fill=COLOR_BADGE_BG,
            )
            draw.text(
                (badge_x + (badge_w - wd_w) // 2, badge_y + 2),
                wd_str, font=weekday_font, fill=COLOR_TEXT_PRIMARY,
            )
            # タイトル開始位置（時刻は表示しない）
            title_x = badge_x + badge_w + 18

            # タイトル
            title_max_w = CANVAS_W - 30 - 20 - title_x
            title_text2 = _truncate(ev["title"], event_font, title_max_w, draw)
            draw.text((title_x, card_y + 14), title_text2, font=event_font, fill=COLOR_TEXT_PRIMARY)

            card_y += card_h + card_gap

        # 件数が多くて切り詰めた場合
        if len(events) > max_show:
            more = f"… 他 {len(events) - max_show} 件"
            draw.text((40, card_y + 4), more, font=subtitle_font, fill=COLOR_TEXT_SECONDARY)

    # フッター: 件数サマリ
    total = len(events)
    footer_text = f"合計 {total} 件の撮影予定"
    bbox_f = draw.textbbox((0, 0), footer_text, font=subtitle_font)
    fw = bbox_f[2] - bbox_f[0]
    draw.text(
        (CANVAS_W - fw - 30, CANVAS_H - 38),
        footer_text, font=subtitle_font, fill=COLOR_TEXT_SECONDARY,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# === 挨拶 =============================================================
ANNOUNCE_MESSAGE = "今週と来週の撮影予定をアナウンスします！"


def _pick_greeting(today: date) -> str:
    # 月曜の朝に届く固定アナウンス文。
    # 日替わりにしたくなったらリスト化して random.Random(today.toordinal()) で選ぶ。
    return ANNOUNCE_MESSAGE


# === Discord 送信 =====================================================
import requests  # noqa: E402


def _format_event_line(ev: dict) -> str:
    start_d, end_d, is_multi = _event_date_range(ev)
    s_wd = WEEKDAY_JP[start_d.weekday()]
    if is_multi:
        e_wd = WEEKDAY_JP[end_d.weekday()]
        date_str = f"{start_d.month}/{start_d.day}（{s_wd}）〜{end_d.month}/{end_d.day}（{e_wd}）"
    else:
        date_str = f"{start_d.month}/{start_d.day}（{s_wd}）"
    return f"・**{date_str}**　{ev['title']}"


def post_to_discord(
    webhook_url: str,
    image_bytes: bytes,
    today: date,
    events: list[dict],
    mention_everyone: bool = True,
) -> None:
    greeting = _pick_greeting(today)

    lines: list[str] = []
    if mention_everyone:
        lines.append("@everyone")
    lines.append("# 📸 撮影予定リマインド")
    lines.append(f"-# 今後 {os.getenv('LOOKAHEAD_DAYS', '14')} 日間の撮影スケジュール")
    lines.append("")
    lines.append(greeting)
    lines.append("")
    if events:
        for ev in events[:8]:
            lines.append(_format_event_line(ev))
        if len(events) > 8:
            lines.append(f"… 他 {len(events) - 8} 件")
    else:
        lines.append("> 今後14日間に撮影予定はありません。")
    lines.append("")
    lines.append("📅 詳細・最新はカレンダーをご確認ください。")

    content = "\n".join(lines)

    bot_name = os.getenv("BOT_NAME", "ミュー").strip() or "ミュー"
    bot_avatar_url = os.getenv(
        "BOT_AVATAR_URL",
        "https://raw.githubusercontent.com/is09061214/youtube-progress-dashboard/main/app/static/bot-avatar.png",
    ).strip()

    payload = {
        "username": bot_name,
        "content": content,
        "allowed_mentions": {
            "parse": ["everyone"] if mention_everyone else []
        },
    }
    if bot_avatar_url:
        payload["avatar_url"] = bot_avatar_url

    files = {"file": ("filming.png", image_bytes, "image/png")}
    data = {"payload_json": json.dumps(payload, ensure_ascii=False)}

    logger.info("Discord に POST します（撮影予定 %d 件）", len(events))
    res = requests.post(webhook_url, data=data, files=files, timeout=30)
    if res.status_code >= 300:
        logger.error("Discord POST 失敗: status=%d body=%s", res.status_code, res.text[:500])
        res.raise_for_status()
    logger.info("Discord POST 成功 (status=%d)", res.status_code)


# === メイン処理 =======================================================
def main() -> int:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL が未設定です")
        return 1

    calendar_id = os.getenv("CALENDAR_ID", "primary").strip() or "primary"
    keyword = os.getenv("FILMING_KEYWORD", "撮影").strip() or "撮影"
    try:
        lookahead = int(os.getenv("LOOKAHEAD_DAYS", "14"))
    except ValueError:
        lookahead = 14
    tz = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tokyo"))
    today = datetime.now(tz).date()
    logger.info("today=%s tz=%s calendar=%s keyword=%r days=%d",
                today, tz, calendar_id, keyword, lookahead)

    try:
        events = fetch_filming_events(calendar_id, tz, lookahead, keyword)
    except Exception:
        logger.exception("カレンダー取得に失敗しました。通知をスキップします。")
        return 2

    image_bytes = generate_summary_image(events, today, lookahead)

    mention = os.getenv("MENTION_EVERYONE", "True").strip().lower() in ("true", "1", "yes")
    post_to_discord(
        webhook_url=webhook_url,
        image_bytes=image_bytes,
        today=today,
        events=events,
        mention_everyone=mention,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
