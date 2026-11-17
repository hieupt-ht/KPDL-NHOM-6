# Chạy và kiểm tra Backend API bằng Docker

Theo CLAUDE.md, chỉ cần Git, Docker Engine và Docker Compose; không cần Python, Node hoặc venv trên máy. Chạy từ thư mục gốc repo.

## Kiểm thử độc lập với dữ liệu dự án

```powershell
./services/api/tests/run.ps1 -Mode Unit
./services/api/tests/run.ps1 -Mode Integration
./services/api/tests/run.ps1 -Mode All
```

Bash/Linux/Git Bash:

```bash
bash services/api/tests/run.sh unit
bash services/api/tests/run.sh integration
bash services/api/tests/run.sh all
```

| Mode | Phạm vi |
| --- | --- |
| Unit | Validation, JWT/JWKS với khóa ký kiểm thử, phân quyền, lỗi và proxy job; không chạy DB/Keycloak |
| Integration | Unit + PostgreSQL thật: query, quyền api_user, read-only transaction, runner/journal/lock |
| All | Toàn bộ các phần trên + đăng nhập Authorization Code/PKCE với Keycloak thật, API và 3 service thật |

Runner tự build image lần lượt, tạo project `kpdl-api-tests-*`, kiểm tra và dọn project đó. Lần đầu cần Internet để tải image/package; lần sau Docker dùng cache. Không cần .env, CF_API_TOKEN hoặc mật khẩu thật. Các giá trị test-only trong compose.yml chỉ dành cho mạng Docker nội bộ, không publish port ra host. PostgreSQL dùng tmpfs; dừng container là mất dữ liệu kiểm thử. Các volume Warehouse/Mart của ứng dụng không được mount hay xóa.

All kiểm tra hợp đồng kích hoạt, quyền và nhật ký, không đánh giá thuật toán Analysis/ML. Một job có thể kết thúc success, failed, partial hoặc skipped; test yêu cầu trạng thái cuối hợp lệ và timestamp tương ứng. Với các task còn stub, journal phải phản ánh failed, không sinh dữ liệu giả làm kết quả thật. Tests của thuật toán thuộc module tương ứng.

Exit code khác 0 nghĩa build/startup/test thất bại. Script dọn tài nguyên trong finally/trap, kể cả khi test lỗi. `-ProjectName kpdl-api-tests-<tên>` có thể đặt tên riêng trên PowerShell; chỉ nhận prefix kiểm thử. `-Keep` giữ container để xem log nhưng không bảo đảm dữ liệu tmpfs tồn tại sau khi container đã dừng. Dọn bằng chính file compose kiểm thử và đúng project đã in ra, không dùng down -v cho ứng dụng.

## Chạy ứng dụng để tích hợp

1. Chuẩn bị .env từ .env.example nếu chưa có; giữ các cấu hình thật hiện có, chỉ bổ sung biến mới.
2. Điền token Cloudflare và mật khẩu; đặt AUTH_ENABLED=true khi kiểm tra xác thực. Có thể tắt SCHEDULER_ENABLED trong lúc kiểm tra thao tác thủ công.
3. Chạy `docker compose up -d --build` theo README. Môi trường này độc lập với bộ test ở trên.

- Swagger: http://localhost:8000/docs
- Liveness: http://localhost:8000/health
- Mart/schema readiness: http://localhost:8000/ready
- User/role: GET /api/me với access token khi bật auth.
- Bảng Gold cần dữ liệu từ Analysis/ML; dữ liệu trống trả 404 là hành vi dự kiến.
- Timeout kết nối/truy vấn và URL JWKS nội bộ đã được ánh xạ trong Compose. Không đổi issuer công khai thành tên container.

Chi tiết hợp đồng: [api-contract.md](api-contract.md). JWT/Keycloak và job: [backend-auth-jobs.md](backend-auth-jobs.md). Điểm cần phối hợp với frontend/Analysis/ML: [backend-integration-handoff.md](backend-integration-handoff.md).

CI dùng `.github/workflows/backend-api.yml` để chạy cùng bộ All cho PR backend vào develop; không cần secret của nhóm. CI chạy thêm `bash services/api/tests/smoke-compose.sh` để build/khởi động đủ 9 container theo Compose ứng dụng với cấu hình giả và scheduler tắt. Bước smoke kiểm tra frontend HTTP, Mart readiness, Keycloak và API yêu cầu token; nó không thay thế nghiệm thu Auth.js/dashboard hoặc pipeline Cloudflare → Silver → Analysis/ML → Gold thật. Smoke publish các port ứng dụng trên host, nên chỉ chạy trên host kiểm thử riêng, không chạy cạnh hệ thống đang sử dụng cùng port.
