# Deploy thủ công lên Azure: VM + Functions + Container Apps + PostgreSQL

Slide của thầy (mục điểm cộng) gợi ý bộ Azure: **VM + Function + Container Apps + Azure PostgreSQL**. Tài liệu này chia hệ thống hiện có thành đúng bốn dịch vụ đó và hướng dẫn dựng bằng tay. Mọi lệnh viết cho **bash** (Linux, macOS, WSL hoặc Git Bash) và dùng Azure CLI.

> **Trạng thái kiểm chứng.** Đã chạy thử trên máy phát triển: script `deploy/azure/init-managed-db.sh` (hai database trên một PostgreSQL 16, chạy hai lần), phân quyền role, `deploy/azure/vm-compose.yml`, `deploy/azure/Dockerfile.models`, test của Function và test CORS của API. **Chưa chạy trên Azure thật**: các lệnh `az` dưới đây viết theo tài liệu CLI và có thể lệch theo phiên bản CLI hoặc chính sách subscription sinh viên. Gặp lỗi thì xem mục 12.

## 1. Kiến trúc

```text
Cloudflare Radar
      │ 5 phút/lần
      ▼
VM (Docker): ingestion ───────────────► PostgreSQL Flexible Server
                                          ├─ database warehouse (bronze, silver)
Functions (timer) ── POST /run ─┐         └─ database mart (gold)
  • analysis   5 phút             ▼                ▲        ▲
  • prediction 5 phút   Container Apps:           │ ghi    │ chỉ đọc
  • clustering 1 ngày     ca-analysis ────────────┘        │
                          ca-prediction  (kèm mô hình)     │
                          ca-clustering  (kèm mô hình)     │
                                                           │
Trình duyệt ──► Container Apps: ca-web ──► ca-api ─────────┘
```

| Yêu cầu của thầy | Thành phần Azure | Chạy gì |
| :--- | :--- | :--- |
| VM | Virtual Machine Ubuntu | `ingestion` (chạy liên tục vì có luồng backfill nền) và `trainer` (huấn luyện một lần) |
| Function | Azure Functions, timer trigger | Hẹn giờ `POST /run`: analysis và prediction 5 phút, clustering mỗi ngày 00:30 giờ VN |
| Container Apps | Container Apps (Consumption) | `ca-analysis`, `ca-prediction`, `ca-clustering`, `ca-api`, `ca-web` |
| Azure PostgreSQL | Flexible Server (Burstable) | **Một server, hai database** `warehouse` và `mart`, vẫn tách ba user theo ranh giới ghi dữ liệu |

Điểm cần biết:

- Các service backend chạy với `SCHEDULER_ENABLED=false`; Functions thay APScheduler. Logic, khóa chạy và nhật ký `gold.service_runs` vẫn do `common.runner` quản lý, nên bấm **Chạy lại** ở `/admin` vẫn hoạt động như cũ.
- Ingestion giữ `SCHEDULER_ENABLED=true` trên VM vì luồng backfill 365 ngày chỉ khởi động ở chế độ này.
- Web và API ở hai domain khác nhau nên API đọc danh sách origin từ biến `CORS_ORIGINS` (thêm vào code trong cùng đợt thay đổi này).
- Mô hình (`*.joblib`) không nằm trong git. Huấn luyện một lần trên VM rồi **đóng gói vào image** clustering/prediction (`deploy/azure/Dockerfile.models`), vì Container Apps không mount `./models` như Compose.

## 2. Chi phí (ước tính, cần tự kiểm tra bằng Pricing Calculator)

Chỉ tính khi chạy liên tục 24/7. Giá USD của Container Apps trên trang chính thức không lấy được tự động, nên phần này dùng đơn giá mình nhớ (idle ~0,000003 USD/vCPU-giây và /GiB-giây), chưa xác minh.

| Thành phần | Cấu hình đề xuất | Ước tính/tháng |
| :--- | :--- | :--- |
| Container Apps | `ca-analysis`, `ca-prediction`: 0,5 vCPU / 1 GiB, luôn bật 1 bản sao (~12 USD mỗi cái). `ca-clustering`, `ca-api`, `ca-web`: scale về 0 khi rảnh (~0). Có [miễn phí hằng tháng](https://learn.microsoft.com/azure/container-apps/billing) 180.000 vCPU-giây, 360.000 GiB-giây, 2 triệu request | ~25 (bật luôn cả 3 app còn lại: ~40) |
| PostgreSQL Flexible B1ms, 32 GB | Azure for Students có [ưu đãi 750 giờ B1ms + 32 GB trong 12 tháng](https://azure.microsoft.com/free/students) | 0 nếu áp dụng được, khoảng 15–20 nếu không |
| VM | `Standard_B1s` (hoặc size 1 GiB còn khả dụng), ổ 30 GB Standard SSD, IP tĩnh | ~0–8 (VM) + ~6 (đĩa, IP) |
| Container Registry Basic | | ~5 |
| Functions (Consumption) + Storage | timer 5 phút ~26.000 lượt/tháng, nằm trong [gói miễn phí 1 triệu lượt](https://azure.microsoft.com/en-us/pricing/details/functions/) | ~1 |

Cộng lại khoảng **35–65 USD/tháng nếu bật liên tục**, tức ngân sách 96 USD chỉ đủ khoảng 1,5–2,5 tháng. Vì vậy dựng, kiểm thử, rồi **thu nhỏ hoặc tắt** khi không dùng (mục 10) và **xóa cả resource group** sau buổi chấm. Đặt budget cảnh báo ở Cost Management trước khi làm gì khác.

## 3. Chuẩn bị

- Máy có `az` (đã `az login`), `docker`, `ssh`/`scp`, `psql` (hoặc dùng Azure Cloud Shell cho các lệnh không cần Docker), `python3`, `openssl`.
- `CF_API_TOKEN` của Cloudflare Radar (token chỉ đọc).
- Chọn **một region** mà subscription cho phép và có đủ PostgreSQL, Container Apps, Functions và VM. Sinh viên hay gặp lỗi chính sách region hoặc [size VM bị chặn](https://learn.microsoft.com/en-us/answers/questions/5640602/azure-for-students-cannot-create-vm-due-to-region). Thử `southeastasia`, không được thì đổi region và làm lại từ đầu mục này.

Lưu khối biến sau vào `~/kpdl-azure.env` (**ngoài repo**, không commit) rồi `source` ở mỗi phiên làm việc mới:

```bash
export LOC=southeastasia
export SUF=$(openssl rand -hex 3)            # hậu tố để tên toàn cầu không trùng
export RG=kpdl-rg
export PG=kpdl-pg-$SUF
export ACR=kpdlacr$SUF                       # chỉ chữ thường và số
export CAE=kpdl-env
export STG=kpdlstg$SUF
export FUNC=kpdl-func-$SUF
export VM=kpdl-vm

export PGADMIN=pgadmin
export PGADMIN_PW=$(openssl rand -hex 16)
export INGESTION_DB_PASSWORD=$(openssl rand -hex 16)
export LOGIC_DB_PASSWORD=$(openssl rand -hex 16)
export API_DB_PASSWORD=$(openssl rand -hex 16)
export JOB_TRIGGER_TOKEN=$(openssl rand -hex 24)
export CF_API_TOKEN='<token Radar thật>'
```

Mật khẩu dùng hex để không có ký tự đặc biệt (chúng nằm trong chuỗi kết nối dạng URL). Khi `source` lại phải dùng đúng file đã lưu, đừng sinh mật khẩu mới.

Đăng ký provider (một lần):

```bash
for p in Microsoft.App Microsoft.OperationalInsights Microsoft.DBforPostgreSQL \
         Microsoft.ContainerRegistry Microsoft.Web Microsoft.Storage Microsoft.Compute; do
  az provider register -n $p --wait
done
az extension add -n containerapp --upgrade
az group create -n $RG -l $LOC
```

## 4. PostgreSQL

```bash
az postgres flexible-server create -g $RG -n $PG -l $LOC \
  --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 \
  --admin-user $PGADMIN --admin-password "$PGADMIN_PW" \
  --public-access 0.0.0.0 --yes
```

Nếu tạo bằng Portal: ở mục **Compute + storage** chọn **Storage type = Premium SSD** (không phải **Premium SSD v2**). Premium SSD v2 làm mờ tầng **Burstable** ("Burstable compute tier is not supported for server with Premium SSD v2"), khi đó chỉ còn General Purpose từ 2 vCore, đắt hơn nhiều. Lệnh `az` ở trên dùng Premium SSD mặc định nên không gặp lỗi này.

`--public-access 0.0.0.0` bật quy tắc "cho phép dịch vụ Azure" để Container Apps, Functions và VM kết nối được mà không cần VNet (rẻ hơn). Đổi lại, server có endpoint công khai: dựa vào mật khẩu mạnh và TLS (`sslmode=require`). Thêm IP máy bạn để chạy `psql`:

```bash
MYIP=$(curl -s https://api.ipify.org)
az postgres flexible-server firewall-rule create -g $RG -n $PG --rule-name my-pc \
  --start-ip-address $MYIP --end-ip-address $MYIP
```

Tạo database, schema, role và quyền (từ thư mục gốc repo; script chạy lại nhiều lần vẫn an toàn):

```bash
PGHOST=$PG.postgres.database.azure.com PGUSER=$PGADMIN PGPASSWORD="$PGADMIN_PW" \
  bash deploy/azure/init-managed-db.sh
```

Script tạo `warehouse` và `mart`, rồi dùng lại đúng `db/*/init/02-users.sh` của Compose nên ranh giới quyền giữ nguyên: `ingestion_user` ghi Bronze/Silver, `logic_user` đọc Silver và ghi Gold, `api_user` chỉ đọc Gold.

Chuỗi kết nối cho các bước sau:

```bash
H=$PG.postgres.database.azure.com
export INGESTION_WAREHOUSE_DSN="postgresql://ingestion_user:$INGESTION_DB_PASSWORD@$H:5432/warehouse?sslmode=require"
export LOGIC_WAREHOUSE_DSN="postgresql://logic_user:$LOGIC_DB_PASSWORD@$H:5432/warehouse?sslmode=require"
export LOGIC_MART_DSN="postgresql://logic_user:$LOGIC_DB_PASSWORD@$H:5432/mart?sslmode=require"
export API_MART_DSN="postgresql://api_user:$API_DB_PASSWORD@$H:5432/mart?sslmode=require"
```

## 5. Registry, môi trường Container Apps, build image

Container Registry. `az acr build` thường **không dùng được** với tài khoản sinh viên ([lỗi `TasksOperationsNotAllowed`](https://learn.microsoft.com/en-us/answers/questions/1661967/does-the-azure-for-students-subscription-allow-one)), nên build ở máy bạn rồi push:

```bash
az acr create -g $RG -n $ACR -l $LOC --sku Basic --admin-enabled true
export ACR_LOGIN=$(az acr show -n $ACR --query loginServer -o tsv)
export ACR_PW=$(az acr credential show -n $ACR --query "passwords[0].value" -o tsv)
echo "$ACR_PW" | docker login $ACR_LOGIN -u $ACR --password-stdin
```

Tạo môi trường Container Apps trước để biết tên miền, vì frontend nhúng `NEXT_PUBLIC_API_URL` lúc build:

```bash
az containerapp env create -g $RG -n $CAE -l $LOC --logs-destination none
export DOMAIN=$(az containerapp env show -g $RG -n $CAE --query properties.defaultDomain -o tsv)
export API_URL=https://ca-api.$DOMAIN
export WEB_URL=https://ca-web.$DOMAIN
echo "$API_URL  $WEB_URL"
```

`--logs-destination none` tránh tạo Log Analytics (tiết kiệm); xem log trực tiếp bằng `az containerapp logs show -g $RG -n <app> --tail 50`. Cần log lịch sử thì bỏ cờ này.

Build và push 7 image (chạy từ thư mục gốc repo; `--platform linux/amd64` để image chạy được cả khi bạn build trên máy Arm):

```bash
build() { # build <tên> <dockerfile> [tham số khác của docker build]
  local name=$1 file=$2; shift 2
  docker build --platform linux/amd64 -f "$file" -t "$ACR_LOGIN/kpdl-$name:v1" "$@" \
    && docker push "$ACR_LOGIN/kpdl-$name:v1"
}
build api        services/api/Dockerfile        .
build analysis   services/analysis/Dockerfile   .
build clustering services/clustering/Dockerfile .
build prediction services/prediction/Dockerfile .
build ingestion  services/ingestion/Dockerfile  .
build trainer    training/Dockerfile            --target trainer .
build web        frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_URL=$API_URL --build-arg NEXT_PUBLIC_DATA_MODE=api frontend
```

Build `web` chạy luôn test đơn vị, lint và `next build`, mất vài phút. Đổi `API_URL` về sau thì phải build lại `web`.

## 6. VM: ingestion và huấn luyện mô hình

Tạo VM (size 1 GiB là đủ vì VM chỉ chạy ingestion và trainer; nếu `B1s` bị chặn, xem `az vm list-skus --location $LOC --size Standard_B -o table` cột `Restrictions`, và chọn size **x64**, không chọn size Arm vì image build `amd64`):

```bash
az vm create -g $RG -n $VM -l $LOC \
  --image Canonical:ubuntu-24_04-lts:server:latest --size Standard_B1s \
  --admin-username azureuser --generate-ssh-keys \
  --os-disk-size-gb 30 --storage-sku StandardSSD_LRS --public-ip-sku Standard
az network nsg rule update -g $RG --nsg-name ${VM}NSG -n default-allow-ssh \
  --source-address-prefixes $MYIP          # chỉ cho IP của bạn SSH
export VMIP=$(az vm show -d -g $RG -n $VM --query publicIps -o tsv)
```

Cài Docker, swap, đăng nhập registry:

```bash
ssh azureuser@$VMIP 'curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker azureuser \
  && sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile \
  && echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab'
echo "$ACR_PW" | ssh azureuser@$VMIP "docker login $ACR_LOGIN -u $ACR --password-stdin"
```

(Lệnh `docker login` cuối chạy sau khi nhóm `docker` đã có hiệu lực; nếu báo permission denied thì thoát SSH rồi chạy lại, hoặc thêm `sudo`.)

Gửi file compose và `.env` lên VM:

```bash
ssh azureuser@$VMIP 'mkdir -p ~/kpdl/models'
scp deploy/azure/vm-compose.yml azureuser@$VMIP:~/kpdl/docker-compose.yml
cat > /tmp/vm.env <<EOF
ACR_LOGIN=$ACR_LOGIN
INGESTION_WAREHOUSE_DSN=$INGESTION_WAREHOUSE_DSN
LOGIC_WAREHOUSE_DSN=$LOGIC_WAREHOUSE_DSN
CF_API_TOKEN=$CF_API_TOKEN
JOB_TRIGGER_TOKEN=$JOB_TRIGGER_TOKEN
EOF
scp /tmp/vm.env azureuser@$VMIP:~/kpdl/.env && rm /tmp/vm.env
ssh azureuser@$VMIP 'chmod 600 ~/kpdl/.env && cd ~/kpdl && docker compose up -d ingestion && docker compose logs --tail 20 ingestion'
```

Chờ backfill 365 ngày (khoảng 5 phút nếu token hợp lệ), kiểm tra bằng `psql` từ máy bạn:

```bash
psql "$LOGIC_WAREHOUSE_DSN" -c "SELECT metric, count(*), min(ts), max(ts) FROM silver.metrics_hourly GROUP BY 1"
```

Cần Silver có ít nhất 30 ngày thì mới huấn luyện được. Huấn luyện một lần trên VM rồi lấy file mô hình về:

```bash
ssh azureuser@$VMIP 'cd ~/kpdl && docker compose --profile training run --rm trainer && ls -la models'
scp azureuser@$VMIP:~/kpdl/models/'*.joblib' models/
ls models
```

## 7. Tạo các Container Apps

Hàm trợ giúp (đều dùng ingress ngoài để Functions và trình duyệt gọi được; `/run` luôn cần `X-Job-Token`):

```bash
ca() { # ca <tên app> <image> <cổng> <cpu> <memory> <min bản sao> [tham số khác của az containerapp create]
  local name=$1 image=$2 port=$3 cpu=$4 mem=$5 min=$6; shift 6
  az containerapp create -g $RG -n "$name" --environment $CAE --image "$ACR_LOGIN/$image" \
    --registry-server $ACR_LOGIN --registry-username $ACR --registry-password "$ACR_PW" \
    --target-port $port --ingress external --cpu $cpu --memory $mem \
    --min-replicas $min --max-replicas 1 "$@"
}
```

Đóng gói mô hình vào image clustering và prediction (context là thư mục `models` chỉ chứa file `.joblib`):

```bash
for s in clustering prediction; do
  docker build --platform linux/amd64 -f deploy/azure/Dockerfile.models \
    --build-arg BASE=$ACR_LOGIN/kpdl-$s:v1 -t $ACR_LOGIN/kpdl-$s:v1-models models \
    && docker push $ACR_LOGIN/kpdl-$s:v1-models
done
```

Tạo năm app. `ca-analysis` và `ca-prediction` luôn bật 1 bản sao (job chạy nền sau khi trả 202, không nên bị scale về 0 giữa chừng); `ca-clustering`, `ca-api`, `ca-web` được phép về 0:

```bash
JOB_ENV="JOB_TRIGGER_TOKEN=secretref:job-token SCHEDULER_ENABLED=false TZ_LOCAL=Asia/Ho_Chi_Minh"
LOGIC_SECRETS=(warehouse-dsn="$LOGIC_WAREHOUSE_DSN" mart-dsn="$LOGIC_MART_DSN" job-token="$JOB_TRIGGER_TOKEN")
LOGIC_ENV="WAREHOUSE_DSN=secretref:warehouse-dsn MART_DSN=secretref:mart-dsn $JOB_ENV"

ca ca-analysis   kpdl-analysis:v1          8001 0.5 1Gi 1 --secrets "${LOGIC_SECRETS[@]}" --env-vars $LOGIC_ENV
ca ca-prediction kpdl-prediction:v1-models 8003 0.5 1Gi 1 --secrets "${LOGIC_SECRETS[@]}" --env-vars $LOGIC_ENV
ca ca-clustering kpdl-clustering:v1-models 8002 0.5 1Gi 0 --secrets "${LOGIC_SECRETS[@]}" --env-vars $LOGIC_ENV

ca ca-api kpdl-api:v1 8000 0.25 0.5Gi 0 \
  --secrets mart-dsn="$API_MART_DSN" job-token="$JOB_TRIGGER_TOKEN" \
  --env-vars MART_DSN=secretref:mart-dsn JOB_TRIGGER_TOKEN=secretref:job-token \
    ANALYSIS_URL=http://ca-analysis CLUSTERING_URL=http://ca-clustering PREDICTION_URL=http://ca-prediction \
    JOB_REQUEST_TIMEOUT_SECONDS=45 CORS_ORIGINS=$WEB_URL

ca ca-web kpdl-web:v1 3000 0.25 0.5Gi 0 --env-vars HOSTNAME=0.0.0.0 PORT=3000
```

`ANALYSIS_URL=http://ca-analysis` là địa chỉ nội bộ trong cùng môi trường; `JOB_REQUEST_TIMEOUT_SECONDS=45` dư cho lần khởi động lạnh của app đã scale về 0. `CORS_ORIGINS` phải đúng bằng `$WEB_URL` (không có dấu `/` ở cuối).

## 8. Azure Functions (bộ hẹn giờ)

```bash
az storage account create -g $RG -n $STG -l $LOC --sku Standard_LRS
az functionapp create -g $RG -n $FUNC --storage-account $STG \
  --consumption-plan-location $LOC --os-type Linux \
  --runtime python --runtime-version 3.11 --functions-version 4
az functionapp config appsettings set -g $RG -n $FUNC --settings \
  ANALYSIS_URL=https://ca-analysis.$DOMAIN \
  CLUSTERING_URL=https://ca-clustering.$DOMAIN \
  PREDICTION_URL=https://ca-prediction.$DOMAIN \
  JOB_TRIGGER_TOKEN=$JOB_TRIGGER_TOKEN
```

Nếu `functionapp create` báo gói Consumption Linux không khả dụng, dùng Flex Consumption: thay `--consumption-plan-location $LOC --os-type Linux` bằng `--flexconsumption-location $LOC`.

Triển khai mã (3 hàm timer trong `deploy/azure/function/`):

```bash
(cd deploy/azure/function && python3 -m zipfile -c ../function.zip function_app.py jobs.py host.json requirements.txt)
az functionapp deployment source config-zip -g $RG -n $FUNC \
  --src deploy/azure/function.zip --build-remote true
rm deploy/azure/function.zip
```

Lịch (UTC): `analysis` và `prediction` mỗi 5 phút (`0 */5 * * * *`), `clustering` lúc 17:30 UTC tức 00:30 giờ Việt Nam (`0 30 17 * * *`). Ingestion không nằm ở đây vì đã tự chạy 5 phút trên VM.

## 9. Kiểm tra

```bash
curl -s $API_URL/health ; echo
curl -s $API_URL/ready  ; echo
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://ca-analysis.$DOMAIN/run    # phải là 401 (thiếu token)
echo $WEB_URL
```

1. Mở `$WEB_URL`, bật **F12 → Network**: các request `/api/...` đi tới `ca-api`, trả JSON (lần đầu có thể chậm vài giây vì app khởi động lạnh).
2. Gold ban đầu trống nên API trả 404 (đúng thiết kế). Vào `$WEB_URL/admin`, bấm **Chạy lại** cho analysis, prediction, clustering và chờ trạng thái cuối.
3. Portal → Function App → **Functions** → từng hàm → **Invocations**: thấy lượt chạy mỗi 5 phút, kết quả "đã nhận lệnh chạy" (hoặc "đang có job chạy, bỏ qua" khi trùng).
4. Tải lại web: đủ biểu đồ, dự báo ngày mai và nhãn rủi ro.

Demo trước thầy: phần "xóa hết container, `docker compose up`" vẫn làm trên máy local theo README mục 12; bản Azure dùng để chứng minh điểm cộng "deploy cloud" (mở URL, F12 xem API, mở Portal thấy bốn dịch vụ).

## 10. Giữ chi phí thấp

Khi chưa cần dùng (giữ nguyên dữ liệu và cấu hình):

```bash
az functionapp stop -g $RG -n $FUNC
for a in ca-analysis ca-prediction ca-clustering ca-api ca-web; do
  az containerapp update -g $RG -n $a --min-replicas 0; done
az vm deallocate -g $RG -n $VM
az postgres flexible-server stop -g $RG -n $PG          # tự khởi động lại sau tối đa 7 ngày
```

Trước buổi chấm (bật lại theo thứ tự PostgreSQL → VM → app → Function):

```bash
az postgres flexible-server start -g $RG -n $PG
az vm start -g $RG -n $VM
for a in ca-analysis ca-prediction ca-api ca-web; do
  az containerapp update -g $RG -n $a --min-replicas 1; done
az functionapp start -g $RG -n $FUNC
```

Ingestion trên VM tự lên lại (`restart: unless-stopped`) và lấp khoảng trống dữ liệu; đừng để nó ngừng quá khoảng 28 ngày, vì khi đó phải nạp bù thủ công (xem `services/ingestion/README.md`). Xong dự án, xóa tất cả:

```bash
az group delete -g $RG --yes --no-wait
```

## 11. Cập nhật phiên bản

Build lại image với tag mới rồi cập nhật app, ví dụ API:

```bash
docker build --platform linux/amd64 -f services/api/Dockerfile -t $ACR_LOGIN/kpdl-api:v2 . && docker push $ACR_LOGIN/kpdl-api:v2
az containerapp update -g $RG -n ca-api --image $ACR_LOGIN/kpdl-api:v2
```

Huấn luyện lại mô hình: lặp lại bước huấn luyện ở mục 6, build lại hai image `:v2-models` và `update --image` cho `ca-prediction`, `ca-clustering`.

## 12. Xử lý sự cố

| Triệu chứng | Cách xử lý |
| :--- | :--- |
| `RequestDisallowedByPolicy`, "location not available", size bị chặn | Subscription sinh viên giới hạn region/size. Đổi `LOC` (và làm lại từ mục 3), hoặc chọn size khác; PostgreSQL Flexible hay bị chặn theo region |
| Web báo lỗi mạng/CORS khi gọi API | `CORS_ORIGINS` của `ca-api` phải đúng `$WEB_URL`: `az containerapp update -g $RG -n ca-api --set-env-vars CORS_ORIGINS=$WEB_URL` |
| Web gọi sai địa chỉ API | `NEXT_PUBLIC_API_URL` nhúng lúc build; build lại `web` với `API_URL` đúng, rồi `update --image` |
| API trả 503 | Không kết nối được DB: kiểm tra DSN có `sslmode=require`, quy tắc firewall "Azure services", log `az containerapp logs show -g $RG -n ca-api --tail 50` |
| Job `failed`: "Chưa có mô hình" | App chưa dùng image `:v1-models`: `az containerapp update -g $RG -n ca-prediction --image $ACR_LOGIN/kpdl-prediction:v1-models` |
| Function báo HTTP 401 | `JOB_TRIGGER_TOKEN` của Function khác của app; đặt lại đồng bộ ở cả hai nơi |
| Function báo timeout | App đang khởi động lạnh quá lâu; để `--min-replicas 1` cho app đó. Không tự thử lại, vì yêu cầu có thể đã được nhận |
| App bị `OOMKilled` | Tăng tài nguyên: `az containerapp update -g $RG -n <app> --cpu 1 --memory 2Gi` |
| Ingestion không có dữ liệu | `ssh azureuser@$VMIP 'cd ~/kpdl && docker compose logs --tail 50 ingestion'`, kiểm tra `CF_API_TOKEN` |
| Trainer dừng vì Silver ít hơn 30 ngày | Chờ backfill xong rồi chạy lại |
| `docker push` bị từ chối | Chạy lại `docker login` với `ACR_PW`; mật khẩu admin của ACR đổi được ở Portal |

## 13. Lưu ý bảo mật

- Dashboard và Jobs API **không có đăng nhập** theo yêu cầu chủ dự án; ai biết URL đều bấm được **Chạy lại**. Chỉ chia sẻ URL cho người cần xem và thu nhỏ/tắt tài nguyên khi không dùng. Không khôi phục cơ chế đăng nhập nếu nhóm chưa quyết định.
- `JOB_TRIGGER_TOKEN` chỉ bảo vệ đường `/run`, đặt ngẫu nhiên và giống nhau ở API, ba service, Function và ingestion trên VM. Không đưa token, DSN hay mật khẩu vào git.
- PostgreSQL có endpoint công khai (quy tắc "Azure services"), nên mật khẩu phải mạnh và kết nối luôn dùng TLS. Muốn chặt hơn cần VNet/Private Endpoint (tốn thêm tiền).
- Mật khẩu admin ACR và mật khẩu DB nằm trong `~/kpdl-azure.env`: giữ file này ngoài repo.

Phương án một VM chạy toàn bộ Docker Compose (rẻ hơn, không dùng Functions/Container Apps/PostgreSQL managed) vẫn còn trong lịch sử git của nhánh này, commit `ae04736`, phòng khi subscription chặn một trong các dịch vụ trên.
