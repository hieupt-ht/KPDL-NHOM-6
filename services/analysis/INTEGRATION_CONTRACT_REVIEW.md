# INTEGRATION CONTRACT REVIEW — Module Data Analysis

- **Repository:** `hieupt-ht/KPDL-NHOM-6`
- **Branch:** `feature/data-analysis`
- **Ngày review:** 2026-11-19
- **Phạm vi:** `services/analysis/` (được sửa), `services/api/`, `backend/common/`, `frontend/`, `services/clustering/`, `services/prediction/`, `db/mart/init/01-schema.sql`, `docs/api-contract.md`, `docs/backend-integration-handoff.md`, `docs/frontend-live-integration.md`, `docs/ml-contract-review.md` (chỉ đọc).

**Lưu ý trung thực:** tài liệu này ghi nhận contract **đã đối chiếu với mã nguồn hiện tại**, không phải xác nhận các thành viên đã thống nhất. Các điểm đánh dấu "chờ xác nhận" vẫn là đề xuất.

---

## 1. Database Contract

### Bảng Analysis được phép ghi — KHỚP

`writer.py` chỉ ghi đúng 6 bảng được phép; test `test_writer.py` assert không có `gold.service_runs` trong mọi câu SQL:

| Bảng | Cột writer ghi | Schema (`db/mart/init/01-schema.sql`) | Khớp |
|---|---|---|---|
| `gold.timeseries_resampled` | `granularity, ts, metric, mean, min, max` | `VARCHAR(8), TIMESTAMPTZ, VARCHAR(32), DOUBLE PRECISION ×3`, PK `(granularity, ts, metric)` | ✅ |
| `gold.histogram` | `metric, bin_start, bin_end, count` | `VARCHAR(32), DOUBLE PRECISION ×2, BIGINT`, PK `(metric, bin_start, bin_end)` | ✅ |
| `gold.trend` | `granularity, ts, metric, trend_value` | `VARCHAR(8), TIMESTAMPTZ, VARCHAR(32), DOUBLE PRECISION`, PK `(granularity, ts, metric)` | ✅ |
| `gold.seasonal` | `period_type, bucket, metric, value` | `VARCHAR(16), INT, VARCHAR(32), DOUBLE PRECISION`, PK `(period_type, bucket, metric)` | ✅ |
| `gold.correlation` | `var_x, var_y, coef, computed_at(now())` | `VARCHAR(32) ×2, DOUBLE PRECISION, TIMESTAMPTZ`, PK `(var_x, var_y)` | ✅ |
| `gold.data_freshness` | `id=1, latest_silver_ts, computed_at(now())` | `SMALLINT PK CHECK(id=1), TIMESTAMPTZ ×2` | ✅ |

### Giá trị domain ghi vào — KHỚP

- `granularity`: `day|week|month` (timeseries), `week|month` (trend) ⊂ `VARCHAR(8)` và ⊂ `Granularity`/`Literal["month","week"]` của API.
- `period_type`: `hour_of_day|day_of_week|month` ⊂ `VARCHAR(16)` và ⊂ `PeriodType` của API.
- `metric`/`var_x`/`var_y`: 5 tên metric ⊂ `VARCHAR(32)` và ⊂ `Metric` Literal của API.
- `bucket`: `hour 0–23`, `dow 0–6` (T2=0), `month 1–12` ⊂ `INT`.
- `ts`: bucket start giờ VN dạng tz-aware → TIMESTAMPTZ lưu đúng instant (VD: thứ Hai 00:00+07 = CN 17:00Z).
- `coef`: correlation emit **cả hai chiều** `(x,y)` và `(y,x)` + đường chéo → ma trận đối xứng đầy đủ, PK không trùng.
- Không ghi NaN/Inf: `_validate_finite_values` trong `writer.py` từ chối giá trị không hữu hạn trước DELETE/INSERT (Task 05).

### Write boundary — KHỚP

- Analysis chỉ mở `get_mart_conn()`; không đọc/ghi `silver`/`bronze`, không chạm `gold.cluster_results`, `gold.forecast_*`, `gold.service_runs` (journal do `common.runner` sở hữu).
- Idempotency: DELETE+INSERT replace theo bảng trong 1 transaction; records rỗng → giữ snapshot cũ, không xóa kết quả thuật toán khác.

---

## 2. API Contract

Đối chiếu `services/api/routers/{timeseries,analysis,status,ml}.py` + `schemas.py` + `docs/api-contract.md`:

| Endpoint | Phân tích đọc | Analysis ghi | Đánh giá |
|---|---|---|---|
| `GET /api/timeseries` | `timeseries_resampled`, `granularity`+`metric` bắt buộc, `start/end` tùy chọn, phân trang `limit/offset`, sort `ts ASC` | `day/week/month` × 5 metric | ✅ khớp |
| `GET /api/histogram` | `histogram`, `metric` bắt buộc, snapshot (422 nếu có start/end), sort `bin_start,bin_end` | **chỉ 3/5 metric** (`http_traffic`, `l7_attack`, `bot_share`) | ⚠️ XEM MỤC 3 |
| `GET /api/trend` | `trend`, `granularity=week/month` + `metric`, `start/end` tùy chọn trên `ts`, sort `ts ASC` | `week/month` | ✅ khớp (Analysis không ghi `day`) |
| `GET /api/seasonal` | `seasonal`, `period_type`+`metric`, snapshot, sort `bucket ASC` | 3 period_type, chỉ bucket có quan sát | ✅ khớp |
| `GET /api/correlation` | `correlation`, snapshot, sort `var_x/var_y`, trả `computed_at` | cặp đối xứng + đường chéo | ✅ khớp |
| `GET /api/status` | `service_runs` (mới nhất/service) + `data_freshness` | `run_all` trả `success/partial/failed/skipped`; freshness chỉ upsert khi ≥1 bảng ghi mới | ✅ khớp |

### Các quy tắc chung — KHỚP

- **Timestamp format:** API trả TIMESTAMPTZ → ISO UTC; bucket ts là instant của mốc đầu bucket giờ VN → frontend convert `Asia/Ho_Chi_Minh` hiển thị đúng. `apiDateRange` frontend gửi bound `+07:00` → `[start,end)` theo ngày VN, khớp bucket VN của Analysis.
- **Null handling:** `Number` validator đổi NaN/Inf → `null`; cột DB nullable → `null`. Analysis không ghi NaN (writer guard) và không bịa 0.
- **Empty → 404** `{"detail":"No Gold data matches the requested filters"}` — đúng thiết kế demo (bước 5), không phải lỗi.
- **Snapshot 422:** histogram/seasonal/correlation/status từ chối `start/end` — frontend `api.ts` đã không gửi (đã kiểm tra `getHistogram/getSeasonal/getCorrelation` chỉ truyền metric/period_type).
- **Sorting:** API `ORDER BY` lại độc lập output writer → không phụ thuộc thứ tự insert.

---

## 3. Frontend Contract

Đối chiếu `frontend/lib/api.ts`, `lib/api-core.ts`, `lib/date-utils.ts`, `app/analysis/page.tsx`, `app/page.tsx`, `components/filters/DashboardFilters.tsx`, `types/api.ts`:

### Tương thích

- Metric selector (`DashboardFilters`) = đủ 5 metric khớp `Metric` Literal API và `ALL_METRICS` của Analysis reader.
- Granularity `day/week/month` → timeseries; trend map `month→month`, còn lại `week` → khớp output Analysis.
- `day_of_week` label `["T2".."CN"][bucket]` với bucket 0=T2 — khớp `dt.dayofweek` của Analysis.
- Correlation heatmap 5×5 cố định, lọc `coef !== null`, nhận cả 2 chiều → ma trận đối xứng đúng.
- Scatter (HTTP × Bot) join bằng `vietnamDay(ts)` + `cluster_results.date` — cùng quy ước ngày VN, không ghép theo vị trí mảng.
- Empty/404 → `ApiError` message "Data Mart chưa có dữ liệu" → `DataState` hiển thị lỗi/empty nhất quán.

### Điểm KHÔNG tương thích

| # | File / dòng | Vấn đề | Phân loại |
|---|---|---|---|
| F1 | `frontend/app/analysis/page.tsx:47-55` | **Trend chart misalignment:** `xAxis.data` lấy từ `trend.data` (đã trim NaN 2 đầu → ít điểm hơn), nhưng series "Trung bình" lấy `trendMean.data` (timeseries đầy đủ) và ECharts gán theo **vị trí index**, không theo `ts`. Với week period=4, trend mất ~2 điểm mỗi đầu → đường "Trung bình" bị **dịch trái ~2 bucket** so với trục thời gian thật. | Lỗi Frontend — bàn giao Vũ |
| F2 | `services/analysis/histogram.py:11` ↔ `frontend` metric selector + API `Metric` enum | Analysis chỉ ghi histogram cho 3/5 metric; user chọn `human_share`/`netflows` → Gold trống → API 404 → panel "Phân phối giá trị" báo lỗi trong khi demo mode vẫn hiển thị. | **Chờ nhóm thống nhất** — không tự mở rộng metric (đúng yêu cầu task) |
| F3 | `frontend/lib/demo-data.ts:56-61` vs live | Demo seasonal luôn trả đủ 24/7/12 bucket; live chỉ trả bucket có quan sát → biểu đồ mùa vụ live thưa hơn demo, đường nối qua các bucket thiếu. Không sai dữ liệu nhưng khác trải nghiệm demo/live. | Ghi nhận — quyết định UX của Frontend |

**Đề xuất cho Frontend (F1):** build `xAxis` từ union các `ts` của trend+timeseries (hoặc join `trendMean` theo `ts`), không map series theo index. F2 cần quyết định: hoặc Analysis mở rộng `HISTOGRAM_METRICS`, hoặc Frontend giới hạn metric histogram / hiển thị "chưa hỗ trợ" thay vì 404-error.

---

## 4. ML Contract

Analysis **không ghi** `gold.cluster_results`, `gold.forecast_continuous`, `gold.forecast_discrete` — đúng boundary (clustering/prediction trên branch này là stub `NotImplementedError`; code thật ở `feature/machine-learning`/PR #12).

### Điểm đối chiếu

- **Metric đầu vào:** Analysis cung cấp đủ 5 metric ở mọi granularity; việc chọn metric cho ML thuộc Prediction (`features.py` hiện `DEFAULT_METRIC="http_traffic"`). `ml-contract-review.md` đã ghi: README mô tả regression `http_traffic` + classification `l7_attack` ngưỡng p75, còn PR #12 dùng `http_traffic` cho cả hai → **chưa thống nhất, Analysis không can thiệp**.
- **Timezone/ngày:** Analysis bucket `day/week/month` theo **Asia/Ho_Chi_Minh**. `prediction/features.py` trên branch này gộp ngày bằng `ts.dt.floor("D")` trên UTC → lệch 7h so với ngày VN; `target_date`/API dùng ngày VN. Đây là mismatch **đã được `ml-contract-review.md` mục 1 ghi nhận** (kèm horizon "ngày mai VN" vs "ngày sau ngày đầy đủ UTC") → **chờ nhóm chốt**, không phải lỗi Analysis sửa.
- **Threshold:** P75/P90, cutoff xác suất — chưa có quyết định issue; Analysis không đặt và không được tự đặt.
- **Trách nhiệm:** Analysis = Silver → 5 bảng thống kê; Clustering = `cluster_results`; Prediction = 2 bảng forecast; `common.runner` = `service_runs`. Phân chia rõ, không chồng lấn.

---

## 5. Anomaly Contract

- **Analysis hiện tạo anomaly ở đâu:** `quality.py:evaluate_data_quality` trả `anomaly_samples` (Robust Z + IQR, phân loại `TRAFFIC_ANOMALY_CANDIDATE`/`STATISTICAL_OUTLIER`) và `issues_detected`. `tasks.run_all` chỉ **log** chúng — **không persist vào Gold, không có API, Frontend không consume**.
- **Frontend đang hiển thị "bất thường" từ đâu:** `cluster_results.cluster_name === "Bất thường"` (timeline ở `app/page.tsx:47,108-112`) — nguồn là **Clustering**, không phải anomaly detection của Analysis.
- **Kết luận:** output anomaly của Analysis hiện là write-only-to-logs; chưa có contract tiêu thụ.
- **Đề xuất (chờ nhóm phê duyệt, KHÔNG tự thêm):** nếu muốn hiển thị anomaly của Analysis, cần contract riêng — ví dụ bảng `gold.anomalies(ts, metric, value, category, detection_method)` do Analysis ghi + endpoint `/api/anomalies`, hoặc mở rộng `data_freshness`/status. Cần chốt schema, retention và ai sở hữu trước khi implement.

---

## 6. Điểm tương thích (đã xác minh bằng code + test)

1. Schema Gold: tên bảng/cột/kiểu/PK/giá trị domain khớp 100% giữa writer ↔ `01-schema.sql` ↔ API SELECT/response_model ↔ frontend types.
2. Timestamp: UTC instant lưu trữ, VN-local bucket boundary, frontend convert `Asia/Ho_Chi_Minh` — nhất quán xuyên Analysis → Gold → API → UI.
3. Metric names, granularity, period_type, bucket ranges khớp ở cả 4 tầng.
4. Empty → 404; null/non-finite → `null`; snapshot không nhận start/end; sorting do API quyết định.
5. Write boundary: Analysis không ghi bảng service khác, không ghi `service_runs`, không sửa Silver.
6. Freshness + `service_runs.status` biểu diễn được `success/partial/failed/skipped` qua `/api/status` hiện có.

## 7. Điểm không tương thích

1. **F1 — Trend chart misalignment (Frontend, `app/analysis/page.tsx:47-55`)**: series mean map theo index thay vì `ts` → đường "Trung bình" lệch ~2 bucket so với đường "Xu hướng". Cần Vũ sửa.
2. **F2 — Histogram chỉ 3/5 metric**: selector frontend + API enum cho phép 5 → 404 cho `human_share`/`netflows`. Cần nhóm quyết định mở rộng `HISTOGRAM_METRICS` hay giới hạn UI.
3. **ML timezone/horizon** (đã ghi ở `ml-contract-review.md`): features ML nhóm ngày UTC vs ngày VN của Analysis/API — chờ Hoàng/nhóm chốt.
4. **Per-table freshness** (ghi nhận từ Task 05): freshness là per-pipeline; bảng có kết quả rỗng giữ snapshot cũ trong khi freshness báo data mới. `gold.correlation.computed_at` là timestamp per-table duy nhất. Nếu cần độ tươi từng bảng → phải đổi schema → quyết định Backend.

## 8. Lỗi thuộc Analysis cần sửa

**Không có lỗi chặn contract nào thuộc Analysis.** Các vấn đề còn lại đều là quyết định nhóm (F2 metric histogram, per-table freshness, anomaly contract) hoặc thuộc module khác (F1 frontend, ML timezone).

## 9. Lỗi thuộc module khác cần bàn giao

| # | Module | File | Vấn đề | Đề xuất |
|---|---|---|---|---|
| F1 | Frontend (Vũ) | `app/analysis/page.tsx:47-55` | Trend "Trung bình" lệch trục thời gian do join theo index | Join series theo `ts`/union categories |
| F2 | Analysis↔FE↔API | `histogram.py:11`, metric selector | Histogram thiếu `human_share`, `netflows` | Nhóm chốt: mở rộng metric hoặc FE hiển thị unsupported |
| — | ML (Hoàng) | `prediction/features.py:32`, `docs/ml-contract-review.md` | Day grouping UTC vs VN; metric/threshold chưa chốt | Theo dõi issue #5/#13, không sửa từ phía Analysis |
| — | Backend (Định) | `db/mart/init/01-schema.sql` | Không có per-table freshness cho 4/5 bảng kết quả | Cân nhắc `computed_at`/`source_latest_ts` nếu cần phân biệt snapshot cũ/mới |

## 10. Quyết định còn chờ nhóm xác nhận

1. Histogram có mở rộng sang `human_share`/`netflows` không (ảnh hưởng Gold + API enum đã sẵn + FE).
2. ML: metric mục tiêu, ngưỡng p75/p90, cutoff xác suất, timezone/horizon ngày (issue #5/#13).
3. Anomaly của Analysis có cần persist/API/UI không → contract riêng.
4. Per-table freshness trong Gold schema (nếu Backend thấy cần).
5. Cluster naming/features mapping giữa nhánh ML và UI (`Cao điểm`/`Bất thường`, `http_mean`/`l7_max`/`bot_mean` vs `value`/`dev_7`) — đã ghi trong `ml-contract-review.md` mục 5.
