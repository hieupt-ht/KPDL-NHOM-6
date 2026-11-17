"""Validated query parameters and short-lived read-only Mart connections."""

from collections.abc import Iterator
from datetime import datetime

import psycopg
from common.config import settings
from fastapi import HTTPException, Query
from psycopg.rows import dict_row


class TimeRange:
    def __init__(self, start: datetime | None = None, end: datetime | None = None):
        for value in (start, end):
            if value is not None and value.utcoffset() is None:
                raise HTTPException(
                    422, "start/end must include a timezone, e.g. 2026-11-01T00:00:00Z"
                )
        if start is not None and end is not None and start >= end:
            raise HTTPException(422, "start must be earlier than end")
        self.start = start
        self.end = end


class SnapshotRange(TimeRange):
    def __init__(self, start: datetime | None = None, end: datetime | None = None):
        super().__init__(start, end)
        if start is not None or end is not None:
            raise HTTPException(
                422,
                "This Gold snapshot does not support start/end; omit both parameters",
            )


class Page:
    def __init__(
        self, limit: int = Query(1000, ge=1, le=10000), offset: int = Query(0, ge=0)
    ):
        self.limit = limit
        self.offset = offset


def get_mart() -> Iterator[psycopg.Connection]:
    if not settings.mart_dsn:
        raise HTTPException(503, "Data Mart is not configured")
    with psycopg.connect(
        settings.mart_dsn,
        connect_timeout=settings.db_connect_timeout_seconds,
        options=f"-c statement_timeout={settings.db_statement_timeout_ms} -c timezone=UTC",
        row_factory=dict_row,
    ) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield connection
