import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
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
    """Trả về (ts, value) giả theo metric trong truy vấn Silver."""

    def __init__(self, data: dict[str, pd.DataFrame]):
        self.data = {m: list(df.itertuples(index=False, name=None)) for m, df in data.items()}

    def execute(self, sql, params=None):
        assert "silver.metrics_hourly" in sql
        return _Result(self.data.get(params[0], []))


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
    return out, tm.make_demo_data(days=90)


def _bundle(centers):
    """Bundle giả: chỉ cần tâm cụm (đã chuẩn hóa) và thứ tự cột, như pipeline thật."""
    return {"model": [None, SimpleNamespace(cluster_centers_=np.array(centers, dtype=float))], "features": tm.CLUSTER_FEATURES}


def test_build_daily_features_columns_and_no_nan(env):
    f = ct.build_daily_features(FakeWarehouse(env[1]))
    assert list(f.columns) == ["http_mean", "l7_max", "bot_mean"] and not f.isna().any().any() and len(f) > 60
    assert str(f.index.tz) == "Asia/Ho_Chi_Minh"


def test_build_daily_features_empty():
    assert ct.build_daily_features(FakeWarehouse({})).empty


def test_assign_clusters_upserts_all_days(env):
    out, data = env
    bundle = ct.load_bundle(out)
    f = ct.build_daily_features(FakeWarehouse(data))
    mart = FakeMart()
    assert ct.assign_clusters(f, bundle, mart) == len(f) == len(mart.upserts)
    day, cid, name, feats = mart.upserts[0]
    assert day == f.index[0].date() and 0 <= cid < bundle["k"] and name
    assert set(feats.obj) == {"http_mean", "l7_max", "bot_mean", "metric"}
    # Mỗi cluster_id luôn cùng một tên.
    assert len({(r[1], r[2]) for r in mart.upserts}) == len({r[1] for r in mart.upserts})


def test_trained_clusters_use_readme_names_and_flag_attack_days(env):
    out, data = env
    mart = FakeMart()
    ct.run_clustering(FakeWarehouse(data), mart, out)
    assert {r[2] for r in mart.upserts} == {"Bình thường", "Cao điểm", "Bất thường"}
    # Ngày demo có tấn công (l7_max cao) phải rơi vào cụm Bất thường.
    attack = [r for r in mart.upserts if r[3].obj["l7_max"] > 35]
    assert attack and all(r[2] == "Bất thường" for r in attack)


def test_cluster_names_rule_three_clusters():
    # cột: http_mean, l7_max, bot_mean (đã chuẩn hóa)
    names = ct.cluster_names(_bundle([[0.2, 0.1, 0.0], [2.0, 0.3, 0.2], [0.5, 2.5, -0.1]]))
    assert names == {0: "Bình thường", 1: "Cao điểm", 2: "Bất thường"}


def test_cluster_names_anomaly_by_bot_even_if_traffic_is_highest():
    # Cụm 1 có traffic cao nhất nhưng bot cao hơn mọi cụm khác: vẫn là Bất thường, không phải Cao điểm.
    names = ct.cluster_names(_bundle([[-1.0, 0.0, 0.0], [3.0, 0.0, 2.0], [1.0, 0.1, 0.1]]))
    assert names == {0: "Bình thường", 1: "Bất thường", 2: "Cao điểm"}


def test_cluster_names_two_and_many_clusters():
    assert ct.cluster_names(_bundle([[1.0, 0.0, 0.0], [0.0, 2.0, 0.0]])) == {0: "Bình thường", 1: "Bất thường"}
    four = ct.cluster_names(_bundle([[3, 0, 0], [0, 0, 0], [2, 0, 0], [1, 0, 0]]))
    assert four == {1: "Cụm 1", 3: "Cụm 2", 2: "Cụm 3", 0: "Cụm 4"}  # xếp theo traffic tăng dần


def test_missing_model_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="train_models"):
        ct.load_bundle(tmp_path)


def test_run_clustering_success_and_idempotent(env):
    out, data = env
    wh, mart = FakeWarehouse(data), FakeMart()
    n1 = ct.run_clustering(wh, mart, out)
    n2 = ct.run_clustering(wh, mart, out)
    assert n1 == n2 > 0
    # Upsert lần 2 trùng ngày với lần 1 (ON CONFLICT lo phần ghi đè).
    assert [r[0] for r in mart.upserts[:n1]] == [r[0] for r in mart.upserts[n1:]]
    assert not mart.runs  # common.runner ghi duy nhất một nhật ký cho mỗi lần chạy


def test_run_clustering_records_failure(tmp_path):
    mart = FakeMart()
    with pytest.raises(FileNotFoundError):
        ct.run_clustering(FakeWarehouse(tm.make_demo_data(days=40)), mart, tmp_path)
    assert not mart.runs and mart.rollbacks == 1


@pytest.mark.parametrize("count,status", [(0, "skipped"), (90, "success")])
def test_runner_receives_actual_outcome(monkeypatch, count, status):
    from contextlib import nullcontext

    monkeypatch.setattr("common.db.get_warehouse_conn", lambda: nullcontext(object()))
    monkeypatch.setattr("common.db.get_mart_conn", lambda: nullcontext(object()))
    monkeypatch.setattr(ct, "run_clustering", lambda *a: count)
    assert ct.run_all() == status
