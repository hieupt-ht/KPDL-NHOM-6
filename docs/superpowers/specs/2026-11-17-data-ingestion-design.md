# Thiết kế: Data Ingestion (Thành viên 1, Hiếu)

Ngày: 2026-11-17 · Nhánh: `feature/data-ingestion` · Phạm vi: `services/ingestion/`, `db/warehouse/`
Trạng thái: **chờ duyệt**

## 1. Mục đích

Đưa dữ liệu thật từ Cloudflare Radar (`location=VN`) vào Data Warehouse theo luồng Bronze → Silver, để Analysis (Minh) và ML (Hoàng) có một chuỗi thời gian sạch, nhất quán và liên tục để làm việc. Đây là đầu vào của toàn bộ hệ thống, nên sai ở đây là sai ở mọi nơi.

Tiêu chí hoàn thành theo issue #2: luồng **Cloudflare Radar → Bronze/Silver** chạy được local bằng dữ liệu thật.

## 2. Phát hiện từ việc gọi API thật (2026-11-17)

Các điều dưới đây đã kiểm chứng bằng token thật, không phải suy đoán.

1. **4 endpoint trong spec đều trả HTTP 200**: `http/timeseries`, `attacks/layer7/timeseries`, `http/timeseries_groups/bot_class` (đang bị đánh dấu deprecated nhưng còn chạy), `netflows/timeseries`.
2. **Dạng response:** `result.serie_0.timestamps` (UTC, từng giờ, đuôi `Z`) cùng `values` (hoặc `bot` và `human` cho bot_class), kèm `result.meta` (có `normalization`, `lastUpdated`).
3. **Độ trễ không đều giữa các chỉ số.** Với `dateRange=2d`: `http_traffic` và `bot_class` có 48 điểm đến 00:00, `l7_attack` 46 điểm đến 22:00, `netflows` 47 điểm đến 23:00. Mỗi chuỗi phải dùng `timestamps` của chính nó.
4. **Thang đo `MIN0_MAX` tính theo từng cửa sổ truy vấn.** `http_traffic`, `l7_attack`, `netflows` đều là `MIN0_MAX`, giá trị lớn nhất của cửa sổ luôn bằng 1. Cùng mốc `2026-11-05T12:00Z`: 0,902153 ở cửa sổ 1→8/11, 0,840159 ở cửa sổ 4→11/11, 0,902153 ở cửa sổ 4→8/11 (đỉnh nằm trong vùng chồng nên hệ số giống cửa sổ đầu). Giá trị của cùng một mốc chỉ khác nhau một **hằng số nhân** giữa các cửa sổ.
5. **`bot_class` dùng `PERCENTAGE`** (bot + human = 100), là số tuyệt đối theo tỉ lệ, không bị lệch thang đo giữa các cửa sổ.
6. **Giới hạn cửa sổ:** `aggInterval=1h` chấp nhận `dateRange` 30 ngày, từ chối 45 ngày (HTTP 400, code 2001). Tham số `normalization` không có lựa chọn nào cho thang cố định (`PERCENTAGE` không hợp lệ cho các endpoint này, `PERCENTAGE_CHANGE` cần chuỗi so sánh).

Hệ quả: spec cũ (backfill từng lô 7 ngày, polling `dateRange=2d`, ghi thẳng vào Silver) sẽ làm Silver bị lệch thang đo tại mỗi điểm nối.

## 3. Mục tiêu, không mục tiêu, và điều không được xảy ra

**Mục tiêu**
- Silver chứa chuỗi giờ liên tục cho 5 chỉ số, nhiều nhất có thể trong 12 tháng gần nhất, **cùng một thang đo** trên toàn chuỗi.
- Thu thập định kỳ 5 phút bền bỉ: API lỗi, timeout, 429 không làm sập service.
- Bronze giữ nguyên văn mọi phản hồi để truy vết và xử lý lại.
- Chạy lại bao nhiêu lần cũng không sinh dữ liệu trùng (idempotent).
- Có hướng dẫn chạy và test (issue yêu cầu mỗi thành viên hướng dẫn chạy module của mình).

**Không mục tiêu**
- Không làm phân tích, Gold, API, dashboard.
- Không sửa `backend/common/` (thuộc Định/trưởng nhóm). Nếu cần sửa, tạo issue hoặc PR riêng.
- Không làm gRPC, API Gateway (đã hoãn).
- Không viết trình nạp dữ liệu demo; chỉ chừa cột để phân biệt (mục 5.3).
- Không dùng proxy hay crawling.

**Điều không được xảy ra**
- Silver chứa các đoạn có thang đo khác nhau mà không ai biết.
- Mất hoặc sửa dữ liệu thô ở Bronze.
- Token Cloudflare xuất hiện trong log, Bronze (`params`), commit hay lỗi trả về.
- Một chỉ số lỗi làm dừng cả chu kỳ, hoặc service chết hẳn khi API sập.

## 4. Các hướng đã cân nhắc (về thang đo)

| Hướng | Nội dung | Đánh đổi |
| :--- | :--- | :--- |
| A | Ghi nguyên giá trị API trả | Đơn giản nhất nhưng chuỗi bị lệch ở mọi điểm nối lô, làm hỏng trend, seasonal và dự đoán. Loại. |
| **B (chọn)** | Ghép lô có vùng chồng, quy đổi về một thang chung bằng hệ số tính từ vùng chồng, rồi mới ghi Silver | Thêm một bước tính, cần test kỹ. Chuỗi nhất quán cho mọi người dùng sau. |
| C | Lưu giá trị gốc kèm ID cửa sổ, để Analysis tự quy đổi | Đẩy việc khó sang người khác và dễ hiểu nhầm. Loại. |

Người dùng chọn B (2026-11-17), nhóm cần báo Minh và Hoàng về ý nghĩa của giá trị Silver (mục 5.2).

## 5. Thiết kế

### 5.1. Chỉ số và endpoint

| `metric` | Endpoint | Trường lấy | Thang đo | Quy đổi? |
| :--- | :--- | :--- | :--- | :--- |
| `http_traffic` | `/radar/http/timeseries` | `values` | MIN0_MAX | **Có** |
| `l7_attack` | `/radar/attacks/layer7/timeseries` | `values` | MIN0_MAX | **Có** |
| `netflows` | `/radar/netflows/timeseries` | `values` | MIN0_MAX | **Có** |
| `bot_share` | `/radar/http/timeseries_groups/bot_class` | `bot` | PERCENTAGE | Không |
| `human_share` | `/radar/http/timeseries_groups/bot_class` | `human` | PERCENTAGE | Không |

Mọi truy vấn: `location=VN`, `aggInterval=1h`, `format=json`. `bot_class` dùng một lần gọi cho cả `bot_share` và `human_share`. Vì endpoint này đang deprecated, client phải kiểm tra `success` và ghi cảnh báo rõ ràng nếu nó biến mất, để biết đường chuyển sang endpoint thay thế.

### 5.2. Quy đổi thang đo (cách B)

Quy tắc: với mỗi chỉ số MIN0_MAX, **Silver là thang tham chiếu**. Mỗi cửa sổ mới `w(t)` được nhân một hệ số `k` để khớp với giá trị đã có trong Silver.

1. Lấy các mốc `t` có mặt ở cả cửa sổ mới và Silver, với `w(t) > 0` và giá trị Silver > 0.
2. `k = median( silver(t) / w(t) )` trên các mốc đó. Dùng trung vị để chống nhiễu và các mốc Cloudflare vừa điều chỉnh.
3. Ghi `k · w(t)` vào Silver cho tất cả các mốc của cửa sổ (kể cả mốc đã có, vì Cloudflare có thể điều chỉnh).
4. Yêu cầu tối thiểu **12 mốc chồng hợp lệ**. Không đủ thì **không ghi Silver** cho chỉ số đó ở lượt này, vẫn giữ Bronze, ghi cảnh báo và thử lại ở lượt sau. Không bao giờ ghi giá trị chưa quy đổi.
5. Khi Silver rỗng cho chỉ số đó, cửa sổ đầu tiên là mốc tham chiếu (`k = 1`).

Ý nghĩa giá trị Silver: **chỉ số tương đối, nhất quán trong toàn chuỗi, có thể lớn hơn 1** (vì cửa sổ cũ hơn có thể có đỉnh cao hơn cửa sổ tham chiếu). Phân tích dùng được cho trend, seasonal, tương quan, nhưng **không được giả định giá trị ≤ 1**. Cần báo cho Minh (histogram, anomaly) và Hoàng (đặc trưng, ngưỡng).

### 5.3. Backfill

- Chạy **từ mới đến cũ**: cửa sổ đầu là 28 ngày gần nhất, các cửa sổ sau lùi dần, mỗi cửa sổ **chồng 2 ngày** lên phần cũ nhất của Silver. Lý do: dữ liệu mới có ngay từ đầu và đang dùng được, và việc tiếp tục sau khi bị ngắt giữa chừng là tự nhiên (chỉ cần lùi tiếp từ mốc cũ nhất đang có).
- Mục tiêu độ sâu: khoảng 12 tháng. Người làm kiểm tra giới hạn tối đa mà `dateStart` cho phép (tài liệu ghi `dateRange` tối đa 364 ngày) và dừng ở mức lớn nhất được phép, ghi lại con số thật.
- Điều kiện còn thiếu: mốc cũ nhất trong Silver của một chỉ số mới hơn độ sâu mục tiêu. Tiếp tục lùi cho đến khi đủ hoặc API không còn dữ liệu cũ hơn.
- Khoảng 14 cửa sổ × 4 endpoint (bot_class chỉ một lần) nên giãn nhịp nhẹ giữa các lần gọi, vẫn dưới xa giới hạn 1.200 request mỗi 5 phút.
- Chạy ở nền khi service khởi động, **không chặn `/health`**, và không chạy song song với chu kỳ 5 phút (dùng một khóa chung).

### 5.4. Chu kỳ 5 phút

Mỗi chu kỳ: gọi các endpoint với `dateRange=2d`, lưu Bronze, parse, quy đổi theo 5.2 so với Silver, UPSERT. Một chỉ số lỗi chỉ được ghi nhận, không dừng chu kỳ. Cuối chu kỳ ghi một dòng `silver.ingestion_runs` với trạng thái `success`, `partial` hoặc `failed`, số dòng ghi và thông báo lỗi.

### 5.5. Xử lý lỗi và retry

- Timeout: kết nối 10 giây, đọc 30 giây.
- Thử lại với backoff 1s → 2s → 4s … tối đa 60s, tối đa khoảng 6 lần, cho: timeout, lỗi kết nối, HTTP 429, HTTP 5xx. Tôn trọng header `Retry-After` nếu có.
- Không thử lại với 400/401/403: ghi lỗi rõ ràng (nêu rõ nếu token sai hoặc thiếu quyền) và dừng chỉ số đó.
- Thiếu `CF_API_TOKEN` hoặc còn giá trị mẫu: báo lỗi cấu hình dễ hiểu, không crash vòng lặp lập lịch.
- Token **không bao giờ** ghi ra log, Bronze hay thông báo lỗi.

### 5.6. Bronze

Mỗi lần gọi (kể cả lỗi) lưu một dòng `bronze.raw_api_responses`: `endpoint`, `params` (cửa sổ, `location`, `aggInterval`, không có header hay token), `status_code`, `payload` nguyên văn, `fetched_at`. Dọn các dòng quá 30 ngày; chạy mỗi chu kỳ, có chỉ mục theo `fetched_at`.

### 5.7. Silver: làm sạch

- Timestamp: parse thành `TIMESTAMPTZ` UTC (đuôi `Z`).
- Bỏ giá trị `null`, không phải số, NaN, vô cực, giá trị âm. Với MIN0_MAX, giá trị thô phải nằm trong [0, 1]; ngoài khoảng thì bỏ. Với `bot_share`/`human_share`, phải nằm trong [0, 100].
- Loại trùng `ts` trong cùng một response (giữ giá trị cuối); UPSERT theo khóa `(ts, metric)`.
- Đổi sang giờ Việt Nam là việc của Analysis, không làm ở đây.

### 5.8. Thay đổi schema (`db/warehouse/`)

- Thêm `silver.metrics_hourly.source VARCHAR(16) NOT NULL DEFAULT 'radar'` để phân biệt dữ liệu thật và dữ liệu demo theo yêu cầu của issue. (Quyết định của người thiết kế, chưa được xác nhận bởi nhóm.)
- Thêm chỉ mục `bronze.raw_api_responses (fetched_at)`.
- `silver.ingestion_runs.status` là `VARCHAR(16)` không ràng buộc, nên giá trị `partial` dùng được mà không cần đổi schema. Không đổi tên cột nào, để không ảnh hưởng người khác.
- Các script trong `db/warehouse/init/` chỉ chạy lần đầu tạo volume, nên máy đã có volume cũ cần `docker compose down -v` để áp dụng (báo cả nhóm).

### 5.9. Cấu trúc code

Giữ nguyên các file có sẵn: `radar_client.py` (HTTP, retry), `bronze.py`, `silver.py` (parse, làm sạch, UPSERT), `main.py` (vòng lặp, backfill). Phần quy đổi thang đo tách thành module riêng có thể test độc lập (ví dụ `rescale.py`). Thư mục `services/ingestion/tests/` chứa test và dữ liệu mẫu.

## 6. Kiểm thử và tiêu chí nghiệm thu

**Test tự động** (dùng JSON thật đã lưu làm dữ liệu mẫu, không chứa bí mật):
- Parse: các endpoint, chuỗi có độ dài khác nhau, giá trị lỗi bị loại.
- Quy đổi: dùng đúng các cửa sổ A/B/C ở mục 2, kiểm tra mốc `2026-11-05T12:00Z` sau quy đổi khớp nhau trong sai số nhỏ; kiểm tra trường hợp không đủ vùng chồng (không ghi).
- Retry: giả lập 429, 5xx, timeout bằng `httpx.MockTransport`; 4xx không thử lại.
- UPSERT idempotent: chạy hai lần cho cùng dữ liệu, số dòng không đổi (cần Postgres, đánh dấu integration test).

**Nghiệm thu bằng dữ liệu thật** (chạy `docker compose up` với token thật):
1. Silver có chuỗi giờ liên tục cho 5 chỉ số, sâu khoảng 12 tháng (nêu rõ con số thực tế).
2. Không có bước nhảy thang đo tại các điểm nối cửa sổ (hai cửa sổ liền kề khớp nhau trên vùng chồng sau quy đổi).
3. Chạy lại không tạo thêm dòng trùng.
4. Bronze giữ nguyên văn payload, không có token.
5. Ngắt mạng hoặc token sai: service vẫn chạy, `ingestion_runs` ghi đúng trạng thái, tự phục hồi khi có lại.
6. Ngắt giữa chừng khi đang backfill rồi chạy lại: tiếp tục từ chỗ dở.

## 7. Cập nhật tài liệu

README cần sửa cho khớp: 3.3 (ghi chú `bot_class` deprecated, `l7_attack` được quy theo vị trí IP của client theo tài liệu Cloudflare, nghĩa là mức tấn công **xuất phát** từ VN, cần xác nhận lại), 3.5 (backfill lô 28 ngày có chồng thay cho lô 7 ngày), 4.1 (cột `source`, ý nghĩa giá trị Silver). Phần README thuộc trưởng nhóm, đề nghị sửa qua PR riêng hoặc gộp cùng PR này kèm sự đồng ý của họ.

## 8. Việc để người làm quyết định

- Số lần retry, độ trễ giữa các lần gọi backfill, kích thước cửa sổ khi API thay đổi giới hạn.
- Tên module, cách đặt khóa, cách chạy backfill nền (luồng riêng hay tác vụ lập lịch một lần).
- Độ sâu tối đa thực tế của backfill sau khi thử.

## 9. Rủi ro và việc cần báo nhóm

- **Giá trị Silver có thể > 1** (báo Minh, Hoàng).
- **Đổi schema Warehouse** cần xóa volume cũ (báo cả nhóm).
- `bot_class` có thể bị Cloudflare gỡ trong tương lai.
- Giả định chưa kiểm chứng: hệ số quy đổi ổn định khi Cloudflare điều chỉnh các mốc gần đây (đã giảm thiểu bằng trung vị và việc ghi đè các mốc chồng).
- Chưa đọc yêu cầu nguyên văn của giảng viên; nếu có quy định riêng về lưu dữ liệu thì thiết kế này cần chỉnh.
