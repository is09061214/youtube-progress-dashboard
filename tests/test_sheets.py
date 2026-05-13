"""シート読み取りのユニットテスト。"""

from datetime import date

from app.sheets import parse_date, row_to_video, validate_header


TODAY = date(2026, 5, 10)


def test_parse_date_full_format():
    assert parse_date("2026/01/15", today=TODAY) == date(2026, 1, 15)
    assert parse_date("2025-10-19", today=TODAY) == date(2025, 10, 19)


def test_parse_date_month_day_recent_past():
    # 5/10 から見て 4/22 は直近過去 → 2026
    assert parse_date("4/22", today=TODAY) == date(2026, 4, 22)


def test_parse_date_month_day_prefers_nearer_year():
    # 5/10 から見て 10/19 は -7ヶ月 vs +5ヶ月 → 近い方の +5ヶ月（2026）を採用
    assert parse_date("10/19", today=TODAY) == date(2026, 10, 19)


def test_parse_date_month_day_future():
    # 5/10 から見て 7/7 は2ヶ月後 → 2026
    assert parse_date("7/7", today=TODAY) == date(2026, 7, 7)


def test_parse_date_month_day_recent_past_takes_previous_year():
    # 5/10 から見て 1/06 は -4ヶ月（同年）が最近接 → 2026
    assert parse_date("1/06", today=TODAY) == date(2026, 1, 6)
    # 12/20 は -5ヶ月（前年）が +7ヶ月（同年）より近い → 2025
    assert parse_date("12/20", today=TODAY) == date(2025, 12, 20)


def test_parse_date_blank_returns_none():
    assert parse_date("", today=TODAY) is None
    assert parse_date(None, today=TODAY) is None


def test_row_to_video_minimal():
    # A:済 B:DEP C:116 D:5/10 E:タイトル F:完了 G:GS H:増田
    row = ["済", "DEP", "116", "5/10", "テストタイトル", "完了", "GS", "増田"]
    v = row_to_video(row, today=TODAY)
    assert v is not None
    assert v.client == "DEP"
    assert v.no == "116"
    assert v.title == "テストタイトル"
    assert v.publish_date == date(2026, 5, 10)
    assert v.status == "完了"
    assert v.editor == "GS"
    assert v.bo == "増田"
    assert v.posted is True


def test_row_to_video_skips_empty():
    assert row_to_video(["", "", "", "", "", "", "", ""], today=TODAY) is None


def test_row_to_video_skips_placeholder_titles():
    base = ["", "1sec", "47", "7/7", "未撮影", "未着手", "", "増田"]
    assert row_to_video(base, today=TODAY) is None
    base[4] = "未入力"
    assert row_to_video(base, today=TODAY) is None
    base[4] = "（無題）"
    assert row_to_video(base, today=TODAY) is None


def test_row_to_video_keeps_legitimate_title():
    row = ["", "1sec", "1", "5/10", "アレルギー検査について", "編集中", "GS", "増田"]
    v = row_to_video(row, today=TODAY)
    assert v is not None
    assert v.title == "アレルギー検査について"


def test_validate_header_passes_for_expected_layout():
    header = ["投稿", "クライアント", "#", "投稿", "動画", "状況", "編集", "BO"]
    assert validate_header(header) == []


def test_validate_header_detects_missing_keyword():
    header = ["投稿", "得意先", "#", "投稿", "動画", "状況", "編集", "BO"]
    issues = validate_header(header)
    assert len(issues) == 1
    assert "クライアント" in issues[0]


def test_validate_header_handles_short_row():
    header = ["投稿", "クライアント", "#"]
    issues = validate_header(header)
    assert any("動画" in m for m in issues)
    assert any("状況" in m for m in issues)
