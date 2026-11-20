import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "services" / "prediction"), str(ROOT / "training")]
import train_models as tm  # noqa: E402

# Nạp theo đường dẫn để không đụng `tasks` của service clustering khi chạy chung một phiên pytest.
_spec = importlib.util.spec_from_file_location("prediction_tasks", ROOT / "services" / "prediction" / "tasks.py")
pt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pt)

NOW = pd.Timestamp("2026-04-01 06:00", tz="UTC")  # ngày 2026-04-01 chưa đủ giờ


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class FakeWarehouse:
    def __init__(self, hourly: pd.DataFrame):
        self.rows = list(hourly.itertuples(index=False, name=None))

    def execute(self, sql, params=None):
        assert "silver.metrics_hourly" in sql
        return _Result(self.rows)


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


def _hourly(days: int, end: str = "2026-04-01") -> pd.DataFrame:
    """Chuỗi giờ giả, kết thúc ngay trước `end` 00:00 UTC, kèm vài giờ của ngày `end` (chưa đủ)."""
    ts = pd.date_range(end=pd.Timestamp(end, tz="UTC") + pd.Timedelta(hours=6), periods=days * 24 + 6, freq="h")
    return pd.DataFrame({"ts": ts, "value": [100.0 + t.day_of_week * 5 + t.hour for t in ts]})


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    out = tmp_path_factory.mktemp("models")
    tm.train_models(demo=True, out_dir=out)
    return out


def test_target_row_is_day_after_last_complete_day():
    target, row = pt.build_target_row(_hourly(30), tm.FEATURES, NOW)
    assert str(target) == "2026-04-01"  # ngày 04-01 chưa đủ giờ bị bỏ, 03-31 là ngày đủ cuối cùng + 1
    assert list(row.columns) == tm.FEATURES and len(row) == 1 and not row.isna().any(axis=None)
    h = _hourly(30)
    day = lambda d: h[h["ts"].dt.strftime("%Y-%m-%d") == d]["value"].mean()
    assert row["lag_1"].iloc[0] == pytest.approx(day("2026-03-31"))
    assert row["lag_7"].iloc[0] == pytest.approx(day("2026-03-25"))
    assert row["dow"].iloc[0] == pd.Timestamp("2026-04-01").day_of_week


def test_target_row_ignores_partial_today():
    h = _hourly(30)
    h.loc[h["ts"] >= pd.Timestamp("2026-04-01", tz="UTC"), "value"] = 1e9  # nếu lọt vào sẽ làm lệch lag
    _, row = pt.build_target_row(h, tm.FEATURES, NOW)
    assert row["lag_1"].iloc[0] < 1e6


def test_target_row_none_when_insufficient():
    assert pt.build_target_row(pd.DataFrame(columns=["ts", "value"]), tm.FEATURES, NOW) is None
    assert pt.build_target_row(_hourly(5), tm.FEATURES, NOW) is None  # thiếu lag_7


def test_target_row_none_with_gap_in_recent_days():
    h = _hourly(30)
    h = h[h["ts"].dt.strftime("%Y-%m-%d") != "2026-03-29"]  # roll_mean_3 thiếu
    assert pt.build_target_row(h, tm.FEATURES, NOW) is None


def test_predict_writes_both_tables(models):
    reg, clf = pt.load_bundle(pt.REGRESSOR_FILE, models), pt.load_bundle(pt.CLASSIFIER_FILE, models)
    target, row = pt.build_target_row(_hourly(60), tm.FEATURES, NOW)
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

    _, row = pt.build_target_row(_hourly(30), tm.FEATURES, NOW)
    for p, expected in ((0.9, pt.LABEL_HIGH), (0.5, pt.LABEL_HIGH), (0.1, pt.LABEL_LOW)):
        label, prob = pt.predict_discrete(row, pd.Timestamp(NOW).date(), {**clf, "model": Stub(p)}, FakeMart())
        assert label == expected and prob == p


def test_classifier_with_single_class_gives_zero_probability(models):
    clf = pt.load_bundle(pt.CLASSIFIER_FILE, models)

    class OneClass:
        classes_ = [0]

        def predict_proba(self, X):
            return [[1.0]]

    _, row = pt.build_target_row(_hourly(30), tm.FEATURES, NOW)
    label, prob = pt.predict_discrete(row, NOW.date(), {**clf, "model": OneClass()}, FakeMart())
    assert (label, prob) == (pt.LABEL_LOW, 0.0)


def test_missing_model_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="train_models"):
        pt.load_bundle(pt.REGRESSOR_FILE, tmp_path)


def test_run_prediction_success_and_idempotent(models):
    wh, mart = FakeWarehouse(_hourly(60)), FakeMart()
    assert pt.run_prediction(wh, mart, models, now=NOW) == 2
    assert pt.run_prediction(wh, mart, models, now=NOW) == 2
    # Cùng dữ liệu thì cùng target_date và cùng kết quả; ON CONFLICT lo phần ghi đè.
    assert mart.cont[0][0] == mart.cont[1][0] and mart.cont[0][1] == pytest.approx(mart.cont[1][1])
    assert mart.disc[0][:2] == mart.disc[1][:2] and mart.disc[0][2] == pytest.approx(mart.disc[1][2])
    assert [r[0] for r in mart.runs] == ["INSERT", "UPDATE"] * 2
    assert all(r[1][0] == "success" for r in mart.runs if r[0] == "UPDATE")


def test_run_prediction_no_data_writes_nothing(models):
    mart = FakeMart()
    assert pt.run_prediction(FakeWarehouse(pd.DataFrame(columns=["ts", "value"])), mart, models, now=NOW) == 0
    assert not mart.cont and not mart.disc and mart.runs[-1][1][0] == "success"


def test_run_prediction_records_failure(tmp_path):
    mart = FakeMart()
    with pytest.raises(FileNotFoundError):
        pt.run_prediction(FakeWarehouse(_hourly(30)), mart, tmp_path, now=NOW)
    status, error, _ = mart.runs[-1][1]
    assert status == "failed" and "rf_regressor.joblib" in error and mart.rollbacks == 1
