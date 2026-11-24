> Cập nhật 22/11/2026: đã gỡ đăng nhập/Keycloak/Viewer/Admin theo yêu cầu chủ dự án. Các hướng dẫn xác thực và số lượng container bên dưới là ghi nhận lịch sử; cách chạy hiện tại ở [frontend-live-integration.md](frontend-live-integration.md). Stack hiện có 8 service, dashboard/API truy cập trực tiếp, chỉ /run nội bộ dùng token.

# Bàn giao tích hợp Backend/API — Định

**Cập nhật 18/11/2026:** develop `c42997c` đã merge PR #7 (training/features) và #8 (UI). Nhánh `codex/backend-dashboard-integration` thực hiện các điểm frontend dưới đây: phiên NextAuth/Keycloak, refresh/quyền, bộ lọc/snapshot/null/phân trang và theo dõi đúng run ID. Xem [hướng dẫn tích hợp hiện tại](frontend-live-integration.md). Bảng và danh sách ngày 17/11 bên dưới là mốc bàn giao trước thay đổi này. Analysis và inference ML chưa triển khai đầy đủ trên develop; không coi integration test là nghiệm thu thuật toán.

## Trạng thái đã đối chiếu

Ngày 17/11/2026: `develop` tại `5787e9b` đã có Ingestion và CLAUDE.md. Nhánh `feature/backend-api` đã merge cập nhật develop này, giữ nguyên phần API/JWT/jobs ở PR #4. Các nhánh của thành viên khác chỉ được đọc để đối chiếu, chưa được merge vào nhánh backend hoặc develop.

| Thành viên/phần việc | Nguồn đối chiếu | Cần phối hợp tiếp |
| --- | --- | --- |
| Hiếu — Ingestion | Đã merge vào develop; issue #2 đã tích phần Hiếu | Dùng Silver thật khi nghiệm thu, không đổi thang tương đối về 0–1 |
| Minh — Analysis | feature/data-analysis tại 75c146f, chưa có trong develop | Review writer/schema Gold, snapshot và trạng thái skip khi Silver không dùng được |
| Hoàng — ML | PR #7, feature/machine-learning tại 6b01c02 | Feature theo ngày đang dùng UTC; cần thống nhất với ngày Việt Nam của target_date/API, rồi hoàn thiện model và tasks |
| Vũ — Frontend | PR #8, feature/frontend-dashboard tại f5043d2 | Nối access token, xử lý snapshot/pagination/null; role preview vẫn là demo |

Đây là ghi nhận từ mã nguồn và issue, không phải xác nhận các thành viên đã đồng ý hợp đồng.

## Những điểm frontend cần xử lý trước khi bật dữ liệu thật

1. `getAccessToken()` trong frontend/lib/api.ts hiện trả null. Với `AUTH_ENABLED=true`, API sẽ trả 401. Auth.js phải lưu/refresh access_token và gửi Bearer token từ browser; lấy role từ `/api/me` hoặc claim đã xác thực. Role switch chỉ trình diễn, không cấp quyền.
2. Các hàm getHistogram/getSeasonal/getCorrelation/getStatus hiện có thể gửi start/end. Gold chưa lưu cửa sổ thống kê, vì vậy backend từ chối hai tham số này bằng 422. Bỏ lọc ngày ở các lời gọi snapshot/status, đồng thời ghi rõ phạm vi thống kê trên UI. Không sửa backend để lặng lẽ bỏ qua bộ lọc mà UI vẫn hiển thị là đã lọc.
3. Response vẫn là array/object theo kiểu dữ liệu hiện có. Cập nhật type các cột nullable thành number|null và xử lý missing values, không đổi thành 0. `features`, timestamps và model_name cũng theo nullability trong Swagger/hợp đồng.
4. Timeseries và clusters có limit/offset; đọc X-Total-Count, X-Limit, X-Offset khi tải nhiều hơn một trang. Header đã được CORS expose. Bộ hiện tại mặc định 1000 dòng/trang.
5. Forecast không truyền khoảng lịch sử đang chọn trên dashboard nếu muốn KPI ngày mai: bỏ start/end để backend lấy đúng ngày mai Việt Nam. Nếu truyền khoảng, backend trả dự báo mới nhất trong khoảng đó.
6. Nút Run chỉ dành Admin. Đọc `{service,run_id,status:"accepted"}` từ 202 và poll `/api/status`; không hiển thị thành công ngay khi POST được nhận. Giữ run_id để phân biệt lần chạy, xử lý 409 đang chạy và 504 chưa biết đã nhận hay chưa.
7. Nguồn bot_share hiện có là dữ liệu tổng hợp; không gắn nhãn giá trị theo giờ mới nhất cho trung bình ngày. Dùng timestamp/granularity thực tế. Scatter cần ghép cùng ts/ngày giữa traffic/bot/cụm, không ghép theo vị trí array.

## Những điểm cần chốt với Analysis/ML

- Chỉ `common.runner` ghi gold.service_runs, tasks không ghi trùng. Trả skipped/partial/failed khi có thể xác định, hoặc ném ngoại lệ nếu thất bại. Một tác vụ trả None sẽ được runner ghi success.
- Nhánh Analysis hiện trả None khi Silver rỗng/quality không dùng được. Khi tích hợp cần quyết định rõ đây là skipped hay success; không nên khiến Admin hiểu nhầm dữ liệu Gold đã được cập nhật.
- Gold snapshot chưa hỗ trợ start/end tùy ý. Nếu cần, phải cùng thiết kế cửa sổ đầu vào và khóa lưu trữ, không chỉ lọc computed_at.
- Chuỗi và thời gian lưu UTC; ngày dự báo/cluster và seasonal theo lịch Việt Nam. Feature ML trên nhánh riêng đang nhóm theo UTC nên phải thống nhất trước khi chạy inference cùng frontend.
- Không giả lập dự báo/model khi thiếu artifact. Báo failed hoặc không có dữ liệu, giữ phân biệt fixture và dữ liệu thật.

## Cổng kiểm tra thuộc phần Backend

Chạy từ repo bằng Docker, không cần Python/Node local, .env hoặc token thật:

```powershell
./services/api/tests/run.ps1 -Mode Unit
./services/api/tests/run.ps1 -Mode Integration
./services/api/tests/run.ps1 -Mode All
```

Bash/Linux: `bash services/api/tests/run.sh unit|integration|all`. Mode All kiểm tra Gold API, JWT/JWKS, role, trigger và nhật ký với PostgreSQL/Keycloak/service thật trên mạng riêng. Nó không đánh giá chất lượng thuật toán Analysis/ML, không chạy Cloudflare và không chứng minh Auth.js trên dashboard đã được nối.

CI ở `.github/workflows/backend-api.yml` dùng cùng script All cho PR vào develop có thay đổi backend liên quan. Không cần secret của nhóm. PostgreSQL kiểm thử là tmpfs; script dọn đúng project kpdl-api-tests-* của nó.

Đã kiểm tra trên Windows bằng runner PowerShell: Unit đạt 56 test; Integration đạt 75 test; All đạt 77 test, gồm PostgreSQL và Keycloak thật. Không dùng Python local hoặc cấu hình bí mật của ứng dụng. Các mode đã tự dọn mạng/container kiểm thử sau khi kết thúc. Các test backend này không đồng nghĩa các PR của Minh/Hoàng/Vũ đã được merge hoặc toàn hệ thống đã nghiệm thu.

## Trình tự nghiệm thu sau khi các PR được review và merge

- [ ] PR backend/Analysis/ML/frontend được người phụ trách review hợp đồng; không tự merge thay họ.
- [ ] Chuẩn bị cấu hình local và model artifact thật; kiểm tra đủ 9 container lên được.
- [ ] Viewer đăng nhập, xem API dữ liệu thật; Viewer bị chặn Run ở cả UI và backend.
- [ ] Admin chạy Analysis/ML, thấy trạng thái cuối và freshness thay đổi đúng kết quả.
- [ ] Trên môi trường demo được chuẩn bị riêng: dọn Gold, UI hiển thị empty/404, giữ nguyên Warehouse.
- [ ] Chạy lại Analysis/ML: Gold được tái tạo và dashboard phục hồi, không huấn luyện lại model trong runtime.
- [ ] Xác minh Network trình duyệt có request JSON mang Bearer token; không có tính toán nghiệp vụ ở frontend.

Không tích hoàn tất toàn bộ phần Định trong issue #2 chỉ dựa vào test fixture; còn bước nghiệm thu tích hợp API với kết quả thật của các module.
