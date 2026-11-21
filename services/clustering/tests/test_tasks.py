import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "services" / "prediction"), str(ROOT / "training")]
import train_models as tm  # noqa: E402

_spec = importlib.util.spec_from_file_location("clustering_tasks", ROOT / "services" / "clustering" / "tasks.py")
ct = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ct)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class FakeWarehouse:
    """Trả về (ts, value) giả cho truy vấn Silver."""

    def __init__(self, hourly: pd.DataFrame):
        self.rows = list(hourly.itertuples(index=False, name=None))

    def execute(self, sql, params=None):
        assert "silver.metrics_hourly" in sql
        return _Result(self.rows)


class FakeMart:
    def __init__(self):
        self.upserts, self.runs, self.commits, self.rollbacks = [], [], 0, 0

    def cursor(self):
        mart = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def executemany(self, sql, rows):
                assert "gold.cluster_results" in sql and "ON CONFLICT (date)" in sql
                mart.upserts.extend(rows)

        return Cur()

    def execute(self, sql, params=None):
        assert "gold.service_runs" in sql
        self.runs.append((sql.split()[0], params))
        return _Result([(1,)])

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    out = tmp_path_factory.mktemp("models")
    tm.train_models(demo=True, out_dir=out)
    return out, tm.make_demo_hourly(days=90)


def test_cluster_matrix_matches_training(env):
    daily = tm.build_features(env[1], dropna=False)
    pd.testing.assert_frame_equal(ct.cluster_matrix(daily), tm.cluster_matrix(daily))


def test_build_daily_features_columns_and_no_nan(env):
    f = ct.build_daily_features(FakeWarehouse(env[1]))
    assert list(f.columns) == tm.CLUSTER_FEATURES and not f.isna().any().any() and len(f) > 60


def test_build_daily_features_empty():
    assert ct.build_daily_features(FakeWarehouse(pd.DataFrame(columns=["ts", "value"]))).empty


def test_assign_clusters_upserts_all_days(env):
    out, hourly = env
    bundle = ct.load_bundle(out)
    f = ct.build_daily_features(FakeWarehouse(hourly))
    mart = FakeMart()
    assert ct.assign_clusters(f, bundle, mart) == len(f) == len(mart.upserts)
    day, cid, name, feats = mart.upserts[0]
    assert day == f.index[0].date() and 0 <= cid < bundle["k"] and name
    assert set(feats.obj) == {"value", "dev_7", "diff_1", "metric"}
    # Mỗi cluster_id luôn cùng một tên.
    assert len({(r[1], r[2]) for r in mart.upserts}) == len({r[1] for r in mart.upserts})


def test_cluster_names_sorted_by_level(env):
    bundle = ct.load_bundle(env[0])
    names = ct.cluster_names(bundle)
    assert sorted(names) == list(range(bundle["k"]))
    pipe = bundle["model"]
    level = pipe[0].inverse_transform(pipe[-1].cluster_centers_)[:, 0]
    lowest, highest = int(level.argmin()), int(level.argmax())
    expected = ct.NAMES.get(bundle["k"])
    first, last = (expected[0], expected[-1]) if expected else ("Cụm 1", f"Cụm {bundle['k']}")
    assert names[lowest] == first and names[highest] == last


def test_cluster_names_three_clusters(tmp_path):
    tm.train_models(demo=True, k=3, out_dir=tmp_path)
    assert sorted(ct.cluster_names(ct.load_bundle(tmp_path)).values()) == sorted(ct.NAMES[3])


def test_missing_model_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="train_models"):
        ct.load_bundle(tmp_path)


def test_run_clustering_success_and_idempotent(env):
    out, hourly = env
    wh, mart = FakeWarehouse(hourly), FakeMart()
    n1 = ct.run_clustering(wh, mart, out)
    n2 = ct.run_clustering(wh, mart, out)
    assert n1 == n2 > 0
    # Upsert lần 2 trùng ngày với lần 1 (ON CONFLICT lo phần ghi đè).
    assert [r[0] for r in mart.upserts[:n1]] == [r[0] for r in mart.upserts[n1:]]
    assert [r[0] for r in mart.runs] == ["INSERT", "UPDATE"] * 2
    assert all(r[1][0] == "success" for r in mart.runs if r[0] == "UPDATE")


def test_run_clustering_records_failure(tmp_path):
    mart = FakeMart()
    with pytest.raises(FileNotFoundError):
        ct.run_clustering(FakeWarehouse(tm.make_demo_hourly(days=40)), mart, tmp_path)
    status, error, _ = mart.runs[-1][1]
    assert status == "failed" and "kmeans.joblib" in error and mart.rollbacks == 1


# ---- Edge case: dữ liệu rỗng / thiếu / lỗi ghi ----


def _const_hourly(days: int, start: str = "2026-01-01") -> pd.DataFrame:
    ts = pd.date_range(start, periods=days * 24, freq="h", tz="UTC")
    return pd.DataFrame({"ts": ts, "value": [100.0 + t.day for t in ts]})


class FailingMart(FakeMart):
    """Ghi gold.cluster_results luôn lỗi."""

    def __init__(self, message="db down"):
        super().__init__()
        self.message = message

    def cursor(self):
        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def executemany(_, sql, rows):
                raise RuntimeError(self.message)

        return Cur()


def test_build_daily_features_needs_eight_days():
    # roll_mean_7/lag_1 cần 7 ngày lịch sử: 7 ngày -> rỗng, 8 ngày -> đúng 1 ngày.
    assert ct.build_daily_features(FakeWarehouse(_const_hourly(7))).empty
    f = ct.build_daily_features(FakeWarehouse(_const_hourly(8)))
    assert len(f) == 1 and f.index[0] == pd.Timestamp("2026-01-08", tz="UTC")


def test_build_daily_features_drops_gap_days():
    h = _const_hourly(30)
    h = h[h["ts"].dt.day != 15]  # thiếu hẳn ngày 15
    f = ct.build_daily_features(FakeWarehouse(h))
    assert not f.isna().any().any()
    assert pd.Timestamp("2026-01-15", tz="UTC") not in f.index  # chính ngày thiếu
    assert pd.Timestamp("2026-01-16", tz="UTC") not in f.index  # lag_1 thiếu


def test_build_daily_features_passes_metric():
    seen = []

    class Wh(FakeWarehouse):
        def execute(self, sql, params=None):
            seen.append(params)
            return super().execute(sql, params)

    ct.build_daily_features(Wh(_const_hourly(10)), metric="l7_attack")
    assert seen == [("l7_attack",)]


def test_assign_clusters_empty_writes_nothing(env):
    bundle = ct.load_bundle(env[0])
    mart = FakeMart()
    empty = ct.build_daily_features(FakeWarehouse(pd.DataFrame(columns=["ts", "value"])))
    assert ct.assign_clusters(empty, bundle, mart) == 0
    assert mart.upserts == [] and mart.commits == 0


def test_assign_clusters_records_metric(env):
    out, hourly = env
    mart = FakeMart()
    f = ct.build_daily_features(FakeWarehouse(hourly)).head(3)
    ct.assign_clusters(f, ct.load_bundle(out), mart, metric="l7_attack")
    assert len(mart.upserts) == 3 and all(r[3].obj["metric"] == "l7_attack" for r in mart.upserts)


def test_cluster_names_more_than_three_clusters(tmp_path):
    tm.train_models(demo=True, k=4, out_dir=tmp_path)
    bundle = ct.load_bundle(tmp_path)
    names = ct.cluster_names(bundle)
    assert sorted(names.values()) == ["Cụm 1", "Cụm 2", "Cụm 3", "Cụm 4"]
    pipe = bundle["model"]
    level = pipe[0].inverse_transform(pipe[-1].cluster_centers_)[:, 0]
    assert names[int(level.argmin())] == "Cụm 1" and names[int(level.argmax())] == "Cụm 4"


def test_run_clustering_no_data_is_success_with_zero_rows(env):
    mart = FakeMart()
    n = ct.run_clustering(FakeWarehouse(pd.DataFrame(columns=["ts", "value"])), mart, env[0])
    assert n == 0 and mart.upserts == [] and mart.rollbacks == 0
    assert mart.runs[-1][1][0] == "success"


def test_run_clustering_too_little_data_is_success_with_zero_rows(env):
    mart = FakeMart()
    assert ct.run_clustering(FakeWarehouse(_const_hourly(5)), mart, env[0]) == 0
    assert mart.upserts == [] and mart.runs[-1][1][0] == "success"


def test_run_clustering_db_error_rolls_back_and_reraises(env):
    mart = FailingMart("db down")
    with pytest.raises(RuntimeError, match="db down"):
        ct.run_clustering(FakeWarehouse(env[1]), mart, env[0])
    status, error, _ = mart.runs[-1][1]
    assert status == "failed" and error == "db down" and mart.rollbacks == 1


def test_run_clustering_truncates_long_error(env):
    mart = FailingMart("x" * 5000)
    with pytest.raises(RuntimeError):
        ct.run_clustering(FakeWarehouse(env[1]), mart, env[0])
    assert len(mart.runs[-1][1][1]) == 1000
