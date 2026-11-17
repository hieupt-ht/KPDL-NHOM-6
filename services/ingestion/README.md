# Ingestion service

Thu thập dữ liệu bất thường mạng Việt Nam (`location=VN`) từ Cloudflare Radar API, ghi vào warehouse-db theo mô hình Medallion.

- **Bronze** (`bronze.raw_api_responses`): JSON thô của từng lần gọi API, giữ 30 ngày.
- **Silver** (`silver.metrics_hourly`): chuỗi theo giờ, khóa `(metric, ts)`, ghi idempotent (`ON CONFLICT`).
- **Nhật ký** (`silver.ingestion_runs`): mỗi chu kỳ một dòng `success` / `partial` / `failed`.

## Chạy

Cần `CF_API_TOKEN` trong `.env` (token chỉ đọc Radar; không bao giờ được ghi vào log).

```bash
docker compose up -d warehouse-db ingestion
docker compose logs -f ingestion
```

- Chu kỳ 5 phút (`INGESTION_INTERVAL_SECONDS`), mỗi lần lấy cửa sổ `dateRange=2d`.
- Khi khởi động, một luồng nền backfill lùi dần từ mới đến cũ (lô 28 ngày, chồng 2 ngày) tới 365 ngày. Chạy tiếp được sau khi bị ngắt; lỗi thì thử lại sau 15 phút. Chu kỳ 5 phút tạm nhường trong lúc backfill.
- Lần đầu mất khoảng 5 phút. Nếu đổi schema, phải tạo lại volume: `docker compose down -v` rồi `up`.

## Kiểm thử

```bash
bash services/ingestion/tests/run.sh                 # test đơn vị (không cần DB)
INTEGRATION=1 bash services/ingestion/tests/run.sh   # thêm test với warehouse-db thật (cần stack đang chạy)
```

Test tích hợp chạy trong transaction và rollback, không làm bẩn dữ liệu.

## Ý nghĩa giá trị trong Silver

| metric | nguồn | ý nghĩa |
|---|---|---|
| `http_traffic`, `l7_attack`, `netflows` | Radar, chuẩn hóa `MIN0_MAX` | mức tương đối theo thời gian |
| `bot_share`, `human_share` | `bot_class` | tỷ lệ phần trăm (0–100), không quy đổi |

Radar chuẩn hóa `MIN0_MAX` **theo từng cửa sổ truy vấn**, nên cùng một giờ có thể ra giá trị khác nhau ở hai lần gọi. Dịch vụ lấy các cửa sổ chồng nhau rồi nhân hệ số `k = median(Silver / cửa sổ mới)` (cần ít nhất 12 điểm chồng) để các đoạn nối liền thang đo. Hệ quả: **giá trị có thể lớn hơn 1** (đã thấy tới ~1,31); đây là bình thường, không phải lỗi. Nơi dùng cần coi đây là thang tương đối, không phải xác suất.

## Giới hạn đã biết

- Radar có dữ liệu ≥ 500 ngày nhưng độ sâu mục tiêu đặt là **365 ngày** (`BACKFILL_TARGET_DAYS`).
- Nếu ingestion ngừng hơn ~36 giờ, cửa sổ 2 ngày không đủ 12 điểm chồng nên chu kỳ bỏ qua cửa sổ đó và để lại **khoảng trống** trong Silver; backfill chỉ đi về quá khứ nên không lấp được. Cần nạp bù thủ công.
- Một số giờ có giá trị 0 thật (ví dụ 2026-07-16 11:00); các metric dùng thang quy đổi bỏ qua điểm bằng 0 khi tính `k`.
