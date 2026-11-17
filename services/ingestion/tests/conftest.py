"""Fixture dùng chung cho test của dịch vụ ingestion."""

import json
import os
from pathlib import Path

import psycopg
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: cần Postgres (đặt TEST_WAREHOUSE_DSN)")


@pytest.fixture
def fixture_json():
    def load(name: str) -> dict:
        return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))

    return load


@pytest.fixture
def db_conn():
    dsn = os.environ.get("TEST_WAREHOUSE_DSN")
    if not dsn:
        pytest.skip("thiếu TEST_WAREHOUSE_DSN")
    conn = psycopg.connect(dsn)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
