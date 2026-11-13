"""Cấu hình logging chung."""

import logging


def configure_logging(service: str) -> None:
    """Đặt định dạng log đơn giản để nhận diện dịch vụ."""
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{service}] %(levelname)s %(message)s")
