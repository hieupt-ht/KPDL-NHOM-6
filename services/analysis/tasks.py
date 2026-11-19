"""Các tác vụ phân tích Silver thành Gold."""

import logging

from quality import evaluate_data_quality
from reader import fetch_silver_metrics
from resampling import compute_resampling_records
from histogram import compute_histogram_records
from trend import compute_trend_records
from seasonal import compute_seasonal_records
from correlation import compute_correlation_records
from writer import (
    write_all_analysis_results,
    write_resampled,
    write_histogram,
    write_trend,
    write_seasonal,
    write_correlation,
)

log = logging.getLogger(__name__)


def compute_resampled() -> None:
    """Tổng hợp chỉ số theo ngày, tuần và tháng rồi ghi Gold."""
    log.info("Bắt đầu tác vụ compute_resampled...")
    df = fetch_silver_metrics()
    if df.empty:
        log.warning("Silver rỗng. Bỏ qua compute_resampled.")
        return
    records = compute_resampling_records(df)
    if records:
        write_resampled(records)
        log.info("compute_resampled hoàn thành: %d bản ghi đã lưu.", len(records))


def compute_histogram() -> None:
    """Chia các chỉ số cần hiển thị thành 20 khoảng histogram."""
    log.info("Bắt đầu tác vụ compute_histogram...")
    df = fetch_silver_metrics()
    if df.empty:
        log.warning("Silver rỗng. Bỏ qua compute_histogram.")
        return
    records = compute_histogram_records(df)
    if records:
        write_histogram(records)
        log.info("compute_histogram hoàn thành: %d bins đã lưu.", len(records))


def compute_trend() -> None:
    """Tách xu hướng của chuỗi tháng hoặc chuỗi tuần nếu thiếu dữ liệu."""
    log.info("Bắt đầu tác vụ compute_trend...")
    df = fetch_silver_metrics()
    if df.empty:
        log.warning("Silver rỗng. Bỏ qua compute_trend.")
        return
    records = compute_trend_records(df)
    if records:
        write_trend(records)
        log.info("compute_trend hoàn thành: %d điểm trend đã lưu.", len(records))


def compute_seasonal() -> None:
    """Tính mùa vụ theo giờ, thứ và tháng theo giờ Việt Nam."""
    log.info("Bắt đầu tác vụ compute_seasonal...")
    df = fetch_silver_metrics()
    if df.empty:
        log.warning("Silver rỗng. Bỏ qua compute_seasonal.")
        return
    records = compute_seasonal_records(df)
    if records:
        write_seasonal(records)
        log.info("compute_seasonal hoàn thành: %d điểm seasonal đã lưu.", len(records))


def compute_correlation() -> None:
    """Tính tương quan Pearson giữa năm chỉ số từ Silver."""
    log.info("Bắt đầu tác vụ compute_correlation...")
    df = fetch_silver_metrics()
    if df.empty:
        log.warning("Silver rỗng. Bỏ qua compute_correlation.")
        return
    records = compute_correlation_records(df)
    if records:
        write_correlation(records)
        log.info(
            "compute_correlation hoàn thành: %d cặp correlation đã lưu.", len(records)
        )


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
       - Seasonal (hour, day_of_week, month)
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

    # Lấy latest_silver_ts trực tiếp từ dữ liệu đã tải — đảm bảo nhất quán với df
    ts_col = df["ts"].dropna()
    if ts_col.empty:
        log.warning("Cột ts không có giá trị hợp lệ. Bỏ qua chu kỳ.")
        return "failed"
    latest_ts = ts_col.max().to_pydatetime()

    # 2. Đánh giá Data Quality & Anomaly Detection
    quality_report = evaluate_data_quality(df)
    if not quality_report.is_usable:
        log.warning(
            "Dữ liệu Silver không đủ điều kiện sử dụng (unusable). Dừng chu kỳ phân tích."
        )
        return "failed"

    if quality_report.issues_detected:
        log.warning(
            "Phát hiện %d vấn đề chất lượng dữ liệu: %s",
            len(quality_report.issues_detected),
            quality_report.issues_detected,
        )

    # 3. Tính toán các thành phần phân tích
    resampled_records = compute_resampling_records(df)
    histogram_records = compute_histogram_records(df)
    trend_records = compute_trend_records(df)
    seasonal_records = compute_seasonal_records(df)
    correlation_records = compute_correlation_records(df)

    all_computed = [
        resampled_records,
        histogram_records,
        trend_records,
        seasonal_records,
        correlation_records,
    ]
    if not any(all_computed):
        log.warning("Không có bất kỳ kết quả phân tích nào được tạo ra. Dừng chu kỳ.")
        return "failed"

    # 4. Ghi nguyên tử (atomic) toàn bộ vào Data Mart
    write_all_analysis_results(
        resampled_records=resampled_records,
        histogram_records=histogram_records,
        trend_records=trend_records,
        seasonal_records=seasonal_records,
        correlation_records=correlation_records,
        latest_silver_ts=latest_ts,
    )

    is_partial = not all(bool(r) for r in all_computed)
    if is_partial:
        log.info("=== HOÀN TẤT CHU KỲ PHÂN TÍCH (MỘT PHẦN / PARTIAL) ===")
        return "partial"

    log.info("=== HOÀN TẤT CHU KỲ PHÂN TÍCH TOÀN DIỆN THÀNH CÔNG ===")
    return "success"
