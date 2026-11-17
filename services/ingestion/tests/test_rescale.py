from datetime import datetime, timedelta, timezone

import pytest

from rescale import apply_scale, compute_scale

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def series(values):
    return {T0 + timedelta(hours=i): v for i, v in enumerate(values)}


def test_compute_scale_recovers_known_factor():
    silver = series([0.1 * (i + 1) for i in range(20)])
    window = {t: v / 2 for t, v in silver.items()}
    assert compute_scale(silver, window) == pytest.approx(2.0)


def test_compute_scale_uses_median_against_outlier():
    silver = series([0.5] * 20)
    window = {t: 0.25 for t in silver}
    window[T0] = 0.001
    assert compute_scale(silver, window) == pytest.approx(2.0)


def test_compute_scale_none_when_overlap_too_small():
    silver = series([0.5] * 11)
    assert compute_scale(silver, dict(silver)) is None


def test_compute_scale_ignores_zero_and_missing():
    silver = series([0.5] * 20)
    window = {t: 0.25 for t in silver}
    for t in list(silver)[:8]:
        window[t] = 0.0  # 12 mốc hợp lệ còn lại
    assert compute_scale(silver, window) == pytest.approx(2.0)
    window2 = {t: 0.0 for t in silver}
    assert compute_scale(silver, window2) is None
    assert compute_scale({}, window) is None


def test_apply_scale_multiplies():
    assert apply_scale({T0: 0.5}, 2.0) == {T0: 1.0}


def _points(doc):
    s = doc["result"]["serie_0"]
    return {datetime.fromisoformat(t): float(v) for t, v in zip(s["timestamps"], s["values"])}


def test_real_windows_agree_after_rescale(fixture_json):
    a, b = _points(fixture_json("winA")), _points(fixture_json("winB"))
    k = compute_scale(a, b)
    assert k is not None
    common = set(a) & set(b)
    assert len(common) >= 12
    for t in common:
        assert abs(k * b[t] - a[t]) < 1e-4
    t = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    assert k * 0.840159 == pytest.approx(0.902153, abs=1e-4)
    assert abs(k * b[t] - 0.902153) < 1e-4
