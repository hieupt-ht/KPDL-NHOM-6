# Bàn giao Backend/API cho issue #13 và PR #12

Đối chiếu ngày 19/11/2026: develop `2e0eda9`, PR #12 head `cca7448`, base **feature/machine-learning**, không phải develop. Nhánh ML có clustering khác develop; nhánh Analysis `c44dacb` cũng chưa merge. Không tự merge code của thành viên khác để làm test API đạt.

## Phần API có thể hỗ trợ

- Giữ nguyên hai bảng forecast và JSON object hiện có cho một mục tiêu mỗi loại; `label` Cao/Thấp, `probability` P(Cao). `model_name` có thể mang nguồn/thời điểm train theo đề xuất ML; API giữ nguyên chuỗi. Trường này không thay thế metadata đầy đủ về metric, threshold hoặc phiên bản feature.
- Bổ sung đọc `features.metric` dạng chuỗi trong cluster JSON, vẫn kiểm tra các số đo còn lại là số/null. Payload thực của nhánh ML trước đó làm API response validation lỗi; đã có regression test qua PostgreSQL và HTTP.
- UI ghi rõ P(Cao), kể cả nhãn Thấp; giữ missing values. Không biến đặc trưng mô hình thành thống kê mà UI chưa có.
- Ngày mặc định của API vẫn là **ngày mai theo Asia/Ho_Chi_Minh**; không lấy forecast cũ thay thế. Đã có test tại thời điểm hai lịch UTC/Việt Nam khác ngày.

Đây là hợp đồng phía API/đề xuất phối hợp, không phải xác nhận mọi thành viên đã đồng ý metric/ngưỡng/schema. Không cần migration DB cho các thay đổi này.

## Điểm cần sửa trước khi tích hợp PR #12 vào develop

1. **Ngày/horizon:** build_target_row bỏ ngày UTC hiện tại và trả ngày sau ngày đầy đủ mới nhất. Nếu Silver mới nhất đầy đủ là 18/11 thì target là 19/11, trong khi dashboard chạy ngày Việt Nam 19/11 cần 20/11. Đây vừa là lệch horizon vừa là khác múi giờ. Cần thống nhất training/features/inference và cách dùng ngày chưa đủ; không chỉ đổi chữ UTC hoặc đổi nhãn ngày ở API.
2. **Nhật ký trùng:** run_prediction và run_clustering tự INSERT/UPDATE gold.service_runs, trong khi main.py dùng common.runner đã sở hữu journal và khóa. Khi đưa về develop, tasks chỉ xử lý dữ liệu; runner ghi một dòng cho mỗi lần chạy. Không ghi success khi thực tế thiếu đầu vào và không có dự báo mà không thể hiện trạng thái thích hợp.
3. **Model trong Docker:** tasks tải /app/models/*.joblib nhưng Dockerfile chỉ COPY common và thư mục service; root Compose chưa mount models. Cần bàn giao artifacts/volume read-only hoặc image packaging, cùng MODELS_DIR, và kiểm thử thiếu model. Không huấn luyện trong API/job inference.
4. **Metric/nhãn:** README hiện mô tả hồi quy http_traffic và phân loại l7_attack với p75; code train/PR #12 hiện dùng http_traffic cho cả hai. Khuyến nghị giữ thiết kế README làm chuẩn cho đến khi nhóm duyệt thay đổi. p75 và cutoff xác suất 0.5 là hai khái niệm khác nhau, cần lưu metadata khi train và đánh giá trên tập thời gian tách biệt. Không tự chỉnh training ở PR API.
5. **Tên cụm/đặc trưng:** nhánh ML dùng Thấp/Bình thường/Cao và value/dev_7/diff_1, trong khi UI đang có Bình thường/Cao điểm/Bất thường và http_mean/l7_max/bot_mean. Cần quyết định mapping hoặc bổ sung thống kê thật. Không suy diễn Cao tương đương Bất thường, không vẽ số 0 cho trường chưa có.

## Nghiệm thu phối hợp tiếp

Sau khi owner sửa/chốt: build image có model, dùng Silver test riêng có mốc UTC/Việt Nam và dữ liệu thiếu, chạy manual qua Admin, kiểm tra đúng một journal/run ID, forecast target đúng lịch, GET /api/clusters không lỗi validation, UI không nhầm P(Cao), rồi mới nghiệm thu pipeline bằng dữ liệu Radar thật. Giữ issue #2/#5/#13 mở đến khi phần việc tương ứng được xác nhận; không tích hoàn thành chỉ vì CI API đạt.
