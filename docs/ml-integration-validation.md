# Kiểm chứng tích hợp ML — 21/11/2026

Nhánh tích hợp lấy `develop` a329820 và PR #22 của Hoàng đến 6fed9f4. Giữ nguyên PR nguồn (base `feature/machine-learning`); PR tích hợp vào `develop` cần review của chủ phần ML. Không đổi schema Gold hay API JSON.

## Thay đổi Backend

- `common.runner` giữ nhật ký/khóa chạy duy nhất. Hai task ML chỉ ghi kết quả, trả `skipped` khi không đủ đầu vào và để lỗi lan lên runner để ghi `failed` an toàn.
- Prediction ghi hai bảng trong cùng transaction; lỗi ở bảng thứ hai phải rollback bảng thứ nhất.
- Chỉ đọc Silver Radar theo cùng điều kiện `COALESCE(source,'radar')='radar'` với Analysis. Ngày Việt Nam cần 24 giờ riêng biệt có giá trị hữu hạn.
- Compose mount `models/` chỉ đọc cho clustering/prediction. Trainer là profile offline riêng, dùng quyền đọc Silver; không huấn luyện trong Jobs API.
- Thiếu Silver để huấn luyện thì dừng. Demo chỉ được tạo khi yêu cầu rõ `--demo`; không tự thay thế dữ liệu thật.

## Chạy lại

```powershell
./training/tests/run.ps1
./services/api/tests/run.ps1 -Mode All
docker compose --profile training build trainer
docker compose --profile training run --rm trainer --out-dir /app/models/validation
```

API E2E dùng Silver tổng hợp trong DB `test_warehouse` và mô hình demo trong volume test riêng, không dùng token Cloudflare hay dữ liệu/volume ứng dụng. Kiểm tra Admin/Viewer, 202 và poll đúng run_id, một journal mỗi lần, upsert chạy lặp, đọc JSON Gold, rollback dự báo và giữ kết quả cũ khi thiếu dữ liệu. Đây là kiểm chứng luồng tích hợp, không chứng minh chất lượng mô hình thật.

## Huấn luyện Silver thật

Chạy offline thành công, `data_source=silver`, timestamp artifact `2026-11-21T11:01:24+07:00`. Dùng 356 ngày dự báo và 364 ngày phân cụm; train 284 ngày (29/11/2025–08/09/2026), test 72 ngày (09/09–19/11/2026). Không gọi API Cloudflare trong lần huấn luyện này; đọc dữ liệu Radar đã thu thập trong Silver.

| Mô hình | Kết quả |
| --- | --- |
| Random Forest hồi quy HTTP | MAE 0,044604; RMSE 0,048363 |
| Baseline giữ giá trị D−2 | MAE 0,014811 — tốt hơn Random Forest trong lần chạy này |
| Random Forest phân loại | Accuracy 0,875; F1 lớp Cao = 0; tỷ lệ Cao train/test 25% / 11,11% |
| Ngưỡng rủi ro | P75 train của trung bình ngày L7 = 0,113840282; cutoff P(Cao) = 0,5 |
| K-Means | k ép = 3; Silhouette 0,289242; k tốt nhất theo phép thử hiện tại = 2 |

Artifact được giữ cục bộ trong `models/validation/` (gitignore), chưa thay artifact chạy dashboard và chưa ghi Gold ứng dụng. Các số đánh giá trên là kết quả kiểm tra, **chưa đạt nghiệm thu ML**: hồi quy chưa thắng baseline, F1 Cao bằng 0. Hoàng cần kiểm tra phân phối/lớp dự báo, đặc trưng, validation theo thời gian và thử cải thiện trước khi chấp nhận mô hình; không tối ưu ngưỡng trực tiếp trên tập test cuối. Giữ Issue #13 mở.
