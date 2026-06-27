"""信号ラベル変換のテスト。

判定そのものはスプレッドシート側で行うため、ここでは
シートのセル値 → 内部キー（"red" など）への変換だけを検証する。
"""

from app.signal import BLUE, GRAY, RED, YELLOW, signal_from_label


def test_label_red_variants():
    assert signal_from_label("赤") == RED
    assert signal_from_label("🔴 要対応") == RED
    assert signal_from_label("要対応") == RED


def test_label_yellow_variants():
    assert signal_from_label("黄") == YELLOW
    assert signal_from_label("🟡 もうすぐ") == YELLOW
    assert signal_from_label("もうすぐ") == YELLOW


def test_label_blue_variants():
    assert signal_from_label("青") == BLUE
    assert signal_from_label("順調") == BLUE


def test_label_gray_variants():
    assert signal_from_label("灰") == GRAY
    assert signal_from_label("情報不足") == GRAY


def test_label_empty_or_unknown():
    assert signal_from_label("") == ""
    assert signal_from_label(None) == ""
    assert signal_from_label("クライアント") == ""
