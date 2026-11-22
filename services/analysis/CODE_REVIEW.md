# CODE REVIEW – MODULE DATA ANALYSIS (AUDIT READ-ONLY)

- **Repository:** `hieupt-ht/KPDL-NHOM-6`
- **Branch audit:** `feature/data-analysis` @ `a329820` (đã là ancestor của `origin/develop` — toàn bộ thay đổi Analysis gồm PR #15, #16 đã merge)
- **Phạm vi:** `services/analysis/` + đối chiếu `db/*/init`, `services/api/`, `frontend/`, `services/ingestion|clustering|prediction`, `backend/common/`, `docker-compose.yml`
- **Reviewer:** Senior Data Engineer / Python Developer / Code Reviewer (Devin)
- **Ngày:** 2026-11-22
- **Báo cáo này ghi đè nội dung cũ của file** (bản 2026-11-18 đã lỗi thời: ghi 70 test, mô tả `main.py` override `/run` đã bị gỡ, `MIN_OBSERVATIONS=2` nay là 3).

---

## 1. Kiến trúc và luồng dữ liệu thực tế

```
Cloudflare Radar ──> ingestion ──> warehouse-db
                                    silver.metrics_hourly (ts, metric, value, source='radar', PK(ts,metric))
                                          │  fetch_silver_metrics() — 1 snapshot / chu kỳ
                                          ▼
                              analysis (main.py → common.runner)
                                ├─ quality.evaluate_data_quality()   → QualityReport (chỉ log, không persist)
                                ├─ resampling.compute_resampling_records()  → day/week/month mean,min,max (giờ VN)
                                ├─ histogram.compute_histogram_records()    → 20 bins × 3 metric
                                ├─ trend.compute_trend_records()            → seasonal_decompose month≥24 else week≥8
                                ├─ temporal_patterns.compute_temporal_pattern_records() → trung bình bucket giờ/thứ/tháng (giờ VN)
                                └─ correlation.compute_correlation_records()→ Pearson 5×5 pairwise
                                          │  write_all_analysis_results() — 1 transaction
                                          ▼
                              mart-db gold.* (5 bảng kết quả + data_freshness)
                                          │  api_user SELECT-only
                                          ▼
                              services/api (/api/timeseries|histogram|trend|seasonal|correlation|status)
                                          │  JWT (AUTH_ENABLED) + NextAuth frontend
                                          ▼
                              frontend dashboard (demo | api mode)
```

`POST /run` (202 + `run_id`, `X-Job-Token`, local lock + PG advisory lock) → `gold.service_runs`; scheduler APScheduler theo `ANALYSIS_INTERVAL_SECONDS` (mặc định 300s). `run_all` trả `"success" | "partial" | "failed" | "skipped"` — runner map thẳng vào `service_runs.status`.

## 2. Trách nhiệm từng file/hàm chính

| File | Vai trò | Ghi chú |
|---|---|---|
| `main.py` | `create_service_app("analysis", run_all, interval)` | Đúng skeleton chung; `/run` của runner (202/auth/lock/journal) |
| `tasks.py` | `run_all()` điều phối; 5 hàm `compute_*` + import `write_*` đơn lẻ | `compute_*` là dead code production (xem M4) |
| `reader.py` | `fetch_silver_metrics` (toàn bộ silver, source='radar', UTC, float64); `get_latest_silver_ts` | `get_latest_silver_ts` chỉ còn test dùng |
| `quality.py` | `evaluate_data_quality` → `QualityReport`; Robust-Z + IQR outlier; `algorithm_fitness` | Gate chỉ chặn `unusable`; fitness không gate từng thuật toán (M1) |
| `resampling.py` | Bucket day/week(Mon)/month theo `Asia/Ho_Chi_Minh`, mean/min/max | Không nội suy, không bucket giả |
| `histogram.py` | `np.histogram` 20 bins động; equal-value → range đối xứng | `HISTOGRAM_METRICS` = 3/5 metric (H2) |
| `trend.py` | `_prepare_regular_series` (bucket + coverage + continuity) → `seasonal_decompose` additive | Month ưu tiên ≥24, fallback week ≥8 |
| `temporal_patterns.py` | `compute_temporal_pattern_records` (bucket averages) + `assess_temporal_cycle_completeness` | Bucket averages ≠ xác nhận chu kỳ; assess chỉ log vận hành (M5 → 2B) |
| `correlation.py` | Pivot theo ts → pairwise complete Pearson, min 3 obs, zero-variance skip | Emit cả 2 chiều theo PK `(var_x,var_y)` |
| `writer.py` | `_replace_gold_table` (DELETE+INSERT khi có data) + `_validate_finite_values` + freshness upsert | 1 transaction all-or-nothing; empty → giữ snapshot cũ |

## 3. Phần đã đúng (có bằng chứng trong code)

- **Reader:** lọc `source='radar'` mặc định (`COALESCE(source,'radar')`), whitelist 5 metric, `ts` → UTC tz-aware, bỏ NaT, `value` → float64, cảnh báo duplicate `(ts,metric)`; `get_latest_silver_ts` loại NULL/NaN/±Inf đúng trên PG (không dùng `isinf()` — bug đã sửa ở PR #16).
- **Resampling:** bucket theo giờ VN, tuần bắt đầu thứ Hai (`dayofweek`), tháng mùng 1; groupby chỉ tạo bucket có dữ liệu; timestamp trả về tz-aware đúng instant khi ghi TIMESTAMPTZ.
- **Histogram:** đúng 20 bins, `bin_start < bin_end`, assert `Σcount == n_valid` (raise nếu lệch), min==max → dải đối xứng `±max(1,|v|·0.1)` gom hết vào 1 bin; không clip [0,1] (đúng vì metric đã rescale, HTTP thấy ~1.31).
- **Trend:** month cần ≥24 điểm liên tục (2×12), fallback week ≥8 (2×4); cắt 1 bucket biên thiếu mỗi đầu, **reject toàn chuỗi** nếu bucket trong thiếu giờ, kiểm tra liên tục bằng `date_range` — không nội suy; `trend.dropna()` bỏ NaN hai đầu; `seasonal_decompose(model="additive")`.
- **Temporal pattern averages:** dedup `(metric, ts_local)` bằng mean, loại metric < 3 quan sát, chỉ ghi bucket có dữ liệu (giờ 0–23, thứ 0–6 T2=0, tháng 1–12). Là trung bình bucket — không phải kết luận chu kỳ lặp lại.
- **Correlation:** pairwise `dropna()`, `MIN_OBSERVATIONS=3`, zero-variance → skip (không bịa 0), diagonal = 1.0 khi variance > 1e-12, clamp [-1,1].
- **Writer:** parameterized SQL 100%, 1 transaction cho 5 bảng + freshness, `_validate_finite_values` chặn NaN/Inf trước DELETE, empty records → giữ snapshot cũ, all-empty → không ghi không freshness, không ghi `service_runs`/bảng service khác.
- **Tasks/Main:** 1 snapshot Silver cho cả 5 thuật toán (nhất quán), `latest_silver_ts` lấy từ `valid_ts.max()` của **cùng DataFrame** (không còn 2 connection lệch nhau), status map đúng runner (`success/partial/failed/skipped`).
- **Runner contract (đã verify live):** 401 không/sai token, 202+`run_id`, 409 concurrent, `gold.service_runs` success — xem `REAL_DATA_VALIDATION.md` §5 và `docs/analysis-pipeline-validation.md` (run #4 thật, 20/11).

## 4. Bảng phát hiện

| ID | Mức | Thành phần | Bằng chứng | Hệ quả | Đề xuất | Cần ai duyệt |
|---|---|---|---|---|---|---|
| H1 | **High** | `writer.py:246-259` + `gold.data_freshness` | Freshness upsert khi **≥1** bảng có records; bảng rỗng giữ data cũ | `/api/status` báo "dữ liệu mới" dù `gold.trend` (vd) có thể là snapshot cũ nhiều chu kỳ — consumer không phân biệt được bảng nào stale | Chọn 1: (a) chấp nhận ngữ nghĩa last-known-good + ghi docs; (b) thêm `computed_at`/`source_latest_ts` per-table — **đổi schema** | Backend + nhóm (schema) |
| H2 | **High** | `histogram.py:11` vs `schemas.py:9` vs `DashboardFilters.tsx:7` | `HISTOGRAM_METRICS` = 3 metric; API `Metric` + FE selector = 5 | `GET /api/histogram?metric=human_share|netflows` → 404. FE đã guard (`analysis-series.ts:16`, page.tsx:23,75 hiển thị empty-state, không gọi API) nên user không gặp lỗi, nhưng contract API vẫn hở | Nhóm quyết: mở rộng histogram lên 5 metric hay giới hạn `Metric` cho endpoint này trong docs | Nhóm (contract) |
| M1 | Medium → **ĐÃ SỬA (2A)** | `quality.py`, `tasks.py` | `algorithm_fitness` chỉ feed `can_run_any_algo`; `run_all` không gate từng thuật toán | Fitness per-algorithm là thông tin chết một phần | ✅ `run_all` giờ skip compute + log lý do khi `fitness=False` | — |
| M2 | Medium → **ĐÃ SỬA (2A)** | `quality.py` | Gate `is_sufficient`/`sufficient_for_seasonal` = 24 records nhưng algo seasonal chỉ cần 3; `sufficient_for_trend` = 1344h không tương ứng month path; fitness correlation chỉ cần ≥2 metric có variance | Ngưỡng Gate ≠ ngưỡng thuật toán | ✅ seasonal gate = `MIN_SEASONAL_OBSERVATIONS` distinct ts; trend gate = `trend_series_feasible()` dùng chung `_prepare_regular_series`; correlation gate = `correlation_feasible()` check pairwise ≥3 + variance | — |
| M3 | Medium → **ĐÃ SỬA (2A)** | `trend.py` | `min_hours_per_bucket`: week=151, month=604 cố định. Tháng 31 ngày = 744h → 604 chỉ ~81% | Bucket tháng dài có thể "đầy đủ" theo ngưỡng nhưng thực thiếu tới ~19% giờ | ✅ `_expected_bucket_hours()`: tuần 168h, tháng = `days_in_month × 24` (672/696/720/744); tỷ lệ `distinct_ts/expected ≥ 0.9`; đếm `nunique(ts)` không đếm dòng | — |
| M4 | Medium | `tasks.py:25-89`, `writer.py:133-214` | `compute_resampled/histogram/trend/seasonal/correlation` + 6 `write_*` đơn lẻ: mỗi hàm `fetch_silver_metrics()` riêng, **bỏ qua quality gate**, không freshness | Dead code production — nếu ai gọi nhầm sẽ ghi Gold từ snapshot khác, không gate, không freshness | Xóa, hoặc đánh dấu "chỉ dùng test/nội bộ" + route qua `run_all` | Analysis owner |
| M5 | Medium → **ĐÃ XỬ LÝ (2B, phương án a)** | `temporal_patterns.py` | `assess_temporal_cycle_completeness` từng chỉ được gọi trong test; kết quả `confirmed` không tới Gold/API/FE | Kết quả xác nhận chu kỳ vô dụng trong production | ✅ Đổi tên + sửa `cycle_count` đếm chu kỳ distinct; `run_all` gọi assess và **ghi log vận hành** (không đổi Gold/API). Expose ra contract vẫn chờ nhóm (Q4) | Nhóm (nếu muốn expose) |
| M6 | Medium | `quality.py:243-280` | `anomaly_samples` cap 5/metric đầu tiên theo thời gian; `QualityReport` chỉ log, không persist/API | Analysis phát hiện outlier nhưng không ai tiêu thụ; UI "Bất thường" lấy từ `cluster_results` (Clustering/ML) — hai khái niệm khác nhau dễ gây nhầm | Đề xuất contract riêng nếu muốn expose (bảng/API mới cần nhóm duyệt); tối thiểu ghi rõ trong docs | Nhóm |
| M7 | Medium | `tasks.py:155-180` | Compute cả 5 thuật toán **trước** write; 1 thuật toán raise → cả run failed, không ghi gì; `is_partial` chỉ check list-level rỗng | Per-metric/per-period thiếu hụt bên trong list non-empty vẫn báo `success`; ngược lại 1 exception mất hết kết quả chu kỳ | Chấp nhận all-or-nothing (an toàn) nhưng cân nhắc per-table isolation nếu Backend muốn partial-write mạnh hơn; log rõ metric nào thiếu | Nhóm/Backend |
| L1 | Low | `services/analysis/preview_analysis.py` | File **0 byte** trong service dir, được COPY vào image | Rác, gây nhầm | Xóa file | Analysis owner |
| L2 | Low | `reader.py:28-76` | `get_latest_silver_ts` không còn caller production (tasks.py lấy từ df) | Dead-ish code, chỉ test dùng | Giữ làm utility có docstring rõ, hoặc gỡ | Analysis owner |
| L3 | Low | `reader.py:105-110` | `fetchall()` toàn bộ `silver.metrics_hourly` mỗi chu kỳ 300s | OK ở ~44k rows (đã verify); sẽ chậm khi silver lớn | Cân nhắc `WHERE ts >= now() - interval` khi cần | Analysis owner |
| L4 | Low | `quality.py:251` | `anom_indices[:5]` = 5 outlier **đầu tiên theo thời gian**, không phải lớn nhất | Mẫu log không đại diện | Sắp xếp theo \|robust_z\| giảm dần trước khi lấy 5 | Analysis owner |
| L5 | Low | Docs | `TEST_REPORT.md`/`README.md` ghi "70 test" (thực tế 100); 5 báo cáo `.md` chồng nhau trong `services/analysis/` + `docs/analysis-pipeline-validation.md` | N10 xác nhận — tài liệu lỗi thời/gây nhiễu | Gộp về `CODE_REVIEW.md` (file này) + `README.md`; Prompt 4 quyết định xóa file nào | Analysis owner |
| L6 | Low | `correlation.py:98-139` | Emit cả `(x,y)` và `(y,x)` → 25 dòng cho 5 biến | Đúng PK schema; FE heatmap dùng `indexOf` không bị ảnh hưởng | Giữ nguyên (contract) | — |

### Kết quả kiểm chứng N1–N11

| # | Nghi vấn | Kết luận |
|---|---|---|
| N1 | freshness cập nhật khi partial | **Xác nhận** → H1 |
| N2 | `run_all` không dùng `algorithm_fitness` | **ĐÃ SỬA (2A)** → M1 |
| N3 | Gate seasonal=24 ≠ algo=3; correlation gate không check pairwise | **ĐÃ SỬA (2A)** → M2 |
| N4 | Trend 151h/604h cố định; tháng 29–31 ngày <90%; đếm theo dòng | **ĐÃ SỬA (2A)** → M3 — nay đếm distinct ts / giờ thực của bucket, ngưỡng 90% |
| N5 | Month bucket: Analysis 1..12, FE `T${bucket+1}`, demo 0..11 | **KHÔNG XÁC NHẬN** — code hiện tại nhất quán: Analysis ghi 1–12, FE label `` `T${p.bucket}` `` → T1–T12 (= tháng 1–12), demo-data `bucket+1` → 1–12. Nghi vấn đã lỗi thời |
| N6 | Histogram 3/5 metric → 404 | **Xác nhận** ở tầng API; FE đã mitigate → H2 |
| N7 | `compute_*` riêng lẻ bypass gate/snapshot/freshness | **Xác nhận** → M4 |
| N8 | `check_seasonal_cycle_completeness` không được pipeline dùng | **ĐÃ XỬ LÝ (2B)** → M5 — nay `run_all` gọi `assess_temporal_cycle_completeness` để log |
| N9 | Anomaly chỉ trong QualityReport, không lưu | **Xác nhận** → M6 |
| N10 | Tài liệu lỗi thời, báo cáo trùng | **Xác nhận** → L5 |
| N11 | Chưa có test PostgreSQL thật (writer mock) | **Đã cải thiện một phần** — `test_writer.py` vẫn mock, nhưng PR #16 thêm `services/api/tests/test_analysis_pipeline_e2e.py` chạy Analysis thật + Postgres thật (DB `test_*` riêng) + Keycloak, và `docs/analysis-pipeline-validation.md` ghi nhận **real Radar E2E ngày 20/11** (43.809 dòng, run #4 success). Residual: không có test Postgres thật *bên trong* `services/analysis/tests/` |

## 5. Vấn đề liên module (Database / API / Frontend / service khác)

| ID | Mức | Module | Vấn đề | Bằng chứng | Đề xuất |
|---|---|---|---|---|---|
| IM1 | High | API↔Analysis | Histogram 3/5 metric (H2) — cần nhóm chốt contract | `analysis.py:24` + `histogram.py:11` | Q2 |
| IM2 | High | DB↔API | Freshness per-pipeline không per-table (H1) | `01-schema.sql:40` + `writer.py` | Q1 |
| IM3 | Medium | Analysis↔Clustering/FE | "Bất thường" trên UI = `cluster_results` (ML); outlier Analysis không expose — hai nguồn khác nghĩa | `quality.py` vs `page.tsx` scatter + `cluster_results` | Q3 |
| IM4 | Medium | Ingestion↔DB | `silver.metrics_hourly` PK `(ts,metric)` **không chứa `source`** → upsert `source='demo'` cùng ts+metric sẽ **ghi đè** dòng radar | `01-schema.sql:15-22` + `silver.py:60-64` | Báo owner ingestion/db; nếu demo chỉ là fixture test thì rủi ro thấp |
| IM5 | Medium | Prediction↔Analysis | `prediction/features.py:32` groupby `ts.dt.floor("D")` = **ngày UTC**, trong khi Analysis/API/FE dùng ngày VN — đã biết trong `docs/ml-contract-review.md` (#13) | `features.py` vs `resampling.py` | Thuộc ML branch, không sửa ở đây |
| IM6 | Info | Clustering/Prediction | `tasks.py` cả hai service là stub `NotImplementedError` trên branch này; code ML thật ở `feature/machine-learning` | `clustering/tasks.py`, `prediction/tasks.py` | Điều phối merge, không phải lỗi Analysis |

## 6. Bảng đổi tên (ĐÃ THỰC HIỆN trong Prompt 2B)

"Seasonal" trước đây thực chất là **trung bình theo bucket thời gian** (hour/dow/month), không phải phân tích mùa vụ chu kỳ. Đã đổi tên nội bộ, **giữ nguyên** `gold.seasonal`, `/api/seasonal`, `SeasonalPoint`, `period_type`, label UI.

| Cũ | Mới | Trạng thái |
|---|---|---|
| `services/analysis/seasonal.py` | `temporal_patterns.py` | ✅ `git mv` (giữ lịch sử) |
| `compute_seasonal_records()` | `compute_temporal_pattern_records()` | ✅ |
| `check_seasonal_cycle_completeness()` | `assess_temporal_cycle_completeness()` | ✅ + sửa `cycle_count` đếm chu kỳ distinct |
| `MIN_SEASONAL_OBSERVATIONS` | `MIN_TEMPORAL_PATTERN_OBSERVATIONS` | ✅ |
| `tasks.compute_seasonal` / `compute_seasonal_records` | `compute_temporal_patterns` / `compute_temporal_pattern_records` | ✅ |
| `writer.write_seasonal`, `_SEASONAL_*` | `write_temporal_patterns`, `_TEMPORAL_PATTERN_*` | ✅ (SQL vẫn `gold.seasonal`) |
| `seasonal_records`, `sufficient_for_seasonal`, key `"seasonal"` | `temporal_pattern_records`, `sufficient_for_temporal_pattern`, `"temporal_pattern"` | ✅ |
| `PERIOD_BUCKETS` | giữ nguyên | ✅ đã rõ nghĩa |
| `seasonal_decompose` (statsmodels) | giữ nguyên | ✅ tên hàm thư viện, không phải module mình |

**Phạm vi KHÔNG đổi (contract):** `gold.seasonal`, `/api/seasonal`, `SeasonalPoint`, `PeriodType`, `period_type` values, tên hiển thị UI "Mùa vụ" (quyết định product — xem Q5).

## 7. Task theo ưu tiên (kèm tiêu chí nghiệm thu)

**Nhóm A — cần quyết định contract/schema trước (Prompt 2A):**

- **A1. Freshness semantics** — Chọn (a) last-known-good + docs, hoặc (b) schema per-table timestamp. *Nghiệm thu:* quyết định ghi trong `docs/api-contract.md`; nếu (b) có migration + API expose.
- **A2. Histogram scope** — Mở rộng `HISTOGRAM_METRICS` lên 5 metric (kèm tests + docs) hoặc giới hạn contract. *Nghiệm thu:* `GET /api/histogram` cho mọi metric trong `Metric` trả 200 hoặc docs ghi rõ metric không hỗ trợ; FE bỏ guard tương ứng.
- **A3. Anomaly contract** — Quyết định có persist/API anomaly của Analysis không, quan hệ với "Bất thường" Clustering. *Nghiệm thu:* có/không có proposal contract được nhóm duyệt.
- **A4. Cycle-completeness exposure** — Đưa `confirmed` lên Gold/API/FE hay gỡ hàm. *Nghiệm thu:* quyết định + (nếu expose) schema/API mới được duyệt.

**Nhóm B — sửa code không cần đổi schema (Prompt 2B):**

- **B1.** Dọn dead code: xóa `preview_analysis.py` (0 byte), quyết định `compute_*`/`write_*` đơn lẻ + `get_latest_silver_ts`. *Nghiệm thu:* `pytest` 100% pass; không còn caller mồ côi hoặc đã ghi "internal only".
- **B2.** Đồng bộ Gate↔thuật toán: `sufficient_for_seasonal` theo `MIN_SEASONAL_OBSERVATIONS`, `sufficient_for_trend` theo điều kiện month/week thật, correlation fitness check pairwise ≥3. *Nghiệm thu:* test mới chứng minh status phản ánh đúng khả năng từng thuật toán.
- **B3.** Trend month threshold theo giờ thực của tháng (672/720/744×0.9) + đếm distinct ts. *Nghiệm thu:* test tháng 31 ngày thiếu ~15% giờ bị reject; test hiện có vẫn pass.
- **B4.** Cân nhắc per-table partial-write hoặc log rõ metric/bảng thiếu trong `run_all`. *Nghiệm thu:* `service_runs.status=partial` khi đúng nghĩa, log liệt kê thành phần thiếu.
- **B5.** Gộp tài liệu: cập nhật `README.md` (100 tests, mô tả đúng), quyết định giữ/xóa `TEST_REPORT.md`, `FINAL_REVIEW.md`, `INTEGRATION_CONTRACT_REVIEW.md`, `REAL_DATA_VALIDATION.md` (Prompt 4). *Nghiệm thu:* một nguồn truth cho trạng thái module.

**Nhóm C — đổi tên nội bộ (Prompt 3):** chỉ sau khi A4/Q5 quyết — *Nghiệm thu:* rename nhất quán trong `services/analysis/`, contract DB/API/FE không đổi, tests pass.

## 8. Quyết định cần nhóm đồng ý (checklist)

1. **Freshness:** chấp nhận per-pipeline "last-known-good" + docs, hay yêu cầu per-table `computed_at` (schema change)?
2. **Histogram:** mở rộng lên 5 metric hay giới hạn contract 3 metric?
3. **Anomaly Analysis:** có cần persist + API không? Quan hệ với nhãn "Bất thường" của Clustering trên UI?
4. **Cycle completeness:** có expose `confirmed` ra Gold/API/FE không, hay giữ nội bộ/gỡ?
5. **Naming/UI:** đổi nội bộ `seasonal`→`temporal_patterns`? Label UI "Mùa vụ" có đổi thành "Mẫu hình thời gian"?
6. **Dead code:** `compute_*`/`write_*` đơn lẻ giữ làm manual API hay xóa?
7. **Trend month threshold:** theo giờ thực từng tháng hay giữ 604h cố định?

## 9. Kết quả test thực tế

| Cách chạy | Kết quả |
|---|---|
| `bash services/analysis/tests/run.sh` (Docker `python:3.11-slim`, PYTHONPATH=`services/analysis;backend`) | **110 passed in 14.55s** — 0 fail, 0 skip (sau Prompt 2A; trước đó 100 passed) |
| `pytest services/analysis/tests` trên `.venv-analysis` (cùng requirements) | 100 passed (trước Prompt 2A) |

Phân bố test sau Prompt 2A: reader 13, quality 21, resampling 12, histogram 9, trend 15, seasonal 12, correlation 9, writer 10, tasks 7, service_integration 2 = **110** (+10 test mới: 5 trend completeness/distinct-ts, 4 quality fitness, 1 tasks gate-skip).

**Bản chất test:** unit test dùng DataFrame tổng hợp in-memory (fixtures `conftest.py`) + `MagicMock` cho connection/DB — **không** có test Postgres thật trong `services/analysis/tests/`. Bù lại: `services/api/tests/test_analysis_pipeline_e2e.py` (Mode All) chạy Analysis service thật + Postgres `test_*` + Keycloak; `docs/analysis-pipeline-validation.md` ghi nhận E2E trên **dữ liệu Radar thật** ngày 20/11 (43.809 dòng silver, run #4 `success`, Gold counts đã đối chiếu).

## 10. Đề xuất thứ tự triển khai & câu hỏi cần nhóm trả lời

**Thứ tự đề xuất:** Prompt 2A (quyết định contract A1–A4) → Prompt 2B (fix code B1–B5, không phụ thuộc schema) → Prompt 3 (rename, sau Q5) → Prompt 4 (dọn tài liệu).

**Câu hỏi cần nhóm trả lời trước khi code:**

1. Freshness per-pipeline có được chấp nhận làm contract chính thức không (kèm docs "last-known-good"), hay bắt buộc per-table?
2. Histogram có mở rộng lên đủ 5 metric không — nếu có, ai own việc thêm metric (đồng nghĩa gold.histogram PK coverage thay đổi)?
3. Analysis anomaly có trở thành feature (bảng/API) không, và có gộp khái niệm với "Bất thường" của Clustering không?
4. `confirmed` cycle-completeness có được đưa ra ngoài Analysis không?
5. Nhãn UI "Mùa vụ" có đổi theo tên gọi mới không?
6. `compute_*`/`write_*` đơn lẻ: xóa hay giữ?
7. ~~Trend month bucket: ngưỡng 604h cố định có chấp nhận cho tháng 31 ngày không?~~ → **Đã giải quyết trong Prompt 2A** (xem §11).

---

## 11. PROMPT 2A — SỬA LOGIC THUẬT TOÁN (2026-11-22)

### 11.1 File đã thay đổi

| File | Thay đổi |
|---|---|
| `trend.py` | Thêm `MIN_BUCKET_COMPLETENESS=0.9`, `_expected_bucket_hours()` (tuần=168h, tháng=`days_in_month×24`), viết lại completeness check trong `_prepare_regular_series` (distinct ts / giờ kỳ vọng), thêm `trend_series_feasible()` |
| `correlation.py` | Tách `_pivot_metrics()` dùng chung; thêm `correlation_feasible()` (pairwise ≥3 obs + variance > 0, kể cả tự tương quan) |
| `quality.py` | Import helper của thuật toán; thêm field `sufficient_for_histogram`; cờ `sufficient_for_*` đếm đúng cách thuật toán đếm (finite records / distinct ts / feasibility thật); `algorithm_fitness["correlation"]` dùng `correlation_feasible(df)` thay `len(valid_with_variance)>=2` |
| `tasks.py` | `run_all` lặp qua `algorithm_fns`, skip compute khi `algorithm_fitness[name]=False` + log lý do; log danh sách thuật toán bị skip khi partial |
| `tests/test_trend.py` | +5 test (xem 11.3) |
| `tests/test_quality.py` | +4 test |
| `tests/test_tasks.py` | +1 test |

### 11.2 Lỗi đã xử lý (nguyên nhân, bằng chứng trước/sau)

**Lỗi 1 — Trend month threshold cố định 604h (M3/N4).**
- *Nguyên nhân:* `min_hours_per_bucket = 151 if "W" else 604` — 604 chỉ đúng cho tháng 28 ngày (90%×672); tháng 31 ngày (744h) chỉ đạt ~81%, tháng 29/30 ngày cũng lệch.
- *Trước:* bucket tháng 31 ngày có 660 giờ (88.7%) vẫn bị coi "đầy đủ".
- *Sau:* `_expected_bucket_hours()` trả 672/696/720/744 theo `days_in_month` thực tế; completeness = `nunique(ts)/expected ≥ 0.9` → tháng 31 ngày cần ≥670 giờ. Test `test_trend_month_31days_threshold_is_not_fixed_604` chứng minh 660h bị reject, 670h được chấp nhận.

**Lỗi 2 — Đếm bucket theo số dòng thay vì timestamp distinct (N4).**
- *Nguyên nhân:* `counts = df.groupby("bucket_ts")["value"].count()` đếm dòng; timestamp trùng làm phình độ đầy đủ.
- *Sau:* `ts_counts = df.groupby("bucket_ts")["ts"].nunique()`; test `test_trend_duplicate_timestamps_do_not_inflate_completeness` (151 giờ × 2 dòng = 302 dòng vẫn bị reject).
- *Lưu ý:* silver PK `(ts,metric)` khiến rủi ro thực tế thấp, nhưng hàm là public nên sửa cho đúng.

**Lỗi 3 — Gate seasonal đòi 24 records trong khi thuật toán chỉ cần 3 (M2/N3).**
- *Trước:* `sufficient_for_seasonal = valid_records >= 24`; metric có 5–23 obs vẫn chạy được seasonal nhưng gate báo không đủ.
- *Sau:* `n_distinct_ts >= MIN_SEASONAL_OBSERVATIONS` (import từ `seasonal.py` — cùng hằng số, cùng cách đếm dedup theo timestamp). Test `test_algorithm_fitness_seasonal_uses_algorithm_minimum`.

**Lỗi 4 — Gate trend dùng proxy 1344h, không tương ứng month path lẫn week path (M2).**
- *Trước:* `sufficient_for_trend = valid_records >= 8*168` — metric có 2000 bản ghi rời rạc vẫn "đủ" theo gate nhưng `_prepare_regular_series` reject.
- *Sau:* `trend_series_feasible(finite_df)` gọi đúng `_prepare_regular_series` (M→W) + ngưỡng `2*MONTH_PERIOD`/`2*WEEK_PERIOD` giống `decompose_metric_trend` — cùng hằng số, cùng cách đếm.

**Lỗi 5 — Gate correlation chỉ cần ≥2 metric có variance, không check pairwise (M2/N3).**
- *Trước:* `len(valid_with_variance) >= 2` → 2 metric × 2 obs vẫn báo đủ dù `MIN_OBSERVATIONS=3`.
- *Sau:* `correlation_feasible(df)` dùng chung `_pivot_metrics` + `compute_pearson_r`, kiểm tra mọi cặp (kể cả `var_x==var_y`) có ≥3 quan sát ghép cặp và variance > 0. Test `test_algorithm_fitness_correlation_needs_min_pairwise_observations` + `test_algorithm_fitness_zero_variance_metric`.

**Lỗi 6 — `run_all` không dùng fitness per-algorithm (M1/N2).**
- *Trước:* cả 5 `compute_*` luôn được gọi; fitness chỉ ảnh hưởng status `unusable`.
- *Sau:* `run_all` skip compute + `log.info("Bỏ qua thuật toán '%s': không đủ điều kiện đầu vào theo quality gate.")` khi `fitness=False`; status `partial` + log danh sách skip. Test `test_run_all_uses_quality_gate_per_algorithm` assert `compute_trend_records` **không được gọi** với data 24h.

**Đã kiểm chứng KHÔNG cần sửa:**
- **Resampling (B):** bucket day/week(Mon)/month theo giờ VN đúng, không nội suy — giữ nguyên.
- **Histogram (C):** 20 bins, min==max, `Σcount==n_valid`; `HISTOGRAM_METRICS` giữ 3 metric theo contract — việc mở rộng 5 metric vẫn chờ nhóm duyệt (H2/IM1), **không tự mở rộng**.
- **Correlation (E):** pairwise complete, `MIN_OBSERVATIONS=3`, zero-variance skip, không ghi NaN — chỉ refactor tách `_pivot_metrics` để gate dùng chung, không đổi hành vi.

### 11.3 Test đã thêm & kết quả thực tế

Lệnh: `bash services/analysis/tests/run.sh` → **110 passed in 14.55s** (0 fail, 0 skip), tăng từ 100.

| Test mới | Chứng minh |
|---|---|
| `test_expected_bucket_hours_by_actual_month_length` | 28/29/30/31 ngày → 672/696/720/744; tuần = 168 |
| `test_trend_month_completeness_uses_90_percent_of_actual_hours` | T2/2026: 600h reject, 610h accept (ngưỡng 605) |
| `test_trend_month_31days_threshold_is_not_fixed_604` | T7/2026: 660h reject, 670h accept (ngưỡng 670) |
| `test_trend_week_requires_152_distinct_hours_not_151` | 151h reject, 152h accept (90% của 168 = 151.2) |
| `test_trend_duplicate_timestamps_do_not_inflate_completeness` | 302 dòng nhưng 151 distinct → reject |
| `test_algorithm_fitness_seasonal_uses_algorithm_minimum` | 5 obs → seasonal fitness True, trend False |
| `test_algorithm_fitness_correlation_needs_min_pairwise_observations` | 2 obs/metric → correlation fitness False |
| `test_algorithm_fitness_zero_variance_metric` | Metric hằng số không tạo cặp chéo; gate↔compute khớp |
| `test_gate_fitness_matches_actual_algorithm_output` | Trên 2 fixtures: `fitness[X] == (compute_X(df) != [])` ∀ thuật toán |
| `test_run_all_uses_quality_gate_per_algorithm` | Gate False → compute không được gọi, `partial`, `trend_records=[]` |

### 11.4 Vấn đề còn lại → Prompt 2B/3 hoặc cần nhóm duyệt

- **H1, H2, M4–M7, IM1–IM5** giữ nguyên trạng thái audit — không thuộc phạm vi logic thuật toán 2A (freshness per-table, histogram 5 metric, dead code `compute_*`/`write_*`, anomaly persist, cycle-completeness exposure, per-table partial-write).
- `trend_series_feasible` chạy `_prepare_regular_series` 2 lần/metric trong gate rồi `compute_trend_records` chạy lại khi compute — chấp nhận được ở ~44k rows/300s; nếu silver lớn cần cache (theo dõi cùng L3).
- Gate↔thuật toán khớp ở mức điều kiện đầu vào; `seasonal_decompose` có thể vẫn raise runtime → compute trả `[]` → `partial` (hành vi đúng, đã có log).
- Câu hỏi §8 mục 7 đã được giải quyết bởi fix này.

---

## 12. PROMPT 2B — ĐỔI TÊN "SEASONAL" → "TEMPORAL PATTERN" (2026-11-22)

### 12.1 File đổi tên / sửa

| File | Hành động |
|---|---|
| `seasonal.py` → `temporal_patterns.py` | `git mv` (giữ lịch sử); viết lại docstring "bucket averages ≠ chu kỳ lặp lại" |
| `tests/test_seasonal.py` → `tests/test_temporal_patterns.py` | `git mv` + đổi tên toàn bộ test/hàm import |
| `quality.py` | import `MIN_TEMPORAL_PATTERN_OBSERVATIONS`; field `sufficient_for_temporal_pattern`; fitness key `"temporal_pattern"` |
| `tasks.py` | `compute_temporal_patterns()`; `algorithm_fns` key `"temporal_pattern"`; biến `temporal_pattern_records`; **gọi `assess_temporal_cycle_completeness` ghi log vận hành** (phương án a) |
| `writer.py` | `write_temporal_patterns`, `_TEMPORAL_PATTERN_*`, param `temporal_pattern_records`; SQL vẫn `DELETE/INSERT gold.seasonal` + comment tương thích |
| `tests/test_quality.py`, `test_tasks.py`, `test_writer.py` | Cập nhật tên theo contract mới |
| `README.md` | Mục 4 → "Temporal Pattern Analysis"; sửa N≥3 correlation; cấu trúc file |

### 12.2 Quy tắc đặt tên áp dụng

- Module/chức năng = **temporal pattern** (mẫu hình theo thời gian): trung bình bucket giờ/thứ/tháng — chưa khẳng định chu kỳ lặp lại.
- `assess_temporal_cycle_completeness` = đánh giá riêng khả năng lặp lại; `confirmed` chỉ khi mỗi bucket lặp ở ≥ 2 chu kỳ độc lập (giờ→ngày, thứ→tuần ISO, tháng→năm).
- `cycle_count` sửa từ `obs ÷ độ dài chu kỳ` sang **số chu kỳ distinct** (nunique ngày/tuần ISO/năm) — không bị thổi phồng bởi dữ liệu thưa.
- Giữ nguyên mọi tên contract: `gold.seasonal`, `/api/seasonal`, `SeasonalPoint`, `period_type`, `PERIOD_BUCKETS`, `seasonal_decompose` (tên hàm thư viện statsmodels).

### 12.3 Tên cũ còn giữ & lý do

| Tên giữ | Lý do |
|---|---|
| `gold.seasonal` (bảng + SQL trong writer) | Hợp đồng DB với api/frontend — đổi cần schema migration + đồng bộ 2 service |
| `/api/seasonal`, `SeasonalPoint`, `period_type` | Hợp đồng API/JSON |
| Nhãn UI "Mùa vụ" | Frontend — chỉ **đề xuất** đổi thành "Mẫu hình theo thời gian" (chờ nhóm, Prompt 3/frontend) |
| `seasonal_decompose`, `statsmodels.tsa.seasonal` | Tên hàm thư viện bên thứ ba, không phải module của dự án |

### 12.4 Kết quả `git grep` trước/sau

- **Trước:** `seasonal` xuất hiện rải rác trong `seasonal.py`, `tasks.py`, `quality.py`, `writer.py`, 4 file test, `README.md` + các tham chiếu contract (gold.seasonal, /api/seasonal, SeasonalPoint, frontend, docs).
- **Sau:** trong `services/analysis/` code chỉ còn `gold.seasonal` (SQL, có comment tương thích), `seasonal_decompose` (thư viện), và tài liệu lịch sử (`CODE_REVIEW.md` phần audit, `FINAL_REVIEW.md`, `INTEGRATION_CONTRACT_REVIEW.md` — sẽ dọn ở Prompt 4). `git grep` cho `compute_seasonal_records|check_seasonal_cycle_completeness|MIN_SEASONAL_OBSERVATIONS|write_seasonal|sufficient_for_seasonal|from seasonal import` → **0 kết quả trong code**.

### 12.5 Test & kết quả thực tế

`bash services/analysis/tests/run.sh` → **111 passed in 9.11s** (0 fail, 0 skip), tăng từ 110.

- Đổi tên không đổi kết quả: `compute_temporal_pattern_records` giữ nguyên thuật toán; các test cũ (mean chính xác, bucket giờ 10/11, timezone UTC→VN, min 3 obs, không tạo bucket giả) pass nguyên trạng → đầu ra giống hệt.
- Test chu kỳ mới/cập nhật: 1 ngày (giờ complete nhưng confirmed=False), 2 ngày đủ giờ → hour confirmed, 1 tuần (dow chưa confirmed, `cycle_count=2` do tràn tuần ISO — đã cập nhật assertion), 2 tuần → dow confirmed, 1 năm → month chưa confirmed, 2 năm → month confirmed, `cycle_count` đếm distinct cycles với dữ liệu thưa (24 obs/3 ngày → 3 chứ không phải 1).

### 12.6 Chuyển sang Prompt 3

- Prompt 3 (dọn dead code `compute_*`/`write_*` đơn lẻ, `preview_analysis.py`, gộp docs) có thể chạy độc lập — không phụ thuộc quyết định contract.
- Chờ nhóm: (i) nhãn UI "Mùa vụ" → "Mẫu hình theo thời gian"? (ii) có expose `confirmed` cycle-completeness ra Gold/API không (đổi contract)? (iii) `gold.seasonal` có đổi tên vật lý trong schema tương lai không?
