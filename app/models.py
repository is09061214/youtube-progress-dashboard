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
    status: str           # 状況 (F列) — 「完了」「サムネ待ち」など
    editor: str           # 編集者 (G列)
    bo: str               # BO担当 (H列)
    posted: bool          # A列が「済」か


@dataclass
class VideoSignal:
    """1本の動画について、信号判定を含めたビューモデル。"""

    video: Video
    signal: str           # "blue" | "yellow" | "red" | "gray"
    days_remaining: Optional[int]  # 公開予定日までの日数（負なら遅延）
    reason: str           # 判定理由（人間に読みやすい文字列）
