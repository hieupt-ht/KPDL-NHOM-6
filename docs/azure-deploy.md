# Hướng dẫn deploy lên Azure (tạo tay trên Portal)

Kiến trúc đích khớp slide đồ án: **VM + Function + Container Apps + Azure PostgreSQL**.

```
Cloudflare Radar
      |  mỗi 5 phút
      v
 [VM] ingestion ----> [PostgreSQL #1: warehouse]  (bronze, silver)
                              ^ đọc silver
                              |
 [Function App]  --timer--> POST /run
   - analysis   5 phút   \
   - prediction 5 phút    >--> [Container Apps] analysis / prediction / clustering
   - clustering 1 ngày   /            | ghi gold
                                      v
                          [PostgreSQL #2: mart] <--- đọc --- [Container Apps] api <--- [Container Apps] frontend <--- trình duyệt
```

| Khối trong slide | Chạy ở đâu | Ghi chú |
|---|---|---|
| Data Ingestion (5 phút) | **VM** (1 container) | Chạy liên tục, có luồng backfill nền |
| Data Analysis (5 phút) | **Container Apps** + lịch từ **Function** | `SCHEDULER_ENABLED=false` |
| Prediction (5 phút) | **Container Apps** + lịch từ **Function** | cần file model `.pkl` trong image |
| Clustering (1 ngày) | **Container Apps** + lịch từ **Function** | |
| Database API | **Container Apps** (`api`) | chỉ đọc gold |
| Front End | **Container Apps** (`frontend`) | |
| Database | **Azure PostgreSQL Flexible Server ×2** | warehouse và mart tách riêng |

Hằng số dùng trong tài liệu (thay bằng giá trị của bạn):

| Tên | Ví dụ |
|---|---|
| Region | một region mà gói sinh viên cho phép (thử Southeast Asia, Korea Central, Japan East) |
| Resource group | `rg-kpdl` |
| ACR | `kpdlacr<số ngẫu nhiên>` (tên toàn cục, chỉ chữ thường và số) |
| PG warehouse / mart | `kpdl-pg-wh` / `kpdl-pg-mart` |
| Container Apps environment | `kpdl-env` |
| Function App | `kpdl-func` |

> Mật khẩu: chỉ dùng chữ và số (dài >= 16 ký tự) để khỏi phải mã hóa URL trong chuỗi kết nối.
> Không commit mật khẩu và `CF_API_TOKEN` vào git.

---

## Bước 0. Việc cần chỉnh trong repo trước khi deploy

Hai việc này là **bắt buộc**, nếu không web trên cloud sẽ lỗi:

1. **CORS của API** (`services/api/main.py`) đang gõ cứng `allow_origins=["http://localhost:3000"]`. Trên Azure, trình duyệt gọi API từ địa chỉ `https://kpdl-web....azurecontainerapps.io` nên bị chặn. Cần đọc danh sách origin từ biến môi trường, ví dụ:
   ```python
   import os
   ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
   # allow_origins=ORIGINS
   ```
   Sau đó trên Azure đặt `CORS_ORIGINS=https://<FQDN-của-frontend>`.
2. **Frontend không cần đăng nhập.** Phần bỏ Keycloak do bạn của bạn làm. Frontend hiện ở chế độ `api` vẫn bắt đăng nhập Keycloak, nên phải xong thay đổi đó trước khi build frontend để deploy. Hỏi bạn ấy tên biến build-time mới (nếu có).

Ngoài ra: thư mục `models/` hiện trống. Dịch vụ prediction cần các file `.pkl` (do `training/train_models.py` tạo). Hãy chắc chắn chúng có trong image, nếu không prediction sẽ báo failed.

---

## Bước 1. Resource group và cảnh báo chi phí

1. Portal -> **Resource groups** -> Create -> tên `rg-kpdl`, chọn region.
2. **Cost Management + Billing -> Budgets** -> Add: phạm vi subscription, ngân sách 60 USD, cảnh báo 50% / 80% qua email.

Tất cả tài nguyên bên dưới đều đặt trong `rg-kpdl` để cuối cùng xóa một lần là sạch.

## Bước 2. Hai PostgreSQL Flexible Server

Làm hai lần (warehouse rồi mart).

1. **Create a resource -> Azure Database for PostgreSQL flexible server -> Create**.
2. Basics:
   - Server name: `kpdl-pg-wh` (lần 2: `kpdl-pg-mart`).
   - PostgreSQL version: **16**. Workload type: **Development**.
   - Compute + storage: **Burstable, B1ms**, storage 32 GiB. Tắt High availability.
   - Authentication: PostgreSQL authentication. Admin username: `pgadmin` (không dùng `postgres` hay `admin`, vì bị cấm). Đặt mật khẩu.
3. Networking:
   - Connectivity method: **Public access**.
   - Tick **Allow public access from any Azure service within Azure to this server**.
   - Không cần thêm IP của bạn, vì ta sẽ chạy script khởi tạo từ VM.
4. Review + create.
5. Sau khi tạo: **Databases -> Add**: tạo database `warehouse` (server wh) và `mart` (server mart).

Host kết nối có dạng `kpdl-pg-wh.postgres.database.azure.com`. SSL bắt buộc, nên mọi chuỗi kết nối phải có `?sslmode=require`.

## Bước 3. Container Registry (ACR)

1. **Create a resource -> Container Registry** -> tên `kpdlacr...`, SKU **Basic**.
2. Sau khi tạo: **Settings -> Access keys -> Admin user = Enabled**. Ghi lại *Login server*, *Username*, *Password*.

## Bước 4. VM (ingestion) và khởi tạo database

### 4.1 Tạo VM

- Create a resource -> **Virtual machine**. Image **Ubuntu Server 22.04 LTS**, size **Standard_B2s** (4 GB; dùng 4 GB để build frontend không hết RAM; có thể hạ xuống B1ms sau).
- Xác thực bằng SSH key, username `azureuser`. Disk Standard SSD **64 GB**.
- Inbound ports: chỉ SSH (22). VM **không cần** mở port nào khác, vì ingestion chỉ gọi ra ngoài.

### 4.2 Cài công cụ

```bash
ssh -i key.pem azureuser@<ip-vm>
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # thoát rồi SSH lại
sudo apt-get install -y git postgresql-client
git clone https://github.com/hieupt-ht/KPDL-NHOM-6.git && cd KPDL-NHOM-6
git checkout develop
```

### 4.3 Khởi tạo hai database

Các script trong `db/*/init/` chỉ tự chạy trên volume Docker rỗng, nên với Azure phải chạy tay. Script `02-users.sh` dùng `psql` nên đọc các biến `PGHOST`, `PGPASSWORD`, `PGSSLMODE`, không cần sửa.

**Warehouse:**
```bash
export PGHOST=kpdl-pg-wh.postgres.database.azure.com PGSSLMODE=require
export PGPASSWORD='<mật khẩu pgadmin của kpdl-pg-wh>'
export POSTGRES_USER=pgadmin POSTGRES_DB=warehouse
export INGESTION_DB_PASSWORD='<đặt mật khẩu 1>' LOGIC_DB_PASSWORD='<đặt mật khẩu 2>'
psql -v ON_ERROR_STOP=1 -U pgadmin -d warehouse -f db/warehouse/init/01-schema.sql
sh db/warehouse/init/02-users.sh
```

**Mart:** (dùng **cùng** `LOGIC_DB_PASSWORD` như trên)
```bash
export PGHOST=kpdl-pg-mart.postgres.database.azure.com PGSSLMODE=require
export PGPASSWORD='<mật khẩu pgadmin của kpdl-pg-mart>'
export POSTGRES_USER=pgadmin POSTGRES_DB=mart
export LOGIC_DB_PASSWORD='<mật khẩu 2 ở trên>' API_DB_PASSWORD='<đặt mật khẩu 3>'
psql -v ON_ERROR_STOP=1 -U pgadmin -d mart -f db/mart/init/01-schema.sql
sh db/mart/init/02-users.sh
```

Kiểm tra: `psql -U pgadmin -d mart -c '\dt gold.*'` phải thấy các bảng gold.

Chuỗi kết nối sẽ dùng ở các bước sau:

```
WAREHOUSE_DSN (ingestion) = postgresql://ingestion_user:<mk1>@kpdl-pg-wh.postgres.database.azure.com:5432/warehouse?sslmode=require
WAREHOUSE_DSN (logic)     = postgresql://logic_user:<mk2>@kpdl-pg-wh.postgres.database.azure.com:5432/warehouse?sslmode=require
MART_DSN (logic)          = postgresql://logic_user:<mk2>@kpdl-pg-mart.postgres.database.azure.com:5432/mart?sslmode=require
MART_DSN (api)            = postgresql://api_user:<mk3>@kpdl-pg-mart.postgres.database.azure.com:5432/mart?sslmode=require
```

### 4.4 Build và chạy ingestion trên VM

Thêm swap trước (build Node cần nhiều RAM):
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

Build, đẩy lên ACR và chạy:
```bash
cd ~/KPDL-NHOM-6
ACR=kpdlacr<...>.azurecr.io
docker login $ACR -u <acr-username> -p '<acr-password>'
docker build -t $ACR/ingestion:v1 -f services/ingestion/Dockerfile .
docker push $ACR/ingestion:v1

cat > ~/ingestion.env <<'EOF'
WAREHOUSE_DSN=postgresql://ingestion_user:<mk1>@kpdl-pg-wh.postgres.database.azure.com:5432/warehouse?sslmode=require
CF_API_TOKEN=<token cloudflare>
INGESTION_INTERVAL_SECONDS=300
AUTH_ENABLED=false
SCHEDULER_ENABLED=true
TZ_LOCAL=Asia/Ho_Chi_Minh
EOF
chmod 600 ~/ingestion.env

docker run -d --name ingestion --restart unless-stopped --env-file ~/ingestion.env $ACR/ingestion:v1
docker logs -f ingestion
```

Kiểm tra sau vài phút:
```bash
PGPASSWORD='<mk pgadmin wh>' PGSSLMODE=require psql -h kpdl-pg-wh.postgres.database.azure.com -U pgadmin -d warehouse \
  -c "select count(*), min(ts), max(ts) from silver.metrics_hourly;" \
  -c "select status, count(*) from silver.ingestion_runs group by 1;"
```
Backfill 365 ngày mất khoảng 5 phút. Nếu `count` tăng dần là ổn. **Làm bước này đầu tiên và để chạy sớm** để có đủ dữ liệu cho báo cáo.

## Bước 5. Build các image còn lại (trên VM)

Với frontend, `NEXT_PUBLIC_API_URL` được nhúng lúc build, nên cần biết trước địa chỉ API. FQDN của Container Apps có dạng `<tên-app>.<default-domain-của-environment>`, vậy ta **tạo environment (Bước 6.1) trước**, đọc *Default domain*, rồi mới build frontend. Backend image thì build ngay được:

```bash
for s in api analysis clustering prediction; do
  docker build -t $ACR/$s:v1 -f services/$s/Dockerfile . && docker push $ACR/$s:v1
done
```

Frontend (sau khi biết domain, ví dụ `kpdl-api.<domain>`):
```bash
docker build -t $ACR/frontend:v1 -f frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_URL=https://kpdl-api.<default-domain> \
  --build-arg NEXT_PUBLIC_DATA_MODE=api \
  frontend
docker push $ACR/frontend:v1
```
(Nếu bạn của bạn thêm `ARG` mới cho chế độ không đăng nhập, truyền thêm bằng `--build-arg`.)

## Bước 6. Container Apps

### 6.1 Environment

**Create a resource -> Container Apps Environment** -> tên `kpdl-env`, loại **Consumption only**, cùng region. Tạo xong, vào Overview ghi lại **Default domain** (dạng `xxx.<region>.azurecontainerapps.io`).

### 6.2 Tạo từng app

Với **mỗi** app dưới đây: **Create a resource -> Container App**, rồi:
- Tab Basics: tên app, Environment `kpdl-env`.
- Tab Container: bỏ tick *Use quickstart image*; Image source **Azure Container Registry**, chọn registry, image, tag `v1`. Điền CPU/Memory và **Environment variables** theo bảng.
- Tab Ingress: **Enabled**, *Accepting traffic from anywhere*, *Target port* theo bảng.
- Scale (sau khi tạo: Application -> Scale and replicas -> Edit): **Min replicas = 1**, Max = 1.

| App | Image | Port | CPU / RAM |
|---|---|---|---|
| `kpdl-analysis` | analysis | 8001 | 0.5 / 1 Gi |
| `kpdl-clustering` | clustering | 8002 | 0.5 / 1 Gi |
| `kpdl-prediction` | prediction | 8003 | 0.5 / 1 Gi |
| `kpdl-api` | api | 8000 | 0.25 / 0.5 Gi |
| `kpdl-web` | frontend | 3000 | 0.5 / 1 Gi |

Tên app cố định như trên (để FQDN dự đoán được). Hãy tạo theo thứ tự: analysis, clustering, prediction, api, web.

**Biến môi trường chung cho analysis, clustering, prediction:**

| Biến | Giá trị |
|---|---|
| `WAREHOUSE_DSN` | DSN warehouse của `logic_user` |
| `MART_DSN` | DSN mart của `logic_user` |
| `SCHEDULER_ENABLED` | `false` (Function sẽ đặt lịch) |
| `AUTH_ENABLED` | `false` |
| `JOB_TRIGGER_TOKEN` | chuỗi ngẫu nhiên dài (dùng chung cho cả 3 service, API và Function) |
| `TZ_LOCAL` | `Asia/Ho_Chi_Minh` |

Biến này đặt dạng *Manual entry* (hoặc *Reference a secret* cho DSN và token). Clustering và prediction giữ nguyên các biến cron mặc định.

**`kpdl-api`:**

| Biến | Giá trị |
|---|---|
| `MART_DSN` | DSN mart của `api_user` |
| `AUTH_ENABLED` | `false` |
| `JOB_TRIGGER_TOKEN` | cùng token ở trên |
| `ANALYSIS_URL` | `https://kpdl-analysis.<default-domain>` |
| `CLUSTERING_URL` | `https://kpdl-clustering.<default-domain>` |
| `PREDICTION_URL` | `https://kpdl-prediction.<default-domain>` |
| `JOB_REQUEST_TIMEOUT_SECONDS` | `10` |
| `CORS_ORIGINS` | `https://kpdl-web.<default-domain>` (sau khi sửa code ở Bước 0) |

**`kpdl-web`:** thường chỉ cần các biến runtime mà bạn của bạn quy định sau khi bỏ Keycloak. Biến public `NEXT_PUBLIC_*` đã nhúng lúc build.

### 6.3 Kiểm tra

- `https://kpdl-api.<domain>/health` trả `{"status":"ok"}`; `/ready` kiểm tra kết nối mart.
- `https://kpdl-analysis.<domain>/docs` mở Swagger. Thử `POST /run` với header `X-Job-Token`: trả 202 là đã nhận job.
- Xem kết quả: `https://kpdl-api.<domain>/api/status` (hoặc truy vấn bảng `gold.service_runs`).

## Bước 7. Function App (lịch chạy)

### 7.1 Tạo Function App

**Create a resource -> Function App** -> plan **Flex Consumption** (hoặc Consumption nếu region không có), Runtime **Python 3.11**, cùng region, tạo Storage account mới cho nó.

### 7.2 Code (đặt trong repo ở `azure-functions/`)

`function_app.py`:
```python
import logging
import os

import azure.functions as func
import requests

app = func.FunctionApp()


def _run(service: str) -> None:
    url = os.environ[f"{service.upper()}_URL"].rstrip("/") + "/run"
    token = os.environ.get("JOB_TRIGGER_TOKEN", "")
    response = requests.post(url, headers={"X-Job-Token": token} if token else {}, timeout=30)
    if response.status_code == 409:  # service đang bận
        logging.info("%s: job đang chạy, bỏ qua", service)
        return
    response.raise_for_status()
    logging.info("%s: %s", service, response.json())


@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False)
def analysis_every_5_min(timer: func.TimerRequest) -> None:
    _run("analysis")


@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False)
def prediction_every_5_min(timer: func.TimerRequest) -> None:
    _run("prediction")


# Hàm timer dùng giờ UTC: 00:30 giờ Việt Nam = 17:30 UTC ngày hôm trước.
@app.timer_trigger(schedule="0 30 17 * * *", arg_name="timer", run_on_startup=False)
def clustering_daily(timer: func.TimerRequest) -> None:
    _run("clustering")
```

`requirements.txt`:
```
azure-functions
requests
```

`host.json`:
```json
{
  "version": "2.0",
  "extensionBundle": {"id": "Microsoft.Azure.Functions.ExtensionBundle", "version": "[4.*, 5.0.0)"}
}
```

### 7.3 Cấu hình và deploy

1. Function App -> **Settings -> Environment variables**: thêm `ANALYSIS_URL`, `PREDICTION_URL`, `CLUSTERING_URL` (FQDN https của 3 app) và `JOB_TRIGGER_TOKEN`.
2. Deploy code: cách đơn giản là dùng **Cloud Shell** (bash) với Azure Functions Core Tools (nếu chưa có `func`, dùng tiện ích VS Code *Azure Functions*):
   ```bash
   # trong thư mục chứa function_app.py
   func azure functionapp publish kpdl-func
   ```
3. Kiểm tra: Function App -> **Functions** phải thấy 3 hàm; **Monitor** xem log từng lần chạy (log "analysis: {... 'accepted'}").

## Bước 8. Nghiệm thu (đối chiếu kịch bản demo trong slide)

1. Mở `https://kpdl-web.<domain>`, bật F12 -> Network: thấy các request tới `kpdl-api...` và biểu đồ hiển thị.
2. Xóa dữ liệu pattern trong DB bằng tay (từ VM):
   ```bash
   PGPASSWORD='<mk pgadmin mart>' PGSSLMODE=require psql -h kpdl-pg-mart.postgres.database.azure.com -U pgadmin -d mart -c \
   "TRUNCATE gold.timeseries_resampled, gold.histogram, gold.trend, gold.seasonal, gold.correlation, gold.data_freshness, gold.cluster_results, gold.forecast_continuous, gold.forecast_discrete;"
   ```
3. Tải lại web: thấy lỗi (API trả 404 vì gold rỗng là chủ ý).
4. Mở Swagger của các service logic, bấm `POST /run` (hoặc chờ Function chạy), mở lại DB: dữ liệu quay lại.
5. Tải lại web: biểu đồ hiển thị đầy đủ.

## Bước 9. Kiểm soát chi phí

- Hạng mục chính: VM (khoảng 30 USD/tháng nếu bật 24/7), 2 PostgreSQL B1ms (khoảng 13 USD mỗi cái cộng lưu trữ), ACR Basic (khoảng 5 USD), Container Apps (5 app, min replica 1; có hạn mức miễn phí hằng tháng). Giá thay đổi theo thời điểm và gói sinh viên, hãy kiểm tra bằng Azure Pricing Calculator.
- Khi chưa cần demo: **Stop** hai PostgreSQL (tối đa 7 ngày, sau đó Azure tự bật lại), *Stop (deallocate)* VM, và hạ min replicas của Container Apps xuống 0. Dừng VM thì ingestion dừng; nếu dừng quá 36 giờ thì khi bật lại nó tự bù phần thiếu (tối đa 28 ngày).
- Xong đồ án: xóa cả Resource group `rg-kpdl`.

## Lịch gợi ý (hạn báo cáo 27/11)

| Ngày | Việc |
|---|---|
| 23/11 | Bước 1 đến 4: DB, ACR, VM, ingestion đang chạy và backfill |
| 24/11 | Bước 5 đến 6: build image, Container Apps; sửa CORS (Bước 0) |
| 25/11 | Bước 7: Function; nối frontend sau khi bỏ Keycloak xong |
| 26/11 | Bước 8: nghiệm thu, chụp màn hình, vẽ sơ đồ network cho báo cáo |
| 27/11 | Báo cáo |

## Lưu ý cho báo cáo

Slide yêu cầu báo cáo có *sơ đồ network* và *thông tin cấu hình* (bao lâu cập nhật một lần, thời gian training, khoảng dữ liệu cần để dự đoán...). Sơ đồ ở đầu tài liệu này dùng làm gốc. Các chu kỳ: ingestion 5 phút, analysis 5 phút, prediction 5 phút, clustering 1 ngày (khớp slide).
