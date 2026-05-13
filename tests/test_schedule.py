"""日付ユーティリティ infer_year のテスト。"""

from datetime import date

from app.schedule import infer_year


def test_infer_year_recent_past_same_year():
    today = date(2026, 5, 10)
    assert infer_year(4, 22, today) == 2026


def test_infer_year_near_future_same_year():
    today = date(2026, 5, 10)
    assert infer_year(7, 7, today) == 2026


def test_infer_year_late_year_takes_previous_year():
    today = date(2026, 5, 10)
    assert infer_year(12, 20, today) == 2025


def test_infer_year_early_year_after_year_change():
    today = date(2026, 1, 5)
    assert infer_year(1, 6, today) == 2026


def test_infer_year_invalid_date_falls_back_to_today_year():
    today = date(2026, 5, 10)
    assert infer_year(2, 30, today) == today.year
