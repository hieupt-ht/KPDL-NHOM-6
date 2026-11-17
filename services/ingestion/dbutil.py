"""Tiện ích kết nối DB dùng chung."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from common.db import get_warehouse_conn


@contextmanager
def use_conn(conn: psycopg.Connection | None) -> Iterator[psycopg.Connection]:
    """Dùng kết nối được truyền vào (người gọi tự commit/rollback), hoặc mở mới và commit khi xong."""
    if conn is not None:
        yield conn
        return
    with get_warehouse_conn() as own:  # thoát khối: commit, hoặc rollback nếu có lỗi, rồi đóng
        yield own
