"""ドメインモデル。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class Video:
    """1本の動画案件。"""

    no: str               # 案件番号 (C列)
    client: str           # クライアント名 (B列)
    title: str            # タイトル (E列)
    publish_date: Optional[date]  # 公開予定日 (D列)
    status: str           # 状況 (G列) — 「完了」「サムネ待ち」など
    editor: str           # 編集者 (H列)
    bo: str               # BO担当 (I列)
    posted: bool          # A列が「済」か


@dataclass
class VideoSignal:
    """1本の動画について、信号判定を含めたビューモデル。"""

    video: Video
    signal: str           # "blue" | "yellow" | "red" | "gray"
    days_remaining: Optional[int]  # 公開予定日までの日数（負なら遅延）
    reason: str           # 判定理由 / 状況 / 不足項目（人間に読みやすい文字列）


@dataclass
class DashboardSnapshot:
    """スプレッドシート「ダッシュボード」シートを読み取った結果のスナップショット。

    判定（赤/黄/青/灰）はスプレッドシート側で済んでいるので、ここでは
    その結果（件数・要対応リスト・情報不足リスト）をそのまま保持するだけ。
    """

    counts: dict          # {"red","yellow","blue","gray","total"}
    urgent: list[VideoSignal]      # 赤・黄（シートの並び順 = 優先度順）
    gray_items: list[VideoSignal]  # 灰（情報不足）
    criteria_text: str = ""        # シートに書かれた「判定基準：…」の文言

    @staticmethod
    def empty() -> "DashboardSnapshot":
        return DashboardSnapshot(
            counts={"red": 0, "yellow": 0, "blue": 0, "gray": 0, "total": 0},
            urgent=[],
            gray_items=[],
            criteria_text="",
        )
