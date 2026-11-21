import json

import pytest

import ml_config


def _cfg(**over):
    cfg = json.loads(ml_config.CONFIG_PATH.read_text(encoding="utf-8"))
    for path, value in over.items():
        a, b = path.split(".")
        cfg[a][b] = value
    return cfg


def test_defaults_keep_current_values():
    assert ml_config.METRIC == "http_traffic"
    assert ml_config.MODEL_FEATURES == ["lag_1", "lag_7", "roll_mean_3", "roll_mean_7", "dow"]
    assert ml_config.CLUSTER_FEATURES == ["value", "dev_7", "diff_1"]
    assert (ml_config.RISK_PERCENTILE, ml_config.RISK_PROBA_CUTOFF) == (75, 0.5)
    assert (ml_config.LABEL_HIGH, ml_config.LABEL_LOW) == ("Cao", "Thấp")
    assert list(ml_config.K_RANGE) == [2, 3, 4, 5, 6]
    assert ml_config.CLUSTER_NAMES[3] == ["Thấp", "Bình thường", "Cao"]


@pytest.mark.parametrize("over", [{"cluster.diff_lag": 2}, {"cluster.dev_window": 5}, {"risk.percentile": 100}, {"risk.proba_cutoff": 0}])
def test_invalid_config_rejected(tmp_path, over):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_cfg(**over)), encoding="utf-8")
    with pytest.raises(ValueError):
        ml_config.load_config(p)
