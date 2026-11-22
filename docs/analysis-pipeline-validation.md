> Cập nhật 22/11/2026: đã gỡ đăng nhập/Keycloak/Viewer/Admin theo yêu cầu chủ dự án. Các hướng dẫn xác thực và số lượng container bên dưới là ghi nhận lịch sử; cách chạy hiện tại ở [frontend-live-integration.md](frontend-live-integration.md). Stack hiện có 8 service, dashboard/API truy cập trực tiếp, chỉ /run nội bộ dùng token.

# Nghiệm thu Analysis → Gold → API → Dashboard

Nhánh tích hợp từ develop `0e6adc7` (20/11/2026). Analysis đã có trong develop qua PR #15; Clustering/Prediction thật vẫn nằm trên nhánh ML, không tự merge vào đây.

## Kiểm tra tự động

```powershell
./services/api/tests/run.ps1 -Mode All
docker compose build frontend
```

Mode All nay có test `test_analysis_pipeline_e2e.py`: tạo 84 ngày hourly × 5 metric tổng hợp trong database `test_*`, đăng nhập Keycloak Viewer/Admin, gọi Jobs API, theo dõi đúng run_id, kiểm tra Analysis thật ghi Gold rồi đọc qua API thật. Test đòi hỏi success và đúng một journal, không chấp nhận failed như test trigger tổng quát. Unit/Integration không chạy test cần stack này.

Fixture chỉ dùng ở database thử riêng, không trộn vào dữ liệu người dùng. source='radar' trong fixture nhằm đi qua bộ lọc production của reader, không có nghĩa đây là dữ liệu Radar thu thập thật. TEST_WAREHOUSE_ADMIN_DSN chỉ được Compose thử cung cấp; test kiểm tra tên database trước khi ghi/xóa.

Các kiểm tra gồm: 404 trước khi tính; Viewer không chạy job; 202 + ID; một journal hoàn tất; bucket ngày Việt Nam trả instant UTC; số đo >1; limit/offset/X-Total-Count; đủ bin/bucket/correlation/trend; histogram tổng số quan sát; snapshot từ chối start/end; freshness bỏ qua NaN/Infinity/-Infinity/NULL và nguồn demo mới hơn.

CI chạy thêm 100 unit test Analysis bằng Docker, ngoài backend/Keycloak và smoke 9 container/SSO hiện có.

## Lỗi tích hợp được sửa

Reader freshness gọi `isinf(double precision)`, hàm không tồn tại trên PostgreSQL 16. Mock unit test trước đó chỉ kiểm tra chuỗi SQL nên không phát hiện. Thay bằng loại trực tiếp ba giá trị float8 đặc biệt NaN/Infinity/-Infinity; vẫn lọc NULL và nguồn radar. Không đổi schema hay thuật toán Analysis.

Biểu đồ Trend ghép union timestamp của mean và trend theo instant, sắp xếp rồi điền null vào bucket thiếu. Không ghép theo index, không biến bucket bị trim ở hai đầu thành số 0. Test bao gồm UTC/+07 tương đương và giá trị 0 thật.

Histogram live chỉ gửi request cho HTTP/L7/Bot theo phạm vi Analysis hiện tại. Human/Netflow hiện thông báo chưa hỗ trợ, các biểu đồ khác giữ chỉ số đã chọn; demo mode giữ phân phối minh họa. Không tự mở rộng thuật toán histogram khi chưa thống nhất.

## Điều kiện nghiệm thu dữ liệu thật

Cần CF_API_TOKEN hợp lệ được người triển khai cấu hình trong `.env`; không gửi token vào chat, issue hoặc log. Không xem fixture hoặc CI đạt là bằng chứng đã thu thập dữ liệu Radar thật. Không xóa volume ứng dụng để chạy test.

Sau khi có token/dữ liệu thật: kiểm tra Silver source=radar và độ phủ/mốc giờ, chạy Analysis qua Admin, đối chiếu run_id và Gold với các API/biểu đồ. Xác nhận histogram theo phạm vi 3 metric và Trend đúng timestamp trên trình duyệt. Forecast trống vẫn có thể do ML chưa tích hợp, không phải kết quả nghiệm thu Analysis.

## Kết quả Radar thật ngày 20/11/2026

Đã thực hiện trên máy local sau khi người dùng cấu hình token trong `.env`, với AUTH_ENABLED=true, DATA_MODE=api, SCHEDULER_ENABLED=false. Không ghi token vào tài liệu/log/Git và không reset volume hoặc nạp fixture vào database ứng dụng.

Backfill khoảng 365 ngày bằng pipeline Ingestion hiện có, sau đó chạy một chu kỳ cập nhật thành công. Lần đầu L7/Bot trả HTTP 400 "Must be before now (utc)" ở cửa sổ sát hiện tại; đã chạy lại riêng hai endpoint với mốc kết thúc lùi 3 giờ, rồi dùng polling dateRange=2d để cập nhật điểm mới nhất. Không thay thuật toán rescale hoặc xóa dữ liệu đã có.

| Metric | Source | Số dòng Silver | Mốc cuối (UTC) |
| --- | --- | ---: | --- |
| http_traffic | radar | 8.760 | 2026-11-20 11:00 |
| l7_attack | radar | 8.762 | 2026-11-20 10:00 |
| bot_share | radar | 8.764 | 2026-11-20 12:00 |
| human_share | radar | 8.764 | 2026-11-20 12:00 |
| netflows | radar | 8.759 | 2026-11-20 10:00 |

Tổng **43.809 dòng**, chỉ source=radar, khoảng cách lớn nhất giữa các mốc của từng metric là 1 giờ. Mốc đầu 20/11/2025; ngày đầu/cuối có thể chưa đầy đủ. HTTP có giá trị đến khoảng 1,3099, được giữ nguyên.

Đăng nhập Admin qua NextAuth/Keycloak trên browser và bấm Chạy lại Data Analysis. **Run #4**: started_at=2026-11-20T12:55:45.925053Z, finished_at=2026-11-20T12:55:52.218353Z, status=success, error=null. Tạo một journal mới, giữ nguyên journal failed từ lần chạy cũ trước khi Analysis có implementation.

Gold sau chạy: **2.160 timeseries, 60 histogram, 235 trend, 215 seasonal, 25 correlation**. Freshness latest_silver_ts=2026-11-20T12:00:00Z (19:00 giờ Việt Nam).

Kiểm tra API bằng token Viewer/Admin thực: không token bị 401, Viewer không trigger job/đọc journal chi tiết (403), các API Analysis trả 200; ba điểm timeseries đầu khớp timestamp/mean trong Mart, phân trang đọc trang tiếp theo đúng. HTTP daily có 366 bucket (bao gồm ngày đầu/cuối chưa đầy đủ). Histogram có 20 bin/metric với tổng quan sát lần lượt HTTP=8.760, L7=8.762, Bot=8.764; HTTP weekly trend có 47 điểm, seasonal theo giờ 24 bucket, correlation 25 hệ số. API chỉ dùng tài khoản api_user/read-only để đối chiếu.

Browser xác nhận run #4 Hoàn tất, Timeseries/Histogram/Trend/Seasonal/Heatmap đã vẽ dữ liệu thật ở khoảng 20/11/2025–20/11/2026; chọn Human hiện thông báo histogram chưa hỗ trợ. Không thay tên/diễn giải cụm ML. /api/clusters và hai forecast hiện trả 404; scatter phụ thuộc clusters và trang dự báo vẫn có thể trống. Đây là nghiệm thu **Ingestion → Analysis → Gold → API → Dashboard**, chưa phải nghiệm thu toàn bộ ML/định nghĩa rủi ro của issue #13.
