# Phần Machine Learning

Gồm: huấn luyện offline (`training/`), mô hình đã lưu (`models/`), hai service chỉ **nạp mô hình và chạy** (`services/clustering/`, `services/prediction/`).

```text
Silver: silver.metrics_hourly ──► training/train_models.py ──► models/*.joblib + metrics.json
        (ts, value, metric)                                          │ (nạp, không huấn luyện lại)
                                              ┌──────────────────────┴───────────────┐
                                              ▼                                       ▼
                                   services/clustering (00:30 VN)        services/prediction (5 phút)
                                              │                                       │
                                  gold.cluster_results            gold.forecast_continuous / forecast_discrete
                                              └──────── gold.service_runs (nhật ký) ──┘
```

## 1. Đặc trưng (`services/prediction/features.py`)

Quyết định theo Issue #13; mọi tham số nằm trong `services/prediction/ml_config.json`.

- **Ngày tính theo giờ Việt Nam** (`Asia/Ho_Chi_Minh`, 17:00 UTC hôm trước đến 17:00 UTC hôm sau). Silver vẫn lưu UTC.
- **Ngày chỉ hợp lệ khi đủ 24 mốc giờ.** Ngày thiếu hoặc chưa đủ (thường là ngày cuối vì Radar trễ) là NaN, không bao giờ được dùng.
- **Dự báo D+2 tính từ ngày đủ dữ liệu cuối** (`horizon_days = 2`): đặc trưng của ngày đích D chỉ dùng ngày ≤ D−2. Khi hôm qua đã đủ dữ liệu thì D = ngày mai, đúng với API ("ngày mai" theo giờ VN). Vì không cần dữ liệu của hôm nay (chưa đủ giờ) nên không phải dự báo từ ngày thiếu.

Bộ hồi quy (metric `http_traffic`):

| Cột | Ý nghĩa |
| :--- | :--- |
| `value` | trung bình ngày (nhãn của bộ hồi quy) |
| `lag_2`, `lag_7` | giá trị 2 và 7 ngày trước ngày đích |
| `roll_mean_3`, `roll_mean_7` | trung bình trượt 3 và 7 ngày kết thúc ở D−2 |
| `dow` | thứ của ngày đích (0 = thứ Hai) |

Bộ phân loại dùng thêm `risk_lag_2`, `risk_lag_7`, `risk_roll_mean_3`, `risk_roll_mean_7` tính từ metric rủi ro `l7_attack` (và `risk_value` làm nhãn gốc). Lag của ngày thiếu giữ NaN để đúng lịch; dòng thiếu đặc trưng bị bỏ. Cần khoảng 10 ngày liên tục gần nhất mới dự báo được.

Phân cụm dùng đặc trưng riêng theo ngày VN (README gốc 5.2): `http_mean` (trung bình `http_traffic`), `l7_max` (max `l7_attack`), `bot_mean` (trung bình `bot_share`, đơn vị %).

## 2. Huấn luyện

```bash
pip install -r services/prediction/requirements.txt   # pandas, scikit-learn, joblib, psycopg
export WAREHOUSE_DSN=postgresql://logic_user:<mật_khẩu>@localhost:5432/<WAREHOUSE_DB>

python training/train_models.py                 # đọc Silver
python training/train_models.py --demo          # dữ liệu giả, không cần DB
python training/train_models.py --k 3 --risk-percentile 80 --metric http_traffic --risk-metric l7_attack
```

| Tham số | Mặc định | Ý nghĩa |
| :--- | :--- | :--- |
| `--metric` | `http_traffic` | metric đích của bộ hồi quy |
| `--risk-metric` | `l7_attack` | metric tạo nhãn rủi ro |
| `--demo` | tắt | dùng dữ liệu giả (180 ngày, đủ 3 metric) |
| `--k` | 3 (config) | ép số cụm; `--k` bỏ trống trong code (`k=None`) thì chọn k ∈ [2, 6] có Silhouette cao nhất |
| `--risk-percentile` | 75 | ngưỡng "High" = percentile của tập **train** (theo thời gian) |
| `--min-days` | 30 | Silver ít hơn số ngày này thì **tự chuyển sang demo** (có log cảnh báo) |
| `--out-dir` | `models/` | thư mục lưu kết quả |

Chia train/test **theo thời gian** (80% đầu train, 20% cuối test), không xáo trộn. Seed cố định 42.

### Ba mô hình

| File | Mô hình | Đầu vào | Đầu ra |
| :--- | :--- | :--- | :--- |
| `kmeans.joblib` | `StandardScaler` + `KMeans` (k = 3) | `http_mean`, `l7_max`, `bot_mean` | `cluster_id` |
| `rf_regressor.joblib` | `RandomForestRegressor` (300 cây) | `lag_2, lag_7, roll_mean_3, roll_mean_7, dow` | trung bình `http_traffic` của ngày đích |
| `rf_classifier.joblib` | `RandomForestClassifier` (300 cây, `class_weight=balanced`) | đặc trưng hồi quy + 4 đặc trưng `risk_*` | P(High); High = trung bình ngày `l7_attack` > percentile của train |

Mỗi `.joblib` là dict `{"model", "features", ...metadata}`: `features` là **thứ tự cột** service phải dùng; metadata gồm `data_source` (`silver`/`demo`), `metric`, `risk_metric`, `horizon_days`, `timezone`, `trained_at`, `n_days`, `train_range`, `test_range`. Classifier có thêm `risk_threshold`, `risk_percentile`. Service từ chối nạp mô hình có `horizon_days` khác cấu hình (phải train lại).

### `models/metrics.json`

| Khóa | Nội dung |
| :--- | :--- |
| `kmeans` | `k`, `silhouette`, `scores_by_k`, `cluster_profile` (mean/count từng đặc trưng theo cụm) |
| `rf_regressor` | `mae`, `rmse`, `baseline_naive_mae` (đoán "ngày đích = giá trị ngày đủ gần nhất", lag nhỏ nhất; MAE phải thấp hơn mốc này) |
| `rf_classifier` | `risk_metric`, `risk_percentile`, `risk_threshold` (đơn vị của metric rủi ro), `proba_cutoff`, `accuracy`, `f1`, `train_high_ratio`, `test_high_ratio`, `n_train_days`, `n_test_days` |

> Nếu `data_source` = `demo`, các số này **không** phản ánh dữ liệu thật. Không đưa vào báo cáo. Silhouette < 0.25 thì cụm không tách rõ (script tự cảnh báo).

## 3. Service

Cả hai là FastAPI + APScheduler (khung ở `backend/common/runner.py`), đọc `models/` qua `MODELS_DIR`.

| Service | Port | Lịch | Nhiệm vụ |
| :--- | :--- | :--- | :--- |
| `clustering` | 8002 | cron hằng ngày 00:30 giờ VN (`CLUSTERING_CRON_HOUR/MINUTE`) | gán cụm cho **mọi ngày** có đủ đặc trưng |
| `prediction` | 8003 | mỗi 5 phút (`PREDICTION_INTERVAL_SECONDS`) | dự báo ngày đích (liên tục + rời rạc) |

Biến môi trường: `WAREHOUSE_DSN`, `MART_DSN`, `MODELS_DIR` (compose mount `./models:/app/models:ro` cho cả hai service), `SCHEDULER_ENABLED`, `TZ_LOCAL`.

### Cách gọi

```bash
# Chạy qua Docker (cần đã train, có models/*.joblib)
docker compose up -d --build clustering prediction
curl http://localhost:8002/health        # {"status":"ok","service":"clustering"}
curl http://localhost:8003/health

# Chạy tay một lượt, không qua HTTP (local; đặt WAREHOUSE_DSN, MART_DSN, MODELS_DIR=$PWD/models trước)
(cd services/clustering && PYTHONPATH=../../backend:../prediction python -c "from tasks import run_all; run_all()")
(cd services/prediction && PYTHONPATH=../../backend python -c "from tasks import run_all; run_all()")
```

> **`POST /run` hiện trả `501 Not implemented`** (stub của khung chung). Muốn chạy ngay: dùng lệnh chạy tay ở trên, hoặc `docker compose restart <service>` (scheduler chạy lại theo lịch). Các endpoint `GET /api/clusters`, `/api/forecast/*` trong `services/api/routers/ml.py` cũng còn là stub 501.

### Đầu vào / đầu ra

**Đầu vào:** `silver.metrics_hourly` (cột `ts`, `value`, `metric`) qua `WAREHOUSE_DSN`. **Đầu ra:** Mart qua `MART_DSN`, tất cả dùng `UPSERT` nên chạy lặp vẫn idempotent.

| Bảng Gold | Khóa | Cột | Do |
| :--- | :--- | :--- | :--- |
| `cluster_results` | `date` | `cluster_id`, `cluster_name`, `features` (JSONB: `http_mean`, `l7_max`, `bot_mean`, `metric` = `http_traffic`), `computed_at` | clustering |
| `forecast_continuous` | `target_date` | `predicted_value`, `model_name`, `created_at` | prediction |
| `forecast_discrete` | `target_date` | `label` (`Cao`/`Thấp`), `probability` (= P(Cao), kể cả khi nhãn là Thấp), `model_name`, `created_at` | prediction |
| `service_runs` | `id` | `service`, `started_at`, `finished_at`, `status` (`running`/`success`/`failed`), `error` | cả hai |

Quy ước:

- **Ngày (`date`, `target_date`) tính theo giờ VN**, chỉ ngày đủ 24 giờ.
- **`target_date`** = ngày đủ dữ liệu mới nhất + 2. Ví dụ chạy ngày 21/11 (VN) khi 20/11 đã đủ thì `target_date` = 22/11. Nếu Silver chậm và 20/11 chưa đủ, dòng được ghi cho 21/11. Mỗi lượt upsert 1 dòng mỗi bảng; dòng các ngày trước được giữ.
- **`cluster_name`** theo tâm cụm (README 5.2): `Bất thường` = cụm có `l7_max` hoặc `bot_mean` cao nhất (chuẩn hóa); trong hai cụm còn lại `Cao điểm` = `http_mean` cao hơn, `Bình thường` = thấp hơn. k ≠ 2, 3 dùng `Cụm 1..k` theo traffic tăng dần.
- **`label`** = `Cao` nếu P(High) ≥ 0.5, ngược lại `Thấp`.
- **`model_name`** = `<rf_regressor|rf_classifier>/<data_source>/<trained_at>`.
- Thiếu mô hình hoặc mô hình khác `horizon_days` → lỗi (ghi `service_runs.status='failed'`). Thiếu dữ liệu → prediction ghi log cảnh báo và trả 0 dòng (vẫn `success`, xem mục 5).

Payload mẫu cho Frontend:

```json
// gold.cluster_results
{"date": "2026-11-20", "cluster_id": 1, "cluster_name": "Bất thường",
 "features": {"http_mean": 101.6, "l7_max": 55.2, "bot_mean": 54.8, "metric": "http_traffic"}}
// gold.forecast_discrete
{"target_date": "2026-11-22", "label": "Thấp", "probability": 0.31, "model_name": "rf_classifier/silver/2026-11-21T03:00:00+00:00"}
```

## 4. Kiểm thử

```bash
pytest training/tests services/prediction/tests services/clustering/tests   # giữ đúng thứ tự (xung đột sys.path)
```

## 5. Lưu ý và việc còn mở

- Sau khi đổi `ml_config.json` (đặc trưng, metric, horizon, cụm): **train lại**. Service từ chối mô hình khác `horizon_days`. Container clustering và prediction đều đọc cùng `ml_config.json` (copy lúc build), không còn bản sao `cluster_matrix`.
- Mô hình lưu `.joblib` (README gốc mục 5.4 ghi `.pkl`). `models/` chưa nằm trong `.gitignore`: file nhẹ thì commit, nặng thì dùng LFS.
- Percentile 75 và cutoff 0.5 là **cấu hình khởi đầu**; chỉnh bằng validation khi có dữ liệu thật.
- Trước khi tích hợp vào develop (Định, Issue #13): để `common.runner` sở hữu `gold.service_runs` và khóa chạy (hiện `run_prediction`/`run_clustering` tự ghi), thiếu dữ liệu đầu vào thì không báo `success`, và chạy kiểm thử Docker qua Admin.
- Service dùng đúng phiên bản `scikit-learn~=1.6.0`: train bằng phiên bản khác có thể không nạp được `.joblib`.
- Kết quả train bằng dữ liệu `demo` không phản ánh Silver thật; train lại với `WAREHOUSE_DSN` trước khi báo cáo.
