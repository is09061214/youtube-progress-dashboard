"""毎朝 Discord に進捗サマリを通知するスクリプト。

GitHub Actions の cron から呼び出される想定。
動作:
  1. スプレッドシートから動画一覧を取得（既存の app.sheets を再利用）
  2. 信号判定（既存の app.signal を再利用）
  3. 公開済み・プレースホルダ行を除外
  4. サマリ画像（PNG, 1200x630）を Pillow で生成
  5. Discord Webhook に画像 + リッチエンベッドで POST

必要な環境変数:
  DISCORD_WEBHOOK_URL          Discord のチャンネル Webhook URL（必須）
  SHEET_ID                     スプレッドシート ID（必須）
  WORKSHEET_GID                対象タブの gid（必須）
  GOOGLE_SERVICE_ACCOUNT_JSON  サービスアカウント JSON の中身（文字列）
                               または GOOGLE_APPLICATION_CREDENTIALS にファイルパス
  DASHBOARD_URL                ダッシュボードの公開 URL（任意、Embed のリンク用）
  SHEET_URL                    スプレッドシートの URL（任意、Embed のリンク用）
  TIMEZONE                     既定 Asia/Tokyo
  USE_SAMPLE_DATA              True ならサンプルデータで通知（テスト用）
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

# --- repo root を sys.path に追加（app パッケージを import するため） ---
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_credentials_from_env() -> None:
    """GOOGLE_SERVICE_ACCOUNT_JSON が文字列で渡されていたら、
    一時ファイルに書き出して GOOGLE_APPLICATION_CREDENTIALS にセットする。
    GitHub Secrets では JSON ファイルそのものを置けないので、文字列で受け取って
    実行時にファイル化する運用。
    """
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and os.path.exists(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    ):
        return  # 既にファイルがあるならそのまま
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        return
    fd, path = tempfile.mkstemp(prefix="sa-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        f.write(sa_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path


_setup_credentials_from_env()

# 既存の app パッケージを再利用
from app.config import COMPLETED_STATUSES, EXCLUDE_COMPLETED  # noqa: E402
from app.sheets import fetch_videos  # noqa: E402
from app.signal import evaluate_video, is_completed, summarize  # noqa: E402

logger = logging.getLogger("discord_notify")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


# === Pillow による画像生成 ============================================
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

CANVAS_W, CANVAS_H = 1200, 630

COLOR_BG = "#f8fafc"
COLOR_TEXT = "#1e293b"
COLOR_SUB = "#64748b"
COLOR_TITLE_BG = "#0f172a"
SIGNAL_COLORS = {
    "red": "#ef4444",
    "yellow": "#facc15",
    "blue": "#3b82f6",
    "gray": "#94a3b8",
}

# 日本語フォントの候補（環境ごと）
FONT_CANDIDATES = [
    # GitHub Actions (Ubuntu) で apt install fonts-noto-cjk すると入る
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # 環境変数で明示
    os.getenv("FONT_PATH", ""),
]


def _find_font_path() -> str:
    for p in FONT_CANDIDATES:
        if p and os.path.exists(p):
            return p
    raise RuntimeError(
        "日本語フォントが見つかりませんでした。FONT_PATH を環境変数で指定してください。"
    )


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: int,
    cy: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text((cx - w // 2 - bbox[0], cy - h // 2 - bbox[1]), text, font=font, fill=fill)


def generate_summary_image(counts: dict, today: date) -> bytes:
    font_path = _find_font_path()
    title_font = ImageFont.truetype(font_path, 44)
    huge_font = ImageFont.truetype(font_path, 100)
    label_font = ImageFont.truetype(font_path, 38)
    sub_font = ImageFont.truetype(font_path, 26)
    bottom_font = ImageFont.truetype(font_path, 32)

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # ----- ヘッダー帯 -----
    header_h = 110
    draw.rectangle([0, 0, CANVAS_W, header_h], fill=COLOR_TITLE_BG)
    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][today.weekday()]
    title_text = f"案件進捗サマリ {today.strftime('%Y/%m/%d')} ({weekday_jp})"
    _draw_centered(draw, title_text, CANVAS_W // 2, header_h // 2, title_font, "white")

    # ----- 4色信号 -----
    circles = [
        ("red", "赤", "遅延中", counts.get("red", 0)),
        ("yellow", "黄", "要注意", counts.get("yellow", 0)),
        ("blue", "青", "順調", counts.get("blue", 0)),
        ("gray", "灰", "情報不足", counts.get("gray", 0)),
    ]
    cy = 290
    radius = 95
    spacing = CANVAS_W // 4
    for i, (key, label, sub, count) in enumerate(circles):
        cx = spacing * i + spacing // 2
        # 影
        shadow_off = 6
        draw.ellipse(
            [
                cx - radius + shadow_off,
                cy - radius + shadow_off,
                cx + radius + shadow_off,
                cy + radius + shadow_off,
            ],
            fill="#cbd5e1",
        )
        # 本体
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=SIGNAL_COLORS[key],
        )
        # 内側のハイライト（白い枠）
        draw.ellipse(
            [cx - radius + 8, cy - radius + 8, cx + radius - 8, cy + radius - 8],
            outline=(255, 255, 255, 100),
            width=2,
        )
        # 件数
        _draw_centered(draw, str(count), cx, cy - 5, huge_font, "white")
        # ラベル
        _draw_centered(draw, label, cx, cy + radius + 32, label_font, COLOR_TEXT)
        _draw_centered(draw, sub, cx, cy + radius + 75, sub_font, COLOR_SUB)

    # ----- 下部サマリ -----
    total = counts.get("total", 0)
    urgent = counts.get("red", 0) + counts.get("yellow", 0)
    if urgent > 0:
        bottom_text = f"対応中 {total} 本のうち、要対応 {urgent} 本"
    else:
        bottom_text = f"対応中 {total} 本 — 全て順調です"
    _draw_centered(draw, bottom_text, CANVAS_W // 2, CANVAS_H - 55, bottom_font, COLOR_TEXT)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# === 挨拶の生成 =======================================================
import random  # noqa: E402

# 曜日ごとの挨拶（朝・進捗チェックの文脈に合うもの）
WEEKDAY_GREETINGS = {
    0: ["月曜日の朝です。今週もよろしくお願いします💪", "新しい1週間のスタートです🌱"],
    1: ["火曜日の朝です。今週もペースを掴んでいきましょう", "火曜日、エンジンがかかってきましたね🚗"],
    2: ["水曜日の朝です。週の折り返し地点です🚀", "水曜日、もう半分まで来ました！"],
    3: ["木曜日の朝です。もうひと踏ん張り👊", "木曜日、週末がもう少し見えてきました"],
    4: ["金曜日の朝です。今週のラストスパート✨", "金曜日、今週もあと1日です🌟"],
    5: ["土曜日の朝です。今日もよろしくお願いします🌿", "土曜日、お疲れさまです"],
    6: ["日曜日の朝です。今日もよろしくお願いします🍃", "日曜日、ゆっくりいきましょう"],
}

# 日替わりで使う一般挨拶
GENERAL_GREETINGS = [
    "おはようございます☀️",
    "おはようございます！今日も素敵な1日に✨",
    "おはようございます🌅 今日もよろしくお願いします",
    "おはようございます😊 今日も笑顔で",
    "おはようございます🌷 今日も1日がんばりましょう",
    "おはようございます☕ ホッと一息ついたら確認お願いします",
    "おはようございます🌞 今日もみんなで前進しましょう",
]


def _pick_greeting(today: date) -> str:
    """日付をシードにして「同じ日なら同じ挨拶」だが日が変わると変わるようにする。"""
    rng = random.Random(today.toordinal())
    weekday_pool = WEEKDAY_GREETINGS.get(today.weekday(), [])
    pool = weekday_pool + GENERAL_GREETINGS
    return rng.choice(pool)


# === 本日の格言 =======================================================
# 古今東西の偉人による定番の名言を厳選。
# 名言の出典・言い回しは複数あるため、広く知られているものを採用。
QUOTES: list[dict] = [
    # --- ビジネス・経営（日本） ---
    {"text": "失敗したところでやめてしまうから失敗になる。成功するところまで続ければ成功になる。",
     "author": "松下幸之助", "years": "1894-1989", "title": "パナソニック創業者"},
    {"text": "雨が降ったら傘をさす。当たり前のことを当たり前にやる。",
     "author": "松下幸之助", "years": "1894-1989", "title": "パナソニック創業者"},
    {"text": "成功とは99パーセントの失敗に支えられた1パーセントである。",
     "author": "本田宗一郎", "years": "1906-1991", "title": "本田技研工業創業者"},
    {"text": "チャレンジして失敗を恐れるよりも、何もしないことを恐れろ。",
     "author": "本田宗一郎", "years": "1906-1991", "title": "本田技研工業創業者"},
    {"text": "楽観的に構想し、悲観的に計画し、楽観的に実行する。",
     "author": "稲盛和夫", "years": "1932-2022", "title": "京セラ・KDDI創業者"},
    {"text": "人生・仕事の結果＝考え方×熱意×能力。",
     "author": "稲盛和夫", "years": "1932-2022", "title": "京セラ・KDDI創業者"},
    {"text": "夢なき者に理想なし、理想なき者に計画なし、計画なき者に実行なし、実行なき者に成功なし。",
     "author": "吉田松陰", "years": "1830-1859", "title": "幕末の思想家・教育者"},
    {"text": "道徳なき経済は罪悪であり、経済なき道徳は寝言である。",
     "author": "二宮尊徳", "years": "1787-1856", "title": "江戸後期の思想家・農政家"},
    {"text": "登る山を決めなさい。これで人生の半分が決まる。",
     "author": "孫正義", "years": "1957-", "title": "ソフトバンクグループ創業者"},
    {"text": "成功はゴミ箱に捨てなさい。失敗から学ぶ方が、はるかに価値がある。",
     "author": "柳井正", "years": "1949-", "title": "ファーストリテイリング会長兼社長"},
    {"text": "すぐやる、必ずやる、出来るまでやる。",
     "author": "永守重信", "years": "1944-", "title": "ニデック（旧・日本電産）創業者"},
    {"text": "変化対応こそ、企業の生命線である。",
     "author": "鈴木敏文", "years": "1932-", "title": "セブン&アイ・ホールディングス元会長"},
    {"text": "金も大事だが、人が大事だ。人を中心に考えれば道は開ける。",
     "author": "出光佐三", "years": "1885-1981", "title": "出光興産創業者"},
    {"text": "障子をあけてみよ、外は広いぞ。",
     "author": "豊田佐吉", "years": "1867-1930", "title": "豊田自動織機創業者"},
    {"text": "他人と過去は変えられないが、自分と未来は変えられる。",
     "author": "エリック・バーン", "years": "1910-1970", "title": "カナダの精神科医・交流分析の創始者"},

    # --- ビジネス・経営（海外） ---
    {"text": "ハングリーであれ。愚かであれ。",
     "author": "スティーブ・ジョブズ", "years": "1955-2011", "title": "Apple共同創業者"},
    {"text": "あなたの時間は限られている。だから他人の人生を生きて時間を無駄にしてはいけない。",
     "author": "スティーブ・ジョブズ", "years": "1955-2011", "title": "Apple共同創業者"},
    {"text": "イノベーションは、リーダーと追従者を分けるものだ。",
     "author": "スティーブ・ジョブズ", "years": "1955-2011", "title": "Apple共同創業者"},
    {"text": "未来を予測する最善の方法は、それを創り出すことだ。",
     "author": "ピーター・ドラッカー", "years": "1909-2005", "title": "経営学者"},
    {"text": "成果をあげる者は仕事からスタートしない。時間からスタートする。",
     "author": "ピーター・ドラッカー", "years": "1909-2005", "title": "経営学者"},
    {"text": "成功は最低の教師だ。優秀な人々をして「自分は負けるはずがない」と思い込ませる。",
     "author": "ビル・ゲイツ", "years": "1955-", "title": "マイクロソフト共同創業者"},
    {"text": "私は難しい仕事を、いつも怠け者にやらせることにしている。なぜなら、彼らは簡単な方法を見つけてくれるからだ。",
     "author": "ビル・ゲイツ", "years": "1955-", "title": "マイクロソフト共同創業者"},
    {"text": "もしできると思えばできる、できないと思えばできない。これは絶対的な法則である。",
     "author": "ヘンリー・フォード", "years": "1863-1947", "title": "フォード・モーター創業者"},
    {"text": "20年経って、自分にできなかった事より、できた事を多く誇りに思いなさい。",
     "author": "ヘンリー・フォード", "years": "1863-1947", "title": "フォード・モーター創業者"},
    {"text": "重要なのは何をするかより、何をしないかを決めることだ。",
     "author": "ウォーレン・バフェット", "years": "1930-", "title": "投資家・バークシャー・ハサウェイCEO"},
    {"text": "10年持てない株なら、10分でも持つべきではない。",
     "author": "ウォーレン・バフェット", "years": "1930-", "title": "投資家・バークシャー・ハサウェイCEO"},
    {"text": "完璧を目指すよりも、まず終わらせろ。",
     "author": "マーク・ザッカーバーグ", "years": "1984-", "title": "Meta（旧Facebook）共同創業者"},
    {"text": "成功の秘訣は、普通のことを並はずれて上手にやることである。",
     "author": "ジョン・D・ロックフェラー", "years": "1839-1937", "title": "石油王・スタンダード・オイル創業者"},
    {"text": "緑が成長を意味し、熟したら腐るのみだ。",
     "author": "レイ・クロック", "years": "1902-1984", "title": "マクドナルド創業者"},
    {"text": "もしあなたに素晴らしいチャンスが提供されたが、できるか分からないなら、まずイエスと答えよ。やり方はあとから覚えればいい。",
     "author": "リチャード・ブランソン", "years": "1950-", "title": "ヴァージン・グループ創業者"},
    {"text": "もし重要な何かをやろうとしているのなら、たとえ怖くても、それをやるべきだ。",
     "author": "イーロン・マスク", "years": "1971-", "title": "テスラ・SpaceX CEO"},
    {"text": "発明するためには長期的な視点を持って、誤解されることを覚悟しなければならない。",
     "author": "ジェフ・ベゾス", "years": "1964-", "title": "Amazon創業者"},
    {"text": "顧客とは王様である。お客様の期待を裏切らないことが、すべての出発点だ。",
     "author": "サム・ウォルトン", "years": "1918-1992", "title": "ウォルマート創業者"},
    {"text": "ビジネスとは他の人の金を扱うことだ。やがてその金は底を尽く。",
     "author": "アレクサンドル・デュマ", "years": "1802-1870", "title": "フランスの作家"},

    # --- 哲学・思想 ---
    {"text": "千里の道も一歩から。",
     "author": "老子", "years": "紀元前6世紀頃", "title": "中国の思想家・道家の祖"},
    {"text": "足るを知る者は富む。",
     "author": "老子", "years": "紀元前6世紀頃", "title": "中国の思想家・道家の祖"},
    {"text": "過ちて改めざる、これを過ちという。",
     "author": "孔子", "years": "紀元前551-479", "title": "中国の思想家"},
    {"text": "学びて時にこれを習う、亦た説ばしからずや。",
     "author": "孔子", "years": "紀元前551-479", "title": "中国の思想家"},
    {"text": "汝自身を知れ。",
     "author": "ソクラテス", "years": "紀元前470-399", "title": "古代ギリシャの哲学者"},
    {"text": "ただ生きるのではなく、善く生きることが大切だ。",
     "author": "ソクラテス", "years": "紀元前470-399", "title": "古代ギリシャの哲学者"},
    {"text": "始めることが、最も重要なことである。",
     "author": "プラトン", "years": "紀元前427-347", "title": "古代ギリシャの哲学者"},
    {"text": "優秀さとは行為ではなく、習慣である。",
     "author": "アリストテレス", "years": "紀元前384-322", "title": "古代ギリシャの哲学者"},
    {"text": "あなたが何度生まれ変わろうとも、本当のあなたは変わらない。",
     "author": "マルクス・アウレリウス", "years": "121-180", "title": "ローマ皇帝・ストア派哲学者"},
    {"text": "どこへ向かって進んでいるかを知らない者にとって、いかなる風も順風ではない。",
     "author": "セネカ", "years": "紀元前4-紀元65", "title": "古代ローマの哲学者"},
    {"text": "知識は力なり。",
     "author": "フランシス・ベーコン", "years": "1561-1626", "title": "イギリスの哲学者・政治家"},
    {"text": "人間は考える葦である。",
     "author": "ブレーズ・パスカル", "years": "1623-1662", "title": "フランスの哲学者・数学者"},
    {"text": "勇気を持て。汝自身の理性を使う勇気を持て。",
     "author": "イマヌエル・カント", "years": "1724-1804", "title": "ドイツの哲学者"},
    {"text": "脱皮しない蛇は滅びる。",
     "author": "フリードリヒ・ニーチェ", "years": "1844-1900", "title": "ドイツの哲学者"},
    {"text": "事実と言うものは存在しない。存在するのは解釈だけである。",
     "author": "フリードリヒ・ニーチェ", "years": "1844-1900", "title": "ドイツの哲学者"},
    {"text": "心を変えれば、態度が変わる。態度が変われば、行動が変わる。行動が変われば、習慣が変わる。",
     "author": "ウィリアム・ジェームズ", "years": "1842-1910", "title": "アメリカの哲学者・心理学者"},

    # --- 科学・発明 ---
    {"text": "知識より大切なのは想像力である。",
     "author": "アルベルト・アインシュタイン", "years": "1879-1955", "title": "理論物理学者"},
    {"text": "学べば学ぶほど、自分が何も知らないことに気づく。気づけば気づくほど、もっと学びたくなる。",
     "author": "アルベルト・アインシュタイン", "years": "1879-1955", "title": "理論物理学者"},
    {"text": "天才とは1パーセントのひらめきと99パーセントの努力である。",
     "author": "トーマス・エジソン", "years": "1847-1931", "title": "発明家・起業家"},
    {"text": "私は失敗したことがない。ただ、1万通りのうまくいかない方法を見つけただけだ。",
     "author": "トーマス・エジソン", "years": "1847-1931", "title": "発明家・起業家"},
    {"text": "私が遠くを見ることができたのは、巨人たちの肩の上に乗っていたからだ。",
     "author": "アイザック・ニュートン", "years": "1643-1727", "title": "イギリスの物理学者・数学者"},
    {"text": "それでも地球は動いている。",
     "author": "ガリレオ・ガリレイ", "years": "1564-1642", "title": "イタリアの物理学者・天文学者"},
    {"text": "人生において恐れるべきものは何もない。理解すべきものがあるだけだ。",
     "author": "マリ・キュリー", "years": "1867-1934", "title": "物理学者・化学者・ノーベル賞2度受賞"},
    {"text": "見上げてごらん、足元ではなく星を。",
     "author": "スティーヴン・ホーキング", "years": "1942-2018", "title": "理論物理学者"},

    # --- 芸術・文学 ---
    {"text": "単純さは究極の洗練である。",
     "author": "レオナルド・ダ・ヴィンチ", "years": "1452-1519", "title": "ルネサンス期の芸術家・科学者"},
    {"text": "輝くものすべてが金とは限らない。",
     "author": "ウィリアム・シェイクスピア", "years": "1564-1616", "title": "イギリスの劇作家・詩人"},
    {"text": "苦しみが残せば、美は残る。",
     "author": "ピエール=オーギュスト・ルノワール", "years": "1841-1919", "title": "フランスの画家"},
    {"text": "人は自分で自分を励ますしかない。",
     "author": "ヨハン・ヴォルフガング・フォン・ゲーテ", "years": "1749-1832", "title": "ドイツの作家・詩人・自然科学者"},
    {"text": "いまから20年後、あなたはやったことよりやらなかったことに失望するだろう。",
     "author": "マーク・トウェイン", "years": "1835-1910", "title": "アメリカの作家"},
    {"text": "経験とは、人が自分の失敗につける名前である。",
     "author": "オスカー・ワイルド", "years": "1854-1900", "title": "アイルランド出身の作家・詩人"},
    {"text": "他人より優れているからといって高貴ではない。本当の高貴さとは、過去の自分より優れていることだ。",
     "author": "アーネスト・ヘミングウェイ", "years": "1899-1961", "title": "アメリカの作家・ノーベル文学賞受賞"},
    {"text": "私は何かを学ぶには、自分で体験する以外にはないと思う。",
     "author": "パブロ・ピカソ", "years": "1881-1973", "title": "スペイン出身の画家・彫刻家"},
    {"text": "夢を見ることができるなら、それは実現できる。",
     "author": "ウォルト・ディズニー", "years": "1901-1966", "title": "ディズニー創業者・映画製作者"},
    {"text": "私の人生は楽しくなかった。だから私は自分の人生を創造したのよ。",
     "author": "ココ・シャネル", "years": "1883-1971", "title": "フランスのファッションデザイナー"},

    # --- 日本の文学・芸術 ---
    {"text": "あせってはいけません。ただ、たゆまずに進みなさい。",
     "author": "夏目漱石", "years": "1867-1916", "title": "小説家"},
    {"text": "正しく強く生きるとは、銀河系を自らの中に意識して、これに応じて行くことである。",
     "author": "宮沢賢治", "years": "1896-1933", "title": "詩人・童話作家"},
    {"text": "歳月は、悲しみの最良の医師である。",
     "author": "三島由紀夫", "years": "1925-1970", "title": "小説家・劇作家"},
    {"text": "創造というのは記憶ですね。",
     "author": "黒澤明", "years": "1910-1998", "title": "映画監督"},
    {"text": "大事なものは、たいてい面倒くさい。",
     "author": "宮崎駿", "years": "1941-", "title": "アニメーション映画監督"},
    {"text": "どんな仕事もやり遂げる秘訣は、ひとつのことをやり続ける根気である。",
     "author": "手塚治虫", "years": "1928-1989", "title": "漫画家・アニメーション作家"},

    # --- スポーツ ---
    {"text": "小さなことを積み重ねることが、とんでもないところへ行くただ一つの道です。",
     "author": "イチロー", "years": "1973-", "title": "プロ野球選手"},
    {"text": "夢や目標を達成するには、一つしか方法はない。小さなことを積み重ねることです。",
     "author": "イチロー", "years": "1973-", "title": "プロ野球選手"},
    {"text": "努力は必ず報われる。もし報われない努力があるのなら、それはまだ努力と呼べない。",
     "author": "王貞治", "years": "1940-", "title": "プロ野球選手・指導者"},
    {"text": "失敗とは、成功する前にやめてしまうことだ。",
     "author": "長嶋茂雄", "years": "1936-", "title": "プロ野球選手・指導者"},
    {"text": "勝ちに不思議の勝ちあり、負けに不思議の負けなし。",
     "author": "野村克也", "years": "1935-2020", "title": "プロ野球選手・指導者（言葉自体は松浦静山）"},
    {"text": "勝利者は決してあきらめない。あきらめる者は決して勝てない。",
     "author": "ヴィンス・ロンバルディ", "years": "1913-1970", "title": "アメリカンフットボール指導者"},
    {"text": "私は何度も何度も失敗した。だからこそ、私は成功できたのだ。",
     "author": "マイケル・ジョーダン", "years": "1963-", "title": "プロバスケットボール選手"},
    {"text": "不可能とは、自らの力で世界を切り拓くことを放棄した臆病者の言葉だ。",
     "author": "モハメド・アリ", "years": "1942-2016", "title": "プロボクサー・WBC世界ヘビー級王者"},
    {"text": "目標は必ずしも到達されるべきものではない。しばしば、それは単に狙うものでしかない。",
     "author": "ブルース・リー", "years": "1940-1973", "title": "武道家・俳優"},
    {"text": "考えるな、感じろ。",
     "author": "ブルース・リー", "years": "1940-1973", "title": "武道家・俳優"},

    # --- 政治家・社会活動家 ---
    {"text": "我々の人生における最大の栄光は、決して転ばないことではなく、転ぶたびに起き上がり続けることにある。",
     "author": "ネルソン・マンデラ", "years": "1918-2013", "title": "南アフリカ初の黒人大統領"},
    {"text": "明日死ぬかのように生き、永遠に生きるかのように学べ。",
     "author": "マハトマ・ガンディー", "years": "1869-1948", "title": "インド独立の指導者"},
    {"text": "あなた自身が、世界に望む変化となれ。",
     "author": "マハトマ・ガンディー", "years": "1869-1948", "title": "インド独立の指導者"},
    {"text": "成功とは、情熱を失わずに失敗から失敗へと進む能力である。",
     "author": "ウィンストン・チャーチル", "years": "1874-1965", "title": "イギリスの首相"},
    {"text": "凧が一番高く上がるのは、風に向かっている時である。",
     "author": "ウィンストン・チャーチル", "years": "1874-1965", "title": "イギリスの首相"},
    {"text": "愛の反対は憎しみではなく、無関心です。",
     "author": "マザー・テレサ", "years": "1910-1997", "title": "修道女・ノーベル平和賞受賞者"},
    {"text": "楽観主義は人を成功へと導く信念である。希望がなければ何事も成就するものではない。",
     "author": "ヘレン・ケラー", "years": "1880-1968", "title": "アメリカの社会活動家・著作家"},
    {"text": "私たちが恐れなければならないのは、恐れそのものである。",
     "author": "フランクリン・D・ルーズベルト", "years": "1882-1945", "title": "第32代アメリカ大統領"},
    {"text": "国があなたに何をしてくれるかではなく、あなたが国に何ができるかを問いたまえ。",
     "author": "ジョン・F・ケネディ", "years": "1917-1963", "title": "第35代アメリカ大統領"},
    {"text": "暗闇は暗闇を払えない。光のみがそれをなしうる。憎しみは憎しみを払えない。愛のみがそれをなしうる。",
     "author": "マーティン・ルーサー・キング Jr.", "years": "1929-1968", "title": "アメリカの公民権運動指導者"},
    {"text": "準備しておこう。チャンスはいつか必ずやってくる。",
     "author": "エイブラハム・リンカーン", "years": "1809-1865", "title": "第16代アメリカ大統領"},

    # --- 日本の思想・歴史 ---
    {"text": "天は人の上に人を造らず、人の下に人を造らず。",
     "author": "福沢諭吉", "years": "1835-1901", "title": "啓蒙思想家・慶應義塾の創設者"},
    {"text": "我以外、皆我師なり。",
     "author": "宮本武蔵", "years": "1584-1645", "title": "剣豪・兵法家"},
    {"text": "信念は事を成し、疑念は事を破る。",
     "author": "中村天風", "years": "1876-1968", "title": "思想家・教育者"},
    {"text": "世の人は我を何とも言わば言え。我なすことは我のみぞ知る。",
     "author": "坂本龍馬", "years": "1836-1867", "title": "幕末の志士"},
    {"text": "人の一生は重荷を負うて遠き道を行くがごとし。急ぐべからず。",
     "author": "徳川家康", "years": "1543-1616", "title": "江戸幕府初代将軍"},
    {"text": "鳴かぬなら 鳴くまで待とう ホトトギス。",
     "author": "徳川家康（に擬せられた句）", "years": "1543-1616", "title": "江戸幕府初代将軍"},
    {"text": "人は城、人は石垣、人は堀。情けは味方、仇は敵なり。",
     "author": "武田信玄", "years": "1521-1573", "title": "甲斐国の戦国大名"},
    {"text": "運は天にあり、鎧は胸にあり、手柄は足にあり。",
     "author": "上杉謙信", "years": "1530-1578", "title": "越後国の戦国大名"},
    {"text": "敬天愛人。",
     "author": "西郷隆盛", "years": "1828-1877", "title": "明治維新の指導者"},

    # --- 自己啓発・人生訓 ---
    {"text": "あなたが今日できることを明日に延ばしてはならない。",
     "author": "ベンジャミン・フランクリン", "years": "1706-1790", "title": "アメリカ建国の父・科学者"},
    {"text": "今日という日は、残りの人生の最初の日である。",
     "author": "チャールズ・ディードリッヒ", "years": "1913-1997", "title": "アメリカの社会改革者"},
    {"text": "未来にはいくつもの名前がある。弱者にとっては「不可能」、臆病者にとっては「未知」、しかし勇者にとっては「理想」である。",
     "author": "ヴィクトル・ユーゴー", "years": "1802-1885", "title": "フランスの作家"},
    {"text": "人を動かす秘訣はただ一つしかない。すなわち、相手の心に強い欲求を起こさせること。",
     "author": "デール・カーネギー", "years": "1888-1955", "title": "アメリカの作家・教育者"},
    {"text": "思考は現実化する。",
     "author": "ナポレオン・ヒル", "years": "1883-1970", "title": "アメリカの著作家"},
    {"text": "最も重要なことを、最も重要なものに保ちなさい。",
     "author": "スティーブン・コヴィー", "years": "1932-2012", "title": "アメリカの経営コンサルタント"},
    {"text": "人を喜ばせ、また自分も喜ぶこと。なんと素晴らしいことだろう。",
     "author": "アンネ・フランク", "years": "1929-1945", "title": "「アンネの日記」著者"},
    {"text": "希望とは、もともとあるものとも言えぬし、ないものとも言えない。それは地上の道のようなものである。",
     "author": "魯迅", "years": "1881-1936", "title": "中国の小説家・思想家"},
    {"text": "一年の計は元旦にあり、一日の計は朝にあり。",
     "author": "毛利元就", "years": "1497-1571", "title": "戦国時代の武将（諸説あり）"},
    {"text": "急いではいけない。しかし休んでもいけない。",
     "author": "ヨハン・ヴォルフガング・フォン・ゲーテ", "years": "1749-1832", "title": "ドイツの作家・詩人"},
]


def _pick_quote(today: date) -> dict:
    """日付に応じて格言を1つ選ぶ。

    アルゴリズム:
      - 全格言を1サイクル（=len(QUOTES)日）で必ず1回ずつ巡回する
      - サイクル番号をシードに毎サイクル違う順序で並べ替える
      - これにより「同じ格言が短期間で被ること」を防ぎつつ、
        毎日違うものが届くようにする。
    """
    n = len(QUOTES)
    cycle_num = today.toordinal() // n
    index_in_cycle = today.toordinal() % n
    indices = list(range(n))
    random.Random(cycle_num ^ 0x9E3779B1).shuffle(indices)
    return QUOTES[indices[index_in_cycle]]


def _format_quote(q: dict) -> str:
    """Discord に貼る用に整形する。"""
    return (
        "**【本日の格言】**\n"
        f"> {q['text']}\n"
        f"— {q['author']}（{q['years']}・{q['title']}）"
    )


# === Discord Webhook へ POST ==========================================
import requests  # noqa: E402


def post_to_discord(
    webhook_url: str,
    image_bytes: bytes,
    today: date,
    counts: dict,
    dashboard_url: Optional[str],
    sheet_url: Optional[str],
    mention_everyone: bool = True,
) -> None:
    """シンプルな本文 + 画像で通知する。
    - @everyone（任意、既定 ON）
    - 日替わりの挨拶
    - 「進捗ダッシュボードを確認してください！」+ URL
    - 「案件進捗管理表を最新の状態に更新してください！」+ URL
    - サマリ画像（添付、Discord が自動でプレビュー表示）
    詳細リスト（赤・黄案件）は画像とリンク先に任せて削除。
    """
    greeting = _pick_greeting(today)
    quote = _pick_quote(today)

    lines = []
    if mention_everyone:
        lines.append("@everyone")
    lines.append(greeting)
    lines.append("")
    lines.append(_format_quote(quote))
    lines.append("")
    lines.append("📊 **進捗ダッシュボードを確認してください！**")
    if dashboard_url:
        # `<URL>` で囲むと Discord の自動URL展開（埋め込みカード）が抑制され、本文がスッキリする
        lines.append(f"<{dashboard_url}>")
    lines.append("")
    lines.append("📋 **案件進捗管理表を最新の状態に更新してください！**")
    if sheet_url:
        lines.append(f"<{sheet_url}>")

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

    files = {"file": ("summary.png", image_bytes, "image/png")}
    data = {"payload_json": json.dumps(payload, ensure_ascii=False)}

    logger.info("Discord に POST します（赤=%d 黄=%d 青=%d 灰=%d）",
                counts.get("red", 0), counts.get("yellow", 0),
                counts.get("blue", 0), counts.get("gray", 0))
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

    dashboard_url = os.getenv("DASHBOARD_URL", "").strip() or None
    sheet_url = os.getenv("SHEET_URL", "").strip() or None

    tz = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tokyo"))
    today = datetime.now(tz).date()
    logger.info("today=%s tz=%s", today, tz)

    # ----- データ取得 -----
    try:
        videos = fetch_videos()
    except Exception:
        logger.exception("シート取得に失敗しました。通知をスキップします。")
        return 2

    signals = [evaluate_video(v, today) for v in videos]

    excluded_completed = 0
    if EXCLUDE_COMPLETED:
        before = len(signals)
        signals = [s for s in signals if not is_completed(s.video)]
        excluded_completed = before - len(signals)

    counts = summarize(signals)
    logger.info(
        "summary: red=%d yellow=%d blue=%d gray=%d total=%d (除外 %d)",
        counts.get("red", 0), counts.get("yellow", 0),
        counts.get("blue", 0), counts.get("gray", 0),
        counts.get("total", 0), excluded_completed,
    )

    # ----- 画像生成 -----
    image_bytes = generate_summary_image(counts, today)

    # ----- Discord に POST -----
    mention = os.getenv("MENTION_EVERYONE", "True").strip().lower() in ("true", "1", "yes")
    post_to_discord(
        webhook_url=webhook_url,
        image_bytes=image_bytes,
        today=today,
        counts=counts,
        dashboard_url=dashboard_url,
        sheet_url=sheet_url,
        mention_everyone=mention,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
