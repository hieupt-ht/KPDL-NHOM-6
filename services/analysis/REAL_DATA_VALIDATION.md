# REAL DATA VALIDATION — Analysis Service (Task 07)

**Ngày thực hiện:** 2026-11-19 (giờ container/log UTC+7)
**Branch:** `feature/data-analysis`
**Phạm vi:** nghiệm thu E2E module Analysis theo Task 07.

---

## 1. Môi trường kiểm thử

| Thành phần | Trạng thái |
|---|---|
| Docker Desktop / Compose | Hoạt động (Docker 29.9.3, Compose v5.7.0), project `cyber-radar-vn` |
| `warehouse-db` (PostgreSQL 16) | Up, healthy, schema `silver.*` init đúng |
| `mart-db` (PostgreSQL 16) | Up, healthy, schema `gold.*` init đúng |
| `analysis` | Build + chạy từ source branch hiện tại |
| `api` | Build + chạy (`AUTH_ENABLED=false` — dev mode) |
| `keycloak`, `frontend`, `ingestion`, `clustering`, `prediction` | **Không khởi động** |
| `.env` | Tồn tại; `CF_API_TOKEN` là **placeholder** (`replace-with-...`) → **không có dữ liệu Radar thật**; `AUTH_ENABLED=false`, `SCHEDULER_ENABLED=false` |

**Lưu ý dữ liệu:** `silver.metrics_hourly` được seed bằng **dữ liệu synthetic do kiểm thử tạo** (không phải dữ liệu Cloudflare thật), nhằm kiểm chứng cơ chế pipeline/idempotency/API trên PostgreSQL thật. Dữ liệu này được ghi rõ trong báo cáo và không bị nhầm là dữ liệu production.

## 2. Unit tests

Runner chính thức `services/analysis/tests/run.sh` (Docker `python:3.11-slim`):

```
100 passed in 9.70s
```

Kết quả tương đương trên venv cục bộ (`PYTHONPATH=services/analysis;backend`): **100 passed**. Không test nào fail/skip. Phủ: reader, quality, resampling, histogram, trend, seasonal, correlation, writer, tasks, service integration.

## 3. Real Data Validation

### 3.1. Dữ liệu nguồn

`CF_API_TOKEN` trong `.env` là placeholder → **ingestion không thể gọi Cloudflare Radar thật → không có dữ liệu Silver thật**. Theo yêu cầu task, phần "real Radar data" không được thực hiện và không bịa dữ liệu để thay thế.

Thay vào đó, kiểm thử pipeline trên fixture synthetic trong `silver.metrics_hourly`:

- **8.400 rows** = 5 metric × 1.680 giờ.
- Khoảng thời gian: `2026-08-02 17:00Z` → `2026-10-11 16:00Z` = đúng **10 tuần VN trọn vẹn** (T2 00:00 → CN 23:00 giờ `Asia/Ho_Chi_Minh`).
- `source='radar'` cho toàn bộ.
- Cố tình chèn lỗi để kiểm chứng lọc: `l7_attack` có **3 NULL**, `netflows` có **1 NaN**.
- Không có timestamp trùng (PK `(ts, metric)`), không có ±Inf.

### 3.2. Chạy pipeline (qua `common.runner`, không bypass)

`POST /run` với `X-Job-Token` → `202 {"service":"analysis","run_id":N,"status":"accepted"}` → job chạy async → `gold.service_runs.status='success'`.

Log pipeline xác nhận đúng logic:
- Quality: `status=usable`, phát hiện đúng 2 vấn đề (3 NULL l7_attack, 1 NaN netflows) → không chặn pipeline.
- Resampled: 415 bản ghi.
- Histogram: 60 bins / 3 metrics.
- Trend: month path không đủ (chỉ ~3 bucket tháng < 24 điểm) → **fallback week đúng thiết kế**, 6 trend points/metric sau khi trim + drop NaN.
- Seasonal: 170 bản ghi; Correlation: 25 cặp (5×5, đối xứng, đường chéo = 1).
- Freshness: `latest_silver_ts = 2026-10-11 16:00Z` (khớp max(ts) Silver).

### 3.3. Kết quả Gold (đã kiểm tra trực tiếp)

| Bảng | Rows | Kiểm chứng |
|---|---|---|
| `gold.timeseries_resampled` | 415 | day=350 (5×70), week=50 (5×10), month=15 (5×3); `ts` lưu UTC đúng instant |
| `gold.histogram` | 60 | 3 metrics × 20 bins; `sum(count)`: http_traffic=1680, bot_share=1680, **l7_attack=1677** (= 1680−3 NULL → lọc NULL đúng end-to-end) |
| `gold.trend` | 30 | 5 metrics × 6 điểm, `granularity='week'` |
| `gold.seasonal` | 170 | hour_of_day=120 (5×24), day_of_week=35 (5×7), month=15 (5×3) |
| `gold.correlation` | 25 | đủ 25 cặp ordered, `coef` ∈ [−1,1], `computed_at` = thời điểm chạy |
| `gold.data_freshness` | 1 | upsert đúng, `computed_at` cập nhật mỗi run |
| `gold.service_runs` | 3 | Cả 3 run `analysis` → `success` (xem §5 về fix) |

Silver sau toàn bộ quá trình: vẫn **8.400 rows** — không bị đụng vào. Không bảng nào của Clustering/Prediction bị ghi.

## 4. Idempotency

Chạy pipeline nhiều lần trên cùng input (silver không đổi). So sánh content hash (`md5` trên toàn bộ row) trước/sau mỗi run:

- `timeseries_resampled`, `histogram`, `trend`, `seasonal`: **hash giống hệt** giữa các lần chạy → DELETE+INSERT cho kết quả deterministic, không duplicate PK.
- `correlation`, `data_freshness`: hash khác **chỉ vì `computed_at = now()`** — đúng contract (freshness phải phản ánh lần chạy mới); `coef`/`value`/`latest_silver_ts` không đổi.
- `gold.service_runs` tích lũy 1 row/run — đúng journal semantics.

## 5. Backend Integration — PHÁT HIỆN & ĐÃ SỬA 1 LỖI P1

### Lỗi tìm thấy (trước khi sửa)

`services/analysis/main.py` (commit `8901801`) **ghi đè** endpoint `POST /run` của `common.runner` bằng hàm synchronous:

- Không yêu cầu `X-Job-Token` (bỏ auth).
- Không dùng `JobRunner` → **không lock**, **không ghi `gold.service_runs`**, không trả `run_id`/202.
- Hệ quả đo được: `POST /api/jobs/analysis/run` (admin trigger qua API) → analysis trả `200 {"status":"ok"}` → API validate `AcceptedJob{run_id}` thất bại → **502 "Job service rejected the request"**. Toàn bộ đường trigger thủ công Backend→Analysis bị gãy; `/api/status` không có run nào của analysis.
- Clustering/Prediction dùng `create_service_app` nguyên bản — chỉ Analysis lệch convention (CLAUDE.md: "gives an authenticated /run returning 202").

### Đã sửa

- `services/analysis/main.py`: bỏ override, dùng `/run` mặc định của `common.runner` (202 + `run_id` + token + lock + journal).
- `services/analysis/tests/test_service_integration.py`: cập nhật test assert contract runner (auth dependency + `{service, run_id, status:"accepted"}`) thay vì assert hành vi override sai.

### Kiểm chứng sau sửa (trên Docker thật)

| Kiểm tra | Kết quả |
|---|---|
| `POST /run` không token / sai token | **401** `Invalid internal job token` |
| `POST /run` đúng `JOB_TRIGGER_TOKEN` | **202** `{"service":"analysis","run_id":1,"status":"accepted"}` |
| 2 request đồng thời | Request 2 → **409** `already has a running job` (local + PG advisory lock hoạt động) |
| `gold.service_runs` | run_id 1,2,3 → `success`, `finished_at`/`error` đúng |
| `POST /api/jobs/analysis/run` (admin, AUTH_ENABLED=false) | **202** `{"service":"analysis","run_id":2,"status":"accepted"}` |
| `GET /api/jobs/runs/2` | 200, `status:"success"` |
| `GET /api/status` | `service_runs` mới nhất + `data_freshness` đúng |

## 6. API Integration (live, AUTH_ENABLED=false)

Tất cả endpoint đọc Gold thật, response shape khớp `docs/api-contract.md`:

| Endpoint | Kết quả |
|---|---|
| `GET /api/timeseries?metric=http_traffic&granularity=day` | 200, mảng `{granularity, ts(UTC), metric, mean, min, max}` |
| `GET /api/histogram?metric=bot_share` | 200, 20 bins `{metric, bin_start, bin_end, count}` |
| `GET /api/trend?metric=http_traffic&granularity=week` | 200, `{granularity, ts, metric, trend_value}` |
| `GET /api/seasonal?metric=l7_attack&period_type=day_of_week` | 200, `{period_type, bucket, metric, value}` |
| `GET /api/correlation` | 200, `{var_x, var_y, coef, computed_at}` |
| `GET /api/status` | 200, `service_runs` + `data_freshness` |
| Edge cases | granularity sai → 422; range rỗng → 404; period_type sai → 422; `trend?granularity=month` → 404 (đúng — không có month trend); `histogram?metric=human_share|netflows` → 404 (contract gap đã ghi ở Task 06, chờ nhóm quyết) |

## 7. Frontend Integration

**Không thực thi UI.** `.env` đang `NEXT_PUBLIC_DATA_MODE=demo` + `AUTH_ENABLED=false`; live mode yêu cầu `AUTH_ENABLED=true` + Keycloak (chưa khởi động). Contract frontend↔API đã được xác minh bằng code ở Task 06 (`INTEGRATION_CONTRACT_REVIEW.md`). Không tuyên bố đã kiểm thử UI thực tế.

## 8. Test totals

- Unit/integration Analysis: **100 passed, 0 failed, 0 skipped** (Docker runner chính thức).
- Live E2E: 3 job runs `success`; 6/6 GET endpoints 200; auth/lock/jobs contract đạt sau fix.

## 9. Giới hạn chưa xác minh

1. **Không có dữ liệu Cloudflare Radar thật** (`CF_API_TOKEN` placeholder) → chưa validate trên phân phối dữ liệu thật, độ dài lịch sử thật, hay rescale ratio thực tế. Mọi con số Gold ở §3 là từ fixture synthetic.
2. **Frontend UI chưa chạy** — chỉ verify contract bằng code/test.
3. **JWT/Keycloak path chưa test** (`AUTH_ENABLED=false`); admin jobs endpoint được gọi ở dev-identity mode.
4. Ingestion/clustering/prediction không chạy → chưa kiểm chứng tranh chấp tài nguyên/lock liên service.
5. Histogram 3/5 metric và trend-join frontend (Task 06 F1/F2) vẫn là quyết định mở của nhóm — không phải lỗi Analysis.

## 10. Kết luận nghiệm thu

**CHƯA ĐỦ ĐIỀU KIỆN NGHIỆM THU** — theo đúng điều kiện §9 của task:

- ✅ Unit tests đạt (100/100, runner Docker chính thức).
- ✅ Service integration đúng (sau khi sửa P1 `main.py` override — đã kiểm chứng 401/202/409/`service_runs`/API jobs E2E).
- ✅ Pipeline → Gold → API chạy đúng trên PostgreSQL thật với fixture synthetic; idempotency đạt; Silver/biên ghi không bị vi phạm.
- ❌ **Real-data validation chưa thực hiện** — không có token Radar thật/dữ liệu Silver thật.
- ⚠️ API contract đạt trên dev-auth; frontend UI và JWT path chưa kiểm chứng.

Điều kiện để chuyển sang nghiệm thu: cung cấp `CF_API_TOKEN` thật + chạy ingestion backfill, sau đó lặp lại §3–§4 trên dữ liệu thật; bật `AUTH_ENABLED=true` + Keycloak để verify JWT/admin path; chạy frontend live mode để đóng §7.

---

# PROMPT 3.5 — KIỂM CHỨNG DỮ LIỆU (2026-11-22)

## A. Kiểm tra điều kiện tiên quyết — KHÔNG ĐẠT cho dữ liệu Radar thật

| Điều kiện | Kết quả | Bằng chứng |
|---|---|---|
| CF_API_TOKEN hợp lệ | ❌ **Token bị từ chối** | `curl https://api.cloudflare.com/client/v4/radar/http/timeseries?dateRange=1d&location=VN` với `Authorization: Bearer $CF_API_TOKEN` → HTTP 400, `code 9106 "Authentication failed"`. Token trong `.env` dài 29 ký tự, không phải placeholder, nhưng Cloudflare không chấp nhận (hết hạn/thu hồi/sai). |
| Ingestion chạy được | ❌ **Không build được image** | `docker compose build ingestion` → pip `ResolutionImpossible` trên `python:3.11-slim` (xung đột pydantic/pydantic-core do release mới; `requirements.txt` không pin cứng). Không phải lỗi code Analysis; cần owner Ingestion xử lý. |
| `silver.metrics_hourly` có `source='radar'` | ⚠️ Có label, **nhưng không phải dữ liệu Radar thật** | Xem mục B. |

### Bằng chứng silver hiện tại là dữ liệu TỔNG HỢP, không phải Radar thật

- `bronze.raw_api_responses`: **0 dòng** — chưa từng có response API Radar nào được ingestion ghi.
- `silver.ingestion_runs`: **0 dòng** — ingestion service chưa chạy lần nào trong volume này.
- `docs/analysis-pipeline-validation.md` (20/11) ghi nhận backfill thật 43.809 dòng (~8.760 metric-dòng, phủ ~365 ngày đến 20/11/2026) — **không khớp** với hiện trạng (xem dưới).
- Dữ liệu hiện có: 8.400 dòng = 5 metric × 1.680 giờ, `2026-08-02 17:00Z → 2026-10-11 16:00Z` (70 ngày liên tục, 0 timestamp trùng, 0 giờ thiếu), giá trị trông như công thức sin/tuyến tính mượt (ví dụ http_traffic: 0.6 → 0.6797 → 0.7541 → 0.8183 → 0.8680 theo giờ), và pattern lỗi trùng khớp fixture tổng hợp cũ (`l7_attack` 3 NULL, `netflows` 1 non-finite).

→ **Kết luận provenance:** 8.400 dòng `source='radar'` hiện tại là **seed tổng hợp** (ghi trực tiếp SQL hoặc session trước), KHÔNG phải output của Cloudflare Radar ingestion. Mọi kiểm chứng dưới đây là trên **dữ liệu tổng hợp** — hợp lệ để verify thuật toán/writer/idempotency/API, nhưng **không được tuyên bố là nghiệm thu dữ liệu Radar thật**.

## B. Những gì ĐÃ kiểm chứng trên dataset hiện có (TỔNG HỢP)

Môi trường: stack `docker compose` thật — warehouse-db + mart-db (PostgreSQL 16, volume ứng dụng) + analysis (image build lại từ branch hiện tại, gồm Prompt 2A/2B/3) + api (`AUTH_ENABLED=false`).

### B.1. `run_all` trên silver hiện có

- Gọi trực tiếp `tasks.run_all()` trong container analysis: **status=`success`, ~2.3s**.
- Gọi qua đường production `POST /run` + `X-Job-Token` → **202 run_id=4** → `gold.service_runs.status='success'`, `finished_at` đúng; `/api/status` phản ánh đúng.
- Log: quality `usable` (phát hiện đúng 2 vấn đề NULL/NaN đã biết); resampled 415; histogram 60 bins/3 metric; trend fallback week 30 bản ghi; temporal_pattern 170; correlation 25 cặp; **"Freshness cập nhật: True"** (đủ 5/5 nhóm — đúng phương án A).

### B.2. Đối chiếu độc lập Gold ↔ SQL thủ công (cùng snapshot silver)

| Kiểm tra | Kết quả |
|---|---|
| Resample day VN 2026-08-03, http_traffic | mean/min/max **khớp tuyệt đối** (0.6224563581583934 / 0.33477449009293664 / 0.9123260466978156, n=24) |
| Resample week T2 2026-08-03→10 (168h) | mean=0.6167, min/max **khớp** gold |
| Resample month T9/2026 VN (720h) | mean=0.8139423781151559 vs gold 0.8139423781151555 (lệch ~4e-16, float) — **khớp** |
| Histogram tổng count | http_traffic=1680, bot_share=1680, l7_attack=**1677** (=1680−3 NULL → lọc đúng); chỉ 3 metric theo contract |
| Temporal pattern hour bucket 14 VN | gold 0.6184000000000025 vs SQL độc lập 0.6184000000000023 — **khớp** |
| Correlation (http_traffic, l7_attack) | SQL `corr()` trên 1.677 cặp đủ hai phía = 0.47110072605460185 vs gold 0.4711007260545994 — **khớp** (~2e-15) |
| Trend | month path loại đúng (2 điểm < 24 yêu cầu) → fallback week; bucket tháng cuối T10/2026 bị trim (264h = 35.5% < 90%) — đúng thiết kế; 6 điểm trend/metric sau trim NaN 2 đầu của seasonal_decompose |
| `latest_silver_ts` | = `2026-10-11 16:00Z` = **max(ts) silver thật**, không phải `now()` |
| Temporal cycle | log xác nhận `hour_of_day, day_of_week` cho cả 5 metric; **month KHÔNG confirmed** (dữ liệu <12 tháng) — đúng logic distinct-cycle |

### B.3. Idempotency trên Postgres thật

Chạy `run_all` 3 lần (2 lần exec trực tiếp + 1 lần qua `/run`). So sánh dump toàn bảng trước/sau:

- `timeseries_resampled`, `histogram`, `trend`, `seasonal`: **giống hệt từng byte** sau sort → không duplicate, deterministic.
- `correlation`: `(var_x, var_y, coef)` giống hệt; chỉ `computed_at` đổi (đúng contract — timestamp ghi).
- `data_freshness`: `latest_silver_ts` giữ nguyên; `computed_at` cập nhật mỗi lần đủ 5/5 nhóm.

### B.4. API readback (AUTH_ENABLED=false, dev identity)

| Endpoint | Kết quả |
|---|---|
| `/api/histogram` | 200 cho http_traffic/l7_attack/bot_share; **404 cho human_share/netflows** (contract gap F2 đã biết, FE có empty-state) |
| `/api/trend?granularity=week` | 200 cả 5 metric; `granularity=month` sẽ 404 (đúng — không có month trend) |
| `/api/seasonal` | 200 cả 5 metric × 3 period_type; month bucket trả `8,9,10` (T8/T9/T10 — khớp nhãn FE `T${bucket}`) |
| `/api/correlation` | 200, 25 cặp, `coef` ∈ [−1,1], đường chéo =1 |
| `/api/timeseries`, `/api/status` | 200; status trả `service_runs` mới nhất + `data_freshness` đúng |

### B.5. Frontend

**Chưa kiểm thử được:** frontend image chưa build (`AUTH_ENABLED=false`, live mode yêu cầu `AUTH_ENABLED=true` + Keycloak + rebuild với `NEXT_PUBLIC_DATA_MODE=api`). Contract FE↔API đã verify bằng code ở Prompt 1/3 (nhãn tháng `T${bucket}` khớp bucket 1..12; dow `T2..CN` khớp 0..6; heatmap lọc null; histogram empty-state cho metric không hỗ trợ).

## C. Phát hiện mới

1. **CF_API_TOKEN không còn hiệu lực** (9106 auth failed) → chặn toàn bộ việc thu thập Radar mới. Cần người quản lý token cấp lại.
2. **Image `ingestion` không build được** do xung đột dependency pip (pydantic/pydantic-core releases mới vs `requirements.txt` chưa pin) → kể cả khi có token, ingestion hiện không chạy được trên môi trường này. Cần owner Ingestion pin version hoặc cập nhật requirements.
3. **Silver `source='radar'` hiện tại là dữ liệu tổng hợp** — cần cảnh báo cho mọi người không diễn giải kết quả Gold hiện tại là "dữ liệu Radar thật".
4. `run_all` gọi trực tiếp (không qua `/run`) **không ghi `gold.service_runs`** — đúng thiết kế (journal thuộc `common.runner`), nhưng cần lưu ý khi vận hành thủ công.

## D. Kết luận

**CHƯA ĐỦ ĐIỀU KIỆN NGHIỆM THU dữ liệu Radar thật** — điều kiện tiên quyết không đạt:

- Không có token Radar hợp lệ → không thể backfill/fetch dữ liệu thật.
- Ingestion image không build được → không chạy được pipeline thu thập.
- Silver hiện có là tổng hợp → không đủ căn cứ tuyên bố kiểm chứng trên dữ liệu Cloudflare thật.

**Đã kiểm chứng được (trên dữ liệu tổng hợp, Postgres thật):** toàn bộ thuật toán đối chiếu độc lập khớp; writer transaction/idempotency đúng; freshness phương án A hoạt động (chỉ cập nhật khi đủ 5/5 nhóm); API readback đúng contract; `run_all` qua runner thật → `success` + journal.

**Điều kiện để nghiệm thu thật:** (1) token Radar mới → (2) sửa build ingestion → (3) backfill → (4) lặp lại §B trên dữ liệu thật → (5) frontend live mode.
