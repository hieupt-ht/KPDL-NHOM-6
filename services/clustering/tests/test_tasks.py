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
