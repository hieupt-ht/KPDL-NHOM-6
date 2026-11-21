"""Huấn luyện offline các mô hình phân cụm và dự báo.

Chạy từ thư mục gốc repo:
    python training/train_models.py                 # đọc Silver qua WAREHOUSE_DSN
    python training/train_models.py --demo          # dữ liệu giả (gắn nhãn demo)
    python training/train_models.py --k 3 --risk-percentile 80
    python training/train_models.py --metric http_traffic --risk-metric l7_attack

Kết quả trong models/: kmeans.joblib, rf_regressor.joblib, rf_classifier.joblib,
metrics.json. Mỗi file .joblib là dict {"model", "features", ...} để service
biết đúng thứ tự cột khi dự đoán.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    silhouette_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "prediction"))
from features import (  # noqa: E402
    classifier_inputs,
    regressor_inputs,
    DEFAULT_METRIC,
    build_cluster_features,
    build_features,
    load_cluster_hourly,
    load_hourly,
)
from ml_config import (  # noqa: E402
    CLASSIFIER_FEATURES,
    CLUSTER_FEATURES,
    HORIZON,
    K_FORCED,
    K_RANGE,
    LAGS,
    MIN_DAYS,
    MODEL_FEATURES as FEATURES,
    BASE_FEATURE,
    RF_ESTIMATORS,
    RF_LEAF_GRID,
    VAL_RATIO,
    RISK_METRIC,
    RISK_PERCENTILE,
    RISK_LABEL_MODE,
    RISK_ROLLING_DAYS,
    RISK_PROBA_CUTOFF,
    RISK_TUNE_CUTOFF,
    SEED,
    TEST_RATIO,
    TIMEZONE,
    WEAK_SILHOUETTE,
)

log = logging.getLogger("train_models")

MODELS_DIR = ROOT / "models"
# Đặc trưng, tham số huấn luyện, ngưỡng rủi ro, k: xem services/prediction/ml_config.json.


def make_demo_data(days: int = 180, seed: int = SEED) -> dict[str, pd.DataFrame]:
    """Sinh chuỗi theo giờ giả lập cho http_traffic, l7_attack, bot_share.

    Chu kỳ ngày + tuần, xu hướng nhẹ, nhiễu; vài ngày "cao điểm" (traffic tăng, tấn công bình thường)
    và vài ngày "bất thường" (l7_attack và bot_share tăng) để ba cụm tách được.
    """
    rng = np.random.default_rng(seed)
    ts = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("D"), periods=days * 24, freq="h")
    local = ts.tz_convert(TIMEZONE)  # ngày, giờ, thứ tính theo giờ VN như dữ liệu thật
    hour = local.hour.to_numpy()
    dow = local.day_of_week.to_numpy()
    t = np.arange(len(ts)) / 24
    day_idx = (local.normalize() - local[0].normalize()).days.to_numpy()
    n = max(1, days // 20)
    picked = rng.choice(int(day_idx.max()) - 1, size=2 * n, replace=False)
    peak_days = picked[:n]
    attack_days = np.unique(np.r_[picked[n:], picked[n:] + 1])  # tấn công kéo dài 2 ngày
    is_peak, is_attack = np.isin(day_idx, peak_days), np.isin(day_idx, attack_days)

    traffic = 100 + 0.05 * t + 25 * np.sin(2 * np.pi * (hour - 8) / 24) - 12 * (dow >= 5) + rng.normal(0, 5, len(ts))
    traffic *= np.where(is_peak, rng.uniform(1.5, 2.5), 1.0)
    l7 = 10 + 2 * np.sin(2 * np.pi * hour / 24) + rng.normal(0, 1, len(ts)) + is_attack * (30 + 15 * (hour % 6 == 0))
    bot = 30 + rng.normal(0, 2, len(ts)) + is_attack * 25
    frame = lambda v: pd.DataFrame({"ts": ts, "value": v})  # noqa: E731
    return {"http_traffic": frame(traffic), "l7_attack": frame(l7), "bot_share": frame(bot)}


def make_demo_hourly(days: int = 180, seed: int = SEED) -> pd.DataFrame:
    """Chuỗi http_traffic giả lập (xem make_demo_data)."""
    return make_demo_data(days, seed)["http_traffic"]


def load_data(metric: str, risk_metric: str, demo: bool, min_days: int) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Trả về (đặc trưng dự báo theo ngày, đặc trưng phân cụm theo ngày, nguồn 'silver' | 'demo')."""
    if not demo:
        dsn = os.environ.get("WAREHOUSE_DSN", "").strip()
        if not dsn:
            raise SystemExit("Thiếu WAREHOUSE_DSN. Đặt biến môi trường hoặc chạy với --demo.")
        import psycopg

        with psycopg.connect(dsn) as conn:
            df = build_features(load_hourly(conn, metric), risk_hourly=load_hourly(conn, risk_metric))
            cl = build_cluster_features(load_cluster_hourly(conn))
        if len(df) >= min_days and len(cl) >= min_days:
            return df, cl, "silver"
        raise SystemExit(
            f"Silver chỉ có {len(df)} ngày dự báo và {len(cl)} ngày phân cụm dùng được (< {min_days}). "
            "Cần bổ sung dữ liệu; chỉ dùng --demo khi chủ động kiểm thử dữ liệu giả."
        )
    data = make_demo_data()
    df = build_features(data.get(metric, data["http_traffic"]), risk_hourly=data.get(risk_metric, data["l7_attack"]))
    return df, build_cluster_features(data), "demo"


def train_kmeans(cl: pd.DataFrame, k: int | None) -> tuple[dict, dict]:
    """Thử k trong K_RANGE, chọn k Silhouette cao nhất (trừ khi ép --k)."""
    X = cl[CLUSTER_FEATURES]
    scaled = StandardScaler().fit_transform(X)
    scores = {}
    for kk in K_RANGE:
        if kk >= len(X):
            break
        km = KMeans(n_clusters=kk, n_init=10, random_state=SEED).fit(scaled)
        scores[kk] = {"silhouette": float(silhouette_score(scaled, km.labels_)), "inertia": float(km.inertia_)}
    best_k = max(scores, key=lambda kk: scores[kk]["silhouette"])
    chosen = k or best_k
    model = make_pipeline(StandardScaler(), KMeans(n_clusters=chosen, n_init=10, random_state=SEED)).fit(X)
    labels = model.predict(X)
    sil = float(silhouette_score(model[0].transform(X), labels))
    if sil < WEAK_SILHOUETTE:
        log.warning("Silhouette = %.3f < %.2f: các cụm không tách biệt rõ.", sil, WEAK_SILHOUETTE)
    profile = X.assign(cluster=labels).groupby("cluster").agg(["mean", "count"])
    profile.columns = [f"{c}_{s}" for c, s in profile.columns]
    metrics = {
        "k": chosen,
        "best_k_by_silhouette": best_k,
        "k_forced": k is not None,
        "silhouette": sil,
        "scores_by_k": scores,
        "cluster_profile": profile.round(3).to_dict(orient="index"),
    }
    return {"model": model, "features": CLUSTER_FEATURES, "k": chosen}, metrics


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chia theo thời gian, không xáo trộn: phần cuối làm test."""
    cut = int(len(df) * (1 - TEST_RATIO))
    return df.iloc[:cut], df.iloc[cut:]


def _regressor(leaf: int) -> RandomForestRegressor:
    return RandomForestRegressor(n_estimators=RF_ESTIMATORS, min_samples_leaf=leaf, random_state=SEED, n_jobs=-1)


def _base(df: pd.DataFrame):
    return df[BASE_FEATURE] if BASE_FEATURE else 0.0


def _X(df: pd.DataFrame) -> pd.DataFrame:
    return regressor_inputs(df, FEATURES, BASE_FEATURE)


def choose_leaf(train: pd.DataFrame) -> tuple[int, dict[int, float]]:
    """Chọn min_samples_leaf theo MAE trên đoạn cuối của train (chia theo thời gian, không đụng tập test)."""
    cut = int(len(train) * (1 - VAL_RATIO))
    fit, val = train.iloc[:cut], train.iloc[cut:]
    if len(fit) < 10 or val.empty:
        return RF_LEAF_GRID[0], {}
    scores = {}
    for leaf in RF_LEAF_GRID:
        m = _regressor(leaf).fit(_X(fit), fit["value"] - _base(fit))
        scores[leaf] = float(mean_absolute_error(val["value"], m.predict(_X(val)) + _base(val)))
    return min(scores, key=scores.get), scores


def train_regressor(train: pd.DataFrame, test: pd.DataFrame) -> tuple[dict, dict]:
    leaf, val_mae = choose_leaf(train)
    model = _regressor(leaf)
    base_te = _base(test)
    model.fit(_X(train), train["value"] - _base(train))  # delta: học chênh lệch so với giá trị ngày gần nhất
    pred = model.predict(_X(test)) + base_te
    metrics = {
        "mae": float(mean_absolute_error(test["value"], pred)),
        "rmse": float(np.sqrt(mean_squared_error(test["value"], pred))),
        # Mốc so sánh: đoán "giá trị ngày đích = giá trị ngày gần nhất đã biết" (lag nhỏ nhất).
        "baseline_naive_mae": float(mean_absolute_error(test["value"], test[f"lag_{min(LAGS)}"])),
        "baseline_naive_lag": min(LAGS),
        "target": "delta" if BASE_FEATURE else "level",
        "min_samples_leaf": leaf,
        "val_mae_by_leaf": val_mae,
    }
    return {"model": model, "features": FEATURES, "base_feature": BASE_FEATURE, "relative": bool(BASE_FEATURE), "min_samples_leaf": leaf}, metrics


CUTOFF_GRID = [round(c, 2) for c in np.arange(0.1, 0.91, 0.05)]


def _classifier() -> RandomForestClassifier:
    return RandomForestClassifier(n_estimators=RF_ESTIMATORS, class_weight="balanced", random_state=SEED, n_jobs=-1)


def _p_high(model, X) -> np.ndarray:
    classes = list(model.classes_)
    return model.predict_proba(X)[:, classes.index(1)] if 1 in classes else np.zeros(len(X))


def choose_cutoff(train: pd.DataFrame, y_train: pd.Series) -> tuple[float, dict[float, float]]:
    """Chọn cutoff P(High) theo F1 trên đoạn cuối của train (không đụng tập test).

    Không chỉnh (dùng ml_config) nếu tắt tune_cutoff, hoặc đoạn fit/val thiếu một trong hai lớp.
    """
    cut = int(len(train) * (1 - VAL_RATIO))
    y_fit, y_val = y_train.iloc[:cut], y_train.iloc[cut:]
    if not RISK_TUNE_CUTOFF or y_fit.nunique() < 2 or y_val.sum() == 0:
        return RISK_PROBA_CUTOFF, {}
    X = classifier_inputs(train, CLASSIFIER_FEATURES)
    proba = _p_high(_classifier().fit(X.iloc[:cut], y_fit), X.iloc[cut:])
    scores = {c: float(f1_score(y_val, (proba >= c).astype(int), zero_division=0)) for c in CUTOFF_GRID}
    best = max(scores.values())
    # Hòa điểm: lấy cutoff gần ml_config nhất để ổn định.
    return min((c for c in scores if scores[c] == best), key=lambda c: abs(c - RISK_PROBA_CUTOFF)), scores


def train_classifier(train: pd.DataFrame, test: pd.DataFrame, percentile: float, risk_metric: str) -> tuple[dict, dict]:
    """Nhãn High risk (1) theo ml_config risk.label_mode.

    - "rolling": trung bình ngày của metric rủi ro > risk_ref (percentile của các ngày gần đây đã biết).
    - "train": > percentile của tập train (chia theo thời gian, không nhìn tập test).
    `risk_threshold` ghi lại ngưỡng train (mode train) hoặc trung vị risk_ref trên train (mode rolling, để tham khảo).
    """
    if RISK_LABEL_MODE == "rolling":
        if percentile != RISK_PERCENTILE:
            raise ValueError("Nhãn rolling dùng percentile trong ml_config.json để khớp risk_ref; sửa config rồi train lại.")
        threshold = float(train["risk_ref"].median())
        y_train = (train["risk_value"] > train["risk_ref"]).astype(int)
        y_test = (test["risk_value"] > test["risk_ref"]).astype(int)
    else:
        threshold = float(np.percentile(train["risk_value"], percentile))
        y_train = (train["risk_value"] > threshold).astype(int)
        y_test = (test["risk_value"] > threshold).astype(int)
    cutoff, val_f1 = choose_cutoff(train, y_train)
    model = _classifier().fit(classifier_inputs(train, CLASSIFIER_FEATURES), y_train)
    pred = (_p_high(model, classifier_inputs(test, CLASSIFIER_FEATURES)) >= cutoff).astype(int)
    metrics = {
        "risk_metric": risk_metric,
        "risk_percentile": percentile,
        "risk_label_mode": RISK_LABEL_MODE,
        "risk_rolling_days": RISK_ROLLING_DAYS if RISK_LABEL_MODE == "rolling" else None,
        "risk_threshold": threshold,
        "proba_cutoff": cutoff,
        "val_f1_by_cutoff": val_f1,
        "accuracy": float(accuracy_score(y_test, pred)),
        "f1": float(f1_score(y_test, pred, zero_division=0)),
        "train_high_ratio": float(y_train.mean()),
        "test_high_ratio": float(y_test.mean()),
        "n_train_days": len(train),
        "n_test_days": len(test),
    }
    bundle = {
        "model": model,
        "features": CLASSIFIER_FEATURES,
        "risk_metric": risk_metric,
        "risk_threshold": threshold,
        "risk_percentile": percentile,
        "risk_label_mode": RISK_LABEL_MODE,
        "risk_rolling_days": RISK_ROLLING_DAYS if RISK_LABEL_MODE == "rolling" else None,
        "proba_cutoff": cutoff,
    }
    return bundle, metrics


def train_models(
    metric: str = DEFAULT_METRIC,
    risk_metric: str = RISK_METRIC,
    demo: bool = False,
    k: int | None = K_FORCED,
    risk_percentile: float = RISK_PERCENTILE,
    min_days: int = MIN_DAYS,
    out_dir: Path = MODELS_DIR,
) -> dict:
    """Đọc Silver (hoặc demo), huấn luyện 3 mô hình và lưu kết quả vào out_dir."""
    df, cl, source = load_data(metric, risk_metric, demo, min_days)
    if len(df) < 10 or len(cl) < 10:
        raise SystemExit(f"Quá ít dữ liệu để huấn luyện ({len(df)} ngày dự báo, {len(cl)} ngày phân cụm).")
    train, test = split(df)

    km, km_m = train_kmeans(cl, k)
    reg, reg_m = train_regressor(train, test)
    clf, clf_m = train_classifier(train, test, risk_percentile, risk_metric)

    meta = {
        "data_source": source,
        "metric": metric,
        "risk_metric": risk_metric,
        "horizon_days": HORIZON,
        "timezone": TIMEZONE,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_days": len(df),
        "cluster_n_days": len(cl),
        "train_range": [str(train.index[0].date()), str(train.index[-1].date())],
        "test_range": [str(test.index[0].date()), str(test.index[-1].date())],
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, bundle in (("kmeans", km), ("rf_regressor", reg), ("rf_classifier", clf)):
        joblib.dump({**bundle, **meta}, out_dir / f"{name}.joblib")

    report = {**meta, "kmeans": km_m, "rf_regressor": reg_m, "rf_classifier": clf_m}
    (out_dir / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--metric", default=DEFAULT_METRIC, help="metric đích của bộ hồi quy")
    p.add_argument("--risk-metric", default=RISK_METRIC, help="metric tạo nhãn rủi ro")
    p.add_argument("--demo", action="store_true", help="dùng dữ liệu giả, không cần DB")
    p.add_argument("--k", type=int, default=K_FORCED, help="ép số cụm; mặc định chọn theo Silhouette")
    p.add_argument("--risk-percentile", type=float, default=RISK_PERCENTILE, help="ngưỡng High risk (percentile tập train)")
    p.add_argument("--min-days", type=int, default=MIN_DAYS)
    p.add_argument("--out-dir", type=Path, default=MODELS_DIR)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    r = train_models(a.metric, a.risk_metric, a.demo, a.k, a.risk_percentile, a.min_days, a.out_dir)
    tag = " [DEMO]" if r["data_source"] == "demo" else ""
    print(
        f"Nguồn: {r['data_source']}{tag}, {r['n_days']} ngày\n"
        f"KMeans: k={r['kmeans']['k']} (tốt nhất theo Silhouette: {r['kmeans']['best_k_by_silhouette']}), "
        f"Silhouette={r['kmeans']['silhouette']:.3f}\n"
        f"RF Regressor (min_samples_leaf={r['rf_regressor']['min_samples_leaf']}): MAE={r['rf_regressor']['mae']:.3f}, RMSE={r['rf_regressor']['rmse']:.3f} "
        f"(baseline lag_{r['rf_regressor']['baseline_naive_lag']} MAE={r['rf_regressor']['baseline_naive_mae']:.3f})\n"
        f"RF Classifier (cutoff={r['rf_classifier']['proba_cutoff']:.2f}): Accuracy={r['rf_classifier']['accuracy']:.3f}, F1={r['rf_classifier']['f1']:.3f} "
        f"(rủi ro theo {r['risk_metric']}, nhãn {r['rf_classifier']['risk_label_mode']}: ngưỡng p{r['rf_classifier']['risk_percentile']:g} ~ {r['rf_classifier']['risk_threshold']:.3f}, "
        f"tỉ lệ High train/test = {r['rf_classifier']['train_high_ratio']:.2f}/{r['rf_classifier']['test_high_ratio']:.2f})\n"
        f"Đã lưu vào {a.out_dir}"
    )


if __name__ == "__main__":
    main()
