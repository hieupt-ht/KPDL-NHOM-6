# JWT/Keycloak, Viewer/Admin và chạy job

## Phạm vi

Backend xác minh access token của Keycloak; Viewer/Admin được đọc API, Admin được kích hoạt job. `GET /api/me` trả username, sub và realm roles cho frontend. Luồng đăng nhập/refresh/logout trong giao diện NextAuth của Vũ vẫn cần được tích hợp ở frontend; backend không tự thu mật khẩu người dùng hoặc phát hành token thay Keycloak.

Jobs API và runner chạy được, ghi log và chống chạy trùng. Các hàm phân tích/ML của Minh/Hoàng hiện vẫn là `NotImplementedError`; khi gọi sẽ nhận 202 rồi thấy lần chạy `failed` trong status. Cần các tác vụ thật để tái tạo Gold/dự báo; không coi 202 là tính toán đã thành công.

## Cấu hình và chạy

1. Sao chép `.env.example` thành `.env` nếu chưa có. Giữ các giá trị hiện có và thêm các biến mới khi đã có .env, không ghi đè file chứa cấu hình thật.
2. Điền `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_DEMO_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, `JOB_TRIGGER_TOKEN` và mật khẩu DB. Dùng token nội bộ ngẫu nhiên đủ dài, cùng giá trị ở API và các service. Các giá trị `change-*`/`replace-*` chỉ là mẫu.
3. Đặt `AUTH_ENABLED=true`. Để kiểm thử khi chưa cần dữ liệu Cloudflare, đặt `SCHEDULER_ENABLED=false`; sau đó bật lại để chạy lịch.
4. Chạy `docker compose up -d --build`. Nếu máy ít RAM, build từng service với `docker compose build <service>` rồi chạy `docker compose up -d`. Keycloak local được giới hạn Java heap 384 MB để tránh chiếm quá nhiều RAM.
5. Kiểm tra `docker compose ps`, Keycloak http://localhost:8080 và Swagger http://localhost:8000/docs.

Compose chờ Keycloak health ready trước khi chạy API/frontend. Realm import nằm ở đúng tên `cyber-radar-realm.json`, đọc mật khẩu/secret từ biến môi trường, có hai role viewer/admin và client dashboard với Authorization Code + PKCE S256. Password grant bị tắt. Access token có audience `cyber-radar-api`; ID token không có audience API và không thể dùng để gọi API.

User demo là `demo` (viewer) và `admin` (admin), mật khẩu là hai biến riêng ở trên. Tài khoản quản trị Keycloak là `KC_BOOTSTRAP_ADMIN_USERNAME`/`KC_BOOTSTRAP_ADMIN_PASSWORD`, tách biệt với user admin của ứng dụng.

Khi realm đã tồn tại, Keycloak bỏ qua import lúc khởi động. Thay file JSON hoặc đổi biến secret/mật khẩu sẽ không cập nhật realm đang tồn tại bằng cách restart đơn thuần. Với môi trường local dùng Keycloak dev như Compose hiện tại (không có volume Keycloak), có thể tái tạo riêng container `docker compose up -d --force-recreate keycloak api`; việc này mất cấu hình/session Keycloak lưu trong container, không xóa volume Warehouse/Mart. Với Keycloak có dữ liệu cần giữ, cập nhật mapper, client và user qua Admin Console; không xóa realm để xử lý lỗi đăng nhập.

### Hai địa chỉ Keycloak

- Token issuer công khai: `http://localhost:8080/realms/cyber-radar`.
- API container lấy JWKS nội bộ: `http://keycloak:8080/realms/cyber-radar/protocol/openid-connect/certs`.
- Chạy API ngoài Docker: export `KEYCLOAK_JWKS_URL=http://localhost:8080/realms/cyber-radar/protocol/openid-connect/certs` và giữ nguyên issuer công khai.
- Không đổi issuer thành tên container để né lỗi chữ ký/iss. Audience phải khớp mapper; không tắt kiểm tra audience.
- Auth.js chạy trong container cần dùng issuer công khai để xác minh token, nhưng phải cấu hình các backchannel endpoint token/userinfo/JWKS qua địa chỉ nội bộ. Redirect URI đã đăng ký: `http://localhost:3000/api/auth/callback/keycloak`. Frontend dùng access_token trong Authorization, xử lý refresh và 401/403; không dùng id_token để gọi API.

## Quyền và mã trả về

| Tình huống | Kết quả |
| --- | --- |
| Thiếu token, hết hạn, sai chữ ký/issuer/audience, token ID/refresh | 401 và WWW-Authenticate: Bearer |
| Token đúng, không có viewer/admin | 403 |
| Viewer đọc dữ liệu hoặc /api/me | Cho phép |
| Viewer gọi POST /api/jobs/.../run | 403 |
| Admin gọi Run thành công | 202 `{service,run_id,status:"accepted"}` |
| Cùng service đang có một lần chạy | 409 |
| Service hoặc run journal không sẵn sàng | 503 |
| API chờ phản hồi trigger quá hạn | 504; kiểm tra status trước khi thử lại |
| Upstream trả phản hồi sai | 502, không lộ nội dung lỗi upstream |

`AUTH_ENABLED=false` là bypass phát triển, user development có cả viewer/admin. Nếu đã cấu hình JOB_TRIGGER_TOKEN, service vẫn yêu cầu token nội bộ dù bypass bật. Khi bật auth mà thiếu token nội bộ, trigger trả 503.

## Tích hợp job cho Analysis/ML

- `POST /api/jobs/{analysis|clustering|prediction}/run` chỉ gọi URL nằm trong allowlist cấu hình. API gửi `X-Job-Token`; client trình duyệt không cần và không được cung cấp token nội bộ này.
- Service có `POST /run`, trả 202 sau khi giữ khóa và tạo bản ghi running trong `gold.service_runs`, rồi thực thi nền. Public port của 3 service chỉ bind loopback ở host; truy cập trong Docker qua network cyber-net.
- `common.runner` ghi started_at, finished_at, status, error. **tasks.run_all không ghi thêm service_runs**; tasks chỉ làm nghiệp vụ và trả None/success hoặc partial/failed/skipped. Ném ngoại lệ khi tác vụ thất bại, đừng nuốt lỗi rồi trả None khiến runner ghi success.
- Lịch và manual cùng đi qua runner. PostgreSQL advisory lock theo tên service giữ đến hết tác vụ, chống trùng giữa các process còn sống. Khác service có thể chạy song song.
- Một container dùng một uvicorn worker và một scheduler. Không chạy nhiều scheduler cho cùng service: lock chống chạy đồng thời, không loại bỏ được các lượt lịch trùng chạy nối tiếp.
- Khi worker dừng đột ngột, dòng running có thể còn lại. Lần nhận job tiếp theo sau khi lấy được lock sẽ đánh dấu dòng cũ interrupted. Nếu DB ngắt kết nối giữa job, có thể không ghi được trạng thái kết thúc; cần xem service log.
- Chưa có queue bền vững, retry tự động, hủy job hoặc timeout cưỡng bức tác vụ. Không tự retry POST khi API timeout vì job có thể đã được nhận.
- Ingestion vẫn tự ghi ingestion_runs trong Warehouse và có khóa backfill riêng; runner không ghi Gold cho Ingestion.

Theo dõi qua `GET /api/status` bằng access token. Một phần tử service_runs chứa `id`, `service`, `started_at`, `finished_at`, `status`, `error`. Error lưu trong Gold chỉ là thông báo an toàn và loại ngoại lệ, không sao chép DSN/token hoặc nguyên văn exception.

## Kiểm thử

Từ root repo, dùng lệnh có đường dẫn test rõ ràng để pytest không thu thập nhầm test service khác:

```powershell
uv pip install --python .venv/Scripts/python.exe -r services/api/requirements-dev.txt
.venv/Scripts/python.exe -m pytest -c services/api/pytest.ini services/api/tests -m 'not integration and not keycloak' -q
```

Integration PostgreSQL dùng DB `test_*` tách biệt theo `backend-api-local.md`. Export thêm TEST_MART_LOGIC_DSN với logic_user có quyền ghi Gold để kiểm tra runner:

```powershell
$env:TEST_MART_LOGIC_DSN = 'postgresql://logic_user:<test-password>@127.0.0.1:<test-port>/test_mart'
.venv/Scripts/python.exe -m pytest -c services/api/pytest.ini services/api/tests -m 'not keycloak' -q
```

Kiểm thử Keycloak thật chỉ chạy khi export TEST_KEYCLOAK_URL. Dùng một Compose project kiểm thử riêng, `AUTH_ENABLED=true`, `SCHEDULER_ENABLED=false`, database test_warehouse/test_mart và mật khẩu kiểm thử. Không trỏ test này vào môi trường đang sử dụng: nó đăng nhập và kích hoạt 3 job.

```powershell
$env:TEST_KEYCLOAK_URL = 'http://localhost:8080/realms/cyber-radar'
$env:TEST_API_URL = 'http://127.0.0.1:8000'
$env:TEST_KEYCLOAK_CLIENT_SECRET = '<test-client-secret>'
$env:TEST_KEYCLOAK_DEMO_PASSWORD = '<test-viewer-password>'
$env:TEST_KEYCLOAK_ADMIN_PASSWORD = '<test-admin-password>'
.venv/Scripts/python.exe -m pytest -c services/api/pytest.ini services/api/tests/test_keycloak_e2e.py -q
```

Bộ test đăng nhập bằng Authorization Code + PKCE thật, đổi code lấy token rồi gọi API container, kiểm tra Viewer/Admin, từ chối ID token và xác nhận job stub được ghi failed. Nó không bật password grant và không cần frontend thực thi callback. Khi các tác vụ thật được nhóm triển khai, cập nhật kỳ vọng failed của test này cho phù hợp nghiệp vụ.

Máy ít RAM có thể dùng override `services/api/tests/compose.keycloak.yml` với `-f docker-compose.yml -f services/api/tests/compose.keycloak.yml`. Override chỉ dành cho kiểm thử: Keycloak dùng DB in-memory, heap 256 MB và tối đa 2 processor cho JVM; mất realm/session khi dừng. Realm, mapper và API/service code vẫn là các file thật của dự án. Test HTTPX chỉ mô phỏng ngoại lệ cookie Secure của browser trên HTTP loopback; không tắt kiểm tra JWT hoặc thay cấu hình cookie của ứng dụng.

Kết quả 17/11/2026: **75 test backend đạt**, gồm 19 test PostgreSQL/runner, cùng **2 test đầu cuối Keycloak thật đạt** (tổng 77). Kiểm thử đã đi qua Authorization Code + PKCE, token exchange, API container lấy JWKS nội bộ, Viewer bị chặn Run, Admin kích hoạt đủ 3 service và status phản ánh stub thất bại đúng. Dữ liệu và mật khẩu dùng trong lần kiểm thử là cấu hình mẫu trên Compose project riêng, scheduler tắt; không phải dữ liệu Cloudflare thật.

Đã chạy lại toàn bộ **70 test Ingestion** với Warehouse PostgreSQL kiểm thử sau khi thay đổi common; tất cả đạt. Cả 5 service Python, 2 database và Keycloak đã lên healthy trong Compose kiểm thử. Kiểm tra này không thay thế nghiệm thu tác vụ Analysis/ML thật hoặc luồng Auth.js trên dashboard.

Tham khảo: [PyJWT 2.10.1](https://pyjwt.readthedocs.io/en/2.10.1/api.html), [Keycloak hostname](https://www.keycloak.org/server/hostname), [realm import và biến môi trường](https://www.keycloak.org/server/importExport).
