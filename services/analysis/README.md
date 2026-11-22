# Data Analysis Service – Cyber Radar VN

Dịch vụ phân tích thống kê chuỗi thời gian an ninh mạng (Việt Nam) trong kiến trúc Medallion của Cyber Radar VN.

## 1. Vai trò trong hệ thống

- **Đọc:** `silver.metrics_hourly` (Data Warehouse - PostgreSQL `warehouse-db`).
- **Xử lý:** Làm sạch, kiểm tra chất lượng, tổng hợp thống kê, tách xu hướng, phân tích mẫu hình theo thời gian (temporal pattern), tương quan Pearson và phát hiện bất thường.
- **Ghi:** Tầng `gold` (Data Mart - PostgreSQL `mart-db`) sẵn sàng cho Backend API và Dashboard trực quan hóa.
- **Chu kỳ:** Mặc định chạy tự động mỗi 300 giây (5 phút) qua APScheduler hoặc nhận kích hoạt thủ công qua `POST /run`.

## 2. Các chức năng chính

1. **Resampling (`resampling.py`):**
   - Tổng hợp các chỉ số theo `day`, `week`, `month`.
   - Tính toán `mean`, `min`, `max`.
   - Tuần bắt đầu từ thứ Hai; múi giờ quy chuẩn `Asia/Ho_Chi_Minh`.
   - Không tự nội suy dữ liệu cho khoảng thời gian bị thiếu.
   - Lưu vào: `gold.timeseries_resampled`.

2. **Histogram (`histogram.py`):**
   - Phân chia 20 khoảng tần suất cho 3 chỉ số trọng yếu: `http_traffic`, `l7_attack`, `bot_share`.
   - Dải động thích ứng tự động, không cố định [0, 1] do dữ liệu sau rescaling có thể vượt quá 1.0.
   - Xử lý ca suy biến khi mọi giá trị bằng nhau, bảo toàn $\sum \text{count} = N$.
   - Lưu vào: `gold.histogram`.

3. **Trend Analysis (`trend.py`):**
   - Tách thành phần xu hướng bằng `statsmodels.tsa.seasonal.seasonal_decompose` (additive).
   - Ưu tiên chuỗi tháng (`period = 12`, yêu cầu $\ge 24$ điểm liên tục).
   - Fallback sang chuỗi tuần (`period = 4`, yêu cầu $\ge 8$ điểm liên tục).
   - Loại bỏ các giá trị `NaN` ở đầu và cuối trend. Bỏ qua an toàn khi dữ liệu không đủ 2 chu kỳ.
   - Lưu vào: `gold.trend`.

4. **Temporal Pattern Analysis (`temporal_patterns.py`):**
   - Tính giá trị TRUNG BÌNH theo 3 bucket thời gian (bucket averages — chưa phải kết luận chu kỳ lặp lại):
     - `hour_of_day`: 0–23
     - `day_of_week`: 0–6 (0 là Thứ Hai, 6 là Chủ Nhật)
     - `month`: 1–12
   - Múi giờ địa phương `Asia/Ho_Chi_Minh`.
   - `assess_temporal_cycle_completeness()` đánh giá riêng khả năng lặp lại (mỗi bucket phải lặp ở ≥ 2 chu kỳ độc lập: ngày/tuần ISO/năm); kết quả chỉ ghi log vận hành.
   - Lưu vào: `gold.seasonal` (tên bảng giữ nguyên vì hợp đồng API/frontend).

5. **Correlation Analysis (`correlation.py`):**
   - Tính ma trận tương quan Pearson giữa 5 chỉ số: `http_traffic`, `l7_attack`, `bot_share`, `human_share`, `netflows`.
   - Căn chỉnh dữ liệu theo timestamp; xử lý thiếu theo từng cặp (pairwise complete, $N \ge 3$).
   - Bỏ qua các cặp có zero-variance; không thay thế giá trị không xác định bằng 0.
   - Đảm bảo tính đối xứng $r(x, y) = r(y, x)$ và $r \in [-1.0, 1.0]$.
   - Lưu vào: `gold.correlation`.

6. **Data Quality & Anomaly Detection (`quality.py`):**
   - Kiểm tra NULL, NaN, Infinity, trùng lặp mốc giờ, khoảng trống thời gian.
   - Nhận diện điểm bất thường thống kê bằng Robust Z-score (Median & MAD) kết hợp IQR:
     $$\text{Robust Z-score} = 0.6745 \times \frac{x - \text{median}(x)}{\text{MAD}}$$
   - Phân biệt lỗi chất lượng dữ liệu với biến động an ninh mạng thực tế.
   - Báo cáo nội bộ và ghi log, không làm thay đổi dữ liệu Silver và không tự tạo bảng schema.

7. **Data Freshness (`writer.py`):**
   - Ghi mốc thời gian Silver mới nhất (`latest_silver_ts`) vào `gold.data_freshness` khi và chỉ khi toàn bộ chu kỳ phân tích hoàn tất thành công trong một Transaction duy nhất.

## 3. Cấu trúc thư mục

```text
services/analysis/
├── Dockerfile                   # Cấu hình container dịch vụ
├── requirements.txt             # Thư viện runtime
├── requirements-dev.txt         # Thư viện phục vụ kiểm thử (pytest)
├── main.py                      # Điểm vào FastAPI và scheduler
├── tasks.py                     # Điều phối 6 tác vụ phân tích
├── reader.py                    # Đọc dữ liệu từ silver.metrics_hourly
├── quality.py                   # Data quality và anomaly detection
├── resampling.py                # Tổng hợp Day, Week, Month
├── histogram.py                 # 20 bins histogram
├── trend.py                     # Trend decomposition (statsmodels)
├── temporal_patterns.py         # Trung bình theo giờ, thứ, tháng (temporal pattern)
├── correlation.py               # Ma trận tương quan Pearson
├── writer.py                    # Ghi nguyên tử vào Data Mart
├── README.md                    # Tài liệu kỹ thuật dịch vụ
├── TEST_REPORT.md               # Báo cáo chi tiết 70 test case
├── FINAL_REVIEW.md              # Báo cáo review bàn giao
└── tests/                       # Bộ kiểm thử tự động
    ├── conftest.py              # Fixtures dữ liệu mẫu
    ├── run.sh                   # Script chạy test trong Docker
    ├── test_reader.py
    ├── test_quality.py
    ├── test_resampling.py
    ├── test_histogram.py
    ├── test_trend.py
    ├── test_temporal_patterns.py
    ├── test_correlation.py
    ├── test_writer.py
    ├── test_tasks.py
    └── test_service_integration.py
```

## 4. Cấu hình và biến môi trường

Khai báo trong file `.env` tại thư mục gốc:

| Biến | Ý nghĩa | Mặc định |
| :--- | :--- | :--- |
| `WAREHOUSE_DSN` | Chuỗi kết nối Postgres Data Warehouse | `postgresql://logic_user:...@warehouse-db:5432/...` |
| `MART_DSN` | Chuỗi kết nối Postgres Data Mart | `postgresql://logic_user:...@mart-db:5433/...` |
| `ANALYSIS_INTERVAL_SECONDS` | Chu kỳ chạy tự động của APScheduler | `300` (giây) |
| `SCHEDULER_ENABLED` | Bật/tắt scheduler nền | `true` |
| `TZ_LOCAL` | Múi giờ địa phương cho bucket lịch | `Asia/Ho_Chi_Minh` |

## 5. Hướng dẫn chạy và kiểm thử

### Chạy bằng Docker Compose
```bash
docker compose up -d analysis
```

### Chạy cục bộ
```bash
# Kích hoạt môi trường ảo
source .venv/bin/activate  # Hoặc: .venv\Scripts\activate trên Windows
export PYTHONPATH="services/analysis:backend"

# Chạy ứng dụng uvicorn
uvicorn main:app --host 0.0.0.0 --port 8001
```

### Chạy kiểm thử tự động (Pytest)
```bash
# Chạy toàn bộ test
pytest services/analysis/tests -v

# Chạy test trong môi trường Docker cô lập
bash services/analysis/tests/run.sh
```

