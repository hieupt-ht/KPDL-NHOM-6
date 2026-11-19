# Cyber Radar VN · Frontend

Next.js dashboard dùng bộ màu **Màu 1 – Cyber Navy**. Có bốn trang: Tổng quan (`/`), Phân tích (`/analysis`), Dự báo & phân cụm (`/forecast`), Vận hành (`/admin`).

## Chạy giao diện độc lập

Yêu cầu Node.js 20.9 trở lên và npm. Từ thư mục `frontend/`:

```bash
npm ci
cp env.example .env.local
npm run dev
```

Trên PowerShell thay `cp` bằng `Copy-Item env.example .env.local`. Mở `http://localhost:3000`.

Mặc định `NEXT_PUBLIC_DATA_MODE=demo`: dữ liệu minh họa được gắn nhãn trên giao diện và không cần Docker/API. Góc trên cho phép xem thử Viewer (`Nguyễn Văn A`) hoặc Admin (`Nguyễn Văn B`). Công tắc này chỉ trình diễn hai bố cục; **không xác thực hay cấp quyền thật**. Trong demo, nút Run bị khóa.

Trong chế độ demo, các trang dữ liệu tải lại sau mỗi **8 giây**. Chỉ giá trị điểm cuối của bộ dữ liệu mẫu biến động nhẹ; ngày và các quan sát cũ vẫn giữ nguyên. Biểu đồ vẽ khi mở trang và chuyển mượt đến giá trị mới, giúp trình diễn cách giao diện sẽ phản ứng khi backend có dữ liệu mới. Đây là mô phỏng, không phải luồng dữ liệu thời gian thực. Tắt tab hoặc hệ điều hành bật giảm chuyển động sẽ hạn chế cập nhật/hiệu ứng tương ứng.

Khi mở một tab có biểu đồ, trục và nhãn hiện trước; sau khi ECharts khởi tạo xong, dữ liệu được đưa vào lần lượt từng điểm hoặc từng cột/ô từ trái sang phải. Biểu đồ 31 điểm chạy khoảng **7,5 giây**; biểu đồ ngắn chạy nhanh hơn. Cơ chế này nằm trong `DataChart` và đọc dữ liệu từ `option.series`, nên hoạt động giống nhau với dữ liệu minh họa và dữ liệu API. Các lần cập nhật sau đó chuyển tới giá trị mới trong khoảng **1,1 giây**, giữ nguyên vị trí zoom.

### Tương tác trên trang Tổng quan

- Thanh trạng thái tách thời điểm **kiểm tra API** và **mốc dữ liệu mới nhất** do `/api/status` trả về. Mốc kiểm tra trong chế độ demo là thời gian tải dữ liệu minh họa.
- ECharts vẽ biểu đồ khi mở trang và chuyển tiếp biểu đồ khi dữ liệu đổi; KPI chỉ chuyển động khi giá trị thực sự đổi. SWR kiểm tra API lại mỗi 5 phút trong chế độ `api`, còn tần suất điểm dữ liệu do backend quyết định. Chế độ API không tự mô phỏng giá trị.
- Dòng thời gian đánh dấu các ngày có `cluster_name === "Bất thường"` từ `/api/clusters`. Chọn ngày ở dòng thời gian hoặc trên đường biểu đồ để mở chi tiết HTTP, L7, bot, nhãn cụm và so sánh với ngày trước. Thiếu kết quả phân cụm thì panel ghi rõ là chưa có nhãn.
- Nút **Phát lại dữ liệu lịch sử** chạy qua 7 hoặc 30 mốc ngày có sẵn; không gọi job backend. Dừng khi đổi bộ lọc, khi đến mốc cuối hoặc khi bấm Tạm dừng. Dự báo ngày mai vẫn là kết quả mới nhất và được ghi rõ trong KPI.
- Khi API trả về nhãn dự báo chuyển từ `Thấp` sang `Cao` trong cùng phiên mở trang, một thông báo nhỏ xuất hiện. Đây là thay đổi nhãn mô hình, không phải xác nhận sự cố. Thiết bị bật giảm chuyển động sẽ tắt animation trang và biểu đồ.

## Nối backend sau này

1. Hoàn thiện các endpoint FastAPI trong `services/api/routers/` trả JSON theo `frontend/types/api.ts`.
2. Trong `.env.local`, đặt `NEXT_PUBLIC_DATA_MODE=api` và `NEXT_PUBLIC_API_URL=http://localhost:8000`. Khởi động lại Next.js. `frontend/lib/api.ts` đã có URL, query, lỗi HTTP và các hàm gọi `/api/timeseries`, `/api/histogram`, `/api/trend`, `/api/seasonal`, `/api/correlation`, `/api/clusters`, `/api/forecast/*`, `/api/status`, `/api/jobs/{service}/run`. Trước khi tích hợp SSO, backend cần cấu hình chế độ phát triển `AUTH_ENABLED=false` theo README gốc; chỉ dùng trong môi trường phát triển.
3. Các trang dùng SWR để gọi lại mỗi 5 phút trong chế độ API. Chỉ biểu diễn dữ liệu nhận được; các trường thiếu sẽ hiện trạng thái rỗng hoặc lỗi. Giá trị HTTP/L7/Netflow là **chỉ số tương đối**, bot/human là **%**.
4. Khi hoàn thành SSO, thay `getAccessToken()` trong `lib/api.ts` bằng token Keycloak từ Auth.js; thay role xem thử trong `components/layout/AppShell.tsx` bằng role đã xác thực và bảo vệ route `/admin`. Backend bắt buộc kiểm tra role `admin` tại endpoint chạy job. Công tắc role hiện tại chỉ ẩn/hiện UI.

Hiện backend trong repository còn trả `501` cho nhiều endpoint. Nếu đổi sang `api` trước khi backend hoàn thiện, các panel sẽ báo rõ lỗi thay vì hiển thị số liệu minh họa.

## Kiểm tra

```bash
npm run lint
npm run build
```
