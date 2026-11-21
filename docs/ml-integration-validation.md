# Kiểm chứng tích hợp ML — 21/11/2026

Nhánh tích hợp lấy `develop` a329820, ban đầu PR #22 đến 6fed9f4, sau đó đồng bộ `feature/machine-learning` 50c408e (đã merge PR #20–#28) theo [Issue #29](https://github.com/hieupt-ht/KPDL-NHOM-6/issues/29). PR tích hợp vào `develop` cần review của chủ phần ML. Không đổi schema Gold hay API JSON.

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

## Lần đầu: mô hình trước các cải tiến #24–#28

Chạy offline thành công, `data_source=silver`, timestamp artifact `2026-11-21T11:01:24+07:00`. Dùng 356 ngày dự báo và 364 ngày phân cụm; train 284 ngày (29/11/2025–08/09/2026), test 72 ngày (09/09–19/11/2026). Không gọi API Cloudflare trong lần huấn luyện này; đọc dữ liệu Radar đã thu thập trong Silver.

| Mô hình | Kết quả |
| --- | --- |
| Random Forest hồi quy HTTP | MAE 0,044604; RMSE 0,048363 |
| Baseline giữ giá trị D−2 | MAE 0,014811 — tốt hơn Random Forest trong lần chạy này |
| Random Forest phân loại | Accuracy 0,875; F1 lớp Cao = 0; tỷ lệ Cao train/test 25% / 11,11% |
| Ngưỡng rủi ro | P75 train của trung bình ngày L7 = 0,113840282; cutoff P(Cao) = 0,5 |
| K-Means | k ép = 3; Silhouette 0,289242; k tốt nhất theo phép thử hiện tại = 2 |

Artifact được giữ cục bộ trong `models/validation/` (gitignore), chưa thay artifact chạy dashboard và chưa ghi Gold ứng dụng. Các số đánh giá trên là kết quả kiểm tra, **chưa đạt nghiệm thu ML**: hồi quy chưa thắng baseline, F1 Cao bằng 0. Hoàng cần kiểm tra phân phối/lớp dự báo, đặc trưng, validation theo thời gian và thử cải thiện trước khi chấp nhận mô hình; không tối ưu ngưỡng trực tiếp trên tập test cuối. Giữ Issue #13 mở.

## Cập nhật Issue #29: kiểm chứng độc lập sau cải tiến

Chạy Docker offline lại trên Silver Radar hiện có, artifact `2026-11-21T16:59:49+07:00`, lưu riêng `models/validation/issue29/`. Có 349 ngày dự báo và 364 ngày phân cụm; train 06/12/2025–10/09/2026 (279 ngày), test 11/09–19/11/2026 (70 ngày). Không thay artifact dashboard hoặc ghi Gold ứng dụng.

| Hạng mục | Kết quả trên cùng tập test hiện tại |
| --- | --- |
| RF hồi quy delta, đặc trưng tương đối | MAE 0,011320; RMSE 0,014740; R² 0,303692; leaf = 5 chọn trên validation |
| Baseline lag_2 | MAE 0,014371; RMSE 0,017852; R² −0,021279; RF giảm khoảng 21,2% MAE |
| RF phân loại rolling 28 ngày | Cutoff 0,35; accuracy 0,642857; precision 0,482759; recall 0,583333; F1 0,528302 |
| Xếp hạng phân loại | ROC-AUC 0,646286; PR-AUC 0,450556; tỷ lệ Cao test 0,342857 |
| Luôn Cao | F1 0,510638; precision/PR-AUC 0,342857 |
| Luôn Thấp | Accuracy 0,657143; F1 0 |
| K-Means k=3 | Silhouette 0,289242; Davies-Bouldin 1,225749; k=2 vẫn tốt hơn theo Silhouette |

Các chỉ số này **không phải tái lập nguyên tập test của Hoàng** trong #29 (10/09–20/11). Snapshot Silver và khoảng test khác nhau. Hồi quy đã thắng baseline trong lần kiểm chứng mới; phân loại chỉ hơn nhẹ baseline luôn Cao theo F1 và còn kém luôn Thấp theo accuracy. Không suy ra mô hình đã đủ tốt cho vận hành.

### Phần Backend đã cập nhật

- Giữ runner sở hữu journal/lock và transaction hai forecast khi lấy code ML mới.
- Dùng cutoff lưu trong bundle; E2E đọc cutoff từ metrics của mô hình test, không gán cứng 0,5. API/FE vẫn dùng label đã tính và P(Cao).
- Lưu mode nhãn/cửa sổ rolling vào metadata; từ chối artifact lệch mode, cửa sổ, percentile hoặc múi giờ. Artifact rolling cũ thiếu metadata cần train lại.
- Chặn override percentile qua CLI trong mode rolling khi khác config tạo `risk_ref`, tránh gắn metadata sai ngưỡng thực tế.
- Đưa script đánh giá và matplotlib vào Docker trainer; báo cáo thêm baseline luôn Cao/luôn Thấp trên cùng tập test. Sinh 8 biểu đồ và `eval_report.json` để kiểm tra cục bộ.

### Điểm còn chờ nhóm chốt

1. Hoàng/nhóm xác nhận thay ý nghĩa nhãn Cao từ p75 tập train sang p75 cửa sổ 28 ngày kết thúc ở D−2; lúc khởi động chấp nhận tối thiểu 14 ngày hợp lệ. `risk_threshold` lưu trong bundle rolling chỉ là trung vị tham khảo, không phải ngưỡng cố định áp dụng mọi ngày.
2. FE đã có hiển thị P(Cao) bên cạnh nhãn. Vũ review cách giải thích nhãn mới; không tự suy ra nhãn bằng cutoff 0,5. Không gọi xác suất RF là xác suất đã được hiệu chỉnh nếu chưa đánh giá calibration.
3. Giữ k=3 hay đổi k=2 cần nhóm quyết định; nhánh hiện giữ k=3 theo đề xuất Hoàng. Không tự bỏ giai đoạn đầu hoặc bổ sung metric chưa được xác nhận.

Giữ PR #23 Draft và các issue quyết định mở. Việc tích hợp/kiểm thử kỹ thuật và việc nghiệm thu định nghĩa nhãn, chất lượng mô hình là hai kết luận riêng.
