"""シート読み取り（日付パース・ダッシュボード解析）のユニットテスト。"""

from datetime import date

from app.sheets import parse_dashboard, parse_date


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


def test_parse_date_blank_returns_none():
    assert parse_date("", today=TODAY) is None
    assert parse_date(None, today=TODAY) is None


# --- parse_dashboard ---------------------------------------------------------
def _grid():
    """「ダッシュボード」シートの典型レイアウト。

    実シートと同じく、要対応表（左: 列0-7）と情報不足表（右: 列9-12）が
    同じ行に左右並びで配置されている点を再現する。
    """
    return [
        ["🔴 要対応", "🟡 もうすぐ", "🔵 順調", "⚪ 情報不足", "合計", "", "", "", "", "", "", "", ""],
        ["5", "6", "80", "28", "94", "", "", "", "", "", "", "", ""],
        ["判定基準：🔴要対応＝公開まで2日以内 …", "", "", "", "", "", "", "", "", "", "", "", ""],
        ["いますぐ確認が必要な案件", "", "", "", "", "", "", "", "", "情報不足の案件", "", "", ""],
        ["信号", "クライアント", "タイトル", "公開予定", "残り(日)", "状況", "編集", "BO",
         "", "クラアント", "タイトル", "投稿予定", "不足項目"],
        ["赤", "empowerx", "転職エージェントの闇", "6/29", "2", "CL提出待ち（超過）", "安里", "岩渕",
         "", "1sec._m", "", "8/18", "タイトル 制作担当"],
        ["黄", "四国物産_m", "田中密着", "6/30", "3", "公開設定・納品待ち", "イカラシ", "岩渕",
         "", "DEP_m", "", "8/19", "タイトル 制作担当"],
        ["", "", "", "", "", "", "", "",
         "", "そうぞう_m", "7/7涙やけ_ショート", "", "投稿予定日"],
    ]


def test_parse_dashboard_counts():
    snap = parse_dashboard(_grid(), TODAY)
    assert snap.counts["red"] == 5
    assert snap.counts["yellow"] == 6
    assert snap.counts["blue"] == 80
    assert snap.counts["gray"] == 28
    assert snap.counts["total"] == 94


def test_parse_dashboard_urgent_list():
    snap = parse_dashboard(_grid(), TODAY)
    assert len(snap.urgent) == 2
    first = snap.urgent[0]
    assert first.signal == "red"
    assert first.video.client == "empowerx"
    assert first.video.title == "転職エージェントの闇"
    assert first.days_remaining == 2
    assert "CL提出待ち" in first.reason
    assert snap.urgent[1].signal == "yellow"


def test_parse_dashboard_gray_list_reads_right_table():
    # 情報不足表は右側（列9-12）。左の要対応表の列を誤って拾わないこと。
    snap = parse_dashboard(_grid(), TODAY)
    assert len(snap.gray_items) == 3
    g0 = snap.gray_items[0]
    assert g0.signal == "gray"
    assert g0.video.client == "1sec._m"          # 右表の値（empowerx ではない）
    assert g0.video.title == "(タイトル未入力)"   # 空タイトル
    assert g0.reason == "タイトル 制作担当"
    # 左表が尽きた後（行が左で空）も、右表の行を読み続ける
    g2 = snap.gray_items[2]
    assert g2.video.client == "そうぞう_m"
    assert g2.video.title == "7/7涙やけ_ショート"
    assert g2.reason == "投稿予定日"


def test_parse_dashboard_gray_not_polluted_by_urgent():
    # 要対応のクライアント（empowerx 等）が情報不足に混ざっていないこと
    snap = parse_dashboard(_grid(), TODAY)
    gray_clients = {g.video.client for g in snap.gray_items}
    assert "empowerx" not in gray_clients
    assert "四国物産_m" not in gray_clients


def test_parse_dashboard_criteria_text():
    snap = parse_dashboard(_grid(), TODAY)
    assert "判定基準" in snap.criteria_text


def test_parse_dashboard_total_falls_back_to_sum():
    grid = _grid()
    grid[0][4] = ""  # 合計セルを空に
    grid[1][4] = ""
    snap = parse_dashboard(grid, TODAY)
    assert snap.counts["total"] == 5 + 6 + 80 + 28


def test_parse_dashboard_empty_grid():
    snap = parse_dashboard([], TODAY)
    assert snap.counts["total"] == 0
    assert snap.urgent == []
    assert snap.gray_items == []
