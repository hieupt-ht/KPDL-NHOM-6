import json
from datetime import datetime, timezone

import httpx
import pytest

import metrics
from config import ConfigError, get_token
from radar_client import RadarUnavailable, Window, fetch

TOKEN = "cfut_SECRET_TOKEN_VALUE"
OK = {"success": True, "errors": [], "result": {}}


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def run(handler, window=None):
    sleeps = []
    resp = fetch("/http/timeseries", window or Window.recent(), client=make_client(handler),
                 token=TOKEN, sleep=sleeps.append)
    return resp, sleeps


def test_fetch_sends_bearer_and_expected_params():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["Authorization"]
        seen["q"] = dict(req.url.params)
        seen["path"] = req.url.path
        return httpx.Response(200, json=OK)

    resp, _ = run(handler)
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert seen["q"] == {"location": "VN", "aggInterval": "1h", "format": "json", "dateRange": "2d"}
    assert seen["path"] == "/client/v4/radar/http/timeseries"
    assert resp.ok


def test_window_between_uses_iso_utc_datestart_dateend():
    w = Window.between(datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 29, 5, tzinfo=timezone.utc))
    assert w.as_params() == {"dateStart": "2026-10-01T00:00:00Z", "dateEnd": "2026-10-29T05:00:00Z"}


def test_retries_429_then_succeeds_with_backoff():
    calls = iter([429, 429, 200])
    resp, sleeps = run(lambda r: httpx.Response(next(calls), json=OK))
    assert resp.ok and sleeps == [1, 2]


def test_honours_retry_after_header():
    calls = iter([429, 200])

    def handler(r):
        code = next(calls)
        return httpx.Response(code, json=OK, headers={"Retry-After": "7"} if code == 429 else {})

    resp, sleeps = run(handler)
    assert resp.ok and sleeps == [7]


def test_backoff_caps_at_60s_and_gives_up_after_6_attempts_returns_last_response():
    n = {"c": 0}

    def handler(r):
        n["c"] += 1
        return httpx.Response(503, json={"success": False})

    resp, sleeps = run(handler)
    assert n["c"] == 6
    assert resp.status_code == 503 and not resp.ok
    assert sleeps == [1, 2, 4, 8, 16] and max(sleeps) <= 60


@pytest.mark.parametrize("code", [400, 401, 403])
def test_400_401_403_not_retried(code):
    n = {"c": 0}

    def handler(r):
        n["c"] += 1
        return httpx.Response(code, json={"success": False, "errors": [{"code": 1}]})

    resp, sleeps = run(handler)
    assert n["c"] == 1 and sleeps == [] and not resp.ok and resp.status_code == code


def test_timeout_exhausted_raises_radar_unavailable():
    def handler(r):
        raise httpx.ConnectTimeout("boom", request=r)

    with pytest.raises(RadarUnavailable) as e:
        run(handler)
    assert TOKEN not in str(e.value)


def test_params_never_contain_token():
    resp, _ = run(lambda r: httpx.Response(200, json=OK))
    assert TOKEN not in json.dumps(resp.params)


def test_non_json_body_returns_not_ok_response():
    resp, _ = run(lambda r: httpx.Response(400, text="<html>bad</html>"))
    assert not resp.ok and resp.status_code == 400


def test_get_token_rejects_missing_and_placeholder(monkeypatch):
    monkeypatch.delenv("CF_API_TOKEN", raising=False)
    with pytest.raises(ConfigError):
        get_token()
    for value in ("", "replace-with-cloudflare-token"):
        monkeypatch.setenv("CF_API_TOKEN", value)
        with pytest.raises(ConfigError):
            get_token()
    monkeypatch.setenv("CF_API_TOKEN", TOKEN)
    assert get_token() == TOKEN


def test_config_error_message_has_no_token(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "replace-with-cloudflare-token")
    with pytest.raises(ConfigError) as e:
        get_token()
    assert "cloudflare-token" not in str(e.value)


def test_endpoints_cover_five_metrics():
    assert set(metrics.ALL_METRICS) == {"http_traffic", "l7_attack", "netflows", "bot_share", "human_share"}
    bot = next(e for e in metrics.ENDPOINTS if e.name == "bot_class")
    assert len(bot.metrics) == 2 and all(not m.scaled for m in bot.metrics)
    assert all(m.scaled for e in metrics.ENDPOINTS if e.name != "bot_class" for m in e.metrics)
