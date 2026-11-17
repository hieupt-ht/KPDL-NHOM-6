"""Quy đổi các chuỗi MIN0_MAX về một thang đo chung.

Radar chuẩn hóa mỗi truy vấn theo giá trị lớn nhất của chính cửa sổ đó, nên hai cửa sổ
khác nhau chỉ lệch nhau một hệ số nhân. Hệ số này được ước lượng trên vùng chồng.
"""

from collections.abc import Mapping
from datetime import datetime
from statistics import median

MIN_OVERLAP = 12


def compute_scale(
    silver: Mapping[datetime, float], window: Mapping[datetime, float], min_overlap: int = MIN_OVERLAP
) -> float | None:
    """Trung vị của silver(t)/window(t) trên các mốc chung có cả hai giá trị > 0."""
    ratios = [
        silver[t] / w
        for t, w in window.items()
        if t in silver and silver[t] > 0 and w > 0
    ]
    if len(ratios) < min_overlap:
        return None
    return median(ratios)


def apply_scale(points: Mapping[datetime, float], k: float) -> dict[datetime, float]:
    return {t: v * k for t, v in points.items()}
