"""Ghi dữ liệu thô vào Warehouse."""

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from dbutil import use_conn


def save_raw_response(
    endpoint: str, params: dict[str, Any], status_code: int, payload: dict[str, Any],
    *, conn: psycopg.Connection | None = None,
) -> None:
    """Lưu nguyên văn JSON và metadata của phản hồi API vào Bronze."""
    with use_conn(conn) as c:
        c.execute(
            "INSERT INTO bronze.raw_api_responses (endpoint, params, status_code, payload) VALUES (%s, %s, %s, %s)",
            (endpoint, Jsonb(params), status_code, Jsonb(payload)),
        )


def purge_old(days: int = 30, *, conn: psycopg.Connection | None = None) -> int:
    """Xóa phản hồi thô cũ hơn `days` ngày. Trả số dòng đã xóa."""
    with use_conn(conn) as c:
        cur = c.execute("DELETE FROM bronze.raw_api_responses WHERE fetched_at < now() - make_interval(days => %s)", (days,))
        return cur.rowcount
