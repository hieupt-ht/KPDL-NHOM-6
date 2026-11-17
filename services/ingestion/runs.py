"""Nhật ký các lần chạy (silver.ingestion_runs)."""

import psycopg

from dbutil import use_conn


def start_run(*, conn: psycopg.Connection | None = None) -> int:
    with use_conn(conn) as c:
        row = c.execute(
            "INSERT INTO silver.ingestion_runs (started_at, status) VALUES (now(), 'running') RETURNING id"
        ).fetchone()
    return row[0]


def finish_run(
    run_id: int, status: str, rows_upserted: int, error: str | None, *, conn: psycopg.Connection | None = None
) -> None:
    with use_conn(conn) as c:
        c.execute(
            "UPDATE silver.ingestion_runs SET finished_at = now(), status = %s, rows_upserted = %s, error = %s WHERE id = %s",
            (status, rows_upserted, error, run_id),
        )
