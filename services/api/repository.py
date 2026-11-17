"""Gold reads only. Values are bound parameters; identifiers are server constants."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from common.config import settings
from dependencies import Page, TimeRange
from fastapi import HTTPException, Response
from psycopg import Connection, sql


def require_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise HTTPException(404, "No Gold data matches the requested filters")
    return rows


def time_conditions(
    column: str, window: TimeRange, *, daily: bool = False
) -> tuple[list[sql.Composable], list[Any]]:
    clauses, params = [], []
    for bound, operator in ((window.start, ">="), (window.end, "<")):
        if bound is not None:
            value = (
                bound.astimezone(ZoneInfo(settings.tz_local)).date() if daily else bound
            )
            clauses.append(
                sql.SQL("{} {} %s").format(sql.Identifier(column), sql.SQL(operator))
            )
            params.append(value)
    return clauses, params


def read_rows(
    connection: Connection,
    table: str,
    columns: str,
    order: str,
    clauses: list[sql.Composable] | None = None,
    params: list[Any] | None = None,
    page: Page | None = None,
    response: Response | None = None,
) -> list[dict[str, Any]]:
    condition = sql.SQL(" AND ").join(clauses or [sql.SQL("TRUE")])
    values = list(params or [])
    source = sql.SQL("FROM gold.{} WHERE {}").format(sql.Identifier(table), condition)
    if page is not None:
        total = connection.execute(
            sql.SQL("SELECT COUNT(*) AS total ") + source, values
        ).fetchone()["total"]
        if response is not None:
            response.headers["X-Total-Count"] = str(total)
            response.headers["X-Limit"] = str(page.limit)
            response.headers["X-Offset"] = str(page.offset)
    query = (
        sql.SQL("SELECT {} ").format(sql.SQL(columns))
        + source
        + sql.SQL(" ORDER BY {} ").format(sql.SQL(order))
    )
    if page is not None:
        query += sql.SQL("LIMIT %s OFFSET %s")
        values.extend([page.limit, page.offset])
    return connection.execute(query, values).fetchall()


def forecast(
    connection: Connection, table: str, columns: str, window: TimeRange
) -> dict[str, Any]:
    clauses, params = time_conditions("target_date", window, daily=True)
    if window.start is None and window.end is None:
        tomorrow = datetime.now(ZoneInfo(settings.tz_local)).date() + timedelta(days=1)
        clauses, params = [sql.SQL("target_date = %s")], [tomorrow]
    rows = read_rows(
        connection, table, columns, "target_date DESC", clauses, params, Page(1, 0)
    )
    return require_rows(rows)[0]
