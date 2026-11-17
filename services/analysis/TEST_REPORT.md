# Test Report – Analysis Service (Final Validation)

- **Service:** `analysis` (Cyber Radar VN)
- **Branch:** `feature/data-analysis`
- **Môi trường:** Python 3.11.18, pytest 9.2.0, pandas 2.2.3, statsmodels 0.14.6, scipy 1.17.1, psycopg 3.2.13
- **Tổng quan:** 70/70 tests **PASSED** (100%), 0 failed, 0 skipped, 0 warnings.

---

## 1. Danh sách chi tiết các bài kiểm thử

### A. Resampling Tests (`test_resampling.py` – 12 tests)
| # | Tên kiểm thử | Nội dung kiểm tra | Kết quả |
|---|:---|:---|:---:|
| 1 | `test_empty_dataframe_resampling` | Xử lý DataFrame rỗng trả về `[]` | **PASS** |
| 2 | `test_resampling_aggregation_accuracy` | Mean, Min, Max khớp giá trị kỳ vọng (10, 20, 30 $\to$ 20, 10, 30) | **PASS** |
| 3 | `test_resampling_week_starts_monday` | Tuần bắt đầu đúng Thứ Hai (`weekday == 0`) | **PASS** |
| 4 | `test_resampling_day_boundary` | 23:59 VN và 00:01 VN ngày kế tách đúng ngày lịch | **PASS** |
| 5 | `test_resampling_week_boundary` | Chủ Nhật 22:00 VN và Thứ Hai 08:00 VN tách đúng 2 tuần | **PASS** |
| 6 | `test_resampling_month_boundary` | 31/01 23:59 VN và 01/02 00:01 VN tách đúng tháng 1 và 2 | **PASS** |
| 7 | `test_resampling_no_artificial_missing_data` | Không tự sinh dữ liệu giả cho tháng thiếu ở giữa | **PASS** |
| 8 | `test_resampling_single_point` | 1 quan sát sinh đúng 3 bản ghi (day, week, month) | **PASS** |
| 9 | `test_resampling_constant_values` | Dữ liệu hằng số 42.0 cho `mean = min = max = 42.0` | **PASS** |
| 10 | `test_resampling_duplicate_timestamps` | Timestamp trùng nhau được tổng hợp lấy trung bình | **PASS** |
| 11 | `test_resampling_values_greater_than_one` | Dữ liệu rescaled $> 1.0$ (1.35, 1.45) bảo toàn đúng giá trị | **PASS** |
| 12 | `test_resampling_filters_nan_and_inf` | Lọc bỏ NaN, Infinity trước khi tính toán | **PASS** |

### B. Histogram Tests (`test_histogram.py` – 9 tests)
| # | Tên kiểm thử | Nội dung kiểm tra | Kết quả |
|---|:---|:---|:---:|
| 13 | `test_histogram_20_bins_and_count_sum` | Đúng 20 bins, $\sum \text{count} = 500$, $bin\_start < bin\_end$ | **PASS** |
| 14 | `test_histogram_exact_distribution_known_values` | Mảng chuẩn [0.1..1.0] cho biên và count chính xác | **PASS** |
| 15 | `test_histogram_identical_values_edge_case` | 100 mẫu đều bằng 0.5: 20 bins, 1 bin chứa 100 count, 19 bin=0 | **PASS** |
| 16 | `test_histogram_single_observation` | 1 mẫu duy nhất: 20 bins, 1 bin chứa count=1, 19 bin=0 | **PASS** |
| 17 | `test_histogram_values_above_one` | Bins trải động ngoài 1.0 ([1.2 .. 1.5]), không bị ép về [0, 1] | **PASS** |
| 18 | `test_histogram_large_outlier` | Bins bao quát tới 100.0, tổng count bảo toàn 51 | **PASS** |
| 19 | `test_histogram_filters_nan_and_inf` | Loại bỏ NaN và $\pm\infty$, bảo toàn 4 điểm hợp lệ | **PASS** |
| 20 | `test_histogram_empty_input` | Mảng rỗng trả về `[]` | **PASS** |
| 21 | `test_compute_histogram_records_dataframe` | Chỉ tính cho `http_traffic`, `l7_attack`, `bot_share` | **PASS** |

### C. Trend Analysis Tests (`test_trend.py` – 8 tests)
| # | Tên kiểm thử | Nội dung kiểm tra | Kết quả |
|---|:---|:---|:---:|
| 22 | `test_trend_fallback_to_week_when_months_insufficient` | Fallback sang tuần khi chuỗi tháng thiếu điểm ($< 24$) | **PASS** |
| 23 | `test_trend_increasing_series` | Trend tăng đơn điệu đối với chuỗi có độ dốc tăng rõ rệt | **PASS** |
| 24 | `test_trend_decreasing_series` | Trend giảm đơn điệu đối với chuỗi có độ dốc giảm rõ rệt | **PASS** |
| 25 | `test_trend_stationary_series` | Trend bám sát giá trị hằng số đối với chuỗi ổn định | **PASS** |
| 26 | `test_trend_not_identical_to_scalar_mean` | Trend là đường thời gian biến thiên, không phải hằng số vô hướng | **PASS** |
| 27 | `test_trend_gap_in_data_rejected` | Chuỗi có khoảng trống ở giữa bị bỏ qua, không tự nội suy | **PASS** |
| 28 | `test_trend_insufficient_data_skips_cleanly` | Bỏ qua an toàn khi chuỗi $< 8$ tuần | **PASS** |
| 29 | `test_trend_prefers_month_when_sufficient` | Ưu tiên tính tháng khi chuỗi đủ $\ge 24$ tháng liên tục | **PASS** |

### D. Seasonal Analysis Tests (`test_seasonal.py` – 5 tests)
| # | Tên kiểm thử | Nội dung kiểm tra | Kết quả |
|---|:---|:---|:---:|
| 30 | `test_seasonal_hour_of_day_and_day_of_week` | Miền giá trị bucket hợp lệ: giờ 0–23, thứ 0–6, tháng 1–12 | **PASS** |
| 31 | `test_seasonal_exact_mean_calculation` | Trung bình giờ 15:00 VN cho 3 ngày (10, 20, 30 $\to$ 20) | **PASS** |
| 32 | `test_seasonal_timezone_bucket_mapping` | Ánh xạ UTC 17:00 ngày 01/11 sang đúng 00:00 VN ngày 02/11 (Thứ Hai) | **PASS** |
| 33 | `test_seasonal_single_record` | 1 mẫu sinh đúng 3 bản ghi (1 hour, 1 dow, 1 month) | **PASS** |
| 34 | `test_seasonal_empty_buckets_not_created` | Không tự sinh bucket cho các giờ không có quan sát | **PASS** |

### E. Correlation Analysis Tests (`test_correlation.py` – 8 tests)
| # | Tên kiểm thử | Nội dung kiểm tra | Kết quả |
|---|:---|:---|:---:|
| 35 | `test_pearson_r_bounds_and_accuracy` | Khớp hệ số $r = 1.0$ và $r = -1.0$ với sai số $< 10^{-6}$ | **PASS** |
| 36 | `test_pearson_hand_calculated_general_case` | Khớp tuyệt đối với kết quả tính toán từ `scipy.stats.pearsonr` | **PASS** |
| 37 | `test_pearson_zero_variance` | Biến có phương sai bằng 0 trả về `None`, không tự thay bằng 0.0 | **PASS** |
| 38 | `test_pearson_single_observation` | Chỉ có 1 quan sát ($N < 2$) trả về `None` | **PASS** |
| 39 | `test_correlation_matrix_symmetry_and_self` | Ma trận đối xứng $r(x,y)=r(y,x)$, tự tương quan $r(x,x)=1.0$ | **PASS** |
| 40 | `test_correlation_pairwise_missing` | Căn chỉnh pairwise complete chính xác trên từng cặp | **PASS** |
| 41 | `test_correlation_disjoint_timestamps` | Hai metric không có điểm giao thời gian bị loại bỏ | **PASS** |
| 42 | `test_correlation_constant_series_skipped` | Metric không đổi bị loại bỏ tự tương quan và tương quan chéo | **PASS** |

### F. Data Quality & Anomaly Tests (`test_quality.py` – 11 tests)
| # | Tên kiểm thử | Nội dung kiểm tra | Kết quả |
|---|:---|:---|:---:|
| 43 | `test_empty_dataframe_quality` | DataFrame rỗng được đánh giá `is_usable = False` | **PASS** |
| 44 | `test_quality_unusable_when_all_null` | Dữ liệu chỉ toàn NaN/Inf được đánh giá `is_usable = False` | **PASS** |
| 45 | `test_distribution_exact_hand_calculated` | Đối chiếu giải tích Mean, Med, Min, Max, IQR, MAD | **PASS** |
| 46 | `test_quality_null_and_nan_detection` | Đếm chính xác số lượng Null, NaN, Infinity | **PASS** |
| 47 | `test_quality_duplicate_timestamps` | Phát hiện chính xác trùng lặp mốc thời gian | **PASS** |
| 48 | `test_quality_hourly_gaps_calculation` | Tính đúng số mốc giờ bị khuyết trong chuỗi | **PASS** |
| 49 | `test_quality_invalid_bounds` | Báo cáo vi phạm bounds âm và phần trăm $> 100$ | **PASS** |
| 50 | `test_robust_z_detection` | Nhận diện ngoại lai $|Z| > 3.5$ qua Median và MAD | **PASS** |
| 51 | `test_robust_z_zero_mad` | Xử lý an toàn khi $\text{MAD} = 0$ không tạo ngoại lai giả | **PASS** |
| 52 | `test_iqr_detection` | Nhận diện ngoại lai ngoài khoảng $[Q_1 - 1.5\text{IQR}, Q_3 + 1.5\text{IQR}]$ | **PASS** |
| 53 | `test_immutability_of_source_dataframe` | Đảm bảo DataFrame gốc không bị biến đổi giá trị hay cấu trúc | **PASS** |

### G. Reader Tests (`test_reader.py` – 4 tests)
| # | Tên kiểm thử | Nội dung kiểm tra | Kết quả |
|---|:---|:---|:---:|
| 54 | `test_get_latest_silver_ts` | Đọc đúng mốc thời gian lớn nhất từ Silver | **PASS** |
| 55 | `test_get_latest_silver_ts_empty` | Trả về `None` khi bảng Silver rỗng | **PASS** |
| 56 | `test_fetch_silver_metrics` | Đọc dữ liệu Silver và ép kiểu `['ts', 'metric', 'value']` | **PASS** |
| 57 | `test_fetch_silver_metrics_empty` | Trả về DataFrame rỗng đủ cấu trúc khi không có dòng | **PASS** |

### H. Writer Tests (`test_writer.py` – 6 tests)
| # | Tên kiểm thử | Nội dung kiểm tra | Kết quả |
|---|:---|:---|:---:|
| 58 | `test_write_all_analysis_results_transaction_and_params` | Giao dịch nguyên tử, cập nhật freshness, không ghi `service_runs` | **PASS** |
| 59 | `test_parameterized_queries_verification` | 100% câu lệnh INSERT sử dụng parameterized `%s` | **PASS** |
| 60 | `test_write_rollback_on_failure` | Lỗi trong transaction kích hoạt rollback, không cập nhật dở dang | **PASS** |
| 61 | `test_idempotent_rerun_deletes_old_data` | Xóa dữ liệu cũ trước khi nạp mới trong cùng 1 transaction | **PASS** |
| 62 | `test_write_all_analysis_results_rejects_none_silver_ts` | Ngăn chặn ghi khi `latest_silver_ts` là `None` | **PASS** |
| 63 | `test_individual_writers` | Từng hàm ghi đơn lẻ thực thi giao dịch độc lập | **PASS** |

### I. Tasks Orchestration Tests (`test_tasks.py` – 5 tests)
| # | Tên kiểm thử | Nội dung kiểm tra | Kết quả |
|---|:---|:---|:---:|
| 64 | `test_run_all_skips_when_silver_empty` | Dừng an toàn khi Silver rỗng, không xóa dữ liệu Gold hiện có | **PASS** |
| 65 | `test_run_all_skips_when_silver_all_nan` | Dừng an toàn khi Silver chỉ toàn NaN | **PASS** |
| 66 | `test_run_all_success_flow` | Luồng thành công gọi đủ các module và ghi nguyên tử | **PASS** |
| 67 | `test_run_all_database_error_propagates` | Không nuốt lỗi kết nối cơ sở dữ liệu | **PASS** |
| 68 | `test_individual_compute_tasks` | Từng hàm `compute_*` thực thi độc lập thành công | **PASS** |

### J. Service Integration Tests (`test_service_integration.py` – 2 tests)
| # | Tên kiểm thử | Nội dung kiểm tra | Kết quả |
|---|:---|:---|:---:|
| 69 | `test_health_endpoint` | `GET /health` trả về HTTP 200 `{"status": "ok", "service": "analysis"}` | **PASS** |
| 70 | `test_trigger_run_endpoint` | `POST /run` kích hoạt `run_all()` và trả về HTTP 200 | **PASS** |

---

## 2. Kết luận kiểm thử

- **Tỷ lệ vượt qua:** 100% (70/70 tests).
- **Thời gian thực thi:** 9.77 giây.
- **Tính toàn vẹn hệ thống:** Mọi tính toán thống kê và thao tác cơ sở dữ liệu đã được đối chiếu thực tế.
