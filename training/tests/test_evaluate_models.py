import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate_models import CLASSIFICATION_METRICS, CLUSTER_METRICS, REGRESSION_METRICS, evaluate_models, risk_label  # noqa: E402
from train_models import train_models  # noqa: E402


@pytest.fixture(scope="module")
def evaluated(tmp_path_factory):
    out = tmp_path_factory.mktemp("models")
    train_models(demo=True, out_dir=out)
    return out, evaluate_models(demo=True, models_dir=out)


def test_report_has_all_metrics(evaluated):
    out, r = evaluated
    assert set(r["rf_regressor"]["model"]) == set(REGRESSION_METRICS)
    assert set(r["rf_classifier"]["metrics"]) == set(CLASSIFICATION_METRICS)
    assert set(r["kmeans"]["metrics"]) == set(CLUSTER_METRICS)
    assert json.loads((out / "eval" / "eval_report.json").read_text(encoding="utf-8"))["data_source"] == "demo"


def test_matches_training_metrics(evaluated):
    out, r = evaluated
    saved = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert r["rf_regressor"]["model"]["mae"] == pytest.approx(saved["rf_regressor"]["mae"])
    assert r["rf_classifier"]["metrics"]["f1"] == pytest.approx(saved["rf_classifier"]["f1"])
    assert r["kmeans"]["metrics"]["silhouette"] == pytest.approx(saved["kmeans"]["silhouette"])


def test_figures_written(evaluated):
    out, r = evaluated
    assert len(r["figures"]) >= 7
    for name in r["figures"]:
        assert (out / "eval" / name).stat().st_size > 0


def test_missing_models(tmp_path):
    with pytest.raises(SystemExit):
        evaluate_models(demo=True, models_dir=tmp_path)


def test_risk_label():
    import pandas as pd

    assert risk_label(pd.Series([1, 5, 9]), 5).tolist() == [0, 0, 1]


def test_uses_ml_config(evaluated):
    from ml_config import CLUSTER_NAMES, METRIC, RISK_PROBA_CUTOFF

    r = evaluated[1]
    assert r["metric"] == METRIC and r["rf_classifier"]["proba_cutoff"] == RISK_PROBA_CUTOFF
    k = r["kmeans"]["k"]
    names = set(CLUSTER_NAMES.get(k, [])) or set(r["kmeans"]["cluster_sizes"])
    assert set(r["kmeans"]["cluster_sizes"]) <= names
