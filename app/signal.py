"""信号（赤/黄/青/灰）の定義と、シート上のラベル → 内部キーへの変換。

判定そのものはスプレッドシート「ダッシュボード」シート側で完了している。
このアプリは判定をやり直さず、シートが出した色をそのまま表示する。
そのため、シートのセル値（「赤」「要対応」など）を内部キー（"red" など）に
読み替える変換だけをここに置く。
"""

from __future__ import annotations

BLUE = "blue"
YELLOW = "yellow"
RED = "red"
GRAY = "gray"

# 内部キー → (短ラベル, サブラベル)。表示・画像生成で共有する。
SIGNAL_LABELS: dict[str, tuple[str, str]] = {
    RED: ("赤", "要対応"),
    YELLOW: ("黄", "もうすぐ"),
    BLUE: ("青", "順調"),
    GRAY: ("灰", "情報不足"),
}


def signal_from_label(raw: object) -> str:
    """シートのセル値を内部キーに変換する。

    「赤」「🔴」「要対応」→ "red" のように、表記ゆれを吸収する。
    判定できないときは "" を返す（= リストの終端などとして扱える）。
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    if "🔴" in s or s.startswith("赤") or "要対応" in s or s.lower() == "red":
        return RED
    if "🟡" in s or s.startswith("黄") or "もうすぐ" in s or s.lower() == "yellow":
        return YELLOW
    if "🔵" in s or s.startswith("青") or "順調" in s or s.lower() == "blue":
        return BLUE
    if "⚪" in s or s.startswith("灰") or "情報不足" in s or s.lower() == "gray":
        return GRAY
    return ""
