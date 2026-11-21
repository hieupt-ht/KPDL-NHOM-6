"""Nạp cấu hình ML từ ml_config.json (metric, ngưỡng rủi ro, đặc trưng, tên cụm, tham số huấn luyện).

Dùng chung cho training/, services/prediction, services/clustering. Đường dẫn file đọc từ biến
môi trường ML_CONFIG, mặc định ml_config.json cạnh module này.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(os.environ.get("ML_CONFIG") or Path(__file__).with_name("ml_config.json"))


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    cfg = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    cfg.pop("_comment", None)
    _validate(cfg)
    return cfg


def _validate(cfg: dict[str, Any]) -> None:
    feats, cl = cfg["features"], cfg["cluster"]
    if cl["diff_lag"] not in feats["lags"]:
        raise ValueError(f"cluster.diff_lag={cl['diff_lag']} phải nằm trong features.lags")
    if cl["dev_window"] not in feats["windows"]:
        raise ValueError(f"cluster.dev_window={cl['dev_window']} phải nằm trong features.windows")
    if not 0 < cfg["risk"]["percentile"] < 100:
        raise ValueError("risk.percentile phải trong (0, 100)")
    if not 0 < cfg["risk"]["proba_cutoff"] < 1:
        raise ValueError("risk.proba_cutoff phải trong (0, 1)")


CONFIG = load_config()

METRIC: str = CONFIG["metric"]
LAGS: tuple[int, ...] = tuple(CONFIG["features"]["lags"])  # ngày
WINDOWS: tuple[int, ...] = tuple(CONFIG["features"]["windows"])  # ngày
MODEL_FEATURES: list[str] = [f"lag_{n}" for n in LAGS] + [f"roll_mean_{w}" for w in WINDOWS] + ["dow"]

RISK_PERCENTILE: float = CONFIG["risk"]["percentile"]
RISK_PROBA_CUTOFF: float = CONFIG["risk"]["proba_cutoff"]
LABEL_HIGH: str = CONFIG["risk"]["label_high"]
LABEL_LOW: str = CONFIG["risk"]["label_low"]

_CL = CONFIG["cluster"]
K_RANGE = range(_CL["k_range"][0], _CL["k_range"][1] + 1)
K_FORCED: int | None = _CL["k"]
WEAK_SILHOUETTE: float = _CL["weak_silhouette"]
DEV_COL = f"dev_{_CL['dev_window']}"
DIFF_COL = f"diff_{_CL['diff_lag']}"
CLUSTER_FEATURES = ["value", DEV_COL, DIFF_COL]
CLUSTER_NAMES: dict[int, list[str]] = {int(k): v for k, v in _CL["names"].items()}
CLUSTER_FALLBACK_NAME: str = _CL["fallback_name"]

TRAINING = CONFIG["training"]
TEST_RATIO: float = TRAINING["test_ratio"]
MIN_DAYS: int = TRAINING["min_days"]
SEED: int = TRAINING["seed"]
RF_ESTIMATORS: int = TRAINING["rf_estimators"]


def cluster_matrix(df):
    """Đặc trưng phân cụm: mức lưu lượng, độ lệch so với trung bình trượt, biến động so với lag."""
    import pandas as pd

    return pd.DataFrame(
        {
            "value": df["value"],
            DEV_COL: df["value"] - df[f"roll_mean_{_CL['dev_window']}"],
            DIFF_COL: df["value"] - df[f"lag_{_CL['diff_lag']}"],
        },
        index=df.index,
    )
