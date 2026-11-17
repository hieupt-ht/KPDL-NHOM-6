"""Điểm vào dịch vụ thu thập dữ liệu."""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from backfill import run_backfill
from bronze import purge_old
from common.config import settings
from common.runner import create_service_app
from config import CHUNK_DAYS, OVERLAP_DAYS, ConfigError
from metrics import ENDPOINTS
from pipeline import EndpointResult, ingest_endpoint
from radar_client import Window
from runs import finish_run, start_run
from silver import latest_ts

log = logging.getLogger(__name__)

BACKFILL_RETRY_SECONDS = 900

# Chu kỳ 5 phút và backfill không chạy đồng thời.
ingest_lock = threading.Lock()


def polling_window(now: datetime | None = None, conn=None) -> Window:
    """2 ngày gần nhất; nếu Silver đã cũ hơn ~36 giờ (dịch vụ từng ngừng) thì mở rộng để chồng lên điểm cuối."""
    now = now or datetime.now(timezone.utc)
    try:
        lasts = [latest_ts(m.name, conn=conn) for e in ENDPOINTS for m in e.metrics if m.scaled]
    except Exception:  # noqa: BLE001 - không đọc được Silver thì dùng cửa sổ mặc định
        log.exception("không đọc được mốc Silver cuối")
        return Window.recent()
    lasts = [t for t in lasts if t is not None]
    if not lasts:
        return Window.recent()
    oldest_last = min(lasts)
    if now - oldest_last <= timedelta(hours=36):
        return Window.recent()
    start = max(oldest_last - timedelta(days=OVERLAP_DAYS), now - timedelta(days=CHUNK_DAYS))
    log.info("Silver cũ tới %s, mở rộng cửa sổ thu thập từ %s", oldest_last, start)
    return Window.between(start, now)


def _run_endpoints() -> tuple[str, int, str | None]:
    results: list[EndpointResult] = []
    window = polling_window()
    for spec in ENDPOINTS:
        try:
            results.append(ingest_endpoint(spec, window))
        except ConfigError:
            raise
        except Exception as exc:  # noqa: BLE001 - một endpoint hỏng không dừng chu kỳ
            log.exception("endpoint %s lỗi bất ngờ", spec.name)
            results.append(EndpointResult(spec.name, "error", 0, f"{type(exc).__name__}"))
    rows = sum(r.rows for r in results)
    good = [r for r in results if r.status == "ok"]
    bad = [r for r in results if r.status != "ok"]
    status = "success" if not bad else ("partial" if good else "failed")
    error = "; ".join(f"{r.endpoint}: {r.status} {r.message}".strip() for r in bad)[:1000] or None
    return status, rows, error


def run_cycle() -> str:
    """Gọi các endpoint Radar, ghi Bronze và Silver. Không bao giờ ném lỗi ra scheduler."""
    if not ingest_lock.acquire(blocking=False):
        log.info("đang backfill, bỏ qua chu kỳ này")
        return "skipped"
    try:
        run_id = start_run()
        try:
            status, rows, error = _run_endpoints()
        except ConfigError as exc:
            log.error("lỗi cấu hình: %s", exc)
            finish_run(run_id, "failed", 0, str(exc))
            return "failed"
        try:
            purge_old()
        except Exception:  # noqa: BLE001 - dọn dẹp lỗi không làm hỏng chu kỳ
            log.exception("purge Bronze lỗi")
        finish_run(run_id, status, rows, error)
        log.info("chu kỳ xong: %s, %d dòng", status, rows)
        return status
    except Exception:  # noqa: BLE001
        log.exception("chu kỳ thu thập lỗi")
        return "failed"
    finally:
        ingest_lock.release()


def backfill_done(results: dict[str, list[EndpointResult]]) -> bool:
    """Xong khi mọi endpoint kết thúc ở trạng thái ok/empty hoặc không còn gì để lấy."""
    return all(not rs or rs[-1].status in ("ok", "empty") for rs in results.values())


def run_backfill_background(sleep: Callable[[float], None] = time.sleep) -> None:
    """Nạp lịch sử; nếu còn lỗi thì thử lại sau mỗi 15 phút cho tới khi xong."""
    while True:
        with ingest_lock:
            try:
                results = run_backfill()
            except Exception:  # noqa: BLE001
                log.exception("backfill lỗi")
                results = {"_": [EndpointResult("_", "error", 0)]}
        if backfill_done(results):
            log.info("backfill hoàn tất")
            return
        sleep(BACKFILL_RETRY_SECONDS)


app = create_service_app("ingestion", run_cycle, {"trigger": "interval", "seconds": settings.ingestion_interval_seconds})

if settings.scheduler_enabled:
    threading.Thread(target=run_backfill_background, name="backfill", daemon=True).start()
