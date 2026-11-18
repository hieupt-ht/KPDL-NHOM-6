import json
import sys
from pathlib import Path

import joblib
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from train_models import FEATURES, cluster_matrix, train_models  # noqa: E402


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    out = tmp_path_factory.mktemp("models")
    return out, train_models(demo=True, out_dir=out)


def test_saves_three_models_and_metrics(report):
    out, r = report
    for name in ("kmeans", "rf_regressor", "rf_classifier"):
        bundle = joblib.load(out / f"{name}.joblib")
        assert bundle["data_source"] == "demo"
    assert json.loads((out / "metrics.json").read_text(encoding="utf-8"))["data_source"] == "demo"


def test_kmeans_picks_k_by_silhouette(report):
    km = report[1]["kmeans"]
    assert km["k"] == km["best_k_by_silhouette"] and not km["k_forced"]
    assert set(km["scores_by_k"]) >= {2, 3}


def test_models_predict(report):
    out, r = report
    reg = joblib.load(out / "rf_regressor.joblib")
    clf = joblib.load(out / "rf_classifier.joblib")
    assert reg["features"] == FEATURES and clf["risk_threshold"] == r["rf_classifier"]["risk_threshold"]
    assert r["rf_regressor"]["mae"] >= 0 and 0 <= r["rf_classifier"]["f1"] <= 1


def test_forced_k(tmp_path):
    r = train_models(demo=True, k=3, out_dir=tmp_path)
    assert r["kmeans"]["k"] == 3 and r["kmeans"]["k_forced"]
    km = joblib.load(tmp_path / "kmeans.joblib")
    assert km["model"][-1].n_clusters == 3
    assert km["model"].predict(cluster_matrix(_features())).max() <= 2


def _features():
    from features import build_features
    from train_models import make_demo_hourly

    return build_features(make_demo_hourly(days=30))
