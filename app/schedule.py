"""日付関連のユーティリティ。

シートの公開予定日には年が省略されている（例: "10/19", "1/06"）ため、
今日の日付を基準に最も近い年を補完する関数を用意する。
"""

from __future__ import annotations

from datetime import date


def infer_year(month: int, day: int, today: date, lookback_days: int = 180) -> int:
    """月/日 だけ与えられたとき、もっとも妥当な年を推定する。

    - 「今日からみて 過去 lookback_days 日 〜 未来 (365 - lookback_days) 日」のレンジに入る年
    - 候補が複数あればよりレンジ中心に近いものを採用
    """
    candidates = [today.year - 1, today.year, today.year + 1]
    best_year = today.year
    best_score: float = float("inf")

    for y in candidates:
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        delta = (d - today).days
        if delta < -lookback_days or delta > (365 - lookback_days):
            continue
        score = abs(delta + lookback_days - 90)
        if score < best_score:
            best_score = score
            best_year = y

    return best_year
