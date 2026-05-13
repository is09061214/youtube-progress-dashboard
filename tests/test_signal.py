"""信号判定ロジックのテスト。"""

from datetime import date, timedelta

from app.models import Video
from app.signal import BLUE, GRAY, RED, YELLOW, evaluate_video, summarize


TODAY = date(2026, 5, 10)


def make_video(
    publish_offset,
    status="編集中",
    posted=False,
):
    publish_date = (
        TODAY + timedelta(days=publish_offset) if publish_offset is not None else None
    )
    return Video(
        no="1",
        client="テスト",
        title="t",
        publish_date=publish_date,
        status=status,
        editor="GS",
        bo="増田",
        posted=posted,
    )


def test_status_完了_is_blue():
    v = make_video(-3, status="完了")
    assert evaluate_video(v, TODAY).signal == BLUE


def test_posted_flag_is_blue():
    v = make_video(-3, status="リンク共有待ち", posted=True)
    assert evaluate_video(v, TODAY).signal == BLUE


def test_publish_date_missing_is_gray():
    v = make_video(None, status="企画中")
    assert evaluate_video(v, TODAY).signal == GRAY


def test_blue_when_plenty_of_buffer():
    v = make_video(10, status="編集中")
    assert evaluate_video(v, TODAY).signal == BLUE


def test_blue_at_threshold():
    v = make_video(5, status="編集中")
    assert evaluate_video(v, TODAY).signal == BLUE


def test_yellow_when_within_4_days():
    v = make_video(4, status="サムネ待ち")
    assert evaluate_video(v, TODAY).signal == YELLOW


def test_yellow_at_today():
    v = make_video(0, status="CL確認中")
    assert evaluate_video(v, TODAY).signal == YELLOW


def test_red_when_overdue():
    v = make_video(-1, status="編集中")
    assert evaluate_video(v, TODAY).signal == RED


def test_summary_counts():
    videos = [
        make_video(-3, status="完了"),         # blue (公開済み)
        make_video(10, status="編集中"),        # blue
        make_video(4, status="サムネ待ち"),     # yellow
        make_video(-1, status="編集中"),        # red
        make_video(None, status="企画中"),      # gray
    ]
    signals = [evaluate_video(v, TODAY) for v in videos]
    counts = summarize(signals)
    assert counts["blue"] == 2
    assert counts["yellow"] == 1
    assert counts["red"] == 1
    assert counts["gray"] == 1
    assert counts["total"] == 5
