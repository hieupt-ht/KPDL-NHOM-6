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

## Nghiệm thu dữ liệu thật còn phụ thuộc cấu hình

Cần CF_API_TOKEN hợp lệ được người triển khai cấu hình trong `.env`; không gửi token vào chat, issue hoặc log. Không xem fixture hoặc CI đạt là bằng chứng đã thu thập dữ liệu Radar thật. Không xóa volume ứng dụng để chạy test.

Sau khi có token/dữ liệu thật: kiểm tra Silver source=radar và độ phủ/mốc giờ, chạy Analysis qua Admin, đối chiếu run_id và Gold với các API/biểu đồ. Xác nhận histogram theo phạm vi 3 metric và Trend đúng timestamp trên trình duyệt. Forecast trống vẫn có thể do ML chưa tích hợp, không phải kết quả nghiệm thu Analysis.
