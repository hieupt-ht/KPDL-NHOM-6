import json
import sys
from pathlib import Path

import joblib
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ml_config as tm_config  # noqa: E402
from train_models import CLASSIFIER_FEATURES, FEATURES, build_cluster_features, make_demo_data, train_models  # noqa: E402


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


def test_kmeans_k_from_config_and_scores(report):
    km = report[1]["kmeans"]
    assert km["k"] == 3 and km["k_forced"] and set(km["scores_by_k"]) >= {2, 3}


def test_kmeans_picks_k_by_silhouette_when_not_forced(tmp_path):
    km = train_models(demo=True, k=None, out_dir=tmp_path)["kmeans"]
    assert km["k"] == km["best_k_by_silhouette"] and not km["k_forced"]


def test_models_predict(report):
    out, r = report
    reg = joblib.load(out / "rf_regressor.joblib")
    clf = joblib.load(out / "rf_classifier.joblib")
    assert reg["features"] == FEATURES and clf["features"] == CLASSIFIER_FEATURES
    assert clf["risk_threshold"] == r["rf_classifier"]["risk_threshold"]
    assert r["rf_regressor"]["mae"] >= 0 and 0 <= r["rf_classifier"]["f1"] <= 1
    assert r["rf_regressor"]["baseline_naive_lag"] == 2


def test_regressor_is_delta_vs_smallest_lag(report):
    out, r = report
    reg = joblib.load(out / "rf_regressor.joblib")
    assert reg["base_feature"] == "lag_2" and r["rf_regressor"]["target"] == "delta"


def test_leaf_chosen_from_grid_on_train_tail(report):
    out, r = report
    reg = joblib.load(out / "rf_regressor.joblib")
    m = r["rf_regressor"]
    assert m["min_samples_leaf"] == reg["min_samples_leaf"] and m["min_samples_leaf"] in tm_config.RF_LEAF_GRID
    assert set(m["val_mae_by_leaf"]) <= set(tm_config.RF_LEAF_GRID)
    assert m["min_samples_leaf"] == min(m["val_mae_by_leaf"], key=m["val_mae_by_leaf"].get)


def test_metadata_records_metric_horizon_and_timezone(report):
    out, r = report
    for name in ("kmeans", "rf_regressor", "rf_classifier"):
        b = joblib.load(out / f"{name}.joblib")
        assert (b["metric"], b["risk_metric"], b["horizon_days"], b["timezone"]) == (
            "http_traffic", "l7_attack", 2, "Asia/Ho_Chi_Minh"
        )


def test_risk_threshold_and_class_ratio_recorded_from_train_only(report):
    clf = report[1]["rf_classifier"]
    assert clf["risk_metric"] == "l7_attack" and clf["risk_percentile"] == 75 and clf["proba_cutoff"] == 0.5
    assert 0.0 < clf["train_high_ratio"] < 0.5 and 0.0 <= clf["test_high_ratio"] <= 1.0
    assert clf["n_train_days"] + clf["n_test_days"] == report[1]["n_days"]
    # Ngưỡng nằm trong thang l7_attack (~10), không phải thang http_traffic (~100).
    assert clf["risk_threshold"] < 50


def test_forced_k(tmp_path):
    r = train_models(demo=True, k=2, out_dir=tmp_path)
    assert r["kmeans"]["k"] == 2 and r["kmeans"]["k_forced"]
    km = joblib.load(tmp_path / "kmeans.joblib")
    assert km["model"][-1].n_clusters == 2 and km["features"] == ["http_mean", "l7_max", "bot_mean"]
    assert km["model"].predict(build_cluster_features(make_demo_data(days=60))).max() <= 1
