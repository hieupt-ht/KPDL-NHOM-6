"""Các tác vụ phân cụm trạng thái từng ngày.

Luồng: Silver (metrics_hourly) -> đặc trưng ngày -> K-Means đã huấn luyện
(models/kmeans.joblib) -> upsert gold.cluster_results. Ngày tính theo UTC, khớp
với features.build_features dùng khi huấn luyện.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from psycopg.types.json import Jsonb

from features import DEFAULT_METRIC, build_features, load_hourly
from ml_config import CLUSTER_FALLBACK_NAME, CLUSTER_FEATURES, CLUSTER_NAMES, cluster_matrix

log = logging.getLogger("clustering")

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/app/models"))
MODEL_FILE = "kmeans.joblib"
SERVICE = "clustering"
# Tên cụm theo k (ml_config.json), xếp theo mean `value` tăng dần; k khác dùng tên dự phòng.
NAMES = CLUSTER_NAMES


def load_bundle(models_dir: Path | str | None = None) -> dict[str, Any]:
    """Nạp bundle K-Means {"model", "features", "k", ...}; báo lỗi rõ nếu chưa huấn luyện."""
    path = Path(models_dir or MODELS_DIR) / MODEL_FILE
    if not path.is_file():
        raise FileNotFoundError(f"Chưa có mô hình {path}. Chạy training/train_models.py trước.")
    return joblib.load(path)


def build_daily_features(conn, metric: str = DEFAULT_METRIC) -> pd.DataFrame:
    """Đặc trưng phân cụm theo ngày (index = ngày UTC); bỏ ngày thiếu lag/trung bình trượt."""
    daily = build_features(load_hourly(conn, metric), dropna=False)
    if daily.empty:
        return pd.DataFrame(columns=CLUSTER_FEATURES, index=daily.index)
    return cluster_matrix(daily).dropna()


def cluster_names(bundle: dict[str, Any]) -> dict[int, str]:
    """Ánh xạ cluster_id -> tên, xếp theo mean `value` của tâm cụm (tăng dần)."""
    pipe, feats = bundle["model"], list(bundle["features"])
    centers = pipe[0].inverse_transform(pipe[-1].cluster_centers_)[:, feats.index("value")]
    order = np.argsort(centers)  # order[r] = cluster_id có mức thấp thứ r
    labels = NAMES.get(len(order)) or [CLUSTER_FALLBACK_NAME.format(n=r + 1) for r in range(len(order))]
    return {int(cid): labels[r] for r, cid in enumerate(order)}


def assign_clusters(features: pd.DataFrame, bundle: dict[str, Any], mart_conn, metric: str = DEFAULT_METRIC) -> int:
    """Gán cụm cho từng ngày và upsert vào gold.cluster_results. Trả về số dòng ghi."""
    if features.empty:
        return 0
    X = features[list(bundle["features"])]
    ids = bundle["model"].predict(X)
    names = cluster_names(bundle)
    rows = [
        (
            idx.date(),
            int(cid),
            names[int(cid)],
            Jsonb({**{c: float(v) for c, v in row.items()}, "metric": metric}),
        )
        for idx, cid, (_, row) in zip(features.index, ids, X.iterrows())
    ]
    with mart_conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO gold.cluster_results (date, cluster_id, cluster_name, features, computed_at) "
            "VALUES (%s, %s, %s, %s, now()) "
            "ON CONFLICT (date) DO UPDATE SET cluster_id = EXCLUDED.cluster_id, "
            "cluster_name = EXCLUDED.cluster_name, features = EXCLUDED.features, computed_at = now()",
            rows,
        )
    return len(rows)


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


def run_clustering(warehouse_conn, mart_conn, models_dir: Path | str | None = None, metric: str = DEFAULT_METRIC) -> int:
    """Chạy một lượt, ghi service_runs. Lỗi được ghi lại rồi ném tiếp."""
    run_id = _start_run(mart_conn)
    try:
        bundle = load_bundle(models_dir)
        n = assign_clusters(build_daily_features(warehouse_conn, metric), bundle, mart_conn, metric)
        mart_conn.commit()
    except Exception as exc:
        mart_conn.rollback()
        _finish_run(mart_conn, run_id, "failed", str(exc)[:1000])
        raise
    _finish_run(mart_conn, run_id, "success", None)
    log.info("Đã gán cụm cho %d ngày (metric=%s, nguồn mô hình: %s)", n, metric, bundle.get("data_source"))
    return n


def run_all() -> None:
    """Điểm vào cho scheduler: mở hai kết nối và chạy phân cụm."""
    from common.db import get_mart_conn, get_warehouse_conn

    with get_warehouse_conn() as wh, get_mart_conn() as mart:
        run_clustering(wh, mart)
