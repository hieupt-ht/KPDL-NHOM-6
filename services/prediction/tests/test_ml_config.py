import json

import pytest

import ml_config


def _cfg(**over):
    cfg = json.loads(ml_config.CONFIG_PATH.read_text(encoding="utf-8"))
    for path, value in over.items():
        a, b = path.split(".")
        cfg[a][b] = value
    return cfg


def test_decided_values_from_issue_13():
    assert ml_config.METRIC == "http_traffic" and ml_config.RISK_METRIC == "l7_attack"
    assert (ml_config.TIMEZONE, ml_config.MIN_HOURS_PER_DAY, ml_config.HORIZON) == ("Asia/Ho_Chi_Minh", 24, 2)
    assert ml_config.MODEL_FEATURES == ["lag_2", "lag_7", "roll_mean_3", "roll_mean_7", "dow"]
    assert ml_config.CLASSIFIER_FEATURES == ml_config.MODEL_FEATURES + [
        "risk_lag_2", "risk_lag_7", "risk_roll_mean_3", "risk_roll_mean_7"
    ]
    assert (ml_config.RISK_PERCENTILE, ml_config.RISK_PROBA_CUTOFF) == (75, 0.5)
    assert (ml_config.LABEL_HIGH, ml_config.LABEL_LOW) == ("Cao", "Thấp")
    assert list(ml_config.K_RANGE) == [2, 3, 4, 5, 6] and ml_config.K_FORCED == 3
    assert ml_config.CLUSTER_FEATURES == ["http_mean", "l7_max", "bot_mean"]
    assert ml_config.CLUSTER_METRICS == ["http_traffic", "l7_attack", "bot_share"]
    assert set(ml_config.CLUSTER_NAMES.values()) == {"Bình thường", "Cao điểm", "Bất thường"}


@pytest.mark.parametrize(
    "over",
    [
        {"features.lags": [1, 7]},  # lag < horizon: rò rỉ dữ liệu chưa biết
        {"risk.percentile": 100},
        {"risk.proba_cutoff": 0},
        {"cluster.roles": {"traffic": "nope", "attack": ["l7_max"]}},
    ],
)
def test_invalid_config_rejected(tmp_path, over):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_cfg(**over)), encoding="utf-8")
    with pytest.raises(ValueError):
        ml_config.load_config(p)
