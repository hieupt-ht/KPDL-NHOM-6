# Data Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa 5 chỉ số Cloudflare Radar (VN) vào Warehouse qua Bronze → Silver, với chuỗi giờ liên tục, một thang đo chung và chạy định kỳ 5 phút.

**Architecture:** `radar_client` gọi API có retry; mỗi phản hồi được lưu nguyên văn vào Bronze; `silver` parse và làm sạch; `rescale` quy đổi các chỉ số MIN0_MAX về thang của Silver bằng hệ số tính trên vùng chồng; `pipeline` ghép các bước cho một endpoint; `backfill` lùi dần từ mới đến cũ; `main` chạy chu kỳ 5 phút và backfill nền.

**Tech Stack:** Python 3.11, httpx, psycopg 3, APScheduler (qua `common.runner`), pytest. Máy dev **không có Python**: mọi lệnh test chạy qua Docker (Task 1).

**Spec:** `docs/superpowers/specs/2026-11-17-data-ingestion-design.md`

## Global Constraints

- Chỉ sửa `services/ingestion/` và `db/warehouse/` (+ README ở Task 9, cần trưởng nhóm đồng ý). **Không sửa `backend/common/`.**
- Mọi truy vấn Radar: `location=VN`, `aggInterval=1h`, `format=json`; base URL `https://api.cloudflare.com/client/v4/radar`; header `Authorization: Bearer <CF_API_TOKEN>`.
- 5 chỉ số: `http_traffic`, `l7_attack`, `netflows` (MIN0_MAX, **phải quy đổi**), `bot_share`, `human_share` (PERCENTAGE, không quy đổi).
- Giá trị thô hợp lệ: MIN0_MAX ∈ [0, 1]; PERCENTAGE ∈ [0, 100]; ngoài khoảng hoặc null/NaN/vô cực/không phải số thì bỏ.
- Quy đổi: `k = median(silver(t) / w(t))` trên các mốc chồng có cả hai giá trị > 0; cần **≥ 12** mốc; không đủ thì **không ghi Silver**, vẫn lưu Bronze.
- Cửa sổ `aggInterval=1h` tối đa 30 ngày (45 ngày bị từ chối). Backfill: lô **28 ngày**, chồng **2 ngày**, đi từ mới đến cũ. Polling: `dateRange=2d`.
- Retry: backoff 1s → 2s → 4s … tối đa 60s, tối đa 6 lần, cho timeout, lỗi kết nối, HTTP 429, 5xx; tôn trọng `Retry-After`. Không retry 400/401/403. Timeout kết nối 10s, đọc 30s.
- Token không bao giờ vào log, Bronze `params`, thông báo lỗi hay commit.
- Bronze giữ 30 ngày. Silver lưu `TIMESTAMPTZ` UTC; thêm cột `source VARCHAR(16) NOT NULL DEFAULT 'radar'`.
- Commit: `<type>(ingestion): <mô tả thể mệnh lệnh>`, kết thúc bằng dòng `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Radar trả HTTP 200 nhưng `success:false` hoặc chuỗi rỗng/toàn null: coi là lỗi, lưu Bronze, không ghi Silver (Task 6).
2. Vùng chồng toàn số 0 hoặc quá ít mốc: không ghi, không chia cho 0 (Tasks 2, 6).
3. Backfill phải **dừng** khi API không còn dữ liệu cũ hơn, không lặp vô hạn (Task 7).
4. Một endpoint lỗi (kể cả lỗi DB/exception bất ngờ) không làm dừng chu kỳ; `ingestion_runs` ghi `partial` (Task 8).
5. Thiếu `CF_API_TOKEN` hoặc còn giá trị mẫu: lỗi cấu hình rõ ràng, scheduler không chết (Tasks 4, 8).

---

## File Structure

| File | Trách nhiệm |
| :--- | :--- |
| `services/ingestion/metrics.py` | Bảng endpoint/chỉ số (dữ liệu thuần) |
| `services/ingestion/config.py` | `ConfigError`, `get_token()`, hằng số |
| `services/ingestion/rescale.py` | Hàm thuần quy đổi thang đo |
| `services/ingestion/radar_client.py` | HTTP + retry |
| `services/ingestion/silver.py` | Parse/làm sạch + UPSERT + đọc Silver |
| `services/ingestion/bronze.py` | Lưu thô + dọn 30 ngày |
| `services/ingestion/runs.py` | Ghi `silver.ingestion_runs` |
| `services/ingestion/dbutil.py` | `use_conn()` dùng chung |
| `services/ingestion/pipeline.py` | Một endpoint × một cửa sổ: fetch → Bronze → parse → rescale → Silver |
| `services/ingestion/backfill.py` | Lập cửa sổ lùi dần + vòng backfill |
| `services/ingestion/main.py` | Chu kỳ 5 phút, khóa, luồng backfill nền |
| `services/ingestion/tests/` | Test, `fixtures/` (JSON Radar thật), `run.sh` |

Quy ước DB: mọi hàm DB nhận `conn: psycopg.Connection | None = None`; `None` thì tự mở và commit. Test tích hợp truyền một kết nối rồi **rollback**, nên không chạm dữ liệu thật.

---

### Task 1: Nhánh, bộ chạy test, dữ liệu mẫu

**Files:**
- Create: `services/ingestion/requirements-dev.txt`, `services/ingestion/tests/run.sh`, `services/ingestion/tests/conftest.py`, `services/ingestion/tests/fixtures/{http_traffic,l7_attack,bot_class,netflows,winA,winB,winC}.json`

**Interfaces:**
- Produces: lệnh `bash services/ingestion/tests/run.sh [pytest args]` chạy từ gốc repo; fixture pytest `fixture_json(name) -> dict`; fixture `db_conn` (kết nối Postgres, rollback cuối test, **skip** nếu thiếu `TEST_WAREHOUSE_DSN`); marker `integration`.

- [ ] **Step 1: Tạo nhánh từ `chore/scaffold`** (develop chưa có scaffold): `git checkout -b feature/data-ingestion chore/scaffold`. Bản thiết kế và kế hoạch (thư mục `docs/superpowers/`) đang chưa theo dõi sẽ đi theo.
- [ ] **Step 2: Viết `requirements-dev.txt`** (`-r requirements.txt` + `pytest~=8.3`), `conftest.py` (fixture nêu ở Produces, đọc JSON từ `tests/fixtures/`).
- [ ] **Step 3: Viết `run.sh`**: chạy `docker run --rm` image `python:3.11-slim`, mount repo (dùng `MSYS_NO_PATHCONV=1` và `$(pwd -W)` trên Git Bash), `PYTHONPATH=/work/services/ingestion:/work/backend`, volume cache pip `kpdl-pipcache`, rồi `pip install -q -r services/ingestion/requirements-dev.txt && pytest services/ingestion/tests -q "$@"`. Biến `INTEGRATION=1` thêm `--network cyber-radar-vn_cyber-net` (kiểm tra tên bằng `docker network ls`) và truyền `TEST_WAREHOUSE_DSN` dựng từ `.env` mà không in mật khẩu (`postgresql://ingestion_user:$INGESTION_DB_PASSWORD@warehouse-db:5432/$WAREHOUSE_DB`).
- [ ] **Step 4: Chép dữ liệu mẫu** từ `C:\Users\HIEU\AppData\Local\Temp\claude\1869f342d767c4bc\91a899e1-e542-480c-8bb1-808305927bab\scratchpad\` vào `tests/fixtures/`. Cần có: `http_traffic.json`, `l7_attack.json`, `bot_class.json`, `netflows.json`, `winA.json`, `winB.json`, `winC.json`. Đây là dữ liệu công khai, không chứa token; xác nhận bằng `grep -il "cfut\|cfat\|bearer" services/ingestion/tests/fixtures/*` (kỳ vọng không có kết quả). Nếu thư mục tạm đã mất, gọi lại API như Task chuẩn bị (cùng tham số trong thiết kế mục 2).
- [ ] **Step 5: Chạy** `bash services/ingestion/tests/run.sh` → kỳ vọng `no tests ran` (exit 5) nhưng pip và đường dẫn hoạt động, không có lỗi import.
- [ ] **Step 6: Commit** `chore(ingestion): add dockerised test runner and Radar fixtures` (kèm thiết kế và kế hoạch: `docs: add ingestion design and plan` ở commit riêng).

---

### Task 2: Schema Warehouse

**Files:**
- Modify: `db/warehouse/init/01-schema.sql`
- Test: `services/ingestion/tests/test_schema.py` (integration)

**Interfaces:**
- Produces: `silver.metrics_hourly.source VARCHAR(16) NOT NULL DEFAULT 'radar'`; chỉ mục `idx_bronze_fetched_at` trên `bronze.raw_api_responses (fetched_at)`.

- [ ] **Step 1: Viết test** `test_metrics_hourly_has_source_default_radar` (chèn một dòng không có `source`, đọc lại, assert `== 'radar'`) và `test_bronze_has_fetched_at_index` (truy vấn `pg_indexes`, assert có `idx_bronze_fetched_at`). Đánh dấu `@pytest.mark.integration`, dùng `db_conn`.
- [ ] **Step 2: Chạy** `INTEGRATION=1 bash services/ingestion/tests/run.sh -k schema` → FAIL (chưa có cột/chỉ mục). Trước đó phải có `warehouse-db` đang chạy: `docker compose up -d warehouse-db`.
- [ ] **Step 3: Sửa `01-schema.sql`**: thêm cột và `CREATE INDEX`. Không đổi tên cột nào.
- [ ] **Step 4: Áp dụng lên volume** (init chỉ chạy lần đầu): `docker compose rm -sfv warehouse-db`, `docker volume rm cyber-radar-vn_warehouse-data`, `docker compose up -d warehouse-db`, chờ healthy. Chạy lại test → PASS. Dữ liệu Warehouse cục bộ bị xóa, chấp nhận được vì chưa có gì.
- [ ] **Step 5: Commit** `feat(db): add source column and bronze fetched_at index`. Báo nhóm: máy khác cần xóa volume `warehouse-data`.

---

### Task 3: Quy đổi thang đo (`rescale.py`)

**Files:**
- Create: `services/ingestion/rescale.py`
- Test: `services/ingestion/tests/test_rescale.py`

**Interfaces:**
- Produces: `MIN_OVERLAP = 12`; `compute_scale(silver: Mapping[datetime, float], window: Mapping[datetime, float], min_overlap: int = MIN_OVERLAP) -> float | None`; `apply_scale(points: Mapping[datetime, float], k: float) -> dict[datetime, float]`.

- [ ] **Step 1: Viết test (hàm thuần)**:
  - `test_compute_scale_recovers_known_factor`: `window = {t: v/2}` → `compute_scale(silver, window) == pytest.approx(2.0)`.
  - `test_compute_scale_uses_median_against_outlier`: một mốc lệch mạnh không đổi `k`.
  - `test_compute_scale_none_when_overlap_too_small` (11 mốc → `None`).
  - `test_compute_scale_ignores_zero_and_missing`: mốc có 0 ở một bên không đếm; toàn 0 → `None`, không `ZeroDivisionError`.
  - `test_real_windows_agree_after_rescale`: nạp `winA`, `winB` (từ fixture, `serie_0.timestamps/values`), `k = compute_scale(A, B)`; assert với mọi mốc chồng `abs(k*B[t] - A[t]) < 1e-4`, và mốc `2026-11-05T12:00:00Z` có `k*0.840159 ≈ 0.902153` (sai số 1e-4). **Nếu test này FAIL, dừng lại và báo người dùng**: giả định "chỉ khác hằng số nhân" của thiết kế sai.
- [ ] **Step 2: Chạy** → FAIL (module chưa có).
- [ ] **Step 3: Cài đặt** hai hàm bằng `statistics.median`, không thêm thư viện.
- [ ] **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(ingestion): add overlap-based scale reconciliation`.

---

### Task 4: Bảng chỉ số, cấu hình, Radar client

**Files:**
- Create: `services/ingestion/metrics.py`, `services/ingestion/config.py`
- Modify: `services/ingestion/radar_client.py`
- Test: `services/ingestion/tests/test_radar_client.py`

**Interfaces:**
- Produces (`metrics.py`): `@dataclass(frozen=True) MetricSpec(name: str, field: str, scaled: bool, lo: float, hi: float)`; `@dataclass(frozen=True) EndpointSpec(name: str, path: str, metrics: tuple[MetricSpec, ...])`; `ENDPOINTS: tuple[EndpointSpec, ...]` gồm 4 endpoint (`http_traffic`, `l7_attack`, `bot_class` với 2 metric `bot_share` field `bot` và `human_share` field `human`, `netflows`); `ALL_METRICS: tuple[str, ...]`.
- Produces (`config.py`): `class ConfigError(RuntimeError)`; `get_token() -> str` (đọc `CF_API_TOKEN`; rỗng hoặc bắt đầu bằng `replace-with` thì `ConfigError`); `BACKFILL_TARGET_DAYS = 365`; `CHUNK_DAYS = 28`; `OVERLAP_DAYS = 2`.
- Produces (`radar_client.py`): `@dataclass(frozen=True) Window(date_start: datetime | None, date_end: datetime | None, date_range: str | None)` với `Window.recent(days: int = 2)`, `Window.between(start, end)`, `as_params() -> dict`; `@dataclass RadarResponse(status_code: int, params: dict, payload: dict)` với thuộc tính `ok` (`status_code == 200` và `payload.get("success") is True`); `class RadarUnavailable(RuntimeError)`; `fetch(path: str, window: Window, *, client: httpx.Client | None = None, token: str | None = None, sleep: Callable[[float], None] = time.sleep) -> RadarResponse`.
- Hợp đồng `fetch`: trả `RadarResponse` cho **mọi** phản hồi HTTP cuối cùng (kể cả lỗi), `params` không chứa token; ném `RadarUnavailable` chỉ khi lỗi mạng/timeout hết số lần thử; `ConfigError` nếu thiếu token.

- [ ] **Step 1: Viết test** dùng `httpx.MockTransport` và `sleep` giả ghi lại các khoảng chờ:
  - `test_fetch_sends_bearer_and_expected_params` (header, `location=VN`, `aggInterval=1h`, `format=json`, `dateRange=2d`).
  - `test_window_between_uses_iso_utc_datestart_dateend`.
  - `test_retries_429_then_succeeds_with_backoff` (chờ `[1, 2]`).
  - `test_honours_retry_after_header`.
  - `test_backoff_caps_at_60s_and_gives_up_after_6_attempts_returns_last_response` (5xx liên tục: số lần gọi == 6, các khoảng chờ không vượt 60).
  - `test_400_401_403_not_retried` (đúng 1 lần gọi, trả `RadarResponse` với `ok False`).
  - `test_timeout_exhausted_raises_radar_unavailable`.
  - `test_params_never_contain_token`.
  - `test_get_token_rejects_missing_and_placeholder` (monkeypatch env: thiếu, rỗng, `replace-with-cloudflare-token` đều `ConfigError`; thông báo lỗi không chứa giá trị token).
  - `test_endpoints_cover_five_metrics` (`set(ALL_METRICS) == {...}`; bot_class có đúng 2 metric, `scaled False`).
- [ ] **Step 2: Chạy** → FAIL.
- [ ] **Step 3: Cài đặt.** Thay hàm stub `fetch_metric` bằng `fetch`. `httpx.Timeout(30, connect=10)`. Dùng vòng lặp thử lại tự viết (không thêm thư viện).
- [ ] **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(ingestion): add Radar client with retry and endpoint table`.

---

### Task 5: Parse, làm sạch Silver và các hàm DB

**Files:**
- Modify: `services/ingestion/silver.py`, `services/ingestion/bronze.py`
- Create: `services/ingestion/dbutil.py`, `services/ingestion/runs.py`
- Test: `services/ingestion/tests/test_silver_parse.py`, `services/ingestion/tests/test_db_layer.py` (integration)

**Interfaces:**
- Consumes: `MetricSpec`/`EndpointSpec`/`ENDPOINTS` (Task 4).
- Produces (`dbutil.py`): `use_conn(conn: psycopg.Connection | None) -> ContextManager[psycopg.Connection]`.
- Produces (`silver.py`): `parse_series(payload: dict, spec: MetricSpec) -> dict[datetime, float]` (UTC aware, đã làm sạch, đã loại trùng giữ giá trị cuối; payload không có `result.serie_0` hoặc `success` khác `True` thì `{}`); `upsert_metrics(metric: str, points: Mapping[datetime, float], *, source: str = "radar", conn=None) -> int`; `read_range(metric: str, start: datetime, end: datetime, *, conn=None) -> dict[datetime, float]`; `earliest_ts(metric: str, *, conn=None) -> datetime | None`. Xóa hàm stub `parse_response`.
- Produces (`bronze.py`): `save_raw_response(endpoint: str, params: dict, status_code: int, payload: dict, *, conn=None) -> None`; `purge_old(days: int = 30, *, conn=None) -> int`.
- Produces (`runs.py`): `start_run(*, conn=None) -> int`; `finish_run(run_id: int, status: str, rows_upserted: int, error: str | None, *, conn=None) -> None`.

- [ ] **Step 1: Test parse (thuần, dùng fixture thật)**:
  - `test_parse_http_traffic_fixture` (48 điểm, mọi timestamp tz-aware UTC, mọi giá trị ∈ [0,1]).
  - `test_parse_bot_class_splits_bot_and_human` (hai `MetricSpec` cho cùng payload, tổng `bot + human ≈ 100` tại mỗi mốc).
  - `test_drops_null_nan_inf_negative_and_out_of_range`; `test_duplicate_timestamps_keep_last`; `test_length_mismatch_uses_shorter_series_without_crash`; `test_success_false_payload_returns_empty`; `test_missing_serie_returns_empty`.
- [ ] **Step 2: Test DB (integration, `db_conn`, rollback)**:
  - `test_upsert_is_idempotent_and_updates_value` (ghi hai lần → số dòng không đổi, giá trị mới thắng, `source == 'radar'`).
  - `test_read_range_and_earliest_ts`.
  - `test_bronze_saves_verbatim_payload_and_status` (JSON khứ hồi bằng nhau; lưu cả khi `status_code=429`).
  - `test_purge_old_deletes_only_older_than_30_days` (chèn một dòng với `fetched_at = now() - 31 days`, một dòng mới; trả 1 và dòng mới còn lại).
  - `test_run_log_start_finish`.
- [ ] **Step 3: Chạy** → FAIL.
- [ ] **Step 4: Cài đặt.** Parse dùng `datetime.fromisoformat` (Python 3.11 hiểu đuôi `Z`) và `math.isfinite`. UPSERT dùng `executemany` với `ON CONFLICT (ts, metric) DO UPDATE SET value = EXCLUDED.value, updated_at = now(), source = EXCLUDED.source`. Payload Bronze dùng `psycopg.types.json.Jsonb`.
- [ ] **Step 5: Chạy** (`INTEGRATION=1 ...`) → PASS.
- [ ] **Step 6: Commit** `feat(ingestion): parse and persist Bronze and Silver`.

---

### Task 6: Pipeline một endpoint

**Files:**
- Create: `services/ingestion/pipeline.py`
- Test: `services/ingestion/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `fetch`, `Window`, `RadarResponse`, `RadarUnavailable` (Task 4); `parse_series`, `upsert_metrics`, `read_range` (Task 5); `save_raw_response`; `compute_scale`, `apply_scale` (Task 3).
- Produces: `@dataclass EndpointResult(endpoint: str, status: str, rows: int, message: str)` với `status ∈ {"ok", "skipped", "error", "empty"}`; `ingest_endpoint(spec: EndpointSpec, window: Window, *, client=None, conn=None, sleep=time.sleep) -> EndpointResult`.
- Hành vi: luôn lưu Bronze cho mọi phản hồi nhận được. `not ok` → `error`, không ghi Silver. Parse không ra điểm nào cho mọi metric → `empty` (không ghi). Với metric `scaled`: đọc Silver trên khoảng của cửa sổ, `k = compute_scale(...)`; Silver rỗng cho metric đó → `k = 1`; `k is None` (vùng chồng không đủ) → bỏ metric đó, trạng thái `skipped` kèm thông báo. Metric không `scaled` ghi nguyên. `RadarUnavailable` → `error`.

- [ ] **Step 1: Test** (`MockTransport` trả fixture; `db_conn`, integration):
  - `test_first_window_on_empty_silver_writes_with_k_1`.
  - `test_second_window_is_rescaled_to_silver`: ghi `winA` rồi `winB`; mốc `2026-11-05T12:00Z` trong Silver vẫn ≈ 0.902153 (1e-4), và các mốc mới của B (sau 8/11) liền mạch (không nhảy so với k·B).
  - `test_success_false_payload_writes_bronze_but_no_silver` (HTTP 200, `{"success": false, ...}` → `error`, một dòng Bronze, không dòng Silver).
  - `test_empty_series_reports_empty_and_writes_nothing`.
  - `test_insufficient_overlap_skips_scaled_metric_but_keeps_bronze`.
  - `test_all_zero_overlap_skips_without_exception`.
  - `test_percentage_metrics_not_rescaled` (bot_class ghi nguyên).
  - `test_http_500_exhausted_records_bronze_and_returns_error`.
- [ ] **Step 2: Chạy** → FAIL. **Step 3: Cài đặt.** **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(ingestion): add per-endpoint ingest pipeline with rescaling`.

---

### Task 7: Backfill

**Files:**
- Create: `services/ingestion/backfill.py`
- Test: `services/ingestion/tests/test_backfill.py`

**Interfaces:**
- Consumes: `ingest_endpoint`, `EndpointResult`, `earliest_ts`, `ENDPOINTS`, `Window`, hằng số config.
- Produces: `next_window(earliest: datetime | None, now: datetime, target_start: datetime, chunk_days: int = CHUNK_DAYS, overlap_days: int = OVERLAP_DAYS) -> tuple[datetime, datetime] | None` (hàm thuần; `earliest is None` → `(now - chunk, now)`; ngược lại kết thúc tại `earliest + overlap`, bắt đầu `end - chunk`, cắt không sớm hơn `target_start`; `earliest <= target_start` → `None`); `backfill_endpoint(spec: EndpointSpec, *, now: datetime | None = None, client=None, conn=None, sleep=time.sleep, pause_seconds: float = 0.5) -> list[EndpointResult]`; `run_backfill(**same) -> dict[str, list[EndpointResult]]`.
- Hành vi: `earliest` của endpoint = **min** `earliest_ts` trên các metric của nó (một trong số đó `None` → coi là rỗng). Lặp: lấy cửa sổ tiếp theo, `ingest_endpoint`; dừng khi `next_window` trả `None`, hoặc kết quả `empty` (API không còn dữ liệu cũ hơn), hoặc `error`/`skipped` (để lượt sau thử lại). Có trần số vòng (ví dụ `ceil(target_days / (chunk - overlap)) + 2`) để không bao giờ lặp vô hạn.

- [ ] **Step 1: Test:**
  - `test_next_window_empty_silver_is_latest_28_days`.
  - `test_next_window_overlaps_earliest_by_2_days` (`end == earliest + 2d`, `end - start == 28d`).
  - `test_next_window_clamps_to_target_start` và `test_next_window_none_when_target_reached`.
  - `test_backfill_stops_when_chunk_has_no_points` (Mock API: các cửa sổ gần có dữ liệu, cửa sổ cũ hơn trả chuỗi rỗng; assert số lần gọi hữu hạn, trả về kết quả cuối `empty`).
  - `test_backfill_is_resumable` (ghi trước một đoạn rồi chạy `backfill_endpoint`: cửa sổ đầu tiên chồng lên đoạn cũ nhất có sẵn, không gọi lại phần đã có) (integration).
  - `test_backfill_stops_on_error_without_raising`.
  - `test_backfill_loop_has_hard_iteration_cap` (Mock API luôn trả dữ liệu mới nhưng `earliest` không lùi; vẫn thoát).
- [ ] **Step 2: Chạy** → FAIL. **Step 3: Cài đặt.** **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(ingestion): add resumable newest-to-oldest backfill`.

---

### Task 8: Chu kỳ 5 phút và khởi động

**Files:**
- Modify: `services/ingestion/main.py`
- Test: `services/ingestion/tests/test_main.py`

**Interfaces:**
- Consumes: `ingest_endpoint`, `run_backfill`, `purge_old`, `start_run`, `finish_run`, `get_token`/`ConfigError`.
- Produces: `ingest_lock: threading.Lock`; `run_cycle() -> str` (trả `"success" | "partial" | "failed" | "skipped"`); `run_backfill_background() -> None`. Giữ nguyên `app = create_service_app("ingestion", run_cycle, {...})`. Xóa stub `backfill_if_empty`.
- Hành vi `run_cycle`: không lấy được khóa (đang backfill) → `"skipped"`, không ghi run. Ngược lại `start_run`, chạy `ingest_endpoint(spec, Window.recent())` cho từng endpoint, **bọc từng endpoint trong `try/except Exception`** (lỗi chỉ ghi nhận), `purge_old()`, `finish_run`: mọi endpoint `ok` → `success`; có endpoint `ok` và có lỗi → `partial`; không có endpoint `ok` → `failed`. `ConfigError` → log lỗi rõ, `finish_run(..., "failed", ...)`, **không ném ra ngoài** scheduler. Khi `settings.scheduler_enabled`, import `main` khởi động một luồng nền daemon chạy `run_backfill_background` (giữ `ingest_lock` trong lúc chạy), không chặn `/health`.

- [ ] **Step 1: Test** (monkeypatch các phụ thuộc, không cần mạng):
  - `test_run_cycle_success_when_all_endpoints_ok`.
  - `test_run_cycle_swallows_endpoint_exception_and_records_partial` (một endpoint ném `RuntimeError`, các endpoint khác vẫn được gọi).
  - `test_run_cycle_failed_when_nothing_ok`.
  - `test_run_cycle_config_error_logged_not_raised` (và `finish_run` ghi `failed`, thông báo không chứa token).
  - `test_run_cycle_skips_while_lock_held`.
  - `test_run_cycle_never_logs_token` (dùng `caplog`).
- [ ] **Step 2: Chạy** → FAIL. **Step 3: Cài đặt.** **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(ingestion): wire 5-minute cycle and background backfill`.

---

### Task 9: Nghiệm thu bằng dữ liệu thật, tài liệu, PR

**Files:**
- Create: `services/ingestion/README.md` (cách chạy, cách test, ý nghĩa giá trị Silver)
- Modify (cần trưởng nhóm đồng ý, commit riêng): `README.md` các mục 3.3, 3.5, 4.1 theo mục 7 của thiết kế

- [ ] **Step 1: Chạy toàn bộ test**: `INTEGRATION=1 bash services/ingestion/tests/run.sh` → tất cả PASS.
- [ ] **Step 2: Kiểm tra độ sâu tối đa của `dateStart`**: gọi thử `http/timeseries` với `dateStart` cách đây 365, 400 ngày (cửa sổ 28 ngày) để biết API có trả dữ liệu không; nếu 365 ngày không được, đặt `BACKFILL_TARGET_DAYS` ở mức lớn nhất được phép và ghi con số thật vào README của service.
- [ ] **Step 3: Chạy thật**: đảm bảo `.env` có token thật, `docker compose up -d --build warehouse-db ingestion`, `docker compose logs -f ingestion`. Kỳ vọng: backfill tiến dần, không lỗi token trong log.
- [ ] **Step 4: Nghiệm thu bằng SQL** (`make psql-warehouse`):
  - Độ sâu và số điểm: `SELECT metric, count(*), min(ts), max(ts) FROM silver.metrics_hourly GROUP BY metric;` → 5 chỉ số, khoảng 12 tháng (nêu con số thật), `max(ts)` gần hiện tại.
  - Không có khoảng trống lớn: `SELECT metric, max(ts - lag_ts) FROM (SELECT metric, ts, lag(ts) OVER (PARTITION BY metric ORDER BY ts) lag_ts FROM silver.metrics_hourly) s GROUP BY metric;` → khoảng trống lớn nhất nhỏ (ghi nhận nếu có).
  - Không có bước nhảy thang đo ở điểm nối lô: liệt kê 5 bước nhảy giờ-sang-giờ lớn nhất mỗi chỉ số MIN0_MAX (`abs(value - lag(value))`) và đối chiếu với các mốc ranh giới lô (`now - 26d·n`); các bước nhảy lớn nhất không được trùng ranh giới.
  - Idempotent: ghi lại `count(*)`, đợi một chu kỳ, `count(*)` chỉ tăng đúng số mốc giờ mới.
  - Bronze nguyên văn và không có token: `SELECT endpoint, status_code, fetched_at FROM bronze.raw_api_responses ORDER BY id DESC LIMIT 8;` và `SELECT count(*) FROM bronze.raw_api_responses WHERE params::text ILIKE '%bearer%' OR payload::text ILIKE '%cfut%';` → 0.
  - `SELECT * FROM silver.ingestion_runs ORDER BY id DESC LIMIT 5;` → `success`.
- [ ] **Step 5: Thử chịu lỗi**: `docker compose stop ingestion`, đặt `CF_API_TOKEN` sai, khởi động lại → log báo lỗi cấu hình/401 rõ ràng, service vẫn sống, `/health` OK; trả lại token đúng → tự phục hồi sau một chu kỳ. Ngắt giữa chừng khi đang backfill (`docker compose restart ingestion`) → chạy tiếp từ chỗ dở.
- [ ] **Step 6: Viết `services/ingestion/README.md`** và (khi được đồng ý) sửa README gốc. Commit `docs(ingestion): add run and test guide`, riêng một commit `docs(readme): align ingestion section with measured API limits`.
- [ ] **Step 7: Đẩy nhánh và mở PR vào `develop`** (theo CONTRIBUTING, không push thẳng). Lưu ý trong mô tả PR: nhánh dựa trên `chore/scaffold`, nên PR scaffold cần được merge trước hoặc PR này sẽ chứa cả các commit scaffold. Nêu rõ 5 điều cần báo nhóm trong thiết kế mục 9. Chỉ tích checkbox Thành viên 1 trong issue #2 khi tất cả bước nghiệm thu trên đã đạt.
