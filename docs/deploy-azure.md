# Deploy thủ công lên Azure (1 VM + Docker Compose + HTTPS)

Mục tiêu: chạy nguyên stack 8 container của repo trên **một VM Azure**, thêm Caddy để có HTTPS và để trình duyệt gọi API cùng domain với web (không cần sửa code, không dính CORS). Chi phí thấp, hợp với tài khoản Azure for Students (~100 USD).

> Tài liệu này là hướng dẫn thao tác tay, chưa được chạy thử trên Azure. Phần cấu hình Compose/Caddy đã kiểm tra bằng `docker compose config` (merge đúng, DB/API/FE không còn publish cổng ra ngoài), nhưng chưa build trên máy Azure thật.

## 0. Chuẩn bị

- Tài khoản Azure for Students còn credit.
- **`CF_API_TOKEN`**: token Cloudflare Radar (chỉ đọc). Không có token thì ingestion không có dữ liệu, các biểu đồ trống.
- Một SSH key (`ssh-keygen -t ed25519`) hoặc để Azure tự tạo và tải file `.pem`.

## 1. Chọn cấu hình VM (tiết kiệm)

Cần khoảng 2–3 GB RAM cho 8 container (2 PostgreSQL, 5 service Python có pandas/scikit-learn, 1 Next.js), và build image cần thêm RAM.

| Cấu hình | Dùng được? |
| :--- | :--- |
| Các size miễn phí của Azure for Students (B1s, B2ats v2, B2pts v2) | **Không**, chỉ 1 GiB RAM |
| `Standard_B2s` (2 vCPU, 4 GiB) | **Khuyến nghị**, khoảng 38 USD/tháng nếu bật 24/7 ở Southeast Asia (số của site thứ ba, chưa kiểm chứng) |
| `Standard_B2als_v2` hoặc `B2as_v2` (2 vCPU, 4 GiB trở lên) | Phương án thay thế nếu B2s bị chặn ở subscription của bạn |

Sinh viên hay gặp lỗi `NotAvailableForSubscription` hoặc "region không được phép". Nếu size/region không hiện: thử region khác trong danh sách được phép, hoặc kiểm tra bằng Cloud Shell:

```bash
az vm list-skus --location southeastasia --size Standard_B2 --output table
```

Cột `Restrictions` cho biết size nào bị chặn.

Ước tính chi phí: VM bật khoảng 0,05 USD/giờ, ổ đĩa Standard SSD 30 GB ~ vài USD/tháng, IP tĩnh ~ vài USD/tháng. **VM đã Stop (deallocate) không tính tiền compute**, chỉ còn ổ đĩa và IP. Cách rẻ nhất: dựng và kiểm thử xong thì Stop VM, chỉ Start lại 1–2 ngày trước buổi chấm.

## 2. Tạo VM trên Azure Portal

1. **Create a resource → Virtual machine**.
2. Resource group mới (ví dụ `kpdl-rg`, để cuối cùng xóa cả nhóm cho sạch). Region: chọn region gần (Southeast Asia nếu được phép).
3. Image: **Ubuntu Server 24.04 LTS (x64)**. Size: `Standard_B2s`.
4. Authentication: SSH public key. Username: `azureuser`.
5. Inbound ports: chọn **SSH (22)** tạm thời. Tab Disks: **Standard SSD**, 30 GB là đủ.
6. Tạo xong, vào VM → **Networking**:
   - Thêm rule inbound **80** và **443** (Source: Any).
   - Sửa rule SSH 22: Source = **My IP address**.
   - **Tuyệt đối không mở** 5432, 5433, 8000, 3000 ra Internet.
7. VM → **Overview → Public IP address → Configuration → DNS name label**: đặt tên, ví dụ `kpdl6`. Domain sẽ là `kpdl6.<region>.cloudapp.azure.com` (miễn phí, Caddy xin được chứng chỉ Let's Encrypt cho tên này).
8. **Cost Management → Budgets**: tạo budget 50 USD kèm email cảnh báo.

## 3. Cài Docker và swap trên VM

```bash
ssh azureuser@kpdl6.<region>.cloudapp.azure.com
```

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Thoát SSH rồi vào lại để nhận quyền nhóm `docker`, sau đó thêm 2 GB swap (tránh hết RAM lúc build Next.js):

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
docker compose version   # cần >= 2.24 để dùng "!reset"
```

## 4. Lấy code và tạo `.env`

```bash
git clone -b develop https://github.com/hieupt-ht/KPDL-NHOM-6.git
cd KPDL-NHOM-6
cp .env.example .env
```

(Nếu repo private: dùng Personal Access Token hoặc `gh auth login`.)

Sinh mật khẩu ngẫu nhiên dạng hex (không có ký tự đặc biệt, vì mật khẩu nằm trong DSN dạng URL):

```bash
for i in 1 2 3 4 5 6; do openssl rand -hex 16; done
```

Mở `nano .env` và sửa các dòng sau, **trước khi chạy `up` lần đầu** (script khởi tạo DB chỉ chạy một lần trên volume trống, đổi mật khẩu sau đó phải `down -v`):

```dotenv
CF_API_TOKEN=<token Radar thật>
WAREHOUSE_ADMIN_PASSWORD=<hex 1>
MART_ADMIN_PASSWORD=<hex 2>
INGESTION_DB_PASSWORD=<hex 3>
LOGIC_DB_PASSWORD=<hex 4>
API_DB_PASSWORD=<hex 5>
JOB_TRIGGER_TOKEN=<hex 6>
NEXT_PUBLIC_API_URL=https://kpdl6.<region>.cloudapp.azure.com
NEXT_PUBLIC_DATA_MODE=api
SITE_HOST=kpdl6.<region>.cloudapp.azure.com
```

`NEXT_PUBLIC_*` được nhúng lúc build frontend; đổi giá trị thì phải build lại frontend.

## 5. Thêm Caddy và restart policy (chỉ trên VM)

Repo không có service HTTPS và các container chưa có `restart`, nên VM khởi động lại hoặc Start sau khi Stop thì container không tự lên. Tạo hai file sau trong thư mục repo trên VM. `docker-compose.override.yml` đã nằm trong `.gitignore`; đừng commit `Caddyfile` nếu chưa thống nhất với nhóm.

`Caddyfile`:

```caddyfile
{$SITE_HOST} {
	encode gzip
	handle /api/* {
		reverse_proxy api:8000
	}
	handle {
		reverse_proxy frontend:3000
	}
}
```

`docker-compose.override.yml`:

```yaml
services:
  warehouse-db:
    restart: unless-stopped
    ports: !reset []
  mart-db:
    restart: unless-stopped
    ports: !reset []
  ingestion:
    restart: unless-stopped
  analysis:
    restart: unless-stopped
  clustering:
    restart: unless-stopped
  prediction:
    restart: unless-stopped
  api:
    restart: unless-stopped
    ports: !reset []
  frontend:
    restart: unless-stopped
    ports: !reset []
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    environment:
      SITE_HOST: ${SITE_HOST}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    depends_on:
      api: {condition: service_healthy}
      frontend: {condition: service_started}
    networks: [cyber-net]

volumes:
  caddy-data:
  caddy-config:
```

Cổng `127.0.0.1:8001-8003` của analysis/clustering/prediction vẫn giữ nguyên, chỉ truy cập được từ chính VM (dùng cho SSH tunnel nếu cần mở Swagger `/docs` của từng service).

## 6. Build và chạy

Build tuần tự để giảm đỉnh RAM:

```bash
export COMPOSE_PARALLEL_LIMIT=1
docker compose build
docker compose up -d
docker compose ps
```

Lần build frontend chạy luôn `test:unit`, `lint`, `build`, mất vài phút trên B2s. Nếu bị `Killed` (hết RAM), kiểm tra swap đã bật và build lại từng service: `docker compose build frontend`.

## 7. Chờ dữ liệu, huấn luyện mô hình, chạy job

`models/` trong repo **trống** và `*.joblib` bị `.gitignore`, nên clustering/prediction sẽ báo `failed` ("Chưa có mô hình") cho tới khi bạn huấn luyện trên VM.

1. Chờ ingestion backfill 365 ngày (khoảng 5 phút nếu token hợp lệ):

   ```bash
   docker compose logs -f ingestion
   make psql-warehouse
   ```

   ```sql
   SELECT metric, count(*), min(ts), max(ts) FROM silver.metrics_hourly GROUP BY 1;
   ```

   Cần Silver có ít nhất 30 ngày (`--min-days 30`) mới huấn luyện được.

2. Huấn luyện một lần (file nằm ở `./models` trên ổ VM, **không mất** khi xóa container):

   ```bash
   docker compose --profile training run --rm trainer
   ls -la models
   ```

3. Chạy job: mở `https://<domain>/admin`, bấm **Chạy lại** lần lượt analysis, clustering, prediction. Mỗi lần trả 202 chỉ là "đã nhận", trạng thái cuối xem ngay trên trang Vận hành.

4. Mở `https://<domain>`, bật **F12 → Network**: các request `/api/...` phải trả 200 và JSON.

## 8. Chạy kịch bản demo của thầy trên VM

Giữ nguyên volume và thư mục `models/`:

```bash
docker compose down            # KHÔNG thêm -v
docker ps -a                   # không còn container
docker compose up -d
make reset-mart                # bước "xóa dữ liệu pattern trong DB"
```

Sau đó tải lại web (thấy lỗi/trống), bấm Run ở `/admin`, tải lại web (đủ biểu đồ).

## 9. Vận hành tiết kiệm

- Không dùng thì **Stop VM** ở Portal (trạng thái "Stopped (deallocated)"). Start lại thì container tự lên (nhờ `restart: unless-stopped`), đợi 1–2 phút.
- Đừng để VM tắt quá khoảng 28 ngày: ingestion không còn vùng chồng để quy đổi thang và phải nạp bù thủ công (xem `services/ingestion/README.md`).
- Cập nhật code: `git pull && docker compose build && docker compose up -d`.
- Xong dự án: xóa cả resource group `kpdl-rg` để dừng toàn bộ chi phí.

## 10. Lưu ý bảo mật

Theo yêu cầu chủ dự án, dashboard và Jobs API **không có đăng nhập**. Khi đưa lên Internet, ai biết URL đều bấm được **Chạy lại** ở `/admin`. Chỉ gửi URL cho người cần xem, và Stop VM khi không dùng. `JOB_TRIGGER_TOKEN` chỉ bảo vệ đường nội bộ API → service, đã được đặt ngẫu nhiên ở bước 4. Không thêm lại cơ chế đăng nhập khi chưa có chủ trương của nhóm.

## 11. Nếu muốn dùng Vercel cho frontend

Làm được, nhưng cần thêm công việc và không rẻ hơn đáng kể (frontend chỉ ~150 MB RAM trên VM):

1. **Sửa CORS trong code.** `services/api/main.py` đang cố định `allow_origins=["http://localhost:3000"]`, nên web trên domain Vercel bị trình duyệt chặn. Cần đọc danh sách origin từ biến môi trường rồi build lại API (nhớ theo workflow: nhánh feature, PR vào `develop`).
2. API phải có **HTTPS** (trình duyệt chặn trang HTTPS gọi API HTTP). Vẫn cần Caddy (bỏ phần `handle` frontend) và một domain trỏ vào API.
3. Vercel: Import repo, **Root Directory = `frontend`**, đặt `NEXT_PUBLIC_API_URL=https://<domain API>` và `NEXT_PUBLIC_DATA_MODE=api`, rồi Deploy. Đổi biến thì phải Redeploy.

## 12. Xử lý sự cố nhanh

| Triệu chứng | Cách xử lý |
| :--- | :--- |
| Trình duyệt báo cert lỗi / Caddy không lấy được cert | Kiểm tra DNS name label đã gán, NSG đã mở 80 và 443, `docker compose logs caddy` |
| Web mở được nhưng biểu đồ trống, API 404 | Gold trống, chưa chạy job (bước 7.3). Đây là hành vi đúng của dự án |
| Run clustering/prediction báo `failed` | Chưa có `models/*.joblib`, làm bước 7.2 |
| Trainer dừng vì Silver ít hơn 30 ngày | Chờ backfill xong, kiểm tra `CF_API_TOKEN` và log ingestion |
| Container bị kill khi build/chạy | `free -h`, `docker stats`; kiểm tra swap; cân nhắc size 8 GiB |
| Đổi mật khẩu DB không có tác dụng | Script init chỉ chạy lúc volume trống; chỉ khi chấp nhận mất dữ liệu mới `docker compose down -v` |
