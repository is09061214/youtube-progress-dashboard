"""動画案件ごとの信号（青/黄/赤）を判定するロジック。

判定方針:
- F列「状況」が「完了」or A列「済」 → 公開済み（青扱い、ただし main 側で除外設定なら一覧から外れる）
- 公開予定日が未設定 → グレー（情報不足）
- 公開予定日まで残り日数 ≥ SIGNAL_BLUE_MIN_DAYS  → 青（順調）
- 残り日数 SIGNAL_YELLOW_MIN_DAYS 以上 SIGNAL_BLUE_MIN_DAYS 未満 → 黄（要注意）
- 残り日数が SIGNAL_YELLOW_MIN_DAYS 未満（=過ぎている） → 赤（遅延）

具体的な閾値は app/config.py で変更できます（既定: 青>=5日 / 黄 0〜4日 / 赤 マイナス）。
"""

from __future__ import annotations

from datetime import date

from .config import COMPLETED_STATUSES, SIGNAL_BLUE_MIN_DAYS, SIGNAL_YELLOW_MIN_DAYS
from .models import Video, VideoSignal

BLUE = "blue"
YELLOW = "yellow"
RED = "red"
GRAY = "gray"


def is_completed(video: Video) -> bool:
    if video.posted:
        return True
    return video.status.strip() in COMPLETED_STATUSES


def evaluate_video(video: Video, today: date) -> VideoSignal:
    if is_completed(video):
        return VideoSignal(
            video=video,
            signal=BLUE,
            days_remaining=None,
            reason="公開済み",
        )

    if video.publish_date is None:
        return VideoSignal(
            video=video,
            signal=GRAY,
            days_remaining=None,
            reason="公開予定日が未設定",
        )

    days = (video.publish_date - today).days

    status_text = video.status.strip() or "状況未記入"

    if days >= SIGNAL_BLUE_MIN_DAYS:
        signal = BLUE
        reason = f"{status_text}（公開まで {days} 日）"
    elif days >= SIGNAL_YELLOW_MIN_DAYS:
        signal = YELLOW
        reason = f"{status_text}（公開まで残り {days} 日）"
    else:
        signal = RED
        reason = f"{status_text}（公開予定日を {abs(days)} 日 超過）"

    return VideoSignal(
        video=video,
        signal=signal,
        days_remaining=days,
        reason=reason,
    )


SIGNAL_SORT_ORDER: dict[str, int] = {
    RED: 0,
    YELLOW: 1,
    GRAY: 2,
    BLUE: 3,
}


def sort_key(vs: VideoSignal) -> tuple[int, int, str]:
    """赤 → 黄 → グレー → 青、同信号内では遅延が大きい順、最後にタイトル順。"""
    days = vs.days_remaining if vs.days_remaining is not None else 9999
    return (SIGNAL_SORT_ORDER.get(vs.signal, 9), days, vs.video.title)


def summarize(signals: list[VideoSignal]) -> dict[str, int]:
    counts = {BLUE: 0, YELLOW: 0, RED: 0, GRAY: 0}
    for s in signals:
        counts[s.signal] = counts.get(s.signal, 0) + 1
    counts["total"] = len(signals)
    return counts
