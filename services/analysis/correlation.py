"""Tính toán ma trận tương quan Pearson (Correlation Analysis) giữa 5 chỉ số."""

import logging
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

CORRELATION_VARS: tuple[str, ...] = (
    "http_traffic",
    "l7_attack",
    "bot_share",
    "human_share",
    "netflows",
)
MIN_OBSERVATIONS: int = 2


def compute_pearson_r(x: np.ndarray, y: np.ndarray) -> float | None:
    """Tính hệ số tương quan Pearson giữa 2 mảng quan sát.

    Điều kiện:
    - Cần ít nhất 2 quan sát hợp lệ (N >= 2).
    - Cả hai biến phải có phương sai > 0 (không zero-variance).
    - Trả về None nếu hệ số không xác định (không tự ý thay bằng 0).
    - Hệ số kết quả thuộc [-1.0, 1.0].
    """
    n = len(x)
    if n < MIN_OBSERVATIONS:
        return None

    x_mean = np.mean(x)
    y_mean = np.mean(y)

    x_diff = x - x_mean
    y_diff = y - y_mean

    ss_x = np.sum(x_diff ** 2)
    ss_y = np.sum(y_diff ** 2)

    # Kiểm tra zero variance
    if ss_x <= 1e-12 or ss_y <= 1e-12:
        return None

    cov_xy = np.sum(x_diff * y_diff)
    denom = np.sqrt(ss_x * ss_y)

    if denom <= 1e-12:
        return None

    r = float(cov_xy / denom)

    # Chống sai số làm tròn số thực vượt ngoài [-1, 1]
    r = max(-1.0, min(1.0, r))

    if np.isnan(r) or np.isinf(r):
        return None

    return r


def compute_correlation_records(
    df: pd.DataFrame,
    variables: tuple[str, ...] = CORRELATION_VARS,
) -> list[dict[str, Any]]:
    """Tính ma trận tương quan 5x5 giữa các chỉ số.

    Quy định:
    - Căn chỉnh dữ liệu theo timestamp.
    - Xử lý missing theo từng cặp quan sát (pairwise complete observations).
    - Bỏ qua các cặp có số quan sát < 2 hoặc zero-variance.
    - Không lưu NaN, Infinity hoặc tự tiện thay hệ số không xác định bằng 0.
    - Đảm bảo tính đối xứng và hệ số thuộc [-1, 1].
    """
    if df.empty or "ts" not in df.columns or "metric" not in df.columns or "value" not in df.columns:
        return []

    # Lọc chỉ lấy các metric trong danh sách cần tính
    sub_df = df[df["metric"].isin(variables)].copy()
    valid_mask = sub_df["value"].notna() & ~np.isinf(sub_df["value"])
    clean_df = sub_df[valid_mask]

    if clean_df.empty:
        return []

    # Căn chỉnh dữ liệu theo timestamp (Pivot table)
    # Nếu có timestamp trùng lặp cho cùng một metric, lấy trung bình
    pivoted = clean_df.pivot_table(index="ts", columns="metric", values="value", aggfunc="mean")

    records: list[dict[str, Any]] = []

    # Tính toán cho từng cặp (var_x, var_y)
    for i, var_x in enumerate(variables):
        for j, var_y in enumerate(variables):
            if var_x not in pivoted.columns or var_y not in pivoted.columns:
                continue

            # Pairwise complete: chỉ lấy các dòng mà cả 2 biến đều có giá trị
            pair_df = pivoted[[var_x, var_y]].dropna()
            if len(pair_df) < MIN_OBSERVATIONS:
                log.info(
                    "Cặp (%s, %s) chỉ có %d quan sát hợp lệ (< %d). Bỏ qua tương quan.",
                    var_x,
                    var_y,
                    len(pair_df),
                    MIN_OBSERVATIONS,
                )
                continue

            x_vals = pair_df[var_x].to_numpy(dtype=float)
            y_vals = pair_df[var_y].to_numpy(dtype=float)

            if var_x == var_y:
                # Tự tương quan: nếu variance > 0 thì bằng 1.0
                if np.var(x_vals) > 1e-12:
                    r = 1.0
                else:
                    log.warning("Biến '%s' có zero variance, không xác định tự tương quan.", var_x)
                    continue
            else:
                r = compute_pearson_r(x_vals, y_vals)
                if r is None:
                    log.warning(
                        "Không xác định được tương quan cho cặp (%s, %s) do zero-variance hoặc lỗi số học.",
                        var_x,
                        var_y,
                    )
                    continue

            records.append({
                "var_x": var_x,
                "var_y": var_y,
                "coef": r,
            })

    log.info("Tính toán tương quan thành công: %d cặp hệ số", len(records))
    return records

