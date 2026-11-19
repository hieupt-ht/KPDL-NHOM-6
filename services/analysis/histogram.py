"""Tính toán biểu đồ phân phối tần suất (Histogram) 20 bins."""

import logging
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

HISTOGRAM_METRICS: tuple[str, ...] = ("http_traffic", "l7_attack", "bot_share")
NUM_BINS: int = 20


def compute_metric_histogram(
    metric_name: str,
    values: np.ndarray,
    num_bins: int = NUM_BINS,
) -> list[dict[str, Any]]:
    """Tính 20 bins cho một mảng giá trị của chỉ số.

    Quy định:
    - Loại bỏ NULL, NaN, Infinity.
    - Không cố định range 0-1 (dữ liệu có thể vượt quá 1).
    - Xử lý trường hợp mọi giá trị giống nhau (min == max).
    - Đảm bảo bin_start < bin_end và tổng count == số quan sát hợp lệ.
    """
    valid_mask = ~np.isnan(values) & ~np.isinf(values)
    clean_vals = values[valid_mask].astype(float)
    n_valid = len(clean_vals)

    if n_valid == 0:
        log.warning("Metric '%s' không có quan sát hợp lệ để tạo histogram.", metric_name)
        return []

    min_val = float(np.min(clean_vals))
    max_val = float(np.max(clean_vals))

    if min_val == max_val:
        # Trường hợp tất cả giá trị giống nhau: tạo dải phân phối đối xứng quanh giá trị đó
        delta = max(1.0, abs(min_val) * 0.1)
        edges = np.linspace(min_val - delta, max_val + delta, num_bins + 1)
        # Xác định bin chứa giá trị này
        bin_idx = int(np.digitize([min_val], edges)[0]) - 1
        bin_idx = max(0, min(num_bins - 1, bin_idx))

        counts = np.zeros(num_bins, dtype=int)
        counts[bin_idx] = n_valid
    else:
        counts, edges = np.histogram(clean_vals, bins=num_bins)

    total_count = int(np.sum(counts))
    if total_count != n_valid:
        raise ValueError(
            f"Lỗi tính histogram cho '{metric_name}': tổng count ({total_count}) != số quan sát hợp lệ ({n_valid})"
        )

    records: list[dict[str, Any]] = []
    for i in range(num_bins):
        records.append({
            "metric": metric_name,
            "bin_start": float(edges[i]),
            "bin_end": float(edges[i + 1]),
            "count": int(counts[i]),
        })

    return records


def compute_histogram_records(
    df: pd.DataFrame,
    metrics: tuple[str, ...] = HISTOGRAM_METRICS,
    num_bins: int = NUM_BINS,
) -> list[dict[str, Any]]:
    """Tính histogram cho các chỉ số được chỉ định."""
    if df.empty or "metric" not in df.columns or "value" not in df.columns:
        return []

    records: list[dict[str, Any]] = []

    for m in metrics:
        sub_df = df[df["metric"] == m]
        if sub_df.empty:
            continue
        vals = sub_df["value"].to_numpy(dtype=float)
        m_records = compute_metric_histogram(m, vals, num_bins=num_bins)
        records.extend(m_records)

    log.info("Tính toán histogram thành công: %d bins cho %d metrics", len(records), len(metrics))
    return records
