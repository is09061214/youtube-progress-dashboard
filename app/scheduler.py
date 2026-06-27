"""ダッシュボードデータのキャッシュと、APScheduler による定期更新。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from .config import REFRESH_INTERVAL_MINUTES, TIMEZONE_NAME, now_local
from .models import DashboardSnapshot
from .sheets import fetch_dashboard

logger = logging.getLogger(__name__)


class VideoStore:
    """取得したダッシュボードのスナップショットをメモリにキャッシュする小さなストア。

    最後の取得結果（成功なら時刻、失敗なら例外メッセージ）も保持し、
    /healthz から鮮度を確認できるようにする。
    """

    def __init__(self) -> None:
        self._snapshot: DashboardSnapshot = DashboardSnapshot.empty()
        self._last_updated: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._last_attempted: Optional[datetime] = None
        self._lock = threading.Lock()

    def refresh(self) -> None:
        attempted_at = now_local()
        try:
            snapshot = fetch_dashboard()
        except Exception as e:
            logger.exception("ダッシュボードの取得に失敗しました")
            with self._lock:
                self._last_attempted = attempted_at
                self._last_error = f"{type(e).__name__}: {e}"
            return
        with self._lock:
            self._snapshot = snapshot
            self._last_updated = attempted_at
            self._last_attempted = attempted_at
            self._last_error = None
        logger.info(
            "ダッシュボードを更新しました（要対応・もうすぐ %d 件 / 情報不足 %d 件）",
            len(snapshot.urgent),
            len(snapshot.gray_items),
        )

    @property
    def snapshot(self) -> DashboardSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def last_updated(self) -> Optional[datetime]:
        return self._last_updated

    @property
    def last_attempted(self) -> Optional[datetime]:
        return self._last_attempted

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error


def start_scheduler(store: VideoStore) -> Optional[BackgroundScheduler]:
    """定期実行のスケジューラを起動する（無効なら何もしない）。"""
    if REFRESH_INTERVAL_MINUTES <= 0:
        logger.info("REFRESH_INTERVAL_MINUTES=0 のため自動更新は無効です")
        return None

    scheduler = BackgroundScheduler(timezone=TIMEZONE_NAME)
    scheduler.add_job(
        store.refresh,
        "interval",
        minutes=REFRESH_INTERVAL_MINUTES,
        id="refresh_dashboard",
        replace_existing=True,
        misfire_grace_time=60,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("スケジューラ開始: %d 分ごとに更新（tz=%s）", REFRESH_INTERVAL_MINUTES, TIMEZONE_NAME)
    return scheduler
