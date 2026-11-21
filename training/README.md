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

Gộp giá trị theo giờ thành **trung bình theo ngày UTC** (metric mặc định `http_traffic`), rồi tạo:

| Cột | Ý nghĩa |
| :--- | :--- |
| `value` | trung bình ngày (nhãn của bộ hồi quy) |
| `lag_1`, `lag_7` | giá trị 1 và 7 ngày trước |
| `roll_mean_3`, `roll_mean_7` | trung bình trượt 3 và 7 ngày **trước đó** (không gồm ngày hiện tại, tránh rò rỉ) |
| `dow` | thứ trong tuần (0 = thứ Hai) |

Ngày thiếu dữ liệu được chèn NaN để lag đúng lịch; dòng thiếu lag bị bỏ. Cần **≥ 7 ngày liên tục** mới dự báo được.

## 2. Huấn luyện

```bash
pip install -r services/prediction/requirements.txt   # pandas, scikit-learn, joblib, psycopg
export WAREHOUSE_DSN=postgresql://logic_user:<mật_khẩu>@localhost:5432/<WAREHOUSE_DB>

python training/train_models.py                 # đọc Silver
python training/train_models.py --demo          # dữ liệu giả, không cần DB
python training/train_models.py --k 3 --risk-percentile 80 --metric http_traffic
```

| Tham số | Mặc định | Ý nghĩa |
| :--- | :--- | :--- |
| `--metric` | `http_traffic` | metric trong `silver.metrics_hourly` |
| `--demo` | tắt | dùng dữ liệu giả (180 ngày) |
| `--k` | tự chọn | ép số cụm; mặc định chọn k ∈ [2, 6] có Silhouette cao nhất |
| `--risk-percentile` | 75 | ngưỡng "High" = percentile của tập **train** |
| `--min-days` | 30 | Silver ít hơn số ngày này thì **tự chuyển sang demo** (có log cảnh báo) |
| `--out-dir` | `models/` | thư mục lưu kết quả |

Chia train/test **theo thời gian** (80% đầu train, 20% cuối test), không xáo trộn. Seed cố định 42.

### Ba mô hình

| File | Mô hình | Đầu vào | Đầu ra |
| :--- | :--- | :--- | :--- |
| `kmeans.joblib` | `StandardScaler` + `KMeans` | `value`, `dev_7` (= value − roll_mean_7), `diff_1` (= value − lag_1) | `cluster_id` |
| `rf_regressor.joblib` | `RandomForestRegressor` (300 cây) | `lag_1, lag_7, roll_mean_3, roll_mean_7, dow` | chỉ số lưu lượng ngày mai |
| `rf_classifier.joblib` | `RandomForestClassifier` (300 cây, `class_weight=balanced`) | như bộ hồi quy | P(High); High = `value` > percentile của train |

Mỗi `.joblib` là dict `{"model", "features", ...metadata}`: `features` là **thứ tự cột** service phải dùng; metadata gồm `data_source` (`silver`/`demo`), `metric`, `trained_at`, `n_days`, `train_range`, `test_range`. Classifier có thêm `risk_threshold`, `risk_percentile`.

### `models/metrics.json`

| Khóa | Nội dung |
| :--- | :--- |
| `kmeans` | `k`, `silhouette`, `scores_by_k`, `cluster_profile` (mean/count từng cụm) |
| `rf_regressor` | `mae`, `rmse`, `baseline_lag1_mae` (đoán "ngày mai = hôm nay"; MAE phải thấp hơn mốc này) |
| `rf_classifier` | `accuracy`, `f1`, `risk_threshold`, `test_high_ratio` |

> Nếu `data_source` = `demo`, các số này **không** phản ánh dữ liệu thật. Không đưa vào báo cáo. Silhouette < 0.25 thì cụm không tách rõ (script tự cảnh báo).

## 3. Service

Cả hai là FastAPI + APScheduler (khung ở `backend/common/runner.py`), đọc `models/` qua `MODELS_DIR`.

| Service | Port | Lịch | Nhiệm vụ |
| :--- | :--- | :--- | :--- |
| `clustering` | 8002 | cron hằng ngày 00:30 giờ VN (`CLUSTERING_CRON_HOUR/MINUTE`) | gán cụm cho **mọi ngày** có đủ đặc trưng |
| `prediction` | 8003 | mỗi 5 phút (`PREDICTION_INTERVAL_SECONDS`) | dự báo ngày mai (liên tục + rời rạc) |

Biến môi trường: `WAREHOUSE_DSN`, `MART_DSN`, `MODELS_DIR` (compose mount `./models:/app/models:ro`), `SCHEDULER_ENABLED`, `TZ_LOCAL`.

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
| `cluster_results` | `date` | `cluster_id`, `cluster_name`, `features` (JSONB: `value`, `dev_7`, `diff_1`, `metric`), `computed_at` | clustering |
| `forecast_continuous` | `target_date` | `predicted_value`, `model_name`, `created_at` | prediction |
| `forecast_discrete` | `target_date` | `label` (`Cao`/`Thấp`), `probability` (= P(High)), `model_name`, `created_at` | prediction |
| `service_runs` | `id` | `service`, `started_at`, `finished_at`, `status` (`running`/`success`/`failed`), `error` | cả hai |

Quy ước:

- **Ngày tính theo UTC**, khớp lúc huấn luyện.
- **`target_date` (ngày mai)** = ngày UTC liền sau ngày **đầy đủ** mới nhất trong Silver (bỏ ngày UTC hiện tại vì chưa đủ 24 giờ).
- **`cluster_name`** xếp theo `value` tâm cụm tăng dần: k=2 → `Thấp`, `Cao`; k=3 → `Thấp`, `Bình thường`, `Cao`; k>3 → `Cụm 1..k`.
- **`label`** = `Cao` nếu P(High) ≥ 0.5, ngược lại `Thấp`.
- **`model_name`** = `<rf_regressor|rf_classifier>/<data_source>/<trained_at>`.
- Thiếu mô hình → `FileNotFoundError` (ghi `service_runs.status='failed'`). Thiếu dữ liệu → prediction ghi log cảnh báo, trả 0 dòng.

## 4. Kiểm thử

```bash
pytest training/tests services/prediction/tests services/clustering/tests   # giữ đúng thứ tự (xung đột sys.path)
```

## 5. Lưu ý và việc còn mở

- Sau khi đổi `FEATURES`/`cluster_matrix`: **train lại**, và sửa cả bản sao `cluster_matrix` trong `services/clustering/tasks.py` (container clustering không có `training/`; test đối chiếu hai bản).
- Mô hình lưu `.joblib` (README gốc mục 5.4 ghi `.pkl`). `models/` chưa nằm trong `.gitignore`: file nhẹ thì commit, nặng thì dùng LFS.
- **Chưa chốt với nhóm:** metric mục tiêu `http_traffic` (README gốc 5.3 nói nhãn rủi ro theo `l7_attack`), ngưỡng P(High) 0.5, percentile 75, cách đặt `model_name`.
- Service dùng đúng phiên bản `scikit-learn~=1.6.0`: train bằng phiên bản khác có thể không nạp được `.joblib`.
