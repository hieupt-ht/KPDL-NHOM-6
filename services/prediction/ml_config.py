"""Nạp cấu hình ML từ ml_config.json (metric, ngày VN, horizon, ngưỡng rủi ro, đặc trưng, cụm, huấn luyện).

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
    if min(feats["lags"]) < cfg["horizon_days"]:
        raise ValueError(
            f"features.lags={feats['lags']} có lag nhỏ hơn horizon_days={cfg['horizon_days']}: "
            "đặc trưng sẽ dùng dữ liệu chưa biết lúc dự báo"
        )
    if cfg["horizon_days"] < 1 or cfg["min_hours_per_day"] < 1:
        raise ValueError("horizon_days và min_hours_per_day phải >= 1")
    if cfg["training"]["regressor_target"] not in ("delta", "level"):
        raise ValueError("training.regressor_target chỉ nhận delta hoặc level")
    tr = cfg["training"]
    if not tr["rf_min_samples_leaf_grid"] or min(tr["rf_min_samples_leaf_grid"]) < 1:
        raise ValueError("training.rf_min_samples_leaf_grid phải là danh sách số nguyên >= 1")
    if not 0 < tr["val_ratio"] < 1:
        raise ValueError("training.val_ratio phải trong (0, 1)")
    if cfg["risk"].get("label_mode", "train") not in ("train", "rolling"):
        raise ValueError("risk.label_mode chỉ nhận train hoặc rolling")
    if cfg["risk"].get("rolling_days", 28) < 7:
        raise ValueError("risk.rolling_days phải >= 7")
    if not 0 < cfg["risk"]["percentile"] < 100:
        raise ValueError("risk.percentile phải trong (0, 100)")
    if not 0 < cfg["risk"]["proba_cutoff"] < 1:
        raise ValueError("risk.proba_cutoff phải trong (0, 1)")
    names = [f["name"] for f in cl["features"]]
    if len(set(names)) != len(names):
        raise ValueError("cluster.features: tên đặc trưng bị trùng")
    if any(f["agg"] not in ("mean", "max") for f in cl["features"]):
        raise ValueError("cluster.features[].agg chỉ nhận mean hoặc max")
    roles = cl["roles"]
    if roles["traffic"] not in names or not set(roles["attack"]) <= set(names):
        raise ValueError("cluster.roles phải trỏ tới tên trong cluster.features")


CONFIG = load_config()

METRIC: str = CONFIG["metric"]  # metric đích của bộ hồi quy
TIMEZONE: str = CONFIG["timezone"]  # ngày dương lịch tính theo múi giờ này (Silver vẫn lưu UTC)
MIN_HOURS_PER_DAY: int = CONFIG["min_hours_per_day"]  # ngày chỉ hợp lệ khi đủ số mốc giờ này
HORIZON: int = CONFIG["horizon_days"]  # khoảng cách (ngày) từ ngày đủ dữ liệu cuối đến ngày dự báo

LAGS: tuple[int, ...] = tuple(CONFIG["features"]["lags"])  # ngày
WINDOWS: tuple[int, ...] = tuple(CONFIG["features"]["windows"])  # ngày
MODEL_FEATURES: list[str] = [f"lag_{n}" for n in LAGS] + [f"roll_mean_{w}" for w in WINDOWS] + ["dow"]

RISK_METRIC: str = CONFIG["risk"]["metric"]  # metric tạo nhãn rủi ro (trung bình ngày > percentile train)
RISK_PERCENTILE: float = CONFIG["risk"]["percentile"]
RISK_PROBA_CUTOFF: float = CONFIG["risk"]["proba_cutoff"]  # mặc định; bundle có proba_cutoff riêng thì dùng của bundle
# true: training chọn cutoff theo F1 trên đoạn cuối tập train (val_ratio), lưu vào bundle.
RISK_TUNE_CUTOFF: bool = bool(CONFIG["risk"].get("tune_cutoff", False))
LABEL_HIGH: str = CONFIG["risk"]["label_high"]
LABEL_LOW: str = CONFIG["risk"]["label_low"]
# Bộ phân loại dùng thêm lag và trung bình trượt của chính metric rủi ro.
RISK_FEATURES: list[str] = ["risk_" + f for f in MODEL_FEATURES if f != "dow"]
# "train": High = risk_value > percentile của cả tập train (ngưỡng cố định).
# "rolling": High = risk_value > percentile của rolling_days ngày đã biết trước đó (risk_ref, chỉ dùng ngày
# <= ngày đích - HORIZON): bắt "tăng đột biến so với gần đây", không lệch khi mức tấn công trôi.
RISK_LABEL_MODE: str = CONFIG["risk"].get("label_mode", "train")
RISK_ROLLING_DAYS: int = CONFIG["risk"].get("rolling_days", 28)
CLASSIFIER_FEATURES: list[str] = MODEL_FEATURES + RISK_FEATURES + (["risk_ref"] if RISK_LABEL_MODE == "rolling" else [])

_CL = CONFIG["cluster"]
K_RANGE = range(_CL["k_range"][0], _CL["k_range"][1] + 1)
K_FORCED: int | None = _CL["k"]
WEAK_SILHOUETTE: float = _CL["weak_silhouette"]
CLUSTER_SPECS: list[dict[str, str]] = _CL["features"]  # name, metric, agg (theo ngày)
CLUSTER_FEATURES: list[str] = [f["name"] for f in CLUSTER_SPECS]
CLUSTER_METRICS: list[str] = list(dict.fromkeys(f["metric"] for f in CLUSTER_SPECS))
CLUSTER_TRAFFIC: str = _CL["roles"]["traffic"]
CLUSTER_ATTACK: list[str] = list(_CL["roles"]["attack"])
CLUSTER_NAMES: dict[str, str] = _CL["names"]  # normal | peak | anomaly
CLUSTER_FALLBACK_NAME: str = _CL["fallback_name"]

TRAINING = CONFIG["training"]
TEST_RATIO: float = TRAINING["test_ratio"]
MIN_DAYS: int = TRAINING["min_days"]
SEED: int = TRAINING["seed"]
RF_ESTIMATORS: int = TRAINING["rf_estimators"]
# Chuỗi ngày gần phẳng thì RF lá nhỏ học nhiễu: chọn min_samples_leaf theo MAE trên đoạn cuối của tập train.
RF_LEAF_GRID: list[int] = list(TRAINING["rf_min_samples_leaf_grid"])
VAL_RATIO: float = TRAINING["val_ratio"]
# "delta": bộ hồi quy dự báo (value - lag nhỏ nhất) rồi cộng lại lag đó, để không bị kẹt trong khoảng giá trị
# đã thấy lúc train khi mức trung bình trôi (Random Forest không ngoại suy). "level": dự báo thẳng value.
REGRESSOR_TARGET: str = TRAINING["regressor_target"]
BASE_FEATURE: str | None = f"lag_{min(LAGS)}" if REGRESSOR_TARGET == "delta" else None


def name_clusters(centers, features: list[str]) -> dict[int, str]:
    """Tên cụm theo tâm cụm (không gian đã chuẩn hóa; cột theo `features`), README 5.2.

    k = 2: Bất thường (tấn công/bot cao nhất) và Bình thường. k = 3: thêm Cao điểm (traffic cao hơn
    trong hai cụm còn lại). k khác: tên dự phòng "Cụm n" xếp theo traffic tăng dần.
    Dùng chung cho services/clustering và training/evaluate_models.py.
    """
    import numpy as np

    centers = np.asarray(centers, dtype=float)
    traffic = centers[:, features.index(CLUSTER_TRAFFIC)]
    attack = centers[:, [features.index(c) for c in CLUSTER_ATTACK]].max(axis=1)
    k = len(centers)
    if k in (2, 3):
        anomaly = int(np.argmax(attack))
        rest = sorted((c for c in range(k) if c != anomaly), key=lambda c: traffic[c])
        names = {anomaly: CLUSTER_NAMES["anomaly"], rest[0]: CLUSTER_NAMES["normal"]}
        if k == 3:
            names[rest[1]] = CLUSTER_NAMES["peak"]
        return names
    order = np.argsort(traffic)
    return {int(cid): CLUSTER_FALLBACK_NAME.format(n=r + 1) for r, cid in enumerate(order)}
