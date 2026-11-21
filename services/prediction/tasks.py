"""Các tác vụ dự báo bằng mô hình Random Forest đã huấn luyện.

Luồng: Silver (metrics_hourly) -> đặc trưng ngày (features.py) ->
models/rf_regressor.joblib và rf_classifier.joblib -> upsert
gold.forecast_continuous / gold.forecast_discrete -> nhật ký gold.service_runs.

Quy ước (ml_config.json, Issue #13):
- Hồi quy: trung bình ngày của metric đích (http_traffic). Phân loại: "Cao" nếu P(High) >= proba_cutoff,
  High = trung bình ngày của metric rủi ro (l7_attack) > percentile của tập train (bundle["risk_threshold"]).
- Ngày tính theo giờ VN, ngày chỉ hợp lệ khi đủ 24 mốc giờ (features.daily_agg).
- Ngày dự báo (target_date) = ngày đủ dữ liệu mới nhất + horizon_days (mặc định 2), tức ngày mai
  khi hôm qua đã đủ dữ liệu. Mô hình được huấn luyện đúng horizon này nên không dùng dữ liệu chưa đủ ngày.
  Khi Silver chậm, target_date lùi tương ứng (ví dụ hôm nay) và dòng cũ được giữ.
- Upsert theo target_date: dự báo các ngày khác được giữ, chạy lặp 5 phút/lần vẫn idempotent.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from features import DEFAULT_METRIC, daily_agg, feature_frame, load_hourly
from ml_config import HORIZON, LABEL_HIGH, LABEL_LOW, RISK_METRIC, RISK_PROBA_CUTOFF

log = logging.getLogger("prediction")

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/app/models"))
REGRESSOR_FILE = "rf_regressor.joblib"
CLASSIFIER_FILE = "rf_classifier.joblib"
SERVICE = "prediction"


def load_bundle(filename: str, models_dir: Path | str | None = None) -> dict[str, Any]:
    """Nạp bundle {"model", "features", ...}; báo lỗi rõ nếu chưa huấn luyện."""
    path = Path(models_dir or MODELS_DIR) / filename
    if not path.is_file():
        raise FileNotFoundError(f"Chưa có mô hình {path}. Chạy training/train_models.py trước.")
    bundle = joblib.load(path)
    if bundle.get("horizon_days") != HORIZON:
        raise ValueError(
            f"{path.name} huấn luyện với horizon_days={bundle.get('horizon_days')}, cấu hình hiện tại là {HORIZON}. "
            "Chạy lại training/train_models.py."
        )
    return bundle


def model_name(bundle: dict[str, Any], stem: str) -> str:
    """Tên mô hình ghi vào Gold: <tên>/<nguồn dữ liệu>/<thời điểm huấn luyện> (<= 128 ký tự)."""
    return f"{stem}/{bundle.get('data_source', '?')}/{bundle.get('trained_at', '?')}"[:128]


def build_target_row(hourly: pd.DataFrame, risk_hourly: pd.DataFrame, features: list[str]) -> tuple[date, pd.DataFrame] | None:
    """Đặc trưng cho ngày dự báo (1 dòng). Trả về None nếu thiếu dữ liệu lịch sử.

    Ngày dự báo = ngày đủ 24 giờ mới nhất của metric đích + HORIZON. Lag và trung bình trượt chỉ lấy
    các ngày <= ngày đủ cuối, nên không cần giá trị của ngày hôm nay (chưa đủ giờ).
    """
    daily = daily_agg(hourly)
    valid = daily.dropna()
    if valid.empty:
        return None
    target = valid.index[-1] + pd.Timedelta(days=HORIZON)
    frame = feature_frame(daily, daily_agg(risk_hourly), upto=target)
    row = frame.loc[[target], features]
    if row.isna().any(axis=None):
        return None
    return target.date(), row


def predict_continuous(row: pd.DataFrame, target_date: date, bundle: dict[str, Any], mart_conn) -> float:
    """Dự báo chỉ số lưu lượng của ngày đích và upsert gold.forecast_continuous."""
    value = float(bundle["model"].predict(row[list(bundle["features"])])[0])
    mart_conn.execute(
        "INSERT INTO gold.forecast_continuous (target_date, predicted_value, model_name, created_at) "
        "VALUES (%s, %s, %s, now()) "
        "ON CONFLICT (target_date) DO UPDATE SET predicted_value = EXCLUDED.predicted_value, "
        "model_name = EXCLUDED.model_name, created_at = now()",
        (target_date, value, model_name(bundle, "rf_regressor")),
    )
    return value


def predict_discrete(row: pd.DataFrame, target_date: date, bundle: dict[str, Any], mart_conn) -> tuple[str, float]:
    """Phân loại rủi ro của ngày đích (Cao/Thấp) và upsert gold.forecast_discrete."""
    model = bundle["model"]
    proba = model.predict_proba(row[list(bundle["features"])])[0]
    classes = list(model.classes_)
    p_high = float(proba[classes.index(1)]) if 1 in classes else 0.0  # classifier huấn luyện chỉ thấy 1 lớp
    label = LABEL_HIGH if p_high >= RISK_PROBA_CUTOFF else LABEL_LOW
    mart_conn.execute(
        "INSERT INTO gold.forecast_discrete (target_date, label, probability, model_name, created_at) "
        "VALUES (%s, %s, %s, %s, now()) "
        "ON CONFLICT (target_date) DO UPDATE SET label = EXCLUDED.label, "
        "probability = EXCLUDED.probability, model_name = EXCLUDED.model_name, created_at = now()",
        (target_date, label, p_high, model_name(bundle, "rf_classifier")),
    )
    return label, p_high


def _start_run(mart_conn) -> int:
    row = mart_conn.execute(
        "INSERT INTO gold.service_runs (service, started_at, status) VALUES (%s, now(), 'running') RETURNING id",
        (SERVICE,),
    ).fetchone()
    mart_conn.commit()
    return row[0]


def _finish_run(mart_conn, run_id: int, status: str, error: str | None) -> None:
    mart_conn.execute(
        "UPDATE gold.service_runs SET finished_at = now(), status = %s, error = %s WHERE id = %s",
        (status, error, run_id),
    )
    mart_conn.commit()


def run_prediction(warehouse_conn, mart_conn, models_dir: Path | str | None = None) -> int:
    """Chạy một lượt dự báo, ghi service_runs. Trả về số dự báo đã ghi (0 nếu thiếu dữ liệu)."""
    run_id = _start_run(mart_conn)
    try:
        reg = load_bundle(REGRESSOR_FILE, models_dir)
        clf = load_bundle(CLASSIFIER_FILE, models_dir)
        metric, risk_metric = reg.get("metric", DEFAULT_METRIC), clf.get("risk_metric", RISK_METRIC)
        features = list(dict.fromkeys([*reg["features"], *clf["features"]]))
        target = build_target_row(load_hourly(warehouse_conn, metric), load_hourly(warehouse_conn, risk_metric), features)
        if target is None:
            log.warning("Chưa đủ dữ liệu Silver (metric=%s, rủi ro=%s) để dự báo", metric, risk_metric)
            n = 0
        else:
            target_date, row = target
            value = predict_continuous(row, target_date, reg, mart_conn)
            label, p_high = predict_discrete(row, target_date, clf, mart_conn)
            n = 2
            log.info("Dự báo %s (metric=%s): %.3f, rủi ro %s=%s (P=%.2f)", target_date, metric, value, risk_metric, label, p_high)
        mart_conn.commit()
    except Exception as exc:
        mart_conn.rollback()
        _finish_run(mart_conn, run_id, "failed", str(exc)[:1000])
        raise
    _finish_run(mart_conn, run_id, "success", None)
    return n


def run_all() -> None:
    """Điểm vào cho scheduler: mở hai kết nối và chạy cả hai dự báo."""
    from common.db import get_mart_conn, get_warehouse_conn

    with get_warehouse_conn() as wh, get_mart_conn() as mart:
        run_prediction(wh, mart)
