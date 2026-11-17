"""Integration tests require an explicitly named, disposable test database."""

import os
from pathlib import Path

import psycopg
import pytest
from common.config import settings
from fastapi.testclient import TestClient
from main import app
from psycopg.conninfo import conninfo_to_dict


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    try:
        with TestClient(app) as instance:
            yield instance
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def mart(monkeypatch):
    admin_dsn = os.environ.get("TEST_MART_ADMIN_DSN")
    api_dsn = os.environ.get("TEST_MART_API_DSN")
    if not admin_dsn or not api_dsn:
        pytest.skip(
            "Set TEST_MART_ADMIN_DSN and TEST_MART_API_DSN for integration tests"
        )
    database = conninfo_to_dict(admin_dsn).get("dbname", "")
    if (
        not database.startswith("test_")
        or conninfo_to_dict(api_dsn).get("dbname") != database
    ):
        pytest.fail(
            "Integration tests only operate on the same explicitly named test_* database"
        )
    monkeypatch.setattr(settings, "mart_dsn", api_dsn)
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='gold'"
        ).fetchall()
        assert len(tables) == 10, "Initialize the database with db/mart/init first"
        from psycopg import sql

        connection.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
                sql.SQL(", ").join(sql.Identifier("gold", row[0]) for row in tables)
            )
        )
        connection.execute(
            Path(__file__).with_name("seed.sql").read_text(encoding="utf-8")
        )
        yield connection
