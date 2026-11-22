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
| `GET /api/status` | `service_runs` (mới nhất/service) + `data_freshness` | `run_all` trả `success/partial/failed/skipped`; freshness chỉ upsert khi **cả 5 nhóm** có kết quả mới (Prompt 3 — phương án A) | ✅ khớp |

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
4. **Per-table freshness — ĐÃ XỬ LÝ theo phương án A (Prompt 3):** `data_freshness` chỉ cập nhật khi cả 5 nhóm kết quả đều có dữ liệu mới trong chu kỳ (freshness = mốc Silver của lần ghi "đủ" gần nhất). Khi một nhóm rỗng: các nhóm khác vẫn ghi, bảng rỗng giữ snapshot cũ, freshness giữ nguyên, `run_all` trả `partial`. Phương án B (freshness theo bảng) vẫn là đề xuất cần Backend duyệt — xem §12.

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

---

## 11. Prompt 3 — Pipeline, Gold Writer & Freshness (cập nhật 2026-11-20)

### 11.1 Luồng dữ liệu thực tế (đã đối chiếu code)

```
silver.metrics_hourly (warehouse-db)
  └─ reader.fetch_silver_metrics()          # ĐỌC 1 LẦN / chu kỳ, lọc source='radar'
       └─ quality.evaluate_data_quality()   # Gate + anomaly (QualityReport)
            └─ run_all(): cùng 1 DataFrame snapshot cho cả 5 thuật toán
                 ├─ compute_resampling_records   (day/week/month, giờ VN)
                 ├─ compute_histogram_records    (3 metric: http_traffic, l7_attack, bot_share)
                 ├─ compute_trend_records        (week/month, seasonal_decompose)
                 ├─ compute_temporal_pattern_records (hour_of_day/day_of_week/month → gold.seasonal)
                 ├─ compute_correlation_records  (Pearson 5×5, cặp đối xứng)
                 └─ assess_temporal_cycle_completeness() → CHỈ LOG (phương án a)
            └─ write_all_analysis_results()   # 1 transaction: DELETE+INSERT 5 bảng
                 └─ _upsert_freshness()        # CHỈ khi cả 5 nhóm đều có kết quả mới
  └─ gold.* (mart-db) → api (api_user, SELECT-only) → frontend
```

- `latest_silver_ts` = `df["ts"].max()` của snapshot thực tế (không phải `now()`), timestamp hợp lệ, tz-aware UTC.
- `run_all` trả `success`/`partial`/`failed` khớp `backend/common/runner.py`; exception DB/đọc Silver → log + `failed`, không ghi Gold.
- **Entry point duy nhất:** `run_all`. Các hàm `compute_resampled/compute_histogram/compute_trend/compute_temporal_patterns/compute_correlation` và `write_resampled/write_histogram/write_trend/write_temporal_patterns/write_correlation/write_freshness` đơn lẻ đã bị **xóa** (không còn production caller — `git grep` xác nhận chỉ tests dùng). Không còn hai đường chạy bypass gate/snapshot/freshness. `compute_*_records` ở module thuật toán vẫn giữ — đó là hàm tính thuần, chỉ `run_all` gọi trong production.

### 11.2 Gold Writer & Data Freshness

**Kiểm tra writer (bằng code + test):**

| Hạng mục | Kết quả | Bằng chứng |
|---|---|---|
| Đúng bảng/cột/kiểu | ✅ | `writer.py` table_specs ↔ `db/mart/init/01-schema.sql` (bảng ở §1) |
| Timestamp/metric | ✅ | `ts` bucket start giờ VN tz-aware → TIMESTAMPTZ; metric ∈ 5 tên contract |
| Một transaction | ✅ | `_execute_in_transaction` bọc toàn bộ DELETE+INSERT trong `c.transaction()` |
| Rollback khi lỗi | ✅ (unit) | exception giữa chừng → transaction abort; test `test_writer.py` assert không partial write |
| Idempotency | ✅ (unit + E2E) | DELETE+INSERT replace toàn bảng; chạy lại cho cùng kết quả, không trùng dòng (PK bảo đảm) |
| Không xóa ngoài phạm vi | ✅ | writer chỉ DELETE đúng 5 bảng gold kết quả; không đụng `service_runs`, `cluster_results`, `forecast_*`, silver |
| Kết quả rỗng | ✅ | `_replace_gold_table` bỏ qua bảng rỗng → giữ snapshot cũ |

**Freshness — vấn đề N1/H1 đã xử lý bằng PHƯƠNG ÁN A (đã triển khai):**

- Trước: `_upsert_freshness` chạy khi **≥1** nhóm có kết quả → consumer tưởng mọi bảng mới trong khi bảng rỗng giữ data cũ.
- Sau: `_upsert_freshness` chỉ chạy khi **cả 5 nhóm** (`timeseries_resampled`, `histogram`, `trend`, `seasonal`, `correlation`) đều có records mới trong chu kỳ. Một nhóm rỗng → các nhóm khác vẫn ghi, bảng rỗng giữ cũ, freshness giữ nguyên, `run_all` trả `partial`, log liệt kê bảng giữ data cũ.
- Ngữ nghĩa mới: **freshness = `latest_silver_ts` của lần ghi "đủ" gần nhất** (5/5 nhóm). Đây là thay đổi hành vi trong `services/analysis/` — không đổi schema/API/JSON.
- Lưu ý hệ quả: nếu histogram vĩnh viễn chỉ có 3/5 metric nhưng vẫn sinh records (metric được hỗ trợ có data), nhóm histogram vẫn "fresh"; chỉ khi TOÀN BỘ histogram rỗng mới chặn freshness.

**So sánh A vs B:**

| | A — đã triển khai | B — đề xuất, chờ duyệt |
|---|---|---|
| Cách | Freshness đơn = mốc Silver lần đủ 5/5 gần nhất | Thêm `table_name`/`computed_at` per-table (hoặc nhiều dòng freshness) |
| Schema | Không đổi | Đổi `db/mart/init/01-schema.sql` + migration cho volume hiện có |
| API | Không đổi (`/api/status` đọc 1 dòng) | Đổi `services/api/routers/status.py`, `schemas.py`, response shape → breaking hoặc mở rộng |
| Frontend | Không đổi | Đổi `frontend/` để hiển thị freshness per-table |
| Thông tin mất | Không biết bảng nào stale khi partial | Biết chính xác độ tươi từng bảng |
| Rủi ro | Consumer chỉ thấy "freshness = lần đủ gần nhất", phải suy ra bảng stale từ `run status=partial` | Migration + phối hợp 3 module |

**Đề xuất:** giữ A cho hiện tại (đủ chặn false-freshness); cân nhắc B ở Prompt 4+ nếu vận hành cần per-table freshness. File ảnh hưởng nếu làm B: `db/mart/init/01-schema.sql`, `services/api/routers/status.py`, `services/api/schemas.py`, `frontend/` (status UI), migration script cho DB đã init.

### 11.3 Bảng đối chiếu hợp đồng Analysis Output ↔ Gold ↔ API ↔ Frontend

| Analysis Output | Gold Schema | API Schema | Frontend Usage | Status | Bằng chứng |
|---|---|---|---|---|---|
| Resampling `day/week/month` | `timeseries_resampled(granularity,ts,metric,mean,min,max)` PK `(granularity,ts,metric)` | `GET /api/timeseries`: granularity+metric bắt buộc, start/end tùy chọn, `limit/offset`, sort `ts ASC` | `getTimeseries` → line chart mean/min/max; granularity selector day/week/month | ✅ Tương thích | `resampling.py`, `writer.py`, `routers/timeseries.py`, `lib/api.ts` |
| Histogram | `histogram(metric,bin_start,bin_end,count)` — **chỉ 3 metric**: `http_traffic`, `l7_attack`, `bot_share` | `GET /api/histogram`: metric bắt buộc, snapshot (422 nếu start/end) | Selector 5 metric → `human_share`/`netflows` → API 404 → empty-state "chưa có dữ liệu" (đã kiểm `page.tsx`) | ⚠️ Cần nhóm duyệt (F2) | `histogram.py:HISTOGRAM_METRICS`, E2E assert 404 cho 2 metric |
| Trend `week/month` | `trend(granularity,ts,metric,trend_value)` | `GET /api/trend`: granularity `week/month` + metric | Trend chart; granularity map `month→month`, còn lại `week`; không data → empty state | ✅ Tương thích (F1 misalignment là lỗi FE riêng, không phải contract) | `trend.py`, `routers/analysis.py`, `page.tsx` |
| Temporal pattern → `gold.seasonal` | `seasonal(period_type,bucket,metric,value)`; month bucket **1..12**, dow **0..6** (T2=0) | `GET /api/seasonal`: period_type+metric, snapshot, sort bucket ASC; `SeasonalPoint` | Label month `T${bucket}` → T1..T12 khớp 1..12; dow `["T2".."CN"][bucket]` khớp 0..6 | ✅ Tương thích | `temporal_patterns.py`, `page.tsx` label code |
| Correlation 5×5 | `correlation(var_x,var_y,coef,computed_at)` — cặp đối xứng + đường chéo | `GET /api/correlation`: snapshot, trả cả `computed_at` | Heatmap 5×5 lọc `coef !== null`, cặp thiếu → ô trống (không hiển thị sai) | ✅ Tương thích | `correlation.py`, FE heatmap filter null |
| Freshness/status | `data_freshness(id=1,latest_silver_ts,computed_at)` | `GET /api/status`: `data_freshness` + `service_runs` mới nhất/service | Hiển thị "last updated" từ `data_freshness.latest_silver_ts` + run status | ✅ Tương thích (sau A: freshness = lần đủ 5/5) | `writer._upsert_freshness`, `routers/status.py` |
| Đơn vị & timezone | `*_share` = % (0..100); metric khác = chỉ số chuẩn hóa (có thể >1 do rescale ingestion) | Trả nguyên giá trị, không đổi đơn vị | Hiển thị raw + format; trục thời gian convert `Asia/Ho_Chi_Minh` | ✅ Tương thích — ghi nhận đơn vị trong docs | `reader.py`, ingestion `rescale.py`, `date-utils.ts` |

### 11.4 Vấn đề đã sửa (Prompt 3)

| # | Vấn đề | Xử lý | File |
|---|---|---|---|
| N1/H1 | Freshness cập nhật khi partial write | **Phương án A**: chỉ upsert khi 5/5 nhóm có kết quả; partial → giữ freshness cũ + log bảng giữ data cũ | `writer.py` |
| M4/N7 | `compute_*`/`write_*` đơn lẻ bypass gate/snapshot/freshness | Xóa toàn bộ (không production caller); `run_all` là entry point duy nhất | `tasks.py`, `writer.py`, tests |
| — | Log thiếu nhóm bị skip | `run_all` đã log lý do skip theo `algorithm_fitness` (Prompt 2A); writer log bảng giữ data cũ | `tasks.py`, `writer.py` |

### 11.5 Vấn đề cần phối hợp (kèm người liên quan)

| # | Vấn đề | Owner | Trạng thái |
|---|---|---|---|
| F2 | Histogram 3/5 metric vs selector 5 metric → 404 (FE đã có empty-state) | Nhóm + Frontend (Vũ) + API | Chờ quyết định: mở rộng `HISTOGRAM_METRICS` hay giới hạn UI |
| F1 | Trend chart "Trung bình" join theo index → lệch ~2 bucket | Frontend (Vũ) | Bàn giao — không phải lỗi Analysis |
| B-fresh | Per-table freshness (phương án B) | Backend (Định) + nhóm | Đề xuất — chờ duyệt, chưa implement |
| Anomaly | `anomaly_samples` chỉ trong `QualityReport` + log, không persist/API | Nhóm | Đề xuất contract riêng nếu muốn hiển thị — chưa implement |
| ML | timezone/horizon, metric, threshold | Hoàng/nhóm | Theo dõi issue #5/#13 |

### 11.6 Anomaly semantics (ghi nhận)

- `quality.py` phân loại `STATISTICAL_OUTLIER` (Robust Z/IQR thuần thống kê) vs `TRAFFIC_ANOMALY_CANDIDATE` (nghi vấn traffic bất thường — **không phải** tấn công đã xác nhận). Không đổi ngữ nghĩa, không dùng từ "tấn công đã xác nhận".
- Kết quả anomaly hiện **chỉ nằm trong `QualityReport` và log** của `run_all` — không bảng Gold, không endpoint, Frontend không consume (đã grep: không có `anomal` nào trong `db/mart`, `services/api`, `frontend`).
- Nhãn "Bất thường" trên dashboard đến từ **Clustering** (`cluster_name == "Bất thường"` trong `gold.cluster_results`) — **nguồn khác nghĩa**, không được dùng chung nhãn với anomaly thống kê của Analysis.
- Đề xuất (chờ nhóm): nếu muốn hiển thị, cần contract riêng (bảng `gold.anomalies` + endpoint) — không tự thêm.

### 11.7 Test đã chạy — kết quả thực tế

| Suite | Lệnh | Kết quả | Dữ liệu |
|---|---|---|---|
| Analysis unit | `bash services/analysis/tests/run.sh` | **111 passed / 0 failed** (7.91s, Docker py3.11) | DataFrame tổng hợp + MagicMock conn; KHÔNG phải Postgres thật |
| API E2E All-mode | `bash services/api/tests/run.sh all` | **88 passed, 2 skipped** (32.98s tests; stack thật: mart-db + warehouse-db Postgres 16 + Keycloak + analysis/api services) | Postgres `test_*` thật + Silver **tổng hợp** (không phải Radar thật); gồm `test_analysis_pipeline_e2e` chạy Analysis service thật → ghi Gold → đọc lại qua API có auth |

Test mới Prompt 3:
- `test_freshness_updated_only_when_all_five_groups_present`: cả 5 nhóm → freshness upsert 1 lần; chỉ 1 nhóm → **không** upsert, bảng rỗng không bị DELETE (giữ snapshot cũ).
- `test_run_all_is_single_entry_point`: assert không còn `compute_*` đơn lẻ.
- `test_write_all_partial_run_returns_partial_status`: 30h data → trend rỗng → `run_all` trả `partial`, `trend_records=[]`, `latest_silver_ts` = max ts thật.
- Rollback: `test_writer.py` assert transaction bao toàn bộ; exception → không partial write (MagicMock transaction).

**Chưa kiểm thử được / giới hạn:**
- Idempotency "chạy 2 lần trên Postgres thật": E2E All-mode đã verify ghi→đọc lại đúng trên Postgres thật (88 passed), nhưng **chưa có test chạy run_all 2 lần liên tiếp** đếm duplicate trên DB thật — DELETE+INSERT replace + PK unique làm trùng lặp không thể xảy ra về mặt cấu trúc, vẫn ghi là "cover gián tiếp".
- Rollback trên Postgres thật: chưa kiểm thử (unit test dùng MagicMock transaction); rollback path là `c.transaction()` chuẩn psycopg — rủi ro thấp nhưng chưa có bằng chứng DB thật.

### 11.8 Rủi ro còn lại trước Prompt 4

1. Freshness A là "all-or-fresh" ở mức pipeline: một nhóm rỗng kéo freshness về lần đủ gần nhất — nếu histogram mãi chỉ partial metric, freshness vẫn cập nhật (vì nhóm histogram vẫn có records). Chấp nhận được, ghi rõ ngữ nghĩa.
2. `preview_analysis.py` (untracked, có sẵn từ trước) chưa review — cần quyết định giữ/xóa ở Prompt 4.
3. Nhiều báo cáo cũ (`TEST_REPORT.md`, `FINAL_REVIEW.md`, `REAL_DATA_VALIDATION.md`…) trùng/lỗi thời — Prompt 4 gộp/xóa.
4. F2 histogram metric vẫn treo chờ nhóm — ảnh hưởng UX 404→empty-state.
5. Per-table freshness (B) và anomaly persist là quyết định kiến trúc chưa chốt.
