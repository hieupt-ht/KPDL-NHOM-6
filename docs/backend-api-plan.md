# Kế hoạch phần việc Backend/API — Định

Ngày khảo sát: 17/11/2026. Đây là kế hoạch triển khai, chưa phải xác nhận chức năng đã chạy.

**Cập nhật triển khai 17/11/2026:** đã tạo nhánh `feature/backend-api` từ `origin/develop`; triển khai 9 endpoint đọc Gold, schema response, validation, phân trang, timeout, xử lý lỗi DB và readiness. Đã chạy 30 test thành công (12 integration test với PostgreSQL 16 thật, schema/quyền khởi tạo bằng script của repo), cùng smoke check health/OpenAPI của cả 5 service Python. Hợp đồng API và cách chạy nằm trong `docs/api-contract.md`, `docs/backend-api-local.md`. Hợp đồng hiện là đề xuất triển khai, chưa có xác nhận của nhóm. JWT/SSO và Jobs API/runner chưa hoàn thiện; chưa nghiệm thu pipeline thật hoặc dashboard. Các mô tả hiện trạng ở mục 1 bên dưới ghi lại thời điểm khảo sát ban đầu.

## 1. Căn cứ và hiện trạng

**Cập nhật tiếp theo 17/11/2026:** đã triển khai JWT/JWKS RS256, Viewer/Admin, `/api/me`, Jobs API, khung chạy nền có khóa PostgreSQL và `service_runs`. Đã kiểm tra 75 test backend + 2 test Authorization Code/PKCE với Keycloak và API/service container thật. Hướng dẫn hiện tại: `docs/backend-auth-jobs.md`. Nghiệp vụ Analysis/ML vẫn là stub của các thành viên khác; runner báo failed đúng, chưa có luồng tái tạo Gold hoàn chỉnh hoặc frontend Auth.js. Những checklist nghiệm thu toàn đồ án ở dưới vẫn cần các module tương ứng để hoàn tất.

- Repo: https://github.com/hieupt-ht/KPDL-NHOM-6
- Phân công: https://github.com/hieupt-ht/KPDL-NHOM-6/issues/2, mục Thành viên 4 — Backend/API — Định. Tài khoản GitHub đang hoạt động là `VoHoangDinh`, tên hiển thị Hoàng Định Võ; từ đó xác định đây là phần việc của người dùng.
- Đã kiểm tra toàn bộ danh sách issue mở/đóng: hiện chỉ có issue #2; không có bình luận và không gán assignee ở metadata. Phân công nằm trong nội dung issue.
- Local đang ở `main`, commit `7f17556`, chỉ có README, CONTRIBUTING, .gitignore và cấu hình GitHub. Cây thư mục trong README là thiết kế, không phản ánh đầy đủ checkout hiện tại.
- Bộ khung đã được merge qua PR #1 vào `develop`, commit `ea743db443484565d91a915d0dac8f1b25e898bf`. Đã đọc cây mã nguồn và các file API, common, Mart, Keycloak, Compose, kiểu dữ liệu và client frontend trên nhánh này.
- API có đủ route khung nhưng 10 endpoint nghiệp vụ đều trả 501. `require_user` và `require_admin` chưa xác minh token khi bật auth.
- `backend/common/runner.py` có scheduler nhưng POST `/run` chưa gọi job. Tác vụ Analysis/ML cũng mới là stub.
- Mart có 10 bảng Gold và tài khoản API chỉ được SELECT trên các bảng hiện có. Keycloak có realm/client/role/user demo, chưa có luồng xác thực hoàn chỉnh.
- Chưa chạy ứng dụng, Docker hoặc test; nhận xét trên dựa vào kiểm tra mã nguồn.

## 2. Phạm vi của Định

Phụ trách chính `services/api/`, `backend/common/`, `keycloak/`, `db/mart/` theo issue #2. Các chỉnh sửa `.env.example`, Compose, README phục vụ tích hợp phải ghi rõ trong PR và phối hợp người phụ trách.

Luồng cần hoàn thiện:

```text
Analysis/ML ghi Gold → API đọc Gold → JSON cho dashboard
Admin → API kiểm tra quyền → POST /run của service tương ứng
Keycloak → access token → API kiểm tra JWT và role
```

API không đọc Silver, không tính lại histogram/correlation, không huấn luyện mô hình và không tự ghi dữ liệu nghiệp vụ vào Gold. Các job và nhật ký chạy do Business Logic thực hiện bằng tài khoản logic_user.

## 3. Những điểm cần chốt trước khi triển khai

1. **Nhánh tích hợp:** issue #2 và PR template yêu cầu PR vào `develop`, trong khi CONTRIBUTING cũ hướng dẫn vào `main`. Kế hoạch dùng `develop` theo phân công hiện tại. Tạo `feature/backend-api` từ `origin/develop`, không bắt đầu từ bản main chỉ có tài liệu.
2. **Schema và thời gian thống kê:** histogram/seasonal hiện không có khoảng dữ liệu đầu vào; correlation chỉ có computed_at. Không thể lọc lại thống kê theo start/end tùy ý chỉ từ các bảng này. Cần thống nhất với Minh và Vũ: giai đoạn đầu trả thống kê toàn bộ tập dữ liệu, bỏ hoặc từ chối bộ lọc không hỗ trợ; nếu bắt buộc lọc thì Analysis phải tính/lưu theo cửa sổ với khóa và metadata phù hợp. Không giả vờ lọc bằng computed_at, không tính lại từ Silver trong API.
3. **JSON:** frontend đã có `frontend/types/api.ts`: đa số endpoint trả array, forecast trả object, status trả object. Dùng chúng làm điểm xuất phát, chốt nullability và lỗi; nếu đổi sang envelope phải cập nhật hợp đồng và phối hợp frontend trước.
4. **Phân trang:** đề xuất limit/offset cho timeseries và clusters, thứ tự ổn định; tổng số/trang tiếp theo qua header được CORS expose nếu giữ body dạng array. Không phân trang tùy tiện làm thiếu ô correlation hay bin histogram. Forecast không nhận phân trang.
5. **Forecast:** chốt mặc định trả dự báo ngày mai theo Asia/Ho_Chi_Minh, hành vi khi không có bản ghi đúng ngày, và cách xử lý start/end vì frontend hiện mong một object. Không âm thầm trả bản ghi cũ mà không thể hiện ngày.
6. **Scatter và KPI:** timeseries hiện mỗi request chỉ nhận một metric; thống nhất frontend ghép chuỗi theo ts và cụm theo ngày. Gold hiện chưa có nguồn rõ ràng cho bot_share mới nhất theo giờ; không gọi trung bình ngày là giá trị hiện tại. Chốt dùng giá trị tổng hợp gần nhất kèm độ phân giải hoặc bổ sung snapshot do Analysis ghi.
7. **Job:** chốt mã HTTP, chạy đồng bộ hay nền, trạng thái và cách chống chạy trùng giữa scheduler với thao tác thủ công. Đề xuất chạy nền, trả 202 khi được nhận, 409 khi đang chạy; UI đọc kết quả qua status. Phải bảo đảm semantics này được thực hiện ở service, không chỉ đổi response phía API.
8. **Keycloak:** tách issuer công khai `http://localhost:8080/realms/cyber-radar` và địa chỉ JWKS nội bộ container; vẫn kiểm tra iss đúng. Phối hợp Vũ xử lý discovery/token exchange của Auth.js chạy trong container. Chốt audience và cấu hình mapper/client tương ứng, không tắt kiểm tra JWT để né lỗi mạng.
9. **Quyền DB:** script hiện cấp quyền cho bảng có sẵn; cần kế hoạch cấp quyền cho bảng tạo sau này. Init script chỉ chạy khi tạo volume mới, nên thay đổi schema/quyền phải có cách cập nhật DB đã tồn tại, không yêu cầu xóa dữ liệu Warehouse.
10. **CODEOWNERS:** còn username giữ chỗ; phân công common/Mart trong CONTRIBUTING cũng khác issue. Ghi nhận để nhóm cập nhật, chưa dựa vào CODEOWNERS để suy ra người duyệt thật.

## 4. Các giai đoạn và sản phẩm bàn giao

### Bước 1 — Hợp đồng dữ liệu và API (0,5–1 ngày)

- Lập bảng endpoint: query, schema response, sort, null, lỗi, timezone và phân trang.
- Xác định enum 5 metric, granularity, period_type và 3 tên service.
- Quy định timestamp có timezone, start <= end, ranh giới lọc thời gian; thống nhất chuyển date cho kết quả theo ngày.
- Chốt các điểm ở mục 3 với Minh, Hoàng, Vũ và Hiếu nếu ảnh hưởng dữ liệu nguồn.
- Bàn giao `docs/api-contract.md`, ví dụ JSON và danh sách thay đổi schema đã thống nhất.

Hoàn tất khi mỗi biểu đồ/KPI có nguồn Gold xác định và mỗi tham số API có semantics có thể thực hiện.

### Bước 2 — Cấu hình, kết nối Mart và nền API (0,5–1 ngày)

- Bổ sung settings cho DB timeout, issuer/JWKS/audience và URL nội bộ của 3 service; cập nhật .env.example bằng giá trị mẫu.
- Tổ chức lớp schema/validation, truy vấn và xử lý lỗi trong services/api; tránh lặp SQL ở router.
- Mở/đóng kết nối đúng vòng đời, dùng SQL tham số hóa và api_user SELECT-only; xử lý mất kết nối bằng lỗi dịch vụ phù hợp, không lộ DSN.
- Thiết kế lỗi thống nhất: 401 token lỗi, 403 sai quyền, 404 không có dữ liệu, 422 query sai, 503 phụ thuộc không sẵn sàng; upstream job lỗi/timeout có mã rõ ràng.
- Giữ GET /health cho trạng thái tiến trình; bổ sung readiness kiểm tra Mart nếu cần. Xem lại POST /run 501 thừa ở API vì job công khai đã có route riêng.
- Hoàn thiện schema/quyền và script cập nhật DB hiện hữu nếu thực sự thay đổi.

Hoàn tất khi API khởi động, có thể đọc Mart bằng api_user và các thao tác ghi bằng tài khoản đó bị DB từ chối.

### Bước 3 — Các endpoint đọc Gold (1–1,5 ngày)

| Endpoint | Nguồn và yêu cầu chính |
| --- | --- |
| GET /api/timeseries | gold.timeseries_resampled; metric, granularity, thời gian, sort, phân trang |
| GET /api/histogram | gold.histogram; metric, bin tăng dần, semantics khoảng thống kê theo hợp đồng |
| GET /api/trend | gold.trend; tuần/tháng, metric, thời gian |
| GET /api/seasonal | gold.seasonal; period_type, metric, bucket hợp lệ |
| GET /api/correlation | gold.correlation; cặp biến và null cho hệ số không xác định theo hợp đồng |
| GET /api/clusters | gold.cluster_results; lọc ngày, thứ tự ổn định, phân trang |
| GET /api/forecast/continuous | gold.forecast_continuous; target_date, predicted_value, model_name, created_at |
| GET /api/forecast/discrete | gold.forecast_discrete; target_date, label Cao/Thấp, probability |
| GET /api/status | gold.service_runs và gold.data_freshness; lần chạy mới nhất của mỗi service, timestamp dữ liệu |

- Dùng dữ liệu seed xác định, ghi rõ là fixture kiểm thử; không cần đợi pipeline thật để phát triển API.
- Kiểm tra response tương thích frontend; serialize datetime, JSONB, null và số không hữu hạn hợp lệ.
- Endpoint dữ liệu trả 404 khi không có kết quả theo hợp đồng. Status nên có thể phản ánh hệ thống chưa chạy, thay vì làm trang Admin không dùng được.

Hoàn tất khi các endpoint đọc đúng seed, lọc đúng và có ví dụ Swagger; không còn 501 trong nhóm đọc dữ liệu.

### Bước 4 — Khung chạy job và Jobs API (0,5–1 ngày)

- Hoàn thiện common.runner để POST /run gọi job, dùng cơ chế khóa chung với scheduler để tránh chạy chồng.
- Thống nhất một nơi ghi service_runs cho cả chạy lịch và thủ công, tránh ghi nhật ký hai lần giữa runner và tasks.
- Ghi started_at, finished_at, status, error; xử lý ngoại lệ không làm chết scheduler, luôn giải phóng khóa.
- API ánh xạ tên service từ allowlist sang URL nội bộ cố định, gọi POST /run với timeout; bổ sung dependency HTTP nếu cần.
- Chỉ require_admin được kích hoạt. Xác định cách bảo vệ endpoint /run nội bộ và hạn chế public port nếu cần thay đổi Compose.
- Sửa common phải chạy smoke test tất cả service Python và kiểm tra cả lịch interval lẫn cron theo quy ước repo.

Hoàn tất khi có thể phân biệt accepted/running/succeeded/failed, xử lý timeout và chống chạy trùng. Với tasks hiện còn stub, chỉ xác nhận cơ chế bằng job kiểm thử; nghiệm thu đầu cuối cần tác vụ thật từ Minh/Hoàng.

### Bước 5 — Keycloak và phân quyền (1–1,5 ngày)

- Triển khai Bearer JWT: kiểm tra chữ ký qua JWKS, thuật toán cho phép, issuer, audience, exp và các claim thời gian áp dụng; cache JWKS và xử lý đổi khóa.
- require_user cho viewer/admin, require_admin cho admin; thiếu/hết hạn/sai token là 401, token hợp lệ thiếu quyền là 403.
- Hoàn thiện realm/client/role/audience và cách nạp secret/mật khẩu demo theo cấu hình; không commit thông tin bí mật thật.
- Kiểm tra issuer công khai và JWKS nội bộ, Keycloak sẵn sàng trước khi tích hợp; Compose hiện chỉ chờ service_started.
- Phối hợp Vũ hoàn thiện Auth.js, chuyển access token đến browser để gọi API và xử lý refresh; phần frontend do Vũ phụ trách.
- Kiểm tra CORS preflight và Authorization từ localhost:3000, bảo đảm API request hiện trong Network trình duyệt.
- AUTH_ENABLED=false chỉ dùng phát triển; nghiệm thu xác thực bắt buộc bật true.

Hoàn tất khi viewer đọc được nhưng không chạy job, admin chạy được, token sai/hết hạn bị chặn và luồng đăng nhập trong Docker hoạt động.

### Bước 6 — Tích hợp, kiểm thử và hướng dẫn (0,5–1 ngày)

- Test tích hợp với PostgreSQL thật cho query, quyền, dữ liệu trống và lỗi DB; test auth và job bằng phụ thuộc được kiểm soát, rồi kiểm tra Keycloak/service thật.
- Chạy Compose và luồng thực: Silver → Analysis/ML → Gold → API → dashboard. Đợi module thật của các bạn để nghiệm thu phần này.
- Kiểm tra kịch bản demo trên dữ liệu kiểm thử riêng: Gold có dữ liệu → dọn Gold → API 404 và UI empty → admin chạy lại service → Gold và UI phục hồi; giữ nguyên Warehouse. Tắt hoặc kiểm soát scheduler trong bước kiểm tra empty để kết quả không bị tự phục hồi giữa chừng.
- Viết hướng dẫn chạy, cấu hình, gọi API, tài khoản demo, bảng mã lỗi và xử lý sự cố issuer/JWKS/DB.
- Mở PR vào develop theo mẫu repo, ghi rõ thay đổi API/schema/common và bằng chứng kiểm tra.

Hoàn tất khi có thể lặp lại luồng demo và không còn 501 trong API nghiệp vụ hoặc /run của Business Logic; chỉ đánh dấu phần Định trong issue #2 sau khi toàn bộ nhiệm vụ của mình đã chạy và được kiểm tra. Không đóng issue phân công của cả nhóm khi chỉ xong phần Định.

## 5. Thứ tự PR đề xuất

1. Hợp đồng API và schema/quyền Gold đã thống nhất.
2. Nền API và các endpoint đọc Gold.
3. common.runner, nhật ký và Jobs API.
4. JWT/Keycloak và tích hợp đăng nhập.
5. Kiểm thử đầu cuối, cấu hình tích hợp và tài liệu.

Các PR nhỏ, có quan hệ phụ thuộc và đều nhắm develop; phần thay đổi common phải có kiểm tra các service Python liên quan. Chưa tạo nhánh hoặc PR trong lần khảo sát này.

## 6. Phối hợp và tiến độ dự kiến

| Thành viên | Cần thống nhất/bàn giao |
| --- | --- |
| Hiếu — Ingestion | Schema Silver, timezone, chỉ số/đơn vị và dữ liệu thật để tích hợp |
| Minh — Analysis | Gold thống kê, semantics cửa sổ thời gian, freshness, nhật ký và contract chạy job |
| Hoàng — ML | Schema features/cụm, ngày dự báo, label/probability, dữ liệu thiếu và contract chạy job |
| Vũ — Frontend | JSON/nullable, pagination, empty/error, scatter/KPI, access token/refresh và trang Admin |
| Người phụ trách hạ tầng | Compose, env, readiness Keycloak, URL nội bộ/công khai và CODEOWNERS |

Ước lượng tổng khoảng **5–8 ngày làm việc tập trung**, chưa gồm thời gian chờ thống nhất hoặc chờ pipeline và frontend hoàn thiện. Không có deadline trong issue nên đây là ước lượng, không phải cam kết ngày bàn giao. Có thể phát triển API bằng fixture trong khi các service khác đang làm; không xem fixture là bằng chứng pipeline thật đã hoàn tất.

Ưu tiên bắt đầu: dùng develop làm nền, chốt hợp đồng Gold/JSON và semantics bộ lọc; sau đó làm Mart + endpoint đọc. Hai rủi ro tích hợp chính là thống kê không lưu cửa sổ thời gian và luồng OIDC qua mạng Docker.
