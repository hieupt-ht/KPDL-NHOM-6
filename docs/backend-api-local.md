# Chạy và kiểm tra Backend API

Các lệnh PowerShell dưới đây chạy từ thư mục gốc repo. Python đích là 3.11; `uv` chỉ dùng để tạo môi trường, không thay Python hệ thống. Cài API trong venv riêng theo quy ước repo.

## Chạy local với Mart của dự án

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r services/api/requirements-dev.txt
$env:PYTHONPATH = "$PWD\backend;$PWD\services\api"
$env:AUTH_ENABLED = 'false'
$env:MART_DSN = 'postgresql://api_user:<API_DB_PASSWORD>@localhost:5433/<MART_DB>'
.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Thay placeholder bằng cấu hình thật, URL encode ký tự đặc biệt trong DSN. Không commit mật khẩu. Các settings đọc environment của tiến trình; file .env không tự được nạp khi chạy trực tiếp bằng lệnh trên. Docker Compose vẫn lấy cấu hình từ .env theo cấu hình có sẵn.

- Swagger: http://localhost:8000/docs
- Sống: `Invoke-RestMethod http://localhost:8000/health`
- Mart sẵn sàng: `Invoke-RestMethod http://localhost:8000/ready`
- Dữ liệu: `Invoke-RestMethod 'http://localhost:8000/api/timeseries?metric=http_traffic&granularity=day'`
- Các bảng Gold cần được Analysis/ML ghi dữ liệu trước khi có kết quả thật. Không có dữ liệu trả 404 là hành vi dự kiến.
- Timeout mặc định là 5 giây kết nối, 10000 ms truy vấn. Có thể export `DB_CONNECT_TIMEOUT_SECONDS` và `DB_STATEMENT_TIMEOUT_MS` khi chạy local. Compose hiện dùng mặc định; nếu muốn đổi qua .env cần bổ sung ánh xạ hai biến vào environment của API.

## Unit test không cần DB

```powershell
.venv/Scripts/python.exe -m pytest -c services/api/pytest.ini -m 'not integration' -q
```

## Integration test bằng PostgreSQL riêng

Yêu cầu Docker engine đang chạy. Container sau chỉ chứa fixture nhân tạo, khởi tạo schema và quyền bằng đúng script db/mart/init của repo. Dữ liệu fixture được ghi rõ trong services/api/tests/seed.sql; không phải Cloudflare thật.

```powershell
docker run --detach --rm --name cyber-radar-api-test-db --publish 127.0.0.1:55439:5432 --env POSTGRES_DB=test_mart --env POSTGRES_USER=test_admin --env POSTGRES_PASSWORD=test-admin-only --env LOGIC_DB_PASSWORD=test-logic-only --env API_DB_PASSWORD=test-api-only --mount "type=bind,source=$PWD\db\mart\init,target=/docker-entrypoint-initdb.d,readonly" postgres:16
docker exec cyber-radar-api-test-db pg_isready -U test_admin -d test_mart
$env:TEST_MART_ADMIN_DSN = 'postgresql://test_admin:test-admin-only@127.0.0.1:55439/test_mart'
$env:TEST_MART_API_DSN = 'postgresql://api_user:test-api-only@127.0.0.1:55439/test_mart'
.venv/Scripts/python.exe -m pytest -c services/api/pytest.ini -q
docker stop cyber-radar-api-test-db
```

Nếu pg_isready chưa thành công, kiểm tra log khởi tạo và thử lại trước khi chạy test. Nếu container cùng tên đã tồn tại, chỉ dùng lại khi chắc chắn đó là container kiểm thử; không xóa container dự án để tránh trùng tên.

Integration tests dọn các bảng Gold trước mỗi test. Chỉ trỏ TEST_MART_* vào DB kiểm thử; fixture từ chối database không bắt đầu bằng test_ hoặc hai DSN khác database. Thiếu TEST_MART_* thì integration tests bị skip, không có nghĩa DB đã được kiểm tra.

Để xem API chạy với fixture vừa kiểm thử, giữ container trước lệnh stop, dùng MART_DSN bằng TEST_MART_API_DSN và chạy uvicorn như ở trên. Dữ liệu còn lại tùy test cuối cùng; khi cần bộ dữ liệu demo lặp lại, tự chạy lại seed trên đúng database kiểm thử sau khi dọn fixture cũ.

## Phạm vi chưa nghiệm thu

Kết quả kiểm tra ngày 17/11/2026: **30 test đạt**, gồm 18 test validation/lỗi/CORS và 12 integration test với PostgreSQL 16. Đã kiểm tra api_user có thể SELECT nhưng bị từ chối DELETE; transaction API là read-only. Smoke check health và OpenAPI đạt cho ingestion, analysis, clustering, prediction, api (scheduler tắt, chưa chạy tác vụ nghiệp vụ). Ruff kiểm tra mã thay đổi và định dạng đạt. Có một cảnh báo deprecation từ Starlette/AnyIO của môi trường test, không ảnh hưởng kết quả. Chưa chạy toàn bộ Docker Compose.

JWT/SSO, Viewer/Admin, Jobs API và runner chưa triển khai trong giai đoạn này. Chưa nghiệm thu luồng Cloudflare thật → Gold → frontend. Không đánh dấu hoàn tất toàn bộ phần Định trong issue #2 chỉ dựa vào bộ kiểm thử API đọc.
