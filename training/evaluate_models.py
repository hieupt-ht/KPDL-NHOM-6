"""Đánh giá 3 mô hình đã huấn luyện (chạy ngay sau train_models.py).

Chạy từ thư mục gốc repo:
    python training/evaluate_models.py                # Silver qua WAREHOUSE_DSN (rơi về demo nếu thiếu dữ liệu)
    python training/evaluate_models.py --demo
    python training/evaluate_models.py --metric http_traffic --risk-metric l7_attack

Kết quả trong models/eval/: eval_report.json + các biểu đồ .png.

Metric đích, metric rủi ro (l7_attack), ngưỡng rủi ro (percentile, cutoff P(High)), tên nhãn/cụm, horizon, test_ratio...
đọc từ services/prediction/ml_config.json (dùng chung với train/prediction/clustering):
đổi quyết định Issue #13 thì sửa file đó, huấn luyện lại rồi chạy script này.
Muốn thêm metric đánh giá: sửa REGRESSION_METRICS, CLASSIFICATION_METRICS,
CLUSTER_METRICS bên dưới. Ngưỡng High dùng đúng giá trị lưu trong rf_classifier.joblib.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    ConfusionMatrixDisplay,
    PrecisionRecallDisplay,
    RocCurveDisplay,
    accuracy_score,
    average_precision_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    silhouette_score,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_models import MODELS_DIR, load_data, split  # noqa: E402
from features import regressor_inputs  # noqa: E402
from ml_config import (  # noqa: E402  (train_models đã thêm services/prediction vào sys.path)
    CLUSTER_FEATURES,
    CLUSTER_TRAFFIC,
    HORIZON,
    LABEL_HIGH,
    LABEL_LOW,
    LAGS,
    METRIC,
    MIN_DAYS,
    RISK_METRIC,
    RISK_PERCENTILE,
    RISK_PROBA_CUTOFF,
    WEAK_SILHOUETTE,
    name_clusters,
)

log = logging.getLogger("evaluate_models")

# ---- Danh sách metric: thêm/bớt ở đây, báo cáo tự cập nhật ----------------
# Hồi quy: fn(y_true, y_pred) -> float
REGRESSION_METRICS = {
    "mae": mean_absolute_error,
    "rmse": lambda y, p: float(np.sqrt(mean_squared_error(y, p))),
    "mape": lambda y, p: float(np.mean(np.abs((y - p) / np.where(y == 0, np.nan, y))) * 100),
    "r2": r2_score,
}
# Phân loại: fn(y_true, y_pred, proba) -> float (proba = P(High))
CLASSIFICATION_METRICS = {
    "accuracy": lambda y, p, s: accuracy_score(y, p),
    "precision": lambda y, p, s: precision_score(y, p, zero_division=0),
    "recall": lambda y, p, s: recall_score(y, p, zero_division=0),
    "f1": lambda y, p, s: f1_score(y, p, zero_division=0),
    "roc_auc": lambda y, p, s: roc_auc_score(y, s),
    "pr_auc": lambda y, p, s: average_precision_score(y, s),
}
# Phân cụm: fn(X_scaled, labels) -> float
CLUSTER_METRICS = {
    "silhouette": silhouette_score,
    "davies_bouldin": davies_bouldin_score,  # thấp hơn là tốt
    "calinski_harabasz": calinski_harabasz_score,
}


def risk_label(values: pd.Series, threshold: float) -> pd.Series:
    """Nhãn High risk (1) = trung bình ngày của metric rủi ro > ngưỡng. Phải khớp train_classifier()."""
    return (values > threshold).astype(int)


def _safe(fn, *args) -> float | None:
    """Metric không tính được (vd. test chỉ có 1 lớp) -> None thay vì làm hỏng cả báo cáo."""
    try:
        v = float(fn(*args))
        return None if np.isnan(v) else v
    except ValueError as e:
        log.warning("Bỏ qua metric: %s", e)
        return None


def _save(fig, out_dir: Path, name: str) -> str:
    fig.tight_layout()
    fig.savefig(out_dir / name, dpi=120)
    plt.close(fig)
    return name


# ---- Hồi quy ----------------------------------------------------------------
def eval_regressor(bundle: dict, test: pd.DataFrame, out_dir: Path) -> tuple[dict, list[str]]:
    model, feats = bundle["model"], bundle["features"]
    X = regressor_inputs(test, feats, bundle.get("base_feature") if bundle.get("relative") else None)
    y, pred = test["value"].to_numpy(), model.predict(X)
    if bundle.get("base_feature"):  # mô hình delta: cộng lại giá trị ngày gần nhất đã biết
        pred = pred + test[bundle["base_feature"]].to_numpy()
    base_lag = min(LAGS)
    base = test[f"lag_{base_lag}"].to_numpy()  # mốc so sánh: ngày đích = giá trị ngày đủ gần nhất đã biết
    res = {
        "model": {k: _safe(f, y, pred) for k, f in REGRESSION_METRICS.items()},
        "baseline_naive": {k: _safe(f, y, base) for k, f in REGRESSION_METRICS.items()},
        "baseline_lag": base_lag,
    }
    if res["model"]["mae"] is not None and res["baseline_naive"]["mae"]:
        res["mae_improvement_vs_baseline_pct"] = (1 - res["model"]["mae"] / res["baseline_naive"]["mae"]) * 100

    figs = []
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(test.index, y, label="Thực tế", lw=1.5)
    ax.plot(test.index, pred, label="Dự đoán (RF)", lw=1.5)
    ax.plot(test.index, base, label=f"Baseline lag_{base_lag}", lw=1, ls=":", alpha=0.7)
    ax.set(title="Hồi quy: thực tế vs dự đoán (tập test)", ylabel=bundle.get("metric", "value"))
    ax.legend()
    figs.append(_save(fig, out_dir, "regressor_actual_vs_pred.png"))

    resid = y - pred
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].hist(resid, bins=20)
    axes[0].set(title="Phân phối sai số (thực tế - dự đoán)", xlabel="residual")
    axes[1].scatter(pred, resid, s=14)
    axes[1].axhline(0, color="k", lw=0.8)
    axes[1].set(title="Residual theo giá trị dự đoán", xlabel="dự đoán", ylabel="residual")
    figs.append(_save(fig, out_dir, "regressor_residuals.png"))

    imp = pd.Series(model.feature_importances_, index=X.columns).sort_values()
    fig, ax = plt.subplots(figsize=(6, 3.5))
    imp.plot.barh(ax=ax, title="Độ quan trọng đặc trưng (RF Regressor)")
    figs.append(_save(fig, out_dir, "regressor_feature_importance.png"))
    return res, figs


# ---- Phân loại rủi ro --------------------------------------------------------
def eval_classifier(bundle: dict, test: pd.DataFrame, out_dir: Path) -> tuple[dict, list[str]]:
    model, feats, thr = bundle["model"], bundle["features"], bundle["risk_threshold"]
    y = risk_label(test["risk_value"], thr)
    proba = model.predict_proba(test[feats])[:, list(model.classes_).index(1)] if 1 in model.classes_ else np.zeros(len(test))
    # Nhãn dự đoán theo đúng quy tắc service prediction: Cao nếu P(High) >= cutoff.
    cutoff = bundle.get("proba_cutoff", RISK_PROBA_CUTOFF)
    pred = (proba >= cutoff).astype(int)
    if bundle.get("risk_percentile") != RISK_PERCENTILE:
        log.warning(
            "Mô hình train với percentile %s, ml_config.json hiện là %s: hãy train lại.",
            bundle.get("risk_percentile"),
            RISK_PERCENTILE,
        )
    res = {
        "risk_metric": bundle.get("risk_metric"),
        "risk_percentile": bundle.get("risk_percentile"),
        "risk_threshold": thr,
        "proba_cutoff": cutoff,
        "test_high_ratio": float(y.mean()),
        "n_test": len(y),
        "metrics": {k: _safe(f, y, pred, proba) for k, f in CLASSIFICATION_METRICS.items()},
    }
    figs = []
    fig, ax = plt.subplots(figsize=(4.5, 4))
    ConfusionMatrixDisplay.from_predictions(y, pred, labels=[0, 1], display_labels=[LABEL_LOW, LABEL_HIGH], ax=ax, colorbar=False)
    ax.set_title("Ma trận nhầm lẫn (rủi ro)")
    figs.append(_save(fig, out_dir, "classifier_confusion.png"))

    if y.nunique() == 2:
        fig, axes = plt.subplots(1, 2, figsize=(9, 4))
        RocCurveDisplay.from_predictions(y, proba, ax=axes[0])
        PrecisionRecallDisplay.from_predictions(y, proba, ax=axes[1])
        axes[0].set_title("ROC")
        axes[1].set_title("Precision-Recall")
        figs.append(_save(fig, out_dir, "classifier_roc_pr.png"))
    else:
        log.warning("Tập test chỉ có 1 lớp: bỏ biểu đồ ROC/PR.")
    return res, figs


# ---- Phân cụm -----------------------------------------------------------------
def cluster_labels(bundle: dict) -> dict[int, str]:
    """cluster_id -> tên theo tâm cụm (cùng quy tắc services/clustering/tasks.py, ml_config.name_clusters)."""
    return name_clusters(bundle["model"][-1].cluster_centers_, list(bundle["features"]))


def eval_kmeans(bundle: dict, cl: pd.DataFrame, saved_metrics: dict | None, out_dir: Path) -> tuple[dict, list[str]]:
    pipe = bundle["model"]
    X = cl[CLUSTER_FEATURES]
    labels = pipe.predict(X)
    scaled = pipe[0].transform(X)
    names = cluster_labels(bundle)
    res = {"k": int(bundle["k"]), "metrics": {k: _safe(f, scaled, labels) for k, f in CLUSTER_METRICS.items()}}
    sil = res["metrics"].get("silhouette")
    res["weak_silhouette"] = sil is not None and sil < WEAK_SILHOUETTE
    sizes = pd.Series(labels).value_counts().sort_index()
    res["cluster_sizes"] = {names[int(i)]: int(n) for i, n in sizes.items()}

    figs = []
    fig, ax = plt.subplots(figsize=(10, 4))
    for cid, name in sorted(names.items()):
        m = labels == cid
        ax.scatter(cl.index[m], cl[CLUSTER_TRAFFIC][m], s=14, label=name)
    ax.set(title=f"K-Means (k={res['k']}): cụm theo ngày VN", ylabel=CLUSTER_TRAFFIC)
    ax.legend(title="cụm", loc="upper left")
    figs.append(_save(fig, out_dir, "kmeans_clusters_over_time.png"))

    scores = (saved_metrics or {}).get("kmeans", {}).get("scores_by_k")
    if scores:
        ks = sorted(int(k) for k in scores)
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.5))
        axes[0].plot(ks, [scores[str(k)]["silhouette"] for k in ks], marker="o")
        axes[0].axvline(res["k"], color="r", ls="--", lw=0.8)
        axes[0].set(title="Silhouette theo k", xlabel="k")
        axes[1].plot(ks, [scores[str(k)]["inertia"] for k in ks], marker="o")
        axes[1].axvline(res["k"], color="r", ls="--", lw=0.8)
        axes[1].set(title="Inertia theo k (elbow)", xlabel="k")
        figs.append(_save(fig, out_dir, "kmeans_k_selection.png"))

    fig, ax = plt.subplots(figsize=(4.5, 3.5))
    sizes.rename(index=names).plot.bar(ax=ax, title="Số ngày mỗi cụm", xlabel="cụm", rot=0)
    figs.append(_save(fig, out_dir, "kmeans_cluster_sizes.png"))
    return res, figs


# ---- Điều phối -------------------------------------------------------------------
def evaluate_models(
    metric: str = METRIC,
    risk_metric: str = RISK_METRIC,
    demo: bool = False,
    min_days: int = MIN_DAYS,
    models_dir: Path = MODELS_DIR,
    out_dir: Path | None = None,
) -> dict:
    models_dir = Path(models_dir)
    out_dir = Path(out_dir) if out_dir else models_dir / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    bundles = {}
    for name in ("kmeans", "rf_regressor", "rf_classifier"):
        path = models_dir / f"{name}.joblib"
        if not path.exists():
            raise SystemExit(f"Thiếu {path}. Chạy training/train_models.py trước.")
        bundles[name] = joblib.load(path)

    meta = bundles["rf_regressor"]
    if metric != meta["metric"]:
        log.warning("Đánh giá metric %s nhưng mô hình train trên %s: hãy train lại.", metric, meta["metric"])
    if meta.get("horizon_days") != HORIZON:
        log.warning("Mô hình train với horizon_days=%s, ml_config.json hiện là %s: hãy train lại.", meta.get("horizon_days"), HORIZON)
    df, cl, source = load_data(metric, risk_metric, demo, min_days)
    train, test = split(df)  # cùng cách chia với train_models để test không lẫn dữ liệu train
    if source != meta["data_source"]:
        log.warning("Nguồn dữ liệu đánh giá (%s) khác lúc train (%s).", source, meta["data_source"])
    test_range = [str(test.index[0].date()), str(test.index[-1].date())]
    if test_range != list(meta["test_range"]):
        log.warning("Tập test %s khác lúc train %s: dữ liệu đã đổi, hãy train lại.", test_range, meta["test_range"])

    saved = out_dir.parent / "metrics.json"
    saved_metrics = json.loads(saved.read_text(encoding="utf-8")) if saved.exists() else None

    reg, f1 = eval_regressor(bundles["rf_regressor"], test, out_dir)
    clf, f2 = eval_classifier(bundles["rf_classifier"], test, out_dir)
    km, f3 = eval_kmeans(bundles["kmeans"], cl, saved_metrics, out_dir)
    report = {
        "data_source": source,
        "metric": metric,
        "risk_metric": risk_metric,
        "horizon_days": meta.get("horizon_days"),
        "trained_at": meta["trained_at"],
        "n_days": len(df),
        "cluster_n_days": len(cl),
        "test_range": test_range,
        "rf_regressor": reg,
        "rf_classifier": clf,
        "kmeans": km,
        "figures": f1 + f2 + f3,
    }
    (out_dir / "eval_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _fmt(d: dict) -> str:
    return ", ".join(f"{k}={'n/a' if v is None else format(v, '.3f')}" for k, v in d.items())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--metric", default=METRIC, help="metric đích, mặc định: metric trong ml_config.json")
    p.add_argument("--risk-metric", default=RISK_METRIC, help="metric tạo nhãn rủi ro, mặc định: trong ml_config.json")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--min-days", type=int, default=MIN_DAYS)
    p.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    p.add_argument("--out-dir", type=Path, default=None, help="mặc định: <models-dir>/eval")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    r = evaluate_models(a.metric, a.risk_metric, a.demo, a.min_days, a.models_dir, a.out_dir)
    tag = " [DEMO]" if r["data_source"] == "demo" else ""
    print(
        f"Nguồn: {r['data_source']}{tag}, metric={r['metric']}, rủi ro={r['risk_metric']}, test {r['test_range'][0]}..{r['test_range'][1]}\n"
        f"Regressor:  {_fmt(r['rf_regressor']['model'])}\n"
        f"  baseline lag_{r['rf_regressor']['baseline_lag']}: {_fmt(r['rf_regressor']['baseline_naive'])}\n"
        f"Classifier (cutoff={r['rf_classifier']['proba_cutoff']:.2f}): {_fmt(r['rf_classifier']['metrics'])}\n"
        f"KMeans k={r['kmeans']['k']}: {_fmt(r['kmeans']['metrics'])}\n"
        f"Đã lưu {len(r['figures'])} biểu đồ + eval_report.json vào "
        f"{a.out_dir or a.models_dir / 'eval'}"
    )


if __name__ == "__main__":
    main()
