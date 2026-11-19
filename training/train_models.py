"""Huấn luyện offline các mô hình phân cụm và dự báo.

Chạy từ thư mục gốc repo:
    python training/train_models.py                 # đọc Silver qua WAREHOUSE_DSN
    python training/train_models.py --demo          # dữ liệu giả (gắn nhãn demo)
    python training/train_models.py --k 3 --risk-percentile 80

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
from features import DEFAULT_METRIC, build_features, load_hourly  # noqa: E402

log = logging.getLogger("train_models")

MODELS_DIR = ROOT / "models"
FEATURES = ["lag_1", "lag_7", "roll_mean_3", "roll_mean_7", "dow"]
# Phân cụm trạng thái ngày: mức lưu lượng + độ lệch so với tuần trước + biến động so với hôm qua.
CLUSTER_FEATURES = ["value", "dev_7", "diff_1"]
K_RANGE = range(2, 7)
WEAK_SILHOUETTE = 0.25
TEST_RATIO = 0.2
MIN_DAYS = 30
SEED = 42


def make_demo_hourly(days: int = 180, seed: int = SEED) -> pd.DataFrame:
    """Sinh chuỗi theo giờ giả lập: chu kỳ ngày + tuần, xu hướng nhẹ, nhiễu, vài ngày đột biến."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("D"), periods=days * 24, freq="h")
    hour = ts.hour.to_numpy()
    dow = ts.day_of_week.to_numpy()
    t = np.arange(len(ts)) / 24
    value = (
        100
        + 0.05 * t
        + 25 * np.sin(2 * np.pi * (hour - 8) / 24)
        - 12 * (dow >= 5)
        + rng.normal(0, 5, len(ts))
    )
    spike_days = rng.choice(days, size=max(1, days // 20), replace=False)
    day_idx = (t // 1).astype(int)
    value *= np.where(np.isin(day_idx, spike_days), rng.uniform(1.5, 2.5), 1.0)
    return pd.DataFrame({"ts": ts, "value": value})


def load_data(metric: str, demo: bool, min_days: int) -> tuple[pd.DataFrame, str]:
    """Trả về (bảng đặc trưng theo ngày, nguồn 'silver' | 'demo')."""
    if not demo:
        dsn = os.environ.get("WAREHOUSE_DSN", "").strip()
        if not dsn:
            raise SystemExit("Thiếu WAREHOUSE_DSN. Đặt biến môi trường hoặc chạy với --demo.")
        import psycopg

        with psycopg.connect(dsn) as conn:
            df = build_features(load_hourly(conn, metric))
        if len(df) >= min_days:
            return df, "silver"
        log.warning("Silver chỉ có %d ngày dùng được (< %d): chuyển sang dữ liệu DEMO.", len(df), min_days)
    return build_features(make_demo_hourly()), "demo"


def cluster_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Đặc trưng phân cụm; service clustering phải dùng đúng hàm này khi gán cụm."""
    return pd.DataFrame(
        {"value": df["value"], "dev_7": df["value"] - df["roll_mean_7"], "diff_1": df["value"] - df["lag_1"]},
        index=df.index,
    )


def train_kmeans(df: pd.DataFrame, k: int | None) -> tuple[dict, dict]:
    """Thử k trong K_RANGE, chọn k Silhouette cao nhất (trừ khi ép --k)."""
    X = cluster_matrix(df)
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


def train_regressor(train: pd.DataFrame, test: pd.DataFrame) -> tuple[dict, dict]:
    model = RandomForestRegressor(n_estimators=300, random_state=SEED, n_jobs=-1)
    model.fit(train[FEATURES], train["value"])
    pred = model.predict(test[FEATURES])
    metrics = {
        "mae": float(mean_absolute_error(test["value"], pred)),
        "rmse": float(np.sqrt(mean_squared_error(test["value"], pred))),
        # Mốc so sánh: đoán "ngày mai = hôm nay" (lag_1).
        "baseline_lag1_mae": float(mean_absolute_error(test["value"], test["lag_1"])),
    }
    return {"model": model, "features": FEATURES}, metrics


def train_classifier(train: pd.DataFrame, test: pd.DataFrame, percentile: float) -> tuple[dict, dict]:
    """Nhãn High risk (1) = value > percentile của tập train (tránh rò rỉ từ tập test)."""
    threshold = float(np.percentile(train["value"], percentile))
    y_train = (train["value"] > threshold).astype(int)
    y_test = (test["value"] > threshold).astype(int)
    model = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=SEED, n_jobs=-1)
    model.fit(train[FEATURES], y_train)
    pred = model.predict(test[FEATURES])
    metrics = {
        "risk_percentile": percentile,
        "risk_threshold": threshold,
        "accuracy": float(accuracy_score(y_test, pred)),
        "f1": float(f1_score(y_test, pred, zero_division=0)),
        "test_high_ratio": float(y_test.mean()),
    }
    bundle = {"model": model, "features": FEATURES, "risk_threshold": threshold, "risk_percentile": percentile}
    return bundle, metrics


def train_models(
    metric: str = DEFAULT_METRIC,
    demo: bool = False,
    k: int | None = None,
    risk_percentile: float = 75.0,
    min_days: int = MIN_DAYS,
    out_dir: Path = MODELS_DIR,
) -> dict:
    """Đọc Silver (hoặc demo), huấn luyện 3 mô hình và lưu kết quả vào out_dir."""
    df, source = load_data(metric, demo, min_days)
    if len(df) < 10:
        raise SystemExit(f"Quá ít dữ liệu để huấn luyện ({len(df)} ngày).")
    train, test = split(df)

    km, km_m = train_kmeans(df, k)
    reg, reg_m = train_regressor(train, test)
    clf, clf_m = train_classifier(train, test, risk_percentile)

    meta = {
        "data_source": source,
        "metric": metric,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_days": len(df),
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
    p.add_argument("--metric", default=DEFAULT_METRIC)
    p.add_argument("--demo", action="store_true", help="dùng dữ liệu giả, không cần DB")
    p.add_argument("--k", type=int, default=None, help="ép số cụm; mặc định chọn theo Silhouette")
    p.add_argument("--risk-percentile", type=float, default=75.0, help="ngưỡng High risk (percentile tập train)")
    p.add_argument("--min-days", type=int, default=MIN_DAYS)
    p.add_argument("--out-dir", type=Path, default=MODELS_DIR)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    r = train_models(a.metric, a.demo, a.k, a.risk_percentile, a.min_days, a.out_dir)
    tag = " [DEMO]" if r["data_source"] == "demo" else ""
    print(
        f"Nguồn: {r['data_source']}{tag}, {r['n_days']} ngày\n"
        f"KMeans: k={r['kmeans']['k']} (tốt nhất theo Silhouette: {r['kmeans']['best_k_by_silhouette']}), "
        f"Silhouette={r['kmeans']['silhouette']:.3f}\n"
        f"RF Regressor: MAE={r['rf_regressor']['mae']:.3f}, RMSE={r['rf_regressor']['rmse']:.3f} "
        f"(baseline lag_1 MAE={r['rf_regressor']['baseline_lag1_mae']:.3f})\n"
        f"RF Classifier: Accuracy={r['rf_classifier']['accuracy']:.3f}, F1={r['rf_classifier']['f1']:.3f} "
        f"(ngưỡng p{r['rf_classifier']['risk_percentile']:g} = {r['rf_classifier']['risk_threshold']:.3f})\n"
        f"Đã lưu vào {a.out_dir}"
    )


if __name__ == "__main__":
    main()
