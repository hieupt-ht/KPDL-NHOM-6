import importlib.util
import sys
from pathlib import Path

import joblib
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "services" / "prediction"), str(ROOT / "training")]
import train_models as tm  # noqa: E402

# Nạp theo đường dẫn để không đụng `tasks` của service clustering khi chạy chung một phiên pytest.
_spec = importlib.util.spec_from_file_location("prediction_tasks", ROOT / "services" / "prediction" / "tasks.py")
pt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pt)

TZ = "Asia/Ho_Chi_Minh"
ALL_FEATURES = list(dict.fromkeys([*tm.FEATURES, *tm.CLASSIFIER_FEATURES]))


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class FakeWarehouse:
    """Trả về (ts, value) giả theo metric trong truy vấn Silver."""

    def __init__(self, data: dict[str, pd.DataFrame]):
        self.data = {m: list(df.itertuples(index=False, name=None)) for m, df in data.items()}
        self.metrics_asked = []

    def execute(self, sql, params=None):
        assert "silver.metrics_hourly" in sql
        self.metrics_asked.append(params[0])
        return _Result(self.data.get(params[0], []))


class FakeMart:
    def __init__(self):
        self.cont, self.disc, self.runs, self.commits, self.rollbacks = [], [], [], 0, 0

    def execute(self, sql, params=None):
        if "gold.forecast_continuous" in sql:
            assert "ON CONFLICT (target_date)" in sql
            self.cont.append(params)
        elif "gold.forecast_discrete" in sql:
            assert "ON CONFLICT (target_date)" in sql
            self.disc.append(params)
        else:
            assert "gold.service_runs" in sql
            self.runs.append((sql.split()[0], params))
        return _Result([(1,)])

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _hourly(days: int, last_full_day: str = "2026-03-31", base: float = 100.0, partial_hours: int = 6) -> pd.DataFrame:
    """Chuỗi giờ kết thúc ở hết ngày VN `last_full_day`, kèm `partial_hours` giờ của ngày kế tiếp (chưa đủ)."""
    end = pd.Timestamp(last_full_day, tz=TZ) + pd.Timedelta(days=1)
    ts = pd.date_range(end=end, periods=days * 24, freq="h", inclusive="left")
    ts = ts.append(pd.date_range(end, periods=partial_hours, freq="h"))
    return pd.DataFrame({"ts": ts.tz_convert("UTC"), "value": [base + 5 * t.day_of_week + t.hour for t in ts]})


def _data(days: int = 60, **kw) -> dict[str, pd.DataFrame]:
    return {"http_traffic": _hourly(days, **kw), "l7_attack": _hourly(days, base=10.0, **kw)}


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    out = tmp_path_factory.mktemp("models")
    tm.train_models(demo=True, out_dir=out)
    return out


def _row(data=None, features=ALL_FEATURES):
    data = data or _data(30)
    return pt.build_target_row(data["http_traffic"], data["l7_attack"], features)


def test_target_is_last_full_vietnam_day_plus_horizon():
    d = _data(30)
    target, row = _row(d)
    assert str(target) == "2026-04-02"  # 03-31 là ngày đủ cuối; 04-01 mới có 6 giờ
    assert list(row.columns) == ALL_FEATURES and len(row) == 1 and not row.isna().any(axis=None)
    h = d["http_traffic"]
    local = pd.to_datetime(h["ts"]).dt.tz_convert(TZ).dt.strftime("%Y-%m-%d")
    def day(x):
        return h[local == x]["value"].mean()
    assert row["lag_2"].iloc[0] == pytest.approx(day("2026-03-31"))
    assert row["lag_7"].iloc[0] == pytest.approx(day("2026-03-26"))
    assert row["roll_mean_3"].iloc[0] == pytest.approx((day("2026-03-29") + day("2026-03-30") + day("2026-03-31")) / 3)
    assert row["dow"].iloc[0] == pd.Timestamp("2026-04-02").day_of_week
    assert row["risk_lag_2"].iloc[0] == pytest.approx(day("2026-03-31") - 90)  # base rủi ro = 10


def test_partial_last_day_is_ignored():
    d = _data(30)
    h = d["http_traffic"]
    h.loc[pd.to_datetime(h["ts"]).dt.tz_convert(TZ) >= pd.Timestamp("2026-04-01", tz=TZ), "value"] = 1e9
    _, row = _row(d)
    assert row.max(axis=None) < 1e6


def test_target_moves_back_when_silver_is_stale():
    target, _ = _row(_data(30, last_full_day="2026-03-29"))
    assert str(target) == "2026-03-31"  # Radar trễ: dự báo cho hôm nay thay vì ngày mai


def test_none_when_insufficient_or_gaps():
    empty = pd.DataFrame(columns=["ts", "value"])
    assert pt.build_target_row(empty, empty, ALL_FEATURES) is None
    assert _row(_data(5)) is None  # thiếu lag_7
    d = _data(30)
    h = d["http_traffic"]
    d["http_traffic"] = h[pd.to_datetime(h["ts"]).dt.tz_convert(TZ).dt.strftime("%Y-%m-%d") != "2026-03-30"]
    assert _row(d) is None  # roll_mean_3 thiếu ngày
    assert pt.build_target_row(_hourly(30), empty, ALL_FEATURES) is None  # thiếu dữ liệu l7_attack


def test_predict_writes_both_tables(models):
    reg, clf = pt.load_bundle(pt.REGRESSOR_FILE, models), pt.load_bundle(pt.CLASSIFIER_FILE, models)
    target, row = _row(_data(60))
    mart = FakeMart()
    value = pt.predict_continuous(row, target, reg, mart)
    label, p = pt.predict_discrete(row, target, clf, mart)
    assert mart.cont[0][0] == target and mart.cont[0][1] == value and mart.cont[0][2].startswith("rf_regressor/demo/")
    assert mart.disc[0][0] == target and mart.disc[0][1] == label in (pt.LABEL_HIGH, pt.LABEL_LOW)
    assert 0.0 <= p <= 1.0 and mart.disc[0][2] == p and len(mart.disc[0][3]) <= 128


def test_label_follows_probability_cutoff(models):
    clf = pt.load_bundle(pt.CLASSIFIER_FILE, models)

    class Stub:
        classes_ = [0, 1]

        def __init__(self, p):
            self.p = p

        def predict_proba(self, X):
            return [[1 - self.p, self.p]]

    target, row = _row()
    for p, expected in ((0.9, pt.LABEL_HIGH), (0.5, pt.LABEL_HIGH), (0.1, pt.LABEL_LOW)):
        label, prob = pt.predict_discrete(row, target, {**clf, "model": Stub(p)}, FakeMart())
        assert label == expected and prob == p


def test_classifier_with_single_class_gives_zero_probability(models):
    clf = pt.load_bundle(pt.CLASSIFIER_FILE, models)

    class OneClass:
        classes_ = [0]

        def predict_proba(self, X):
            return [[1.0]]

    target, row = _row()
    label, prob = pt.predict_discrete(row, target, {**clf, "model": OneClass()}, FakeMart())
    assert (label, prob) == (pt.LABEL_LOW, 0.0)


def test_missing_model_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="train_models"):
        pt.load_bundle(pt.REGRESSOR_FILE, tmp_path)


def test_model_trained_with_other_horizon_is_rejected(models, tmp_path):
    bundle = joblib.load(models / pt.REGRESSOR_FILE)
    joblib.dump({**bundle, "horizon_days": 1}, tmp_path / pt.REGRESSOR_FILE)
    with pytest.raises(ValueError, match="horizon"):
        pt.load_bundle(pt.REGRESSOR_FILE, tmp_path)


def test_run_prediction_success_and_idempotent(models):
    wh, mart = FakeWarehouse(_data(60)), FakeMart()
    assert pt.run_prediction(wh, mart, models) == 2
    assert pt.run_prediction(wh, mart, models) == 2
    assert set(wh.metrics_asked) == {"http_traffic", "l7_attack"}
    # Cùng dữ liệu thì cùng target_date và cùng kết quả; ON CONFLICT lo phần ghi đè.
    assert str(mart.cont[0][0]) == "2026-04-02" and mart.cont[0][0] == mart.cont[1][0]
    assert mart.cont[0][1] == pytest.approx(mart.cont[1][1])
    assert mart.disc[0][:2] == mart.disc[1][:2] and mart.disc[0][2] == pytest.approx(mart.disc[1][2])
    assert not mart.runs  # common.runner ghi duy nhất một nhật ký cho mỗi lần chạy


def test_next_day_data_adds_new_target_and_keeps_old_one(models):
    mart = FakeMart()
    pt.run_prediction(FakeWarehouse(_data(60)), mart, models)
    pt.run_prediction(FakeWarehouse(_data(61, last_full_day="2026-04-01")), mart, models)
    assert [str(r[0]) for r in mart.cont] == ["2026-04-02", "2026-04-03"]  # khóa target_date khác nhau: không ghi đè


def test_run_prediction_no_data_writes_nothing(models):
    mart = FakeMart()
    assert pt.run_prediction(FakeWarehouse({}), mart, models) == 0
    assert not mart.cont and not mart.disc and not mart.runs


def test_run_prediction_records_failure(tmp_path):
    mart = FakeMart()
    with pytest.raises(FileNotFoundError):
        pt.run_prediction(FakeWarehouse(_data(30)), mart, tmp_path)
    assert not mart.runs and mart.rollbacks == 1


@pytest.mark.parametrize("count,status", [(0, "skipped"), (2, "success")])
def test_runner_receives_actual_outcome(monkeypatch, count, status):
    from contextlib import nullcontext

    monkeypatch.setattr("common.db.get_warehouse_conn", lambda: nullcontext(object()))
    monkeypatch.setattr("common.db.get_mart_conn", lambda: nullcontext(object()))
    monkeypatch.setattr(pt, "run_prediction", lambda *a: count)
    assert pt.run_all() == status
