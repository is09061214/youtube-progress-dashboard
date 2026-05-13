"""FastAPI エントリポイント。"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import (
    APP_TITLE,
    COMPLETED_STATUSES,
    EXCLUDE_COMPLETED,
    REFRESH_INTERVAL_MINUTES,
    SIGNAL_BLUE_MIN_DAYS,
    SIGNAL_YELLOW_MIN_DAYS,
    TIMEZONE_NAME,
    today_local,
)
from .scheduler import VideoStore, start_scheduler
from .signal import is_completed, sort_key, summarize

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title=APP_TITLE)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

store = VideoStore()


@app.on_event("startup")
def _startup() -> None:
    store.refresh()
    start_scheduler(store)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    today: date = today_local()
    signals = store.evaluate(today)
    excluded_completed = 0
    if EXCLUDE_COMPLETED:
        original_count = len(signals)
        signals = [s for s in signals if not is_completed(s.video)]
        excluded_completed = original_count - len(signals)
    counts = summarize(signals)

    urgent = sorted(
        [s for s in signals if s.signal in ("red", "yellow")],
        key=sort_key,
    )

    gray_items = sorted(
        [s for s in signals if s.signal == "gray"],
        key=lambda s: (s.video.client, s.video.title),
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "app_title": APP_TITLE,
            "today": today,
            "counts": counts,
            "urgent": urgent,
            "gray_items": gray_items,
            "last_updated": store.last_updated,
            "last_error": store.last_error,
            "last_attempted": store.last_attempted,
            "refresh_interval_minutes": REFRESH_INTERVAL_MINUTES,
            "next_refresh": _next_refresh(store.last_updated),
            "blue_min_days": SIGNAL_BLUE_MIN_DAYS,
            "yellow_min_days": SIGNAL_YELLOW_MIN_DAYS,
            "completed_statuses": sorted(COMPLETED_STATUSES),
            "exclude_completed": EXCLUDE_COMPLETED,
            "excluded_completed_count": excluded_completed,
            "timezone_name": TIMEZONE_NAME,
        },
    )


@app.post("/refresh")
def refresh() -> RedirectResponse:
    store.refresh()
    return RedirectResponse(url="/", status_code=303)


@app.get("/healthz")
def healthz() -> JSONResponse:
    """死活＋データ鮮度チェック。

    - last_updated が無い、または最終取得がエラー、または
      最終更新から「更新間隔の3倍」以上経過 → 503 を返す。
    """
    now = datetime.now(store.last_updated.tzinfo) if store.last_updated else None
    age_seconds: Optional[float] = None
    if store.last_updated and now:
        age_seconds = (now - store.last_updated).total_seconds()

    is_stale = False
    if REFRESH_INTERVAL_MINUTES > 0 and age_seconds is not None:
        is_stale = age_seconds > REFRESH_INTERVAL_MINUTES * 60 * 3

    payload = {
        "ok": store.last_updated is not None and store.last_error is None and not is_stale,
        "last_updated": store.last_updated.isoformat() if store.last_updated else None,
        "last_attempted": store.last_attempted.isoformat() if store.last_attempted else None,
        "last_error": store.last_error,
        "data_age_seconds": age_seconds,
        "refresh_interval_minutes": REFRESH_INTERVAL_MINUTES,
        "is_stale": is_stale,
    }
    status_code = 200 if payload["ok"] else 503
    return JSONResponse(payload, status_code=status_code)


def _next_refresh(last_updated: Optional[datetime]) -> Optional[datetime]:
    if not last_updated or REFRESH_INTERVAL_MINUTES <= 0:
        return None
    return last_updated + timedelta(minutes=REFRESH_INTERVAL_MINUTES)
