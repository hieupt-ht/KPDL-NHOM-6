# Quy ước làm việc nhóm

Tài liệu này giúp cả nhóm làm chung **một repo (monorepo)** mà không giẫm chân nhau.

---

## 1. Phân công theo thư mục

Mỗi thành viên phụ trách chính một (hoặc vài) thư mục. File `.github/CODEOWNERS` sẽ tự gán người đó review khi có PR chạm vào thư mục của họ.

| Thư mục | Phụ trách |
| :--- | :--- |
| `services/ingestion/`, `db/warehouse/` | *(điền tên)* |
| `services/analysis/`, `db/mart/` | *(điền tên)* |
| `services/clustering/`, `services/prediction/`, `training/`, `models/` | *(điền tên)* |
| `services/api/`, `keycloak/` | *(điền tên)* |
| `frontend/` | *(điền tên)* |
| `docker-compose.yml`, `backend/common/`, `docs/`, README | *(trưởng nhóm)* |

> Muốn sửa thư mục của người khác: vẫn được, nhưng **phải qua Pull Request** và người phụ trách duyệt.

---

## 2. Quy trình làm việc

```bash
# 1. Luôn bắt đầu từ main mới nhất
git checkout main
git pull origin main

# 2. Tạo nhánh cho công việc
git checkout -b feat/ingestion-backfill

# 3. Code, commit nhỏ và thường xuyên
git add services/ingestion/
git commit -m "feat(ingestion): add 12-month backfill in 7-day chunks"

# 4. Trước khi đẩy, cập nhật lại từ main để giảm conflict
git fetch origin
git rebase origin/main        # hoặc: git merge origin/main

# 5. Đẩy nhánh và mở Pull Request trên GitHub
git push -u origin feat/ingestion-backfill
```

**Quy tắc:**

- ❌ **Không push thẳng vào `main`**. Bật *Branch protection* cho `main` (Settings → Branches): bắt buộc PR + ít nhất 1 người duyệt.
- ✅ Mỗi PR chỉ làm **một việc**, càng nhỏ càng dễ review.
- ✅ Sau khi merge, **xóa nhánh** cũ.
- ✅ Dùng **Squash and merge** để lịch sử `main` gọn.

---

## 3. Đặt tên nhánh

```
<loại>/<service>-<mô-tả-ngắn>
```

| Loại | Dùng khi | Ví dụ |
| :--- | :--- | :--- |
| `feat` | Thêm tính năng | `feat/fe-correlation-heatmap` |
| `fix` | Sửa lỗi | `fix/api-401-issuer-mismatch` |
| `refactor` | Cải tổ code | `refactor/common-db-pool` |
| `docs` | Tài liệu | `docs/readme-network-diagram` |
| `chore` | Cấu hình, Docker, phụ thuộc | `chore/compose-healthcheck` |

Viết thường, nối bằng dấu `-`, không dấu tiếng Việt.

---

## 4. Commit message

Theo chuẩn **Conventional Commits**, có tên service trong ngoặc:

```
<loại>(<service>): <mô tả ngắn, thể mệnh lệnh>
```

Ví dụ:

```
feat(ingestion): save raw JSON response to bronze table
fix(prediction): handle missing lag-7 features
feat(fe): add day/week/month tabs to traffic line chart
refactor(common): extract APScheduler runner
chore(docker): add healthcheck for mart-db
docs(readme): update demo steps
```

Tên service hợp lệ: `ingestion`, `analysis`, `clustering`, `prediction`, `api`, `fe`, `db`, `keycloak`, `common`, `training`, `docker`, `ci`, `readme`.

---

## 5. Khi thay đổi ảnh hưởng người khác

| Bạn thay đổi… | Phải làm thêm |
| :--- | :--- |
| Schema DB (`db/*/init.sql`) | Báo người làm service đọc/ghi bảng đó; ghi rõ trong PR |
| Endpoint hoặc dạng JSON của API | Cập nhật bảng endpoint trong README, báo người làm frontend |
| `backend/common/` | Chạy thử **tất cả** service Python trước khi mở PR |
| Biến môi trường mới | Thêm vào `.env.example` (giá trị giả), không bao giờ commit `.env` |
| `docker-compose.yml` | Chạy `docker compose down && docker compose up -d --build` để kiểm tra toàn bộ |

---

## 6. Bí mật & dữ liệu

- `.env` **không bao giờ** được commit. Chỉ commit `.env.example` với giá trị giả.
- Lỡ commit token Cloudflare / mật khẩu: **thu hồi (revoke) ngay** trên Cloudflare / đổi mật khẩu, rồi mới xóa khỏi git — xóa commit không đủ vì lịch sử vẫn còn.
- Không commit dữ liệu thô, file dump DB.
- Model `.pkl` nhẹ (< vài MB) có thể commit; nặng thì dùng Git LFS.

---

## 7. Môi trường phát triển

- Mỗi service Python có `requirements.txt` riêng và tạo `venv` riêng khi chạy ngoài Docker.
- Frontend dùng một trình quản lý gói thống nhất cho cả nhóm (ví dụ `npm`) — **chỉ commit một** file lock (`package-lock.json`).
- Khi phát triển phần khác chưa cần đăng nhập: đặt `AUTH_ENABLED=false` trong `.env`.
