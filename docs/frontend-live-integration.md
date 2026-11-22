# Chạy dashboard trực tiếp — 22/11/2026

Đã gỡ luồng đăng nhập, đăng xuất, cookie phiên NextAuth, Keycloak và phân quyền Viewer/Admin theo yêu cầu chủ dự án. Mọi người vào thẳng Tổng quan, Analysis, Forecast và Vận hành; Jobs API không yêu cầu Bearer token.

## Chạy sau khi pull

1. Sao chép `.env.example` thành `.env` nếu chưa có; giữ mật khẩu DB hiện tại và cấu hình CF_API_TOKEN khi cần thu thập thật.
2. `docker compose up -d --build`. Không xóa volume database.
3. Mở http://localhost:3000. Không cần tạo tài khoản hoặc cấu hình Keycloak/AUTH_SECRET. Các biến AUTH_ENABLED/KEYCLOAK/NEXTAUTH còn trong .env cũ không được sử dụng.
4. Nếu còn container Keycloak từ phiên bản trước: có thể dừng container cũ. Stack mới chỉ có 8 service; không cần cổng 8080.

## Dữ liệu và vận hành

NEXT_PUBLIC_DATA_MODE mặc định api; biến public được nhúng lúc build, cần rebuild khi đổi. Chọn demo chỉ để xem dữ liệu minh họa; demo không chạy job thật.

Browser gọi API JSON trực tiếp, không có Authorization hoặc /api/auth/session. Mọi người dùng được trang /admin và nút Chạy lại. API vẫn dùng tài khoản chỉ SELECT Gold; task logic mới ghi Gold. JOB_TRIGGER_TOKEN bảo vệ /run nội bộ, cấu hình giống nhau ở API/logic, không đưa ra frontend.

202 chỉ là đã nhận; poll /api/jobs/runs/{run_id} đến trạng thái cuối. Giữ khóa, journal và không tự retry POST khi timeout.

Ngày lọc theo Việt Nam; snapshot histogram/seasonal/correlation/status không nhận start/end. Giữ null và phân trang. Forecast mặc định ngày mai VN; dữ liệu trễ có thể 404. HTTP–Bot vẫn vẽ điểm xám khi thiếu nhãn ML.

## Kiểm thử Docker

`./services/api/tests/run.ps1 -Mode All` hoặc `bash services/api/tests/run.sh all`: database/mạng test riêng, kiểm tra dữ liệu, Jobs API mở và token nội bộ. CI smoke thêm 8 service và fresh HTTP client mở /, /analysis, /forecast, /admin không có cookie. Frontend build chạy unit/lint/TypeScript.

Việc gỡ đăng nhập không tạo thêm Silver/Gold hoặc mô hình ML. Thiếu dữ liệu vẫn hiển thị empty/404.