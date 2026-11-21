# Dashboard ↔ Backend ↔ Keycloak

## Chạy bằng Docker

Dùng `.env` hiện có; đối chiếu các biến mới với `.env.example`. Không ghi đè mật khẩu hoặc xóa volume dữ liệu.

```dotenv
NEXT_PUBLIC_DATA_MODE=api
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXTAUTH_URL=http://localhost:3000
AUTH_ENABLED=true
```

```bash
docker compose up -d --build
```

Biến `NEXT_PUBLIC_*` được nhúng khi build: đổi mode/URL phải build lại frontend. `demo` giữ dữ liệu minh họa, công tắc vai trò xem thử và khóa nút chạy job. Mode `api` yêu cầu đăng nhập thật; không chuyển sang demo khi API lỗi.

Tài khoản realm: `demo` (Viewer), `admin` (Admin); mật khẩu lấy từ `KEYCLOAK_DEMO_PASSWORD`/`KEYCLOAK_ADMIN_PASSWORD` trong cấu hình của người triển khai. Import realm chỉ khởi tạo realm chưa tồn tại. Realm đã tồn tại cần thêm thuộc tính client `dashboard`: `post.logout.redirect.uris=http://localhost:3000/` qua Keycloak Admin; không xóa dữ liệu để cập nhật. Giữ redirect URI callback hiện có và PKCE S256.

## Phiên đăng nhập và quyền

Browser dùng issuer công khai `KEYCLOAK_ISSUER`; server NextAuth dùng `KEYCLOAK_INTERNAL_ISSUER` để kết nối token/userinfo/JWKS trong Docker. Issuer công khai vẫn được kiểm tra. Client secret và refresh token chỉ ở server/cookie phiên JWT được mã hóa HttpOnly; session JSON chỉ trả access token và quyền để browser gọi FastAPI bằng Bearer.

NextAuth gọi `API_INTERNAL_URL/api/me` sau đăng nhập và refresh, kiểm tra cùng subject và lấy Viewer/Admin từ backend. Refresh xảy ra trước hạn 30 giây; yêu cầu đồng thời trong một tiến trình được gộp, kết quả giữ tối đa 10 giây. Refresh lỗi xóa access token/quyền khỏi session. Nhiều replica cần cơ chế phối hợp refresh dùng chung nếu bật xoay refresh token nghiêm ngặt. Không dùng localStorage chứa token. Client kiểm tra phiên mỗi phút và khi focus; backend kiểm tra JWT ở mọi request. Quyền thay đổi được lấy lại khi refresh (không phải ngay lập tức khi sửa trong Keycloak).

Route `/admin` có kiểm tra server; Viewer bị chuyển về tổng quan, không thấy nút vận hành. API vẫn là nơi quyết định quyền cuối cùng. POST `/api/logout-url` kiểm tra Origin và cookie phiên; frontend xóa phiên NextAuth rồi đăng xuất Keycloak, quay về root đã đăng ký.

## Dữ liệu và tác vụ

- Lọc ngày chuyển sang nửa đêm Việt Nam `+07:00`, ngày kết thúc bao gồm cả ngày đã chọn qua cận trên ngày kế tiếp. Ghép ngày UTC với ngày cụm theo múi giờ Việt Nam.
- Timeseries/clusters tải các trang theo `X-Total-Count`; giữ số đo null và giá trị lớn hơn 1. HTTP 404 là trạng thái chưa có dữ liệu.
- Scatter HTTP–Bot chỉ cần hai chuỗi số đo theo ngày. Ghép theo cùng instant, tô màu theo nhãn ML của ngày Việt Nam khi có; thiếu nhãn hoặc clusters trả 404/503 vẫn vẽ điểm màu xám và thông báo rõ. Nhãn chưa có quy ước không bị suy diễn thành Bất thường. Chỉ khi thiếu cặp HTTP/Bot hợp lệ mới hiển thị empty; lỗi hai nguồn chính vẫn hiển thị error.
- Histogram/seasonal/correlation là snapshot toàn bộ kết quả hiện tại, không nhận start/end. UI có ghi rõ phạm vi; status cũng không nhận bộ lọc ngày.
- POST jobs trả 202 chỉ xác nhận tiếp nhận. Admin theo dõi `/api/jobs/runs/{run_id}` đến trạng thái cuối, kể cả failed/partial/skipped. Dừng theo dõi không hủy job. Không tự retry POST khi timeout vì job có thể đã bắt đầu.
- Không thay đổi schema Gold hoặc nghiệp vụ Analysis/ML. Task chưa triển khai vẫn báo failed; trang dữ liệu trống không chứng minh pipeline đã hoàn tất.

## Kiểm thử

`docker compose build frontend` chạy unit tests (refresh/role validation, giữ bí mật session, token, phân trang, ngày Việt Nam), ESLint, TypeScript và production build. `services/api/tests/run.ps1 -Mode All` hoặc `run.sh all` kiểm tra backend/DB/Keycloak riêng.

CI `services/api/tests/smoke-compose.sh` dùng project/volume riêng, cấu hình giả, scheduler tắt, build mode API và khởi động đủ 9 service. HTTP E2E đi qua CSRF → NextAuth → form Keycloak → callback → cookie session, kiểm tra Viewer/Admin, exact run ID và logout. Đây là kiểm tra giao thức HTTP/session; chưa thay thế nghiệm thu biểu đồ bằng trình duyệt hoặc thuật toán trên dữ liệu Cloudflare thật.

Thay đổi này chạm frontend (Vũ), API (Định) và client Keycloak. Cần Vũ review giao diện và nhóm Analysis/ML xác nhận đầu ra Gold trong PR trước nghiệm thu toàn bộ. Không tự chốt ngưỡng P75/P90 của issue #5.
