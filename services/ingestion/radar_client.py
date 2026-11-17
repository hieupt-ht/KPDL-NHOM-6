"""Gọi Cloudflare Radar API, có retry với backoff."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from config import get_token

log = logging.getLogger(__name__)

BASE_URL = "https://api.cloudflare.com/client/v4/radar"
MAX_ATTEMPTS = 6
BACKOFF_START = 1.0
BACKOFF_CAP = 60.0
RETRY_STATUSES = {429} | set(range(500, 600))


class RadarUnavailable(RuntimeError):
    """Lỗi mạng/timeout kéo dài, hết số lần thử."""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Window:
    date_start: datetime | None = None
    date_end: datetime | None = None
    date_range: str | None = None

    @classmethod
    def recent(cls, days: int = 2) -> "Window":
        return cls(date_range=f"{days}d")

    @classmethod
    def between(cls, start: datetime, end: datetime) -> "Window":
        return cls(date_start=start, date_end=end)

    def as_params(self) -> dict[str, str]:
        if self.date_range:
            return {"dateRange": self.date_range}
        return {"dateStart": _iso(self.date_start), "dateEnd": _iso(self.date_end)}


@dataclass
class RadarResponse:
    status_code: int
    params: dict[str, Any]
    payload: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and self.payload.get("success") is True


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers["Retry-After"])
    except (KeyError, ValueError):
        return None


def _payload(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {"raw_text": resp.text[:2000]}
    return data if isinstance(data, dict) else {"raw": data}


def fetch(
    path: str,
    window: Window,
    *,
    client: httpx.Client | None = None,
    token: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RadarResponse:
    """Gọi một endpoint Radar. Trả RadarResponse cho mọi phản hồi HTTP cuối cùng (kể cả lỗi).

    Ném RadarUnavailable chỉ khi lỗi mạng/timeout hết số lần thử; ConfigError nếu thiếu token.
    """
    token = token or get_token()
    params = {"location": "VN", "aggInterval": "1h", "format": "json", **window.as_params()}
    headers = {"Authorization": f"Bearer {token}"}
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=10))
    try:
        delay = BACKOFF_START
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last = attempt == MAX_ATTEMPTS
            wait = delay
            try:
                resp = client.get(BASE_URL + path, params=params, headers=headers)
            except httpx.TransportError as exc:
                if last:
                    raise RadarUnavailable(f"Radar không phản hồi sau {attempt} lần: {type(exc).__name__}") from None
                log.warning("Radar lỗi mạng (%s), thử lại sau lần %d", type(exc).__name__, attempt)
            else:
                if resp.status_code not in RETRY_STATUSES or last:
                    return RadarResponse(resp.status_code, params, _payload(resp))
                log.warning("Radar HTTP %d, thử lại sau lần %d", resp.status_code, attempt)
                hinted = _retry_after(resp)
                if hinted is not None:
                    wait = min(max(hinted, 0.0), BACKOFF_CAP)
            sleep(wait)
            delay = min(delay * 2, BACKOFF_CAP)
    finally:
        if own:
            client.close()
    raise RadarUnavailable("không đạt được Radar")  # không bao giờ tới đây
