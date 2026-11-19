# CODE REVIEW – MODULE DATA ANALYSIS

- **Repository:** `hieupt-ht/KPDL-NHOM-6`
- **Branch:** `feature/data-analysis`
- **Phạm vi:** `services/analysis/` và `services/analysis/tests/`
- **Reviewer:** Senior Python Code Reviewer (Devin)
- **Ngày:** 2026-11-18

---

## 1. Tổng quan chất lượng code

Module Analysis được tổ chức tốt theo đúng Shared Service Skeleton: `main.py` → `common.runner.create_service_app`, `tasks.py` điều phối, các module tính toán tách biệt (`reader`, `quality`, `resampling`, `histogram`, `trend`, `seasonal`, `correlation`, `writer`).

**Điểm mạnh:**

- Xử lý NULL/NaN/Infinity nhất quán ở mọi module tính toán (`notna() & ~np.isinf()`).
- Resampling, Histogram, Trend, Seasonal, Correlation đều đúng công thức và có test biên (day/week/month boundary theo giờ VN, min==max, zero-variance, pairwise missing).
- Ghi Gold dùng parameterized SQL, một transaction All-or-Nothing, `DELETE`+`INSERT` idempotent, `data_freshness` chỉ cập nhật khi toàn bộ thành công. Không ghi `gold.service_runs` (đúng phân quyền).
- `run_all` đọc Silver một lần cho toàn bộ 5 tác vụ (nhất quán snapshot), có quality gate trước khi ghi.
- Type hints đầy đủ, docstring tiếng Việt ngắn gọn, đúng convention của repo.

**Kết luận kiểm tra logic:** không phát hiện lỗi CRITICAL hay HIGH. Các thuật toán Resampling/Histogram/Trend/Seasonal/Correlation được cài đặt đúng và khớp README/spec.

---

## 2. Danh sách lỗi phát hiện

### MEDIUM

| # | Vị trí | Vấn đề | Trạng thái |
|---|--------|--------|-----------|
| M1 | `requirements.txt` | `numpy` được import trực tiếp ở 6 module (`resampling`, `histogram`, `trend`, `seasonal`, `correlation`, `quality`) nhưng không khai báo — chỉ có nhờ pandas kéo theo transitively. | **ĐÃ SỬA** |
| M2 | `requirements-dev.txt` | `test_correlation.py` import trực tiếp `scipy.stats.pearsonr` nhưng scipy không khai báo (chỉ có nhờ statsmodels). `pytest-mock` được khai báo nhưng không test nào dùng (`mocker` không xuất hiện). | **ĐÃ SỬA** |
| M3 | `writer.py` | ~200 dòng SQL DELETE/INSERT bị lặp nguyên văn giữa 5 hàm `write_*` đơn lẻ và `write_all_analysis_results`; logic conn/transaction lặp 7 lần. Rủi ro sửa một chỗ quên chỗ khác khi schema Gold đổi. | **ĐÃ SỬA** |
| M4 | `tasks.py`, `writer.py` | `compute_resampled/histogram/trend/seasonal/correlation` + 6 hàm `write_*` đơn lẻ là **dead code trong production**: `main.py` chỉ schedule `run_all`. Chúng fetch Silver riêng từng lần, bỏ qua quality gate và không ghi freshness — nếu ai đó gọi nhầm sẽ ghi Gold không nhất quán. | Chưa xử lý (cần owner quyết định giữ làm API thủ công hay gỡ) |
| M5 | `tasks.py:108-109` | `run_all` gọi `fetch_silver_metrics()` (conn 1) rồi `get_latest_silver_ts()` (conn 2). Nếu ingestion ghi thêm dòng giữa hai query, `latest_silver_ts` vượt quá dữ liệu thực đã phân tích (freshness "ảo" 1 chu kỳ). Tự khắc phục ở chu kỳ sau. | Chưa xử lý (sửa sẽ đổi hành vi đang được test mock) |
| M6 | `quality.py:226` + `writer.py` | `is_usable` chỉ cần ≥1 giá trị hợp lệ bất kỳ → khi Silver suy giảm (vd chỉ còn vài giờ dữ liệu), `gold.trend`/`gold.correlation` bị DELETE sạch do records rỗng, trong khi freshness vẫn báo "thành công". Hệ quả của semantics snapshot-all-or-nothing; chấp nhận được nhưng cần ý thức khi demo. | Chưa xử lý (design decision) |

### LOW

| # | Vị trí | Vấn đề |
|---|--------|--------|
| L1 | `correlation.py:18` | `MIN_OBSERVATIONS = 2`: Pearson với n=2 luôn cho \|r\|=1 — đúng spec/README nhưng giá trị ghi vào Gold thiếu ý nghĩa thống kê khi dữ liệu còn non. |
| L2 | `main.py:14-17` | Gỡ route `/run` mặc định của runner rồi đăng ký lại — hoạt động đúng nhưng fragile nếu `common.runner` đổi cấu trúc route. |
| L3 | `reader.py:39-76` | `fetch_silver_metrics` `fetchall()` toàn bộ `silver.metrics_hourly` mỗi chu kỳ 300s — OK cho quy mô demo, sẽ thành vấn đề khi silver lớn (cân nhắc window `WHERE ts >= now() - interval`). |
| L4 | `quality.py:210` | `anomaly_samples` lấy 5 outlier **đầu tiên theo thời gian** (`head(5)`), không phải 5 outlier lớn nhất — chỉ ảnh hưởng mẫu log/báo cáo. |
| L5 | `quality.py` | `evaluate_data_quality` giả định `ts` đã là datetime (reader đảm bảo); không tự coerce. Đã gia cố guard cột (xem M-fix), nhưng string-ts vẫn có thể lỗi ở bước gap analysis. |
| L6 | `seasonal.py` | Trước sửa có 3 block groupby lặp gần y hệt nhau và hằng `PERIOD_TYPES` không dùng ở đâu — đã gộp thành vòng lặp. |

---

## 3. Các lỗi đã sửa trong đợt review này

1. **`requirements.txt`**: thêm `numpy~=2.4.0` (dependency trực tiếp còn thiếu).
2. **`requirements-dev.txt`**: thêm `scipy~=1.17.0` (test dùng trực tiếp), xóa `pytest-mock` không dùng.
3. **`writer.py`**: refactor toàn bộ — đưa SQL DELETE/INSERT của 5 bảng Gold thành hằng spec dùng chung, thêm helper `_replace_gold_table`, `_upsert_freshness`, `_with_mart_conn`. Giảm từ 368 → 221 dòng, xóa hoàn toàn code trùng; giữ nguyên thứ tự DELETE/INSERT, số lần gọi `transaction()`/`executemany()`/`execute()` để tương thích test hiện có.
4. **`seasonal.py`**: gộp 3 block tính `hour_of_day`/`day_of_week`/`month` thành một vòng lặp theo `PERIOD_BUCKETS`; xóa hằng `PERIOD_TYPES` không dùng. 90 → 70 dòng.
5. **`quality.py`**: guard đầu `evaluate_data_quality` mở rộng kiểm tra đủ 3 cột `ts/metric/value` — trước đây thiếu `ts` sẽ ném `KeyError` thay vì trả về report unusable.

---

## 4. Các vấn đề chưa xử lý

- **M4**: dead code `compute_*`/`write_*` đơn lẻ — đề xuất owner chọn: (a) xóa cùng test liên quan, hoặc (b) expose có chủ đích qua endpoint riêng.
- **M5**: race nhỏ giữa `fetch_silver_metrics` và `get_latest_silver_ts` — đề xuất lấy `latest_ts` từ cùng connection hoặc từ `df["ts"].max()`.
- **M6**: ngưỡng `is_usable` quá lỏng — có thể cân nhắc yêu cầu tối thiểu N giờ dữ liệu hoặc số metric tối thiểu trước khi ghi Gold.
- **L1–L5**: ghi nhận, không blocking.

---

## 5. Kết quả kiểm thử sau sửa

Môi trường không có Docker trên máy review → chạy pytest trực tiếp bằng `uv` với CPython 3.11.18 (cùng phiên bản ghi trong `TEST_REPORT.md`), cài `requirements.txt` + `requirements-dev.txt`.

```
PYTHONPATH="services/analysis;backend" python -m pytest services/analysis/tests -q
70 passed in 16.23s
```

- Trước sửa: **70/70 PASSED** (baseline)
- Sau sửa: **70/70 PASSED** — không hồi quy.
- Lưu ý: `bash services/analysis/tests/run.sh` (Docker) không chạy được trên máy này do thiếu Docker; cần chạy lại trên môi trường có Docker trước khi merge nếu muốn xác nhận image build (`requirements.txt` mới sẽ được cài trong Dockerfile).

---

## 6. Danh sách file đã thay đổi

| File | Thay đổi |
|------|----------|
| `services/analysis/requirements.txt` | +`numpy~=2.4.0` |
| `services/analysis/requirements-dev.txt` | +`scipy~=1.17.0`, −`pytest-mock` |
| `services/analysis/writer.py` | Refactor chống lặp (368 → 221 dòng), giữ nguyên hành vi |
| `services/analysis/seasonal.py` | Gộp block lặp, xóa hằng thừa (90 → 70 dòng) |
| `services/analysis/quality.py` | Guard kiểm tra đủ cột `ts/metric/value` |
| `services/analysis/CODE_REVIEW.md` | Báo cáo này (mới) |

Không thay đổi schema DB, không đụng module service khác, không đổi API/hành vi Gold.

---

## 7. Kết luận

**APPROVED**

Lõi thuật toán (Resampling, Histogram, Trend, Seasonal, Correlation, Quality/Anomaly) chính xác, được test bao phủ tốt cả biên và ca suy biến; tầng ghi Gold đúng chuẩn transaction/parameterized SQL/idempotent. Không còn lỗi CRITICAL/HIGH. Các MEDIUM còn lại là vấn đề maintainability/design (dead code, ngưỡng quality, race nhỏ) đã được ghi nhận để owner quyết định — không block merge.
