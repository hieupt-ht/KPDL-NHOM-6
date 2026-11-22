# Chạy và kiểm thử Backend API

Dashboard/API không cần đăng nhập, Bearer token, NextAuth hoặc Keycloak. Mở http://localhost:3000 vào thẳng Tổng quan; trang /admin và Jobs API dùng trực tiếp. Stack có 8 service.

## Chạy

Tại thư mục gốc: tạo .env từ .env.example nếu chưa có, cấu hình database/CF_API_TOKEN rồi chạy `docker compose up -d --build`. Giữ volume dữ liệu khi cập nhật. Có thể giữ .env cũ: các biến AUTH_ENABLED/KEYCLOAK/NEXTAUTH không còn được dùng. NEXT_PUBLIC_DATA_MODE mặc định api; rebuild frontend khi đổi biến public.

API: http://localhost:8000/docs. /health kiểm tra tiến trình, /ready kiểm tra Mart và schema. Các GET Gold trả 404 khi chưa có dữ liệu; /api/status trống vẫn 200. Không cần cấu hình tài khoản hoặc cổng 8080.

## Kiểm thử Docker

```powershell
./services/api/tests/run.ps1 -Mode Unit
./services/api/tests/run.ps1 -Mode Integration
./services/api/tests/run.ps1 -Mode All
```

Linux: `bash services/api/tests/run.sh unit|integration|all`. Unit kiểm tra validation/transport, Integration thêm PostgreSQL, All thêm các service và Analysis E2E. Hai bài frontend chạy riêng trong CI smoke vì cần frontend thực.

Bộ test dùng DB test_* và network riêng, không đọc .env dự án hoặc gọi Cloudflare. Runner chỉ dọn tài nguyên project kpdl-api-tests-* của nó. Không dùng down -v trên ứng dụng để chạy test.

## Chạy job

POST /api/jobs/{analysis|clustering|prediction}/run không cần tài khoản, trả 202 + run_id. Poll /api/jobs/runs/{run_id} đến trạng thái cuối; /api/status chỉ là tổng hợp mới nhất. API gửi X-Job-Token nội bộ, phải khớp JOB_TRIGGER_TOKEN ở logic service; browser không biết token này.

Giữ allow-list URL, khóa scheduler/manual giữa worker, một journal/lần, không retry POST khi timeout. Chạy job không đồng nghĩa huấn luyện model; thiếu artifact hoặc task chưa triển khai có thể failed, thiếu dữ liệu có thể skipped. Chỉ API dùng quyền SELECT Gold, các logic service mới ghi kết quả.

Việc gỡ đăng nhập là thay đổi phạm vi: mọi người truy cập được dashboard cũng dùng được chức năng Vận hành. Schema Gold/Medallion không thay đổi.