"""Nạp lại lịch sử: lùi dần từ mới đến cũ theo lô, chạy tiếp được sau khi bị ngắt."""

import logging
import math
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx
import psycopg

from config import BACKFILL_TARGET_DAYS, CHUNK_DAYS, OVERLAP_DAYS
from metrics import ENDPOINTS, EndpointSpec
from pipeline import EndpointResult, ingest_endpoint
from radar_client import Window
from silver import earliest_ts

log = logging.getLogger(__name__)


def next_window(
    earliest: datetime | None,
    now: datetime,
    target_start: datetime,
    chunk_days: int = CHUNK_DAYS,
    overlap_days: int = OVERLAP_DAYS,
) -> tuple[datetime, datetime] | None:
    """Cửa sổ kế tiếp cần lấy; None khi đã đủ độ sâu."""
    chunk = timedelta(days=chunk_days)
    if earliest is None:
        return (now - chunk, now)
    if earliest <= target_start:
        return None
    end = earliest + timedelta(days=overlap_days)
    return (max(end - chunk, target_start), end)


def _earliest(spec: EndpointSpec, conn: psycopg.Connection | None) -> datetime | None:
    values = [earliest_ts(m.name, conn=conn) for m in spec.metrics]
    return None if any(v is None for v in values) else min(values)


def backfill_endpoint(
    spec: EndpointSpec,
    *,
    now: datetime | None = None,
    client: httpx.Client | None = None,
    conn: psycopg.Connection | None = None,
    token: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    pause_seconds: float = 0.5,
) -> list[EndpointResult]:
    """Lùi dần tới độ sâu mục tiêu. Dừng khi: đủ sâu, API hết dữ liệu cũ, không tiến triển, hoặc lỗi."""
    now = now or datetime.now(timezone.utc)
    target_start = now - timedelta(days=BACKFILL_TARGET_DAYS)
    max_iter = math.ceil(BACKFILL_TARGET_DAYS / (CHUNK_DAYS - OVERLAP_DAYS)) + 2
    results: list[EndpointResult] = []
    earliest = _earliest(spec, conn)
    for _ in range(max_iter):
        window = next_window(earliest, now, target_start)
        if window is None:
            break
        res = ingest_endpoint(spec, Window.between(*window), client=client, conn=conn, token=token, sleep=sleep)
        results.append(res)
        log.info("backfill %s %s..%s -> %s (%d dòng) %s", spec.name, window[0].date(), window[1].date(),
                 res.status, res.rows, res.message)
        if res.status != "ok":
            break  # empty: API hết dữ liệu cũ; error/skipped: để lượt sau thử lại
        new_earliest = _earliest(spec, conn)
        if earliest is not None and (new_earliest is None or new_earliest >= earliest):
            break  # không lùi thêm được
        earliest = new_earliest
        sleep(pause_seconds)
    return results


def run_backfill(**kwargs) -> dict[str, list[EndpointResult]]:
    """Backfill lần lượt từng endpoint; lỗi ở một endpoint không chặn endpoint khác."""
    out: dict[str, list[EndpointResult]] = {}
    for spec in ENDPOINTS:
        try:
            out[spec.name] = backfill_endpoint(spec, **kwargs)
        except Exception:  # noqa: BLE001 - một endpoint hỏng không dừng cả backfill
            log.exception("backfill %s lỗi bất ngờ", spec.name)
            out[spec.name] = [EndpointResult(spec.name, "error", 0, "lỗi bất ngờ, xem log")]
    return out
