"""Các tác vụ phân tích Silver thành Gold."""

import logging
import numpy as np

from quality import evaluate_data_quality
from reader import fetch_silver_metrics
from resampling import compute_resampling_records
from histogram import compute_histogram_records
from trend import compute_trend_records
from temporal_patterns import (
    assess_temporal_cycle_completeness,
    compute_temporal_pattern_records,
)
from correlation import compute_correlation_records
from writer import write_all_analysis_results

log = logging.getLogger(__name__)


def run_all() -> str:
    """Chạy toàn bộ tác vụ phân tích và ghi thời điểm dữ liệu mới nhất.

    Trả về trạng thái thực thi phù hợp với backend.common.runner (JobRunner):
    - "skipped": khi Silver rỗng, không có dữ liệu để phân tích.
    - "failed": khi dữ liệu không đủ chất lượng (unusable) hoặc không tạo được kết quả.
    - "partial": khi một số thuật toán không đủ dữ liệu (ví dụ trend thiếu 8 tuần) nhưng các thuật toán khác đã ghi thành công.
    - "success": khi toàn bộ 5 thuật toán đều hoàn thành và ghi Data Mart thành công.

    Quy trình:
    1. Đọc dữ liệu Silver một lần duy nhất để bảo đảm tính nhất quán.
    2. Lấy mốc thời gian Silver mới nhất trực tiếp từ dữ liệu vừa đọc.
    3. Đánh giá chất lượng dữ liệu (Data Quality) và phát hiện bất thường (Anomaly Detection).
    4. Tính toán toàn bộ 5 nhóm chỉ số phân tích:
       - Resampling (day, week, month)
       - Histogram (20 bins)
       - Trend (seasonal_decompose)
       - Temporal Pattern (hour, day_of_week, month — trung bình bucket)
       - Correlation (Pearson 5x5)
    5. Kiểm tra kết quả tính toán trước khi ghi Data Mart.
    6. Ghi tất cả vào Data Mart trong MỘT Transaction duy nhất (All-or-Nothing).
    7. Cập nhật gold.data_freshness khi và chỉ khi ghi thành công.
    """
    log.info("=== BẮT ĐẦU CHU KỲ PHÂN TÍCH TOÀN DIỆN (DATA ANALYSIS) ===")

    # 1. Đọc dữ liệu Silver một lần duy nhất để đảm bảo nhất quán
    df = fetch_silver_metrics()

    if df.empty:
        log.warning(
            "Silver rỗng hoặc không có dữ liệu hợp lệ. Bỏ qua chu kỳ và không ghi đè Data Mart."
        )
        return "skipped"

    # Lấy latest_silver_ts từ mốc thời gian có giá trị hợp lệ (NOT NULL, hữu hạn)
    valid_mask = df["value"].notna() & ~np.isinf(df["value"])
    valid_ts = df.loc[valid_mask, "ts"].dropna()
    if valid_ts.empty:
        log.warning("Không có mốc thời gian nào có giá trị hợp lệ. Bỏ qua chu kỳ.")
        return "failed"
    latest_ts = valid_ts.max().to_pydatetime()

    # 2. Đánh giá Data Quality & Anomaly Detection
    quality_report = evaluate_data_quality(df)
    if quality_report.status == "unusable":
        log.warning(
            "Dữ liệu Silver không đủ điều kiện sử dụng (unusable). Dừng chu kỳ phân tích."
        )
        return "failed"

    if quality_report.status == "partial":
        log.info(
            "Dữ liệu Silver đạt trạng thái một phần (partial). Pipeline tiếp tục xử lý các metric và thuật toán hợp lệ."
        )

    if quality_report.issues_detected:
        log.warning(
            "Phát hiện %d vấn đề chất lượng dữ liệu: %s",
            len(quality_report.issues_detected),
            quality_report.issues_detected,
        )

    # 3. Tính toán các thành phần phân tích theo Quality Gate từng thuật toán.
    # Thuật toán có algorithm_fitness = False (không đủ điều kiện đầu vào)
    # được bỏ qua và ghi rõ lý do, không gọi compute để tránh tính thừa.
    algorithm_fns = (
        ("resampling", compute_resampling_records),
        ("histogram", compute_histogram_records),
        ("trend", compute_trend_records),
        ("temporal_pattern", compute_temporal_pattern_records),
        ("correlation", compute_correlation_records),
    )
    computed: dict[str, list] = {}
    skipped_algorithms: list[str] = []
    for name, fn in algorithm_fns:
        if not quality_report.algorithm_fitness.get(name, False):
            log.info(
                "Bỏ qua thuật toán '%s': không đủ điều kiện đầu vào theo quality gate.",
                name,
            )
            computed[name] = []
            skipped_algorithms.append(name)
            continue
        computed[name] = fn(df)
        if not computed[name]:
            log.info(
                "Thuật toán '%s' đủ điều kiện theo gate nhưng không tạo được bản ghi nào.",
                name,
            )

    resampled_records = computed["resampling"]
    histogram_records = computed["histogram"]
    trend_records = computed["trend"]
    temporal_pattern_records = computed["temporal_pattern"]
    correlation_records = computed["correlation"]

    all_computed = [
        resampled_records,
        histogram_records,
        trend_records,
        temporal_pattern_records,
        correlation_records,
    ]
    if not any(all_computed):
        log.warning("Không có bất kỳ kết quả phân tích nào được tạo ra. Dừng chu kỳ.")
        return "failed"

    # Đánh giá khả năng lặp lại của mẫu hình thời gian — CHỈ để ghi log vận hành
    # (phương án a): không đổi Gold/API/Frontend. Kết quả "confirmed" thể hiện
    # dữ liệu đã đủ số chu kỳ quan sát độc lập hay chưa.
    try:
        cycle_assessment = assess_temporal_cycle_completeness(df)
        for metric_name, details in cycle_assessment.items():
            confirmed = [
                p for p, d in details["cycle_details"].items() if d["confirmed"]
            ]
            if confirmed:
                log.info(
                    "Metric '%s': mẫu hình thời gian đã xác nhận chu kỳ lặp lại cho: %s",
                    metric_name,
                    ", ".join(confirmed),
                )
            else:
                log.info(
                    "Metric '%s': chưa đủ chu kỳ lặp lại để xác nhận mẫu hình thời gian.",
                    metric_name,
                )
    except Exception as exc:
        log.warning("Không đánh giá được tính chu kỳ của mẫu hình thời gian: %s", exc)

    # 4. Ghi nguyên tử (atomic) toàn bộ vào Data Mart
    write_all_analysis_results(
        resampled_records=resampled_records,
        histogram_records=histogram_records,
        trend_records=trend_records,
        temporal_pattern_records=temporal_pattern_records,
        correlation_records=correlation_records,
        latest_silver_ts=latest_ts,
    )

    is_partial = not all(bool(r) for r in all_computed)
    if is_partial:
        if skipped_algorithms:
            log.info(
                "Các thuật toán bị quality gate bỏ qua: %s",
                ", ".join(skipped_algorithms),
            )
        log.info("=== HOÀN TẤT CHU KỲ PHÂN TÍCH (MỘT PHẦN / PARTIAL) ===")
        return "partial"

    log.info("=== HOÀN TẤT CHU KỲ PHÂN TÍCH TOÀN DIỆN THÀNH CÔNG ===")
    return "success"
