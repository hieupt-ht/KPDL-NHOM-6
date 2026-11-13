"""Kết nối đến hai cơ sở dữ liệu."""

import psycopg

from common.config import settings


def get_warehouse_conn() -> psycopg.Connection:
    """Mở kết nối Warehouse bằng tài khoản của dịch vụ hiện tại."""
    return psycopg.connect(settings.warehouse_dsn)


def get_mart_conn() -> psycopg.Connection:
    """Mở kết nối Mart bằng tài khoản của dịch vụ hiện tại."""
    return psycopg.connect(settings.mart_dsn)
