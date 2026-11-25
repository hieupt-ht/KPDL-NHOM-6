# Deploy lên Azure bằng Portal: VM + Functions + Container Apps + PostgreSQL

Theo mục điểm cộng trong slide của thầy: **VM + Function + Container Apps + Azure PostgreSQL**. Cách làm:

- **Portal** (web Azure): bấm tạo từng dịch vụ.
- **VM**: mọi lệnh (khởi tạo database, build image, huấn luyện mô hình) chạy trong **một cửa sổ SSH vào VM**. Không cần cài Docker hay Azure CLI trên máy bạn.
- **Cloud Shell** (nút `>_` trên Portal): chỉ dùng một lần để đưa mã Function lên.
- **Vercel** (miễn phí): chạy giao diện web (frontend), nối thẳng với GitHub, không cần build image.

> **Trạng thái kiểm chứng.** Đã chạy thử trên máy phát triển: script `deploy/azure/init-managed-db.sh` (hai database trên một PostgreSQL 16, chạy hai lần), phân quyền role, `deploy/azure/vm-compose.yml`, `deploy/azure/Dockerfile.models`, test của Function và test CORS của API. **Chưa chạy trên Azure thật**: tên nút trên Portal có thể lệch chút, chính sách tài khoản sinh viên có thể chặn một số region hoặc size VM. Gặp lỗi xem mục 14.
> Bản hướng dẫn dùng lệnh `az` trước đây vẫn xem được ở commit `97b8429` (lịch sử git).

## 1. Kiến trúc

```text
Cloudflare Radar
      │ 5 phút/lần
      ▼
VM (Docker): ingestion ───────────────► PostgreSQL Flexible Server (1 server)
                                          ├─ database warehouse (bronze, silver)
Functions (timer) ── POST /run ─┐         └─ database mart (gold)
  • analysis   5 phút             ▼                ▲        ▲
  • prediction 5 phút   Container Apps:           │ ghi    │ chỉ đọc
  • clustering 1 ngày     ca-analysis ────────────┘        │
                          ca-prediction  (kèm mô hình)     │
                          ca-clustering  (kèm mô hình)     │
                                                           │
Trình duyệt ──► Vercel (frontend) ──► ca-api ──────────────┘
```

| Yêu cầu của thầy | Thành phần Azure | Chạy gì |
| :--- | :--- | :--- |
| VM | Virtual Machine Ubuntu | `ingestion` (chạy liên tục, có luồng backfill nền) và `trainer` (huấn luyện một lần); đồng thời là nơi build image |
| Function | Azure Functions, timer | Hẹn giờ `POST /run`: analysis và prediction mỗi 5 phút, clustering mỗi ngày 00:30 giờ VN |
| Container Apps | Container Apps (Consumption) | `ca-analysis`, `ca-prediction`, `ca-clustering`, `ca-api` |
| Front End | Vercel (Hobby, miễn phí) | Next.js, gọi `ca-api` từ trình duyệt. Muốn đặt frontend trong Azure thì xem phụ lục (mục 18) |
| Azure PostgreSQL | Flexible Server (Burstable) | **Một server, hai database** `warehouse` và `mart`, vẫn tách ba user theo ranh giới ghi dữ liệu |

Điểm cần biết:

- Các service backend chạy `SCHEDULER_ENABLED=false`; Function thay APScheduler. Bấm **Chạy lại** ở `/admin` vẫn hoạt động như cũ.
- Ingestion giữ `SCHEDULER_ENABLED=true` trên VM vì luồng backfill 365 ngày chỉ chạy ở chế độ này.
- Web (Vercel) và API (Container Apps) khác domain nên API đọc danh sách origin từ biến `CORS_ORIGINS`, đặt bằng địa chỉ Vercel.
- Mô hình (`*.joblib`) không nằm trong git: huấn luyện một lần trên VM rồi **đóng gói vào image** `ca-prediction` và `ca-clustering`.

## 2. Chi phí (ước tính, cần tự kiểm tra bằng Pricing Calculator)

| Thành phần | Cấu hình | Ước tính/tháng nếu bật 24/7 |
| :--- | :--- | :--- |
| VM `Standard_B2s` (4 GiB) + ổ 64 GiB | 4 GiB cho thoải mái khi build image Python và huấn luyện | ~35 (hạ xuống size nhỏ sau khi build xong thì ít hơn) |
| PostgreSQL B1ms, 32 GiB | một server | 0 nếu dùng được [ưu đãi 12 tháng của gói sinh viên](https://azure.microsoft.com/free/students), khoảng 15–20 nếu không |
| Container Apps | `ca-analysis`, `ca-prediction` luôn bật 1 bản sao (~12 mỗi cái); `ca-clustering` và `ca-api` về 0 khi rảnh | ~25 (đơn giá lấy theo trí nhớ, chưa xác minh) |
| Container Registry Basic | | ~5 |
| Functions + Storage | timer 5 phút, trong [gói miễn phí](https://azure.microsoft.com/en-us/pricing/details/functions/) | ~1 |

Tổng khoảng **60–90 USD/tháng nếu bật liên tục**, tức ~2–3 USD/ngày. Ngân sách 96 USD đủ cho vài ngày demo nhưng **không đủ chạy cả tháng**. Làm xong và quay video/chụp màn hình thì tắt (mục 12), và **xóa cả resource group** sau buổi chấm.

## 3. Chuẩn bị (10 phút)

1. Mở Notepad và ghi các giá trị dưới đây. Bạn sẽ dùng lại nhiều lần.

| Tên | Giá trị |
| :--- | :--- |
| `SUF` | 4 ký tự ngẫu nhiên viết thường/số, ví dụ `x7k2` (để tên không trùng người khác) |
| Region | `Southeast Asia` (nếu bị chặn thì dùng region khác cho **mọi** dịch vụ) |
| Resource group | `kpdl-rg` |
| PostgreSQL | server `kpdl-pg-SUF`, admin `pgadmin` |
| Mật khẩu admin | tự đặt, từ 16 ký tự, có chữ hoa, thường, số và `-`. Không dùng `@ : / ? # %` |
| 3 mật khẩu ứng dụng | `INGESTION_DB_PASSWORD`, `LOGIC_DB_PASSWORD`, `API_DB_PASSWORD`: **chỉ chữ và số**, từ 20 ký tự, mỗi cái khác nhau (chúng nằm trong chuỗi kết nối dạng URL) |
| `JOB_TRIGGER_TOKEN` | chuỗi chữ và số dài từ 32 ký tự (token chung giữa API, Function và các service) |
| `CF_API_TOKEN` | token Cloudflare Radar (quyền Account → Radar → Read) |

Các giá trị này độc lập với `.env` chạy local. Quy tắc của Azure: tên admin không được là `admin`, `administrator`, `root`, `guest`, `public`, `azure_superuser` hoặc bắt đầu bằng `pg_`; mật khẩu admin dài 8–128 ký tự và có ký tự từ ít nhất 3 trong 4 nhóm.

2. (Khuyên làm) Portal → **Cost Management + Billing → Budgets → Add**: phạm vi subscription, ngân sách 60 USD, cảnh báo 50% và 80% qua email.

3. Tài khoản **Vercel** (gói Hobby, miễn phí): đăng ký ở vercel.com bằng nút **Continue with GitHub**, dùng đúng tài khoản GitHub sở hữu repo.

## 4. [Portal] Resource group

**Resource groups → Create**: tên `kpdl-rg`, Region `Southeast Asia`. Mọi tài nguyên sau này đặt trong group này để cuối cùng xóa một lần là sạch.

Nếu gặp lỗi "subscription is not registered to use namespace ...": **Subscriptions → (subscription của bạn) → Resource providers**, tìm tên trong lỗi (ví dụ `Microsoft.App`) rồi **Register**.

## 5. [Portal] PostgreSQL Flexible Server (chỉ tạo MỘT server)

**Create a resource → Azure Database for PostgreSQL flexible server → Create**.

**Tab Basics**

| Ô | Giá trị |
| :--- | :--- |
| Resource group | `kpdl-rg` |
| Server name | `kpdl-pg-SUF` |
| Region | cùng region đã chọn |
| PostgreSQL version | 16 |
| Workload type | Development |
| High availability | tắt |
| Authentication method | PostgreSQL authentication only |
| Admin username / Password | `pgadmin` / mật khẩu admin trong Notepad |

Ở dòng **Compute + storage** bấm **Configure server** và đặt **theo thứ tự này**:

1. **Storage type = Premium SSD** (không phải *Premium SSD v2*; v2 làm mờ tầng Burstable).
2. **Compute tier = Burstable**, **Compute size = Standard_B1ms** (1 vCore, 2 GiB).
3. **Storage size = 32 GiB**. Giữ backup 7 ngày; không bật Geo-redundancy.
4. Bảng **Estimated costs** bên phải phải ở mức vài chục USD/tháng trở xuống, không có dòng High availability. Đúng thì **Save**.

**Tab Networking**

- Connectivity method: **Public access**.
- Tick **Allow public access from any Azure service within Azure to this server** (để VM, Container Apps và Function kết nối được).
- Không cần thêm IP của bạn: lệnh khởi tạo chạy từ VM.

**Review + create → Create.** Server có địa chỉ `kpdl-pg-SUF.postgres.database.azure.com`. Không cần tạo database ở đây, script ở bước 9 sẽ tạo `warehouse` và `mart`.

> Quy tắc "cho phép mọi dịch vụ Azure" nghĩa là server có địa chỉ công khai. Bảo vệ bằng mật khẩu mạnh và SSL (`sslmode=require` trong mọi chuỗi kết nối). Với đồ án ngắn hạn thì chấp nhận được; xong thì xóa resource group.

## 6. [Portal] Container Registry và Container Apps environment

**Container Registry**

1. **Create a resource → Container Registry**: tên `kpdlacrSUF` (chỉ chữ thường và số), Resource group `kpdl-rg`, cùng region, Pricing plan **Basic**. Create.
2. Vào registry → **Settings → Access keys → Admin user: Enabled**. Ghi lại **Login server** (`kpdlacrsuf.azurecr.io`), **Username** và **password** (cái đầu tiên).

**Container Apps environment**

Portal hiện **không có nút tạo riêng** environment (trang *Container Apps Environments* chỉ liệt kê, không có **+ Create**). Environment được tạo **cùng lúc với app đầu tiên** ở bước 11.3, nên ở đây chưa làm gì. Sau khi có app đầu tiên bạn sẽ biết **Default domain** (dạng `happy-sea-1a2b3c4d.southeastasia.azurecontainerapps.io`), gọi là `DOMAIN`; địa chỉ mỗi app là `https://<tên app>.DOMAIN`, ví dụ `https://ca-api.DOMAIN`. Vì vậy `DOMAIN` chưa có trong file `kpdl.env` lúc này.

## 7. [Portal] Máy ảo (VM)

**Create a resource → Virtual machine → Create**.

| Ô | Giá trị |
| :--- | :--- |
| Resource group | `kpdl-rg` |
| Virtual machine name | `kpdl-vm` |
| Region | cùng region |
| Image | **Ubuntu Server 24.04 LTS - x64 Gen2** |
| Size | **Standard_B2s** (4 GiB RAM). Nếu không có, chọn size x64 khác có ≥ 4 GiB (B2s_v2, B2as_v2...). **Không** chọn size Arm (tên có chữ `p`, ví dụ B2ps) |
| Authentication type | SSH public key |
| Username | `azureuser` |
| SSH public key source | **Generate new key pair**, tên `kpdl-vm_key` |
| Public inbound ports | Allow selected ports → **SSH (22)** |

- Tab **Disks**: OS disk type **Standard SSD**, OS disk size **64 GiB**.
- **Không** bật Auto-shutdown ở tab Management (ingestion phải chạy liên tục).
- Bấm **Review + create → Create**. Hộp thoại hiện ra: chọn **Download private key and create resource**. File `kpdl-vm_key.pem` được lưu vào thư mục Downloads. **Giữ file này**, mất là không vào được VM.

Xong vào VM → **Overview**, ghi lại **Public IP address**.

## 8. [VM] Kết nối, cài công cụ, tạo file cấu hình

### 8.1 SSH vào VM

Mac/Linux (Terminal):

```bash
chmod 400 ~/Downloads/kpdl-vm_key.pem
ssh -i ~/Downloads/kpdl-vm_key.pem azureuser@<IP của VM>
```

Windows (PowerShell):

```powershell
ssh -i "$HOME\Downloads\kpdl-vm_key.pem" azureuser@<IP của VM>
```

Nếu Windows báo `UNPROTECTED PRIVATE KEY FILE`, chạy hai lệnh này rồi SSH lại:

```powershell
icacls "$HOME\Downloads\kpdl-vm_key.pem" /inheritance:r
icacls "$HOME\Downloads\kpdl-vm_key.pem" /grant:r "$($env:USERNAME):(R)"
```

Lần đầu máy hỏi `Are you sure you want to continue connecting?` thì gõ `yes`. Dấu nhắc đổi thành `azureuser@kpdl-vm:~$` là bạn đã ở trong VM. **Từ bước này trở đi mọi lệnh gõ trong cửa sổ này.**

### 8.2 Cài Docker, git, psql và bộ nhớ đệm swap

Dán nguyên khối này, bấm Enter, chờ vài phút:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
sudo apt-get install -y git postgresql-client
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
```

Dòng `usermod` chỉ có hiệu lực sau khi đăng nhập lại: gõ `exit` rồi SSH lại như 8.1. Dòng `swapon` giúp VM không hết RAM khi build image và huấn luyện.

### 8.3 Lấy mã nguồn

```bash
git clone -b feat/docker-azure-deploy https://github.com/hieupt-ht/KPDL-NHOM-6.git
cd KPDL-NHOM-6
```

Nhánh `feat/docker-azure-deploy` có các script deploy và bản sửa CORS. Nếu repo là private, git sẽ hỏi tài khoản GitHub và mật khẩu; dùng Personal Access Token thay mật khẩu.

### 8.4 Tạo file cấu hình `~/kpdl.env`

Mở trình soạn thảo: `nano ~/kpdl.env`. Dán khối dưới (chuột phải để dán), **thay các chỗ `<...>` bằng giá trị trong Notepad**, giữ nguyên dấu nháy đơn. Lưu: `Ctrl+O`, `Enter`, thoát: `Ctrl+X`.

```bash
export SUF='x7k2'
export PG="kpdl-pg-$SUF"
export PGHOST="$PG.postgres.database.azure.com"
export PGUSER='pgadmin'
export PGPASSWORD='<mật khẩu admin>'
export PGSSLMODE=require
export INGESTION_DB_PASSWORD='<mật khẩu ingestion>'
export LOGIC_DB_PASSWORD='<mật khẩu logic>'
export API_DB_PASSWORD='<mật khẩu api>'
export JOB_TRIGGER_TOKEN='<token job>'
export CF_API_TOKEN='<token Cloudflare Radar>'
export ACR_NAME='<Username trên trang Access keys của registry>'
export ACR_LOGIN='<Login server trên trang Access keys, dạng xxx.azurecr.io>'
export ACR_PW='<password trên trang Access keys>'
export DOMAIN=''   # để trống, điền sau khi tạo ca-analysis ở bước 11.3

export INGESTION_WAREHOUSE_DSN="postgresql://ingestion_user:$INGESTION_DB_PASSWORD@$PGHOST:5432/warehouse?sslmode=require"
export LOGIC_WAREHOUSE_DSN="postgresql://logic_user:$LOGIC_DB_PASSWORD@$PGHOST:5432/warehouse?sslmode=require"
export LOGIC_MART_DSN="postgresql://logic_user:$LOGIC_DB_PASSWORD@$PGHOST:5432/mart?sslmode=require"
export API_MART_DSN="postgresql://api_user:$API_DB_PASSWORD@$PGHOST:5432/mart?sslmode=require"

# rút gọn lệnh docker compose cho file của VM
dc() { docker compose -f ~/KPDL-NHOM-6/deploy/azure/vm-compose.yml --project-directory ~/KPDL-NHOM-6 "$@"; }
```

Rồi khóa file và nạp vào phiên làm việc:

```bash
chmod 600 ~/kpdl.env
source ~/kpdl.env
```

**Mỗi lần SSH vào VM, việc đầu tiên là `cd ~/KPDL-NHOM-6 && source ~/kpdl.env`.** Bước nào báo "biến chưa đặt" thường là do quên lệnh này. File này chứa mật khẩu: không gửi cho ai, không commit.

## 9. [VM] Khởi tạo database

Từ thư mục `~/KPDL-NHOM-6`:

```bash
bash deploy/azure/init-managed-db.sh
```

Script tạo database `warehouse` và `mart`, các bảng, ba user ứng dụng và quyền (`ingestion_user` ghi Bronze/Silver, `logic_user` đọc Silver và ghi Gold, `api_user` chỉ đọc Gold). Chạy lại nhiều lần vẫn an toàn. Cuối cùng in `Xong: warehouse và mart trên ...`.

Kiểm tra:

```bash
psql "$LOGIC_MART_DSN" -c '\dt gold.*'
```

Phải thấy danh sách bảng gold. Nếu lỗi:

- `connection timed out`: chưa tick "Allow public access from any Azure service" ở server PostgreSQL (Portal → server → **Networking**).
- `password authentication failed`: sai `PGPASSWORD` hoặc sai mật khẩu trong file `kpdl.env`.

## 10. [VM] Chạy ingestion trước (để có dữ liệu)

Ingestion backfill dữ liệu lịch sử mất một lúc, và huấn luyện mô hình cần ít nhất 30 ngày Silver, nên **làm bước này sớm nhất** rồi để nó chạy.

```bash
docker build -f services/ingestion/Dockerfile -t $ACR_LOGIN/kpdl-ingestion:v1 .
dc up -d ingestion
dc logs --tail 30 ingestion
```

Log phải có dòng chạy chu kỳ ingestion và không báo lỗi. Nếu báo `CF_API_TOKEN chưa được cấu hình`: sửa token trong `~/kpdl.env`, `source ~/kpdl.env`, rồi `dc up -d --force-recreate ingestion`.

Kiểm tra dữ liệu (chạy lại sau vài phút, số dòng phải tăng dần):

```bash
psql "$LOGIC_WAREHOUSE_DSN" -c "SELECT metric, count(*), min(ts), max(ts) FROM silver.metrics_hourly GROUP BY 1"
```

Ingestion có `restart: unless-stopped` nên tự chạy lại khi VM khởi động lại.

## 11. [VM] Build image rồi [Portal] tạo Container Apps

### 11.1 [VM] Build và đẩy image lên registry (các image chưa cần `DOMAIN`)

Trong lúc ingestion chạy, build các image khác (giữ cửa sổ SSH mở; mỗi image vài phút):

```bash
echo "$ACR_PW" | docker login $ACR_LOGIN -u $ACR_NAME --password-stdin

for s in analysis api; do
  docker build -f services/$s/Dockerfile -t $ACR_LOGIN/kpdl-$s:v1 . && docker push $ACR_LOGIN/kpdl-$s:v1
done

for s in clustering prediction; do
  docker build -f services/$s/Dockerfile -t $ACR_LOGIN/kpdl-$s:v1 .
done
docker build -f training/Dockerfile --target trainer -t $ACR_LOGIN/kpdl-trainer:v1 .
```

- Hai image `clustering` và `prediction` chỉ build tại VM, **chưa đẩy lên registry**: ở bước 11.5 ta đóng gói mô hình vào rồi mới đẩy.
- Frontend không build ở VM mà chạy trên Vercel (bước 11.4).

In các giá trị cần dán vào Portal ở các bước sau:

```bash
echo "WAREHOUSE_DSN (logic): $LOGIC_WAREHOUSE_DSN"
echo "MART_DSN (logic):      $LOGIC_MART_DSN"
echo "MART_DSN (api):        $API_MART_DSN"
echo "JOB_TRIGGER_TOKEN:     $JOB_TRIGGER_TOKEN"
```

### 11.2 [Portal] Cách tạo một Container App (áp dụng cho mọi app)

**Create a resource**, tìm **Container App** và chọn thẻ **Container App** của *Microsoft* (loại Azure Service). Không chọn *Container App Job*, *Container App Session Pool* hay các thẻ của hãng khác. Bấm **Create**.

- **Basics**: Resource group `kpdl-rg`; Container app name theo bảng; Region cùng region; **Container Apps Environment**: app đầu tiên (11.3) bấm **Create new** (xem 11.3), các app sau chọn `kpdl-env` có sẵn.
- **Container**: bỏ tick **Use quickstart image**. Image source **Azure Container Registry**; Registry `kpdlacrSUF` (nếu hỏi cách xác thực, chọn admin credentials / Secrets); Image và Image tag theo bảng; CPU and Memory theo bảng; thêm **Environment variables** theo bảng (kiểu **Manual entry**).
- **Ingress**: **Enabled**, Ingress traffic **Accepting traffic from anywhere**, Ingress type HTTP, **Target port** theo bảng.
- **Review + create → Create.**
- Sau khi tạo: app → **Application → Scale** (Scale and replicas) → **Edit and deploy** → tab Scale: đặt **Min replicas** và **Max replicas** theo bảng → **Create**.

Tên app phải **đúng như bảng** (địa chỉ có dạng `https://<tên app>.DOMAIN`, các app gọi nhau bằng địa chỉ này).

### 11.3 [Portal] Tạo `ca-analysis` đầu tiên (tạo luôn environment) và lấy `DOMAIN`

Làm theo 11.2 với bảng sau:

| App | Image : tag | Port | CPU / RAM | Min / Max replicas |
| :--- | :--- | :--- | :--- | :--- |
| `ca-analysis` | `kpdl-analysis` : `v1` | 8001 | 0.5 / 1 Gi | 1 / 1 |

Ở tab Basics, mục *Container Apps Environment* bấm **Create new**: tên `kpdl-env`, Environment type **Consumption only** hoặc **Workload profiles** (cả hai đều là loại chuẩn; **không** chọn *Express*, đây là loại mới còn hạn chế), Zone redundancy tắt. Nếu có tab **Workload profiles**, dòng *Consumption* bị mờ là bình thường (profile có sẵn, không xóa được); **không** bấm *Add workload profile* vì profile Dedicated tính tiền theo giờ. Tab Monitoring chọn **Azure Log Analytics** để xem log khi gặp lỗi; **Create**. Nếu Portal báo `ExpressAzureMonitorLogDestNotSupported` thì xem mục 16.

**Biến môi trường `ca-analysis`** (`ca-prediction` và `ca-clustering` ở 11.6 dùng đúng bộ này):

| Tên biến | Giá trị |
| :--- | :--- |
| `WAREHOUSE_DSN` | DSN warehouse của `logic_user` (lệnh `echo` ở 11.1) |
| `MART_DSN` | DSN mart của `logic_user` |
| `JOB_TRIGGER_TOKEN` | token job |
| `SCHEDULER_ENABLED` | `false` |
| `TZ_LOCAL` | `Asia/Ho_Chi_Minh` |

Tạo xong, vào app → **Overview** xem **Application Url**, dạng `https://ca-analysis.<DOMAIN>`. Phần sau `ca-analysis.` chính là `DOMAIN`. Điền vào file cấu hình trên VM:

```bash
nano ~/kpdl.env        # sửa dòng export DOMAIN='' thành giá trị thật, lưu bằng Ctrl+O, Enter, Ctrl+X
source ~/kpdl.env
echo $DOMAIN
```

### 11.4 [Vercel] Frontend, rồi [Portal] tạo `ca-api`

Frontend chạy trên **Vercel**. Nó chỉ cần biết địa chỉ API là `https://ca-api.DOMAIN` (đã xác định được dù `ca-api` chưa tạo), nên làm Vercel **trước**, lấy địa chỉ web để đặt `CORS_ORIGINS` cho `ca-api`.

**Chuẩn bị (một lần):** nhánh mặc định của repo là `main`, mà `main` **chưa có thư mục `frontend`** (code nằm ở `develop`). Để Vercel thấy code: GitHub → repo → **Settings → Branches → Default branch** → đổi sang `develop` → Update. (Chỉ đổi nhánh mặc định, không đổi code; PR của dự án vốn nhắm vào `develop`.)

1. Vào vercel.com → **Add New… → Project** → **Import Git Repository** → chọn `hieupt-ht/KPDL-NHOM-6`. Lần đầu Vercel sẽ yêu cầu cấp quyền đọc repo (nút *Install* / *Adjust GitHub App Permissions*), cấp cho đúng repo này.
2. Ở trang **Configure Project**:
   - **Project Name**: `kpdl-web-SUF` (để địa chỉ ngắn, dạng `https://kpdl-web-SUF.vercel.app`).
   - **Framework Preset**: Next.js.
   - **Root Directory**: bấm **Edit** và chọn thư mục `frontend`.
   - **Environment Variables**: thêm hai biến `NEXT_PUBLIC_API_URL` = `https://ca-api.DOMAIN` và `NEXT_PUBLIC_DATA_MODE` = `api`.
   - Để nguyên Build Command và Output Directory.
3. Bấm **Deploy**, chờ build vài phút. Xong, địa chỉ production hiện ở trang project (nút **Visit** hoặc mục Domains), dạng `https://kpdl-web-SUF.vercel.app`. Ghi lại đúng địa chỉ **ngắn** này (không có `/` ở cuối); gọi là `WEB_URL`. Lúc này web mở được nhưng chưa có dữ liệu vì `ca-api` chưa tạo.
4. Nếu mở web mà bị bắt đăng nhập Vercel: **Settings → Deployment Protection** → tắt *Vercel Authentication* (hoặc dùng địa chỉ production ngắn thay vì địa chỉ dài của từng lần deploy).

Rồi tạo `ca-api` theo 11.2 (environment chọn `kpdl-env` có sẵn):

| App | Image : tag | Port | CPU / RAM | Min / Max replicas |
| :--- | :--- | :--- | :--- | :--- |
| `ca-api` | `kpdl-api` : `v1` | 8000 | 0.25 / 0.5 Gi | 0 / 1 |

**Biến môi trường `ca-api`:**

| Tên biến | Giá trị |
| :--- | :--- |
| `MART_DSN` | DSN mart của `api_user` |
| `JOB_TRIGGER_TOKEN` | token job (**giống** `ca-analysis`) |
| `ANALYSIS_URL` | `https://ca-analysis.DOMAIN` |
| `CLUSTERING_URL` | `https://ca-clustering.DOMAIN` |
| `PREDICTION_URL` | `https://ca-prediction.DOMAIN` |
| `JOB_REQUEST_TIMEOUT_SECONDS` | `45` (dư cho lần khởi động lạnh của app) |
| `CORS_ORIGINS` | `WEB_URL`, tức địa chỉ Vercel ở trên (không có dấu `/` ở cuối) |

(Thay `DOMAIN` bằng Default domain thật. Các DSN và token nhập thẳng vào ô giá trị cho đơn giản; chấp nhận được với đồ án ngắn hạn. Muốn kín hơn thì dùng mục **Secrets** của app rồi chọn *Reference a secret*.)

### 11.5 [VM] Huấn luyện mô hình rồi đóng gói vào image

Chỉ làm khi bước 10 đã cho kết quả ít nhất **30 ngày** Silver (cột `min(ts)` cách `max(ts)` từ 30 ngày trở lên). Chưa đủ thì chờ backfill chạy tiếp, trainer sẽ từ chối huấn luyện.

```bash
dc --profile training run --rm trainer
ls -la models
```

Phải thấy các file `.joblib` (ví dụ `rf_regressor.joblib`, `rf_classifier.joblib`) và `metrics.json`. Rồi đóng gói vào hai image và đẩy lên registry:

```bash
for s in clustering prediction; do
  docker build -f deploy/azure/Dockerfile.models --build-arg BASE=$ACR_LOGIN/kpdl-$s:v1 \
    -t $ACR_LOGIN/kpdl-$s:v1-models models && docker push $ACR_LOGIN/kpdl-$s:v1-models
done
```

### 11.6 [Portal] Hai app còn lại: `ca-prediction`, `ca-clustering`

Tạo như 11.2, **dùng tag `v1-models`** (environment chọn `kpdl-env`):

| App | Image : tag | Port | CPU / RAM | Min / Max replicas |
| :--- | :--- | :--- | :--- | :--- |
| `ca-prediction` | `kpdl-prediction` : `v1-models` | 8003 | 0.5 / 1 Gi | 1 / 1 |
| `ca-clustering` | `kpdl-clustering` : `v1-models` | 8002 | 0.5 / 1 Gi | 0 / 1 |

Biến môi trường: giống `ca-analysis` (5 biến ở 11.3).

`ca-analysis` và `ca-prediction` luôn bật 1 bản sao vì job chạy nền sau khi trả 202, không nên bị tắt giữa chừng. Nếu `ca-clustering` báo job bị gián đoạn thì đặt Min replicas = 1.

## 12. [Portal + Cloud Shell] Azure Function (bộ hẹn giờ)

### 12.1 [Portal] Tạo Function App

**Create a resource → Function App → Create.** Chọn hosting plan **Flex Consumption** (hoặc **Consumption** nếu có).

| Ô | Giá trị |
| :--- | :--- |
| Resource group | `kpdl-rg` |
| Function App name | `kpdl-func-SUF` |
| Region | cùng region |
| Runtime stack | Python, version 3.11 |
| Storage account | tạo mới, tên `kpdlstgSUF` |
| Application Insights | giữ **Yes** (không có thì tab Monitor không hiện lượt chạy) |

### 12.2 [Portal] Thêm biến môi trường cho Function

Function App → **Settings → Environment variables** (hoặc Configuration) → **App settings** → thêm 4 biến, rồi **Apply** và **Confirm**:

| Tên | Giá trị |
| :--- | :--- |
| `ANALYSIS_URL` | `https://ca-analysis.DOMAIN` |
| `PREDICTION_URL` | `https://ca-prediction.DOMAIN` |
| `CLUSTERING_URL` | `https://ca-clustering.DOMAIN` |
| `JOB_TRIGGER_TOKEN` | token job (**giống** các app) |

### 12.3 [Cloud Shell] Đưa mã Function lên

Mở **Cloud Shell** (biểu tượng `>_` trên thanh trên cùng của Portal), chọn **Bash**. Nếu hỏi về storage thì chọn không cần storage account (hoặc tạo mới, rất rẻ). Rồi chạy:

```bash
git clone -b feat/docker-azure-deploy https://github.com/hieupt-ht/KPDL-NHOM-6.git
cd KPDL-NHOM-6/deploy/azure/function
python3 -m zipfile -c ../function.zip function_app.py jobs.py host.json requirements.txt
az functionapp deploy -g kpdl-rg -n kpdl-func-<SUF> --src-path ../function.zip --type zip
```

Thay `<SUF>` bằng hậu tố của bạn. Lệnh dùng được cho cả Flex Consumption lẫn Consumption. Nếu không chạy, cách khác không cần lệnh: cài VS Code + extension **Azure Functions**, mở thư mục `deploy/azure/function`, bấm `F1` → **Azure Functions: Deploy to Function App** → chọn `kpdl-func-SUF`.

Lịch (giờ UTC, trong `function_app.py`): `analysis` và `prediction` mỗi 5 phút (`0 */5 * * * *`); `clustering` lúc 17:30 UTC = 00:30 giờ Việt Nam (`0 30 17 * * *`). Ingestion không nằm ở đây vì đã tự chạy 5 phút trên VM.

## 13. Kiểm tra

Thay `DOMAIN` bằng Default domain thật:

1. Mở `https://ca-api.DOMAIN/health` trên trình duyệt: phải hiện `{"status":"ok","service":"api"}`. `https://ca-api.DOMAIN/ready` kiểm tra kết nối database (lần đầu có thể chậm vài giây vì app khởi động lạnh).
2. Mở `WEB_URL` (địa chỉ Vercel), bật **F12 → Network**: thấy các request `/api/...` đi tới `ca-api`. Gold ban đầu trống nên API trả 404, đây là thiết kế chứ không phải lỗi.
3. Vào `WEB_URL/admin`, bấm **Chạy lại** cho analysis, prediction, clustering và chờ trạng thái cuối.
4. Portal → Function App → **Functions** → từng hàm → **Monitor / Invocations**: thấy lượt chạy mỗi 5 phút, kết quả "đã nhận lệnh chạy" (hoặc "đang có job chạy, bỏ qua" khi trùng).
5. Tải lại web: đủ biểu đồ, dự báo ngày mai và nhãn rủi ro.

Chụp màn hình các bước này và Portal đang hiện bốn loại dịch vụ để đưa vào báo cáo. Phần demo "xóa hết container, `docker compose up`" vẫn làm trên máy local theo README mục 12; bản Azure chứng minh điểm cộng "deploy cloud".

## 14. Chi phí: tắt, bật lại, xóa

**Khi chưa cần dùng** (giữ nguyên dữ liệu và cấu hình), trên Portal:

- **VM** → **Stop** (loại *deallocate*, để ngừng tính tiền máy). Ingestion dừng theo; dừng quá ~36 giờ thì khi bật lại nó tự bù phần thiếu (tối đa 28 ngày).
- **PostgreSQL server** → **Stop** (Azure tự bật lại sau tối đa 7 ngày).
- **Function App** → **Stop**.
- Mỗi **Container App** → Scale → Min replicas = 0.

**Trước buổi chấm**, bật lại theo thứ tự: PostgreSQL → VM → Container Apps (đặt lại Min = 1 cho `ca-analysis`, `ca-prediction`, và nên cả `ca-api` để khỏi chờ khởi động lạnh) → Function App.

**Xong đồ án:** **Resource groups → `kpdl-rg` → Delete resource group** (gõ tên group để xác nhận). Việc này xóa sạch mọi thứ và ngừng tính tiền.

## 15. Cập nhật phiên bản

SSH vào VM, `cd ~/KPDL-NHOM-6 && source ~/kpdl.env`, `git pull`, build lại image với tag mới (ví dụ `v2`) rồi đẩy lên registry. Trên Portal, vào app → **Application → Containers → Edit and deploy**, đổi tag của image rồi Create. Huấn luyện lại mô hình: lặp lại bước 11.5, đẩy `:v2-models`, đổi tag cho `ca-prediction` và `ca-clustering`. Ingestion trên VM: `docker build ... -t $ACR_LOGIN/kpdl-ingestion:v1 .` rồi `dc up -d --force-recreate ingestion`. Frontend: Vercel tự deploy lại mỗi khi có commit mới ở nhánh `develop`; nếu chỉ đổi biến môi trường thì vào **Deployments → ⋯ → Redeploy**.

## 16. Xử lý sự cố

| Triệu chứng | Cách xử lý |
| :--- | :--- |
| `RequestDisallowedByPolicy`, "location not available", size bị chặn | Tài khoản sinh viên giới hạn region/size. Chọn region khác (và dùng cho **mọi** dịch vụ, làm lại từ đầu mục đó) hoặc size VM khác |
| Ô **Burstable** của PostgreSQL bị mờ | Đổi **Storage type** sang **Premium SSD** (không phải v2), rồi chọn lại Burstable |
| Tạo environment báo `ExpressAzureMonitorLogDestNotSupported` | Environment đang ở loại **Express** (không hỗ trợ đích log Azure Monitor). Quay lại hộp tạo environment, đổi loại về **Consumption only** (chuẩn); nếu Portal chỉ cho Express thì ở tab Monitoring chọn **Don't save logs** (không lưu log) |
| Lệnh báo biến rỗng hoặc "chưa đặt" | Quên `cd ~/KPDL-NHOM-6 && source ~/kpdl.env` ở phiên SSH mới |
| `permission denied ... docker.sock` | Chưa đăng nhập lại sau `usermod`: gõ `exit` rồi SSH lại |
| `docker push` bị từ chối | Chạy lại `echo "$ACR_PW" \| docker login $ACR_LOGIN -u $ACR_NAME --password-stdin`. Chưa bật Admin user của registry thì bật ở Access keys |
| Vercel build lỗi | Mở deployment → **Build Logs**. Kiểm tra Root Directory = `frontend` và Production Branch = `develop` (Settings → Git hoặc Environments) |
| Vercel không thấy thư mục `frontend` | Nhánh mặc định của repo vẫn là `main`: đổi sang `develop` như đầu bước 11.4 |
| Web báo lỗi mạng/CORS khi gọi API | `CORS_ORIGINS` của `ca-api` phải đúng `WEB_URL` (địa chỉ Vercel, không có `/` ở cuối). Sửa ở app → **Environment variables** |
| Web gọi sai địa chỉ API | `NEXT_PUBLIC_API_URL` nhúng lúc build: sửa biến trong Vercel (**Settings → Environment Variables**) rồi **Redeploy** |
| API trả 503 | Không kết nối được database: kiểm tra DSN có `sslmode=require`, quy tắc "Azure services" ở PostgreSQL → Networking, xem log của app (app → **Monitoring → Log stream**) |
| Job `failed`: "Chưa có mô hình" | `ca-prediction` hoặc `ca-clustering` chưa dùng image tag `v1-models` |
| Function báo HTTP 401 | `JOB_TRIGGER_TOKEN` của Function khác của app; đặt lại cho đồng nhất ở mọi nơi |
| Function báo timeout | App đang khởi động lạnh quá lâu: đặt Min replicas = 1 cho app đó. Không tự thử lại vì yêu cầu có thể đã được nhận |
| App bị `OOMKilled` | Tăng CPU/RAM của app ở **Containers → Edit and deploy** |
| Ingestion không có dữ liệu | `dc logs --tail 50 ingestion`; kiểm tra `CF_API_TOKEN` |
| Trainer dừng vì Silver ít hơn 30 ngày | Chờ backfill chạy xong rồi chạy lại 11.5 |

## 17. Lưu ý bảo mật

- `~/kpdl.env` (trên VM) chứa mật khẩu và token: không gửi cho ai, không commit, và xóa khi xong đồ án.
- Mật khẩu admin PostgreSQL chỉ dùng cho bước khởi tạo (bước 9); các service chạy bằng ba user ứng dụng có quyền hẹp.
- PostgreSQL mở cho "mọi dịch vụ Azure" và VM mở cổng SSH ra internet (chỉ cho đăng nhập bằng khóa): chỉ phù hợp đồ án ngắn hạn. Xóa resource group khi xong.
- Đừng dán `CF_API_TOKEN`, DSN hoặc `JOB_TRIGGER_TOKEN` vào chat, issue hoặc PR.

## 18. Phụ lục: chạy frontend trong Container Apps (thay cho Vercel)

Chỉ làm khi cần đặt cả frontend trong Azure. Cần `DOMAIN` (sau 11.3). Build image `web` trên VM (cần ≥ 4 GiB RAM, đã có swap):

```bash
docker build -f frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_URL=https://ca-api.$DOMAIN \
  --build-arg NEXT_PUBLIC_DATA_MODE=api \
  -t $ACR_LOGIN/kpdl-web:v1 frontend && docker push $ACR_LOGIN/kpdl-web:v1
```

Build chạy luôn test đơn vị, lint và `next build`, mất vài phút. Rồi tạo app theo 11.2:

| App | Image : tag | Port | CPU / RAM | Min / Max replicas |
| :--- | :--- | :--- | :--- | :--- |
| `ca-web` | `kpdl-web` : `v1` | 3000 | 0.25 / 0.5 Gi | 0 / 1 |

Biến môi trường `ca-web`: `HOSTNAME` = `0.0.0.0`, `PORT` = `3000`. Khi đó `WEB_URL` là `https://ca-web.DOMAIN`; đặt `CORS_ORIGINS` của `ca-api` bằng đúng giá trị này.
