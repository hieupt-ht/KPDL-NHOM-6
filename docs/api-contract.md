# Backend API: Gold và Jobs — truy cập trực tiếp

Đã triển khai trên nhánh `feature/backend-api`, nền `develop`. Các quyết định dưới đây là đề xuất cụ thể để Minh, Hoàng và Vũ cùng tích hợp; chưa có xác nhận của các thành viên. Schema Gold hiện có được giữ nguyên.

## Truy cập

Dashboard và API không còn đăng nhập/Viewer/Admin. Không cần cookie hoặc Bearer token. /api/me và các route NextAuth đã được gỡ. Các cấu hình AUTH_ENABLED/KEYCLOAK/NEXTAUTH cũ không còn tác dụng. /run nội bộ vẫn kiểm tra JOB_TRIGGER_TOKEN; lỗi thiếu cấu hình trả 503, sai token trả 401.

## Quy tắc chung

- Base URL local: `http://localhost:8000`. Swagger: `/docs`, OpenAPI: `/openapi.json`.
- GET dữ liệu trả array JSON; hai endpoint forecast trả một object; status trả object. Không bọc thêm `data` để giữ dạng dữ liệu frontend đã khai báo.
- Metric: `http_traffic`, `l7_attack`, `bot_share`, `human_share`, `netflows`.
- `start`, `end` là ISO 8601 có múi giờ. Khoảng thời gian là `[start, end)`: bao gồm start, không bao gồm end; nếu cùng truyền thì start phải nhỏ hơn end. Thiếu một cận được phép. Khi ghép query thủ công phải URL encode dấu `+` trong offset, hoặc dùng URLSearchParams.
- Chuỗi thời gian lọc theo timestamp và trả timestamp UTC. Với clusters/forecast, hai cận được chuyển sang ngày lịch Việt Nam (`Asia/Ho_Chi_Minh`) trước khi lọc DATE; truyền mốc nửa đêm Việt Nam để chọn nguyên ngày.
- Cột số nullable trong DB có thể trả `null`; NaN/Infinity ở các trường đo lường nullable cũng trả null để tạo JSON hợp lệ. Frontend cần cập nhật các type tương ứng thành `number | null` và xử lý điểm thiếu. Không biến thiếu dữ liệu thành 0.
- Chưa có dữ liệu hoặc không khớp bộ lọc: `404` với `{"detail":"No Gold data matches the requested filters"}`. Riêng status trống trả 200 để trang Vận hành có thể dùng trước lần chạy đầu.
- Tham số không hợp lệ: `422`; DB thiếu cấu hình, không kết nối được, timeout hoặc schema chưa sẵn sàng: `503`. Thông tin kết nối và SQL không được đưa vào lỗi trả cho browser.
- `/health` kiểm tra tiến trình; `/ready` kiểm tra kết nối Mart và sự tồn tại/quyền SELECT của 10 bảng, không yêu cầu có bản ghi. Các endpoint này không yêu cầu token.

## Endpoint

| Method/path | Query | Kết quả |
| --- | --- | --- |
| GET /api/timeseries | metric, granularity=day/week/month bắt buộc; start/end, limit/offset tùy chọn | `[{granularity,ts,metric,mean,min,max}]`, tăng dần theo ts |
| GET /api/histogram | metric bắt buộc | `[{metric,bin_start,bin_end,count}]`, tăng dần theo bin |
| GET /api/trend | metric, granularity=week/month bắt buộc; start/end tùy chọn | `[{granularity,ts,metric,trend_value}]`, tăng dần theo ts |
| GET /api/seasonal | metric, period_type=hour_of_day/day_of_week/month bắt buộc | `[{period_type,bucket,metric,value}]`, tăng dần theo bucket |
| GET /api/correlation | Không có bộ lọc thời gian | `[{var_x,var_y,coef,computed_at}]`, sắp xếp theo var_x/var_y |
| GET /api/clusters | start/end, limit/offset tùy chọn | `[{date,cluster_id,cluster_name,features,computed_at}]`, tăng dần theo date |
| GET /api/forecast/continuous | start/end tùy chọn | `{target_date,predicted_value,model_name,created_at}` |
| GET /api/forecast/discrete | start/end tùy chọn | `{target_date,label,probability,model_name,created_at}` |
| GET /api/status | Không có bộ lọc thời gian | `{service_runs:[...],data_freshness:object hoặc null}` |
| GET /api/jobs/runs/{run_id} | run_id >= 1 | Một ServiceRun; 404 nếu không tồn tại; dùng để theo dõi ID nhận từ 202 |
| POST /api/jobs/{analysis\|clustering\|prediction}/run | Không cần đăng nhập | 202 `{service,run_id,status:"accepted"}`; 409 nếu đang chạy |

Histogram, seasonal và correlation là snapshot được Analysis tính sẵn trên tập dữ liệu đầu vào. Gold chưa lưu cửa sổ tổng hợp nên nếu truyền start/end sẽ nhận **422**, không âm thầm bỏ bộ lọc. Status cũng từ chối start/end vì phản ánh trạng thái hiện tại. Các tham số này vẫn hiện trong Swagger để mô tả lỗi cho client cũ; cần bỏ chúng khỏi lời gọi frontend cho 4 endpoint này. Khi nhóm cần thống kê theo khoảng tùy chọn, phải thống nhất thay đổi cả Analysis và Gold trước.

Timeseries/clusters phân trang với `limit` mặc định 1000, tối đa 10000 và `offset` mặc định 0. Header `X-Total-Count` là tổng số bản ghi khớp bộ lọc, `X-Limit`/`X-Offset` là phân trang hiện tại; body vẫn là array. Header được CORS expose cho frontend. Trang vượt quá kết quả trả 404 theo quy tắc dữ liệu trống. Các snapshot trả đầy đủ các bin/bucket/cặp biến, không phân trang.

Forecast mặc định lấy **đúng ngày mai theo lịch Việt Nam**, không thay bằng dự báo cũ. Khi truyền start/end, trả dự báo có target_date mới nhất trong khoảng lọc; không có kết quả là 404. `label` có thể là Cao, Thấp hoặc null; probability là xác suất 0–1 hoặc null. Đây là kết quả đọc từ Gold, không chạy model trong API.

`probability` được đọc theo nghĩa **P(Cao)** (hợp đồng tích hợp đề xuất ở issue #13), kể cả khi `label="Thấp"`. Ví dụ Thấp + 0.2 nghĩa là xác suất Cao 20%, không phải độ tin cậy Thấp 20%. API giữ nguyên kết quả, không tự đảo xác suất hoặc chọn lại nhãn/cutoff. Metric tính rủi ro, percentile và cutoff cần nhóm ML/Analysis chốt; API không coi các giá trị tạm trong PR #12 là quyết định chung.

Issue #29 đề xuất đổi định nghĩa Cao sang vượt p75 của 28 ngày đã biết trước ngày đích (D−2), thay ngưỡng cố định của tập train. Nhánh tích hợp đang kiểm chứng đề xuất này và cutoff được chọn offline trên validation. Đây là thay đổi ý nghĩa nhãn dù schema Gold không đổi; chưa coi là nhóm đã chốt. Client cần dùng `label` từ API và hiển thị P(Cao), không suy ra nhãn bằng ngưỡng 0.5. Ngưỡng rolling `risk_ref` và cutoff xác suất là hai đại lượng khác nhau.

`cluster_results.features` giữ các số đo số/null và hỗ trợ riêng metadata `metric` thuộc danh sách Metric. Ví dụ `{"metric":"http_traffic","value":1.31,"dev_7":null}`. Chỉ khóa `metric` được chứa tên metric dạng chuỗi; các khóa số đo khác vẫn phải là số/null. JSON ngoài không đổi, không thêm cột DB. Frontend không dùng trường metadata hoặc đặc trưng value/lag/rolling làm thay thế HTTP mean/L7 max/bot mean nếu chưa có quy ước. Các tên cụm ngoài Bình thường/Cao điểm/Bất thường cần nhóm thống nhất cách diễn giải, không tự coi Cao là Bất thường.

Status trả một lần chạy mới nhất của mỗi service (started_at giảm dần, id giảm dần để phá hòa; started_at NULL xếp sau). Chưa chạy service nào thì `service_runs=[]`; chưa có freshness thì `data_freshness=null`. Cấu trúc từng phần tử giữ tên trường của frontend/types/api.ts.

Ví dụ:

```json
[{"granularity":"day","ts":"2026-11-01T00:00:00Z","metric":"http_traffic","mean":0.3,"min":0.1,"max":0.5}]
```

```json
{"target_date":"2026-11-18","label":"Cao","probability":0.8,"model_name":"RandomForestClassifier","created_at":"2026-11-17T01:00:00Z"}
```

## Chạy job

Mọi client gọi Jobs API trực tiếp. API gửi POST tới service cố định, kèm X-Job-Token từ JOB_TRIGGER_TOKEN. Thiếu token nội bộ trả 503; sai token ở /run trả 401. Browser không nhận token này. API không ghi Gold hoặc tự retry POST: timeout trả 504, không kết nối được trả 503, response sai trả 502 đã làm sạch.
Service trả 202 sau khi giữ khóa và tạo dòng `running` trong Gold, sau đó chạy nền. Theo dõi đúng run_id qua `/api/jobs/runs/{run_id}`; `/api/status` là bản tổng hợp: `running`, `success`, `failed`, `partial`, `skipped` hoặc `interrupted`. 202 chỉ có nghĩa đã nhận, không có nghĩa tính toán thành công. Cả scheduler và manual Run dùng cùng khóa trong process và advisory lock PostgreSQL theo service; khác service có thể chạy song song. Lock được giữ bằng một kết nối Mart riêng đến hết job. Sau crash, lần chạy tiếp theo đánh dấu dòng running cũ là interrupted rồi tạo lần chạy mới. Nếu mất kết nối DB trong lúc chạy, service có thể không ghi được trạng thái kết thúc; cần xem log và lần khôi phục sau đó.

`common.runner` là nơi duy nhất ghi `gold.service_runs` cho Analysis/Clustering/Prediction; các hàm tasks.run_all chỉ xử lý dữ liệu và không ghi thêm nhật ký. Chưa có timeout hủy tác vụ đang chạy hoặc job queue bền vững. Chạy một uvicorn worker/service là cấu hình hiện tại; không bật nhiều scheduler để tránh các lượt lịch lặp nối tiếp giữa worker.


Nguồn kỹ thuật tham khảo: [Psycopg — query parameters](https://www.psycopg.org/psycopg3/docs/basic/params.html), [FastAPI — class dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/classes-as-dependencies/).
