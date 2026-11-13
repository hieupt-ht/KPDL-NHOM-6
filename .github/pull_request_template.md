## Mô tả

<!-- PR này làm gì? Vì sao cần? -->
- [ ] PR nhắm vào đúng nhánh: nhánh tạm → `develop` (chỉ `develop` → `main` khi release)
## Service bị ảnh hưởng

- [ ] ingestion
- [ ] analysis
- [ ] clustering
- [ ] prediction
- [ ] api
- [ ] frontend
- [ ] db (warehouse / mart)
- [ ] keycloak / docker / ci
- [ ] docs

## Loại thay đổi

- [ ] `feat` – tính năng mới
- [ ] `fix` – sửa lỗi
- [ ] `refactor` – cải tổ code, không đổi chức năng
- [ ] `docs` – tài liệu
- [ ] `chore` – cấu hình, build, phụ thuộc

## Cách kiểm tra

<!-- Các bước để reviewer tự chạy thử, ví dụ:
1. docker compose up -d --build ingestion warehouse-db
2. Xem log: docker compose logs -f ingestion
3. Kiểm tra bảng silver.metrics_hourly có dữ liệu mới
-->

## Ảnh chụp (nếu đổi giao diện)

<!-- Kéo thả ảnh vào đây -->

## Checklist

- [ ] Đã chạy được bằng `docker compose up` trên máy mình
- [ ] Không commit `.env`, mật khẩu, token
- [ ] Nếu đổi schema DB: đã cập nhật `db/*/init.sql` và báo các service liên quan
- [ ] Nếu đổi API: đã cập nhật bảng endpoint trong README và báo người làm frontend
- [ ] Commit message đúng quy ước trong `CONTRIBUTING.md`

## Liên quan

<!-- Closes #<số issue> -->
