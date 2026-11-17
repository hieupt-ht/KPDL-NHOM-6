import math
from datetime import timezone

from metrics import ENDPOINTS, MetricSpec
from silver import parse_series

MM = MetricSpec("m", "values", True, 0.0, 1.0)


def payload(ts, vals, key="values", success=True):
    return {"success": success, "result": {"serie_0": {"timestamps": ts, key: vals}}}


def spec(name):
    return next(m for e in ENDPOINTS for m in e.metrics if m.name == name)


def test_parse_http_traffic_fixture(fixture_json):
    pts = parse_series(fixture_json("http_traffic"), spec("http_traffic"))
    assert len(pts) == 48
    assert all(t.tzinfo is not None and t.utcoffset().total_seconds() == 0 for t in pts)
    assert all(0 <= v <= 1 for v in pts.values())
    assert all(t.tzinfo == timezone.utc for t in pts)


def test_parse_bot_class_splits_bot_and_human(fixture_json):
    doc = fixture_json("bot_class")
    bot = parse_series(doc, spec("bot_share"))
    human = parse_series(doc, spec("human_share"))
    assert bot and set(bot) == set(human)
    for t in bot:
        assert abs(bot[t] + human[t] - 100) < 0.5


def test_drops_null_nan_inf_negative_and_out_of_range():
    ts = [f"2026-11-01T0{i}:00:00Z" for i in range(8)]
    vals = [0.5, None, math.nan, math.inf, -0.1, 1.5, "abc", True]
    pts = parse_series(payload(ts, vals), MM)
    assert list(pts.values()) == [0.5]


def test_boundaries_are_inclusive():
    pts = parse_series(payload(["2026-11-01T00:00:00Z", "2026-11-01T01:00:00Z"], [0, 1]), MM)
    assert list(pts.values()) == [0.0, 1.0]


def test_duplicate_timestamps_keep_last():
    pts = parse_series(payload(["2026-11-01T00:00:00Z"] * 2, [0.2, 0.7]), MM)
    assert list(pts.values()) == [0.7]


def test_length_mismatch_uses_shorter_series_without_crash():
    pts = parse_series(payload(["2026-11-01T00:00:00Z", "2026-11-01T01:00:00Z", "2026-11-01T02:00:00Z"], [0.1, 0.2]), MM)
    assert len(pts) == 2


def test_bad_timestamp_is_dropped():
    pts = parse_series(payload(["not-a-date", "2026-11-01T01:00:00Z"], [0.1, 0.2]), MM)
    assert len(pts) == 1


def test_success_false_payload_returns_empty():
    assert parse_series(payload(["2026-11-01T00:00:00Z"], [0.1], success=False), MM) == {}


def test_missing_serie_returns_empty():
    assert parse_series({"success": True, "result": {}}, MM) == {}
    assert parse_series({"success": True}, MM) == {}
    assert parse_series({}, MM) == {}


def test_numeric_strings_are_accepted_and_junk_strings_dropped():
    pts = parse_series(payload(["2026-11-01T00:00:00Z", "2026-11-01T01:00:00Z", "2026-11-01T02:00:00Z"], ["0.25", "nan", ""]), MM)
    assert list(pts.values()) == [0.25]
