# Jobs API — không cần đăng nhập

Dashboard và API đã bỏ xác thực người dùng từ 22/11/2026. Mọi người truy cập được Vận hành và gọi POST /api/jobs/{analysis|clustering|prediction}/run. GET /api/jobs/runs/{id} trả đúng nhật ký của lần chạy; GET /api/status trả trạng thái tổng hợp.

API gửi X-Job-Token tới /run nội bộ. JOB_TRIGGER_TOKEN phải khớp ở API/logic; thiếu cấu hình trả 503, sai token nội bộ trả 401. Token không được gửi ra browser. Giữ allow-list service URL, không tự retry POST, 202 + run_id, khóa local/PostgreSQL và common.runner sở hữu duy nhất journal Analysis/ML.

Các endpoint Gold giữ nguyên schema, validation, pagination và tài khoản API chỉ SELECT. Keycloak, JWT/JWKS, /api/me, Viewer/Admin và các route NextAuth đã gỡ. Xem frontend-live-integration.md để chạy sau khi pull.