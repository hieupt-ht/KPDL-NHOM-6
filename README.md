# Hệ thống Giám sát và Cảnh báo Bất thường An ninh mạng Việt Nam

**Kiến trúc microservices và Data Warehouse / Data Mart phân tích dữ liệu chuỗi thời gian từ Cloudflare Radar API (khu vực Việt Nam)**

> Đồ án cuối kỳ môn Khai phá dữ liệu – GVHD: TS. Phạm Tuấn

| Thành phần | Công nghệ |
| :--- | :--- |
| Frontend | Next.js (App Router), Tailwind CSS, Apache ECharts, Auth.js (NextAuth) |
| Backend | Python 3.11, FastAPI, pandas, scikit-learn, statsmodels, APScheduler |
| Lưu trữ | PostgreSQL ×2: **Data Warehouse** (Bronze, Silver) và **Data Mart** (Gold) |
| Xác thực | Keycloak: SSO theo chuẩn OpenID Connect (OIDC) |
| Triển khai | Docker Compose (9 container) |

---

## Mục lục

1. [Hệ thống mục tiêu và phạm vi](#1-hệ-thống-mục-tiêu-và-phạm-vi)
2. [Kiến trúc tổng thể](#2-kiến-trúc-tổng-thể)
3. [Nguồn dữ liệu và Data Ingestion](#3-nguồn-dữ-liệu-và-data-ingestion)
4. [Data Warehouse và Data Mart (Medallion)](#4-data-warehouse-và-data-mart-medallion)
5. [Business Logic: thuật toán](#5-business-logic-thuật-toán)
6. [API và xác thực SSO/OIDC](#6-api-và-xác-thực-ssooidc)
7. [Frontend và các pattern trực quan hóa](#7-frontend-và-các-pattern-trực-quan-hóa)
8. [Thông tin cấu hình hệ thống](#8-thông-tin-cấu-hình-hệ-thống)
9. [Sơ đồ network và Docker](#9-sơ-đồ-network-và-docker)
10. [Cấu trúc mã nguồn](#10-cấu-trúc-mã-nguồn)
11. [Cài đặt và chạy](#11-cài-đặt-và-chạy)
12. [Kịch bản demo](#12-kịch-bản-demo)
13. [Đối chiếu tiêu chí chấm điểm](#13-đối-chiếu-tiêu-chí-chấm-điểm)
14. [Tài liệu tham khảo](#tài-liệu-tham-khảo)

---

## 1. Hệ thống mục tiêu và phạm vi

**Hệ thống áp dụng:** lưu lượng truy cập Web/API và hoạt động tấn công tầng ứng dụng (Layer 7 DDoS, bot traffic) liên quan đến Việt Nam, quan sát qua dữ liệu mạng biên của Cloudflare.

**Phạm vi:**

- Thu thập dữ liệu chuỗi thời gian 5 phút/lần, lưu vào Data Warehouse theo hai tầng Bronze và Silver.
- Phân tích thống kê, re-sampling, tương quan, tính mùa vụ, phân cụm, dự báo (liên tục) và phân loại (rời rạc).
- Ghi kết quả vào Data Mart (tầng Gold).
- Dashboard web có đăng nhập SSO, zoom và filter.
- **Ngoài phạm vi:** không chặn IP và không can thiệp tường lửa.

> **Về bản chất dữ liệu:** Cloudflare Radar **không trả về số request tuyệt đối**. Giá trị đã được chuẩn hóa (`MIN0_MAX` ra thang 0–1, các endpoint dạng nhóm ra tỉ lệ %). Vì vậy hệ thống dùng khái niệm **"chỉ số lưu lượng"** và **"tỉ lệ %"**.

---

## 2. Kiến trúc tổng thể

```text
                                   ┌───────────────────┐
                                   │  Front End        │
                                   │  Next.js+Tailwind │
                                   └─────────┬─────────┘
                                             │ JSON + Bearer token
                                             ▼
                                   ┌───────────────────┐   SSO    ┌──────────────────┐
                                   │       API         │────────► │ Keycloak (OIDC)  │
                                   │     (FastAPI)     │          └──────────────────┘
                                   └───┬───────────┬───┘
                       POST /jobs/run  │           │ SELECT (chỉ đọc)
                                       ▼           ▼
┌─────────────┐  Call API  ┌───────────┐     ┌──────────────────────────────────────┐
│ Data Source │◄─────────► │   Data    │     │           Business Logic             │
│ (Cloudflare │            │ Ingestion │     │  ┌──────────────┐  ┌──────────────┐  │
│ Radar - VN) │            │ (5 phút)  │     │  │Data Analysis │  │  Clustering  │  │
└─────────────┘            └─────┬─────┘     │  │  (5 phút)    │  │  (1 ngày)    │  │
                                 │           │  └──────────────┘  └──────────────┘  │
                                 │           │  ┌───────────────────────────────┐   │
                                 │           │  │ Prediction (5 phút)           │   │
                                 │           │  │  ├ Liên tục: hồi quy          │   │
                                 │           │  │  └ Rời rạc: phân loại         │   │
                                 │           │  └───────────────────────────────┘   │
                                 │           └───────▲────────────────────┬─────────┘
                                 ▼                   │ đọc Silver         │ ghi Gold
                     ┌─────────────────────────┐     │       ┌────────────▼────────────┐
                     │     DATA WAREHOUSE      │─────┘       │        DATA MART        │
                     │  Bronze ──► Silver      │ ──────────► │          Gold           │◄── API đọc
                     │  (thô)      (sạch)      │             │   (kết quả sẵn dùng)    │
                     └─────────────────────────┘             └─────────────────────────┘
```

### Nguyên tắc thiết kế

- **Mỗi khối là một service độc lập**, chạy trong một container (hoặc một terminal khi phát triển).
- **Luồng dữ liệu một chiều qua 3 tầng:** Bronze (thô) → Silver (sạch) → Gold (kết quả).
- **Mỗi service chỉ ghi vào vùng của mình:**
  - Ingestion ghi vào Warehouse.
  - Business Logic đọc Warehouse và ghi vào Mart.
  - API **chỉ đọc** Mart.
- **Các service không gọi nhau để trao đổi dữ liệu.** Ngoại lệ duy nhất: API có thể *kích hoạt* (trigger) các service Business Logic.
- **Frontend không chạm vào database**, chỉ gọi API. Mọi tính toán đều ở backend, **frontend chỉ vẽ**.

### Bảng các khối

| Khối | Chu kỳ | Đọc từ | Ghi vào | Nhiệm vụ |
| :--- | :--- | :--- | :--- | :--- |
| **Data Source** | Liên tục | — | — | Cloudflare Radar API, `location=VN` |
| **Data Ingestion** | 5 phút | Cloudflare | Warehouse | Call API, lưu JSON thô (Bronze), làm sạch và chuẩn hóa (Silver) |
| **Data Warehouse** | Thường trực | — | — | PostgreSQL chứa Bronze và Silver |
| **Data Analysis** | 5 phút | Silver | Gold | Re-sampling, thống kê, histogram, trend, seasonal, tương quan |
| **Clustering** | 1 ngày | Silver | Gold | K-Means phân cụm trạng thái từng ngày |
| **Prediction** | 5 phút | Silver | Gold | Dự báo **liên tục** (chỉ số lưu lượng ngày mai) và **rời rạc** (rủi ro Cao/Thấp) |
| **Data Mart** | Thường trực | — | — | PostgreSQL chứa Gold |
| **API** | Thường trực | Gold | — | REST/JSON cho frontend, xác thực token, trigger job |
| **Keycloak** | Thường trực | — | — | Máy chủ SSO/OIDC |
| **Front End** | Thường trực | API | — | Dashboard Next.js |

---

## 3. Nguồn dữ liệu và Data Ingestion

### 3.1. Phương thức thu thập: Call API, không crawl

Có hai cách lấy dữ liệu từ Data Source: **Call API** chính thức hoặc **crawling**. Nhóm chọn **Call API**:

- Cloudflare Radar cung cấp API chính thức, dữ liệu có cấu trúc JSON, xác thực bằng token.
- Vì không crawl website nên **không cần proxy rotation** (kỹ thuật xoay vòng IP để vượt cơ chế chặn bot khi crawl). Dùng proxy để lách giới hạn của một API chính thức còn vi phạm điều khoản sử dụng.
- Cơ chế chống quá tải thay thế: tuân thủ rate limit và **retry với exponential backoff** khi gặp `HTTP 429`.

### 3.2. Xác thực với Cloudflare

- API Token miễn phí, quyền `Account → Cloudflare Radar → Read`.
- Gửi qua header `Authorization: Bearer <CF_API_TOKEN>`.
- Token để trong file `.env`, **không commit lên git**.

### 3.3. Các chỉ số thu thập

Tất cả truy vấn dùng `location=VN`, `aggInterval=1h` và `format=json`. Base URL: `https://api.cloudflare.com/client/v4`.

| Mã chỉ số (`metric`) | Ý nghĩa | Endpoint |
| :--- | :--- | :--- |
| `http_traffic` | Chỉ số lưu lượng HTTP (0–1) | `GET /radar/http/timeseries` |
| `l7_attack` | Chỉ số tấn công Layer 7 | `GET /radar/attacks/layer7/timeseries` |
| `bot_share`, `human_share` | Tỉ lệ % bot và người dùng thật | `GET /radar/http/timeseries_groups/bot_class` |
| `netflows` | Chỉ số lưu lượng mạng tổng | `GET /radar/netflows/timeseries` |

> **Cố định `aggInterval=1h`** để dữ liệu backfill và polling có cùng bước thời gian. Nếu không chỉ định, Cloudflare tự đổi độ phân giải theo `dateRange`.
>
> **Cần xác minh khi triển khai:** với endpoint Layer 7, kiểm tra xem `location` lọc theo *nguồn tấn công* hay *mục tiêu bị tấn công*, rồi ghi rõ trong báo cáo.

### 3.4. Quy trình mỗi chu kỳ (Bronze → Silver)

1. **Extract:** gọi đồng thời 4 endpoint.
2. **Load (Bronze):** lưu **nguyên văn** JSON response vào `bronze.raw_api_responses`, gồm endpoint, tham số, mã HTTP và thời điểm lấy. Không sửa gì.
3. **Transform (Silver):** parse JSON, tách từng chỉ số, ép kiểu số, chuyển timestamp về UTC, loại giá trị lỗi, sau đó `UPSERT` vào `silver.metrics_hourly`:

```sql
INSERT INTO silver.metrics_hourly (ts, metric, value, updated_at)
VALUES (%s, %s, %s, now())
ON CONFLICT (ts, metric)
DO UPDATE SET value = EXCLUDED.value, updated_at = now();
```

### 3.5. Backfill và polling

- **Backfill ở lần chạy đầu** (khi Silver trống): nạp **12 tháng** bằng `dateStart`/`dateEnd`, mỗi đợt 7 ngày. Lý do: đề bài yêu cầu trend và seasonal theo **tháng**, mà 30 ngày dữ liệu thì không đủ điểm để vẽ.
- **Polling mỗi 300 giây** với `dateRange=2d`, để cập nhật cả những mốc vừa qua mà Cloudflare có thể đã điều chỉnh.
- **Xử lý lỗi:** `try/except` kết hợp backoff 1s → 2s → 4s → … tối đa 60s. Một endpoint lỗi không làm dừng service.
- **Múi giờ:** lưu UTC (`TIMESTAMPTZ`). Business Logic đổi sang `Asia/Ho_Chi_Minh` khi tính theo giờ, theo thứ và khi xác định "ngày mai".

---

## 4. Data Warehouse và Data Mart (Medallion)

Hệ thống chia dữ liệu theo **kiến trúc Medallion** gồm 3 tầng chất lượng, đặt trong **2 database PostgreSQL riêng biệt** (2 container).

| Tầng | Database | Mục đích | Ai ghi | Ai đọc |
| :--- | :--- | :--- | :--- | :--- |
| **Bronze** | Data Warehouse | Dữ liệu thô, giữ nguyên để truy vết và xử lý lại khi cần | Ingestion | Ingestion |
| **Silver** | Data Warehouse | Dữ liệu sạch, chuẩn hóa, không trùng lặp | Ingestion | Business Logic |
| **Gold** | Data Mart | Kết quả phân tích sẵn dùng cho hiển thị | Business Logic | API |

**Vì sao tách Warehouse và Mart?**

- Warehouse là "kho nguyên liệu" lưu toàn bộ lịch sử. Mart là "kho thành phẩm", nhỏ gọn và được tối ưu cho truy vấn của dashboard.
- API chỉ có quyền đọc Mart, nên dữ liệu gốc được bảo vệ.
- Khi demo, xóa Data Mart thì dashboard lỗi nhưng Warehouse vẫn còn nguyên. Chạy lại Business Logic là Mart được tái tạo từ Silver.

### 4.1. Data Warehouse (`warehouse-db`)

```sql
CREATE SCHEMA bronze;
CREATE SCHEMA silver;

CREATE TABLE bronze.raw_api_responses (
    id           BIGSERIAL PRIMARY KEY,
    endpoint     VARCHAR(128) NOT NULL,
    params       JSONB,
    status_code  INT,
    payload      JSONB,
    fetched_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE silver.metrics_hourly (
    ts          TIMESTAMPTZ NOT NULL,
    metric      VARCHAR(32) NOT NULL,   -- http_traffic | l7_attack | bot_share | human_share | netflows
    value       DOUBLE PRECISION,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ts, metric)
);

CREATE TABLE silver.ingestion_runs (
    id           BIGSERIAL PRIMARY KEY,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    status       VARCHAR(16),
    rows_upserted INT,
    error        TEXT
);
```

> Bronze có thể giữ lại 30 ngày gần nhất (có job dọn dẹp). Silver giữ toàn bộ lịch sử.

### 4.2. Data Mart (`mart-db`, schema `gold`)

| Bảng | Service ghi | Nội dung |
| :--- | :--- | :--- |
| `gold.timeseries_resampled` | Data Analysis | `(granularity, ts, metric, mean, min, max)`, granularity là `day`, `week` hoặc `month` |
| `gold.histogram` | Data Analysis | `(metric, bin_start, bin_end, count)` |
| `gold.trend` | Data Analysis | `(granularity, ts, metric, trend_value)` |
| `gold.seasonal` | Data Analysis | `(period_type, bucket, metric, value)`, period_type là `hour_of_day`, `day_of_week` hoặc `month` |
| `gold.correlation` | Data Analysis | `(var_x, var_y, coef, computed_at)` |
| `gold.data_freshness` | Data Analysis | Mốc dữ liệu Silver mới nhất, dùng để hiển thị "cập nhật lúc …" |
| `gold.cluster_results` | Clustering | `(date, cluster_id, cluster_name, features JSONB, computed_at)` |
| `gold.forecast_continuous` | Prediction | `(target_date, predicted_value, model_name, created_at)` |
| `gold.forecast_discrete` | Prediction | `(target_date, label, probability, model_name, created_at)` |
| `gold.service_runs` | Business Logic | Nhật ký mỗi lần chạy của từng service |

**Phân quyền (mỗi service một user PostgreSQL):**

| User | Database | Quyền |
| :--- | :--- | :--- |
| `ingestion_user` | Warehouse | đọc và ghi `bronze`, `silver` |
| `logic_user` | Warehouse | chỉ đọc `silver` |
| `logic_user` | Mart | đọc và ghi `gold` |
| `api_user` | Mart | **chỉ** `SELECT` trên `gold` |

---

## 5. Business Logic: thuật toán

Mỗi service là một ứng dụng FastAPI riêng, có:

- **Scheduler** (APScheduler) chạy tự động theo chu kỳ.
- **`POST /run`** để kích hoạt thủ công.
- **`GET /health`**.

Các service chỉ **nạp mô hình đã huấn luyện sẵn** từ `models/` và **không huấn luyện lại** trong lúc chạy.

### 5.1. Data Analysis (5 phút/lần)

- **Re-sampling:** `pandas.resample` theo `D`, `W` và `M`, lấy mean/min/max.
- **Histogram:** chia `http_traffic`, `l7_attack` và `bot_share` thành 20 bin.
- **Trend:** `statsmodels.seasonal_decompose` trên chuỗi re-sample theo tháng; nếu thiếu điểm thì dùng chuỗi theo tuần.
- **Seasonal:** trung bình theo giờ trong ngày, theo thứ trong tuần và theo tháng (giờ Việt Nam).
- **Tương quan:** hệ số Pearson giữa 5 biến `http_traffic`, `l7_attack`, `bot_share`, `human_share` và `netflows`.

### 5.2. Clustering (1 ngày/lần, 00:30 giờ VN)

- **Thuật toán:** K-Means với k = 3. Mỗi ngày là một điểm dữ liệu.
- **Đặc trưng mỗi ngày:**
  - trung bình và độ lệch chuẩn của `http_traffic`
  - trung bình và giá trị lớn nhất của `l7_attack`
  - trung bình của `bot_share`
- **Chuẩn hóa:** `StandardScaler`.
- **Chọn k:** dùng Elbow và Silhouette score (trình bày trong notebook huấn luyện).
- **Đặt tên cụm theo tâm cụm:**
  - **Bình thường:** traffic và tấn công đều thấp
  - **Cao điểm:** traffic cao, tấn công thấp
  - **Bất thường:** tấn công hoặc bot cao

### 5.3. Prediction (5 phút/lần): liên tục và rời rạc

| | **Liên tục**: hồi quy (pattern 5) | **Rời rạc**: phân loại (pattern 6) |
| :--- | :--- | :--- |
| Mục tiêu | Trung bình `http_traffic` của ngày mai | Mức rủi ro ngày mai: **Cao** / **Thấp** |
| Định nghĩa nhãn | — | **Cao** nếu trung bình `l7_attack` ngày đó lớn hơn percentile 75 của dữ liệu huấn luyện |
| Thuật toán | `RandomForestRegressor` | `RandomForestClassifier` (`class_weight="balanced"`) |
| Đặc trưng | Lag 1, 2, 3 và 7 ngày của traffic; rolling mean 7 ngày; thứ trong tuần; lag 1 ngày của `l7_attack` và `bot_share` | Giống bên hồi quy |
| Đánh giá | MAE, RMSE | Accuracy, F1, confusion matrix |
| Chia dữ liệu | 30 ngày cuối làm tập test, chia theo thời gian (không xáo trộn) | Giống bên hồi quy |

> **Chạy 5 phút/lần nhưng dự báo "ngày mai":** mỗi lần chạy, service lấy dữ liệu Silver mới nhất (có thể Cloudflare vừa điều chỉnh) để cập nhật đặc trưng. Kết quả chỉ đổi khi dữ liệu đầu vào đổi. Service không huấn luyện lại.

### 5.4. Huấn luyện offline

- `training/train_models.py` đọc Silver, huấn luyện K-Means, hồi quy và phân loại, rồi lưu `.pkl` vào `models/`.
- Kết quả đánh giá ghi vào `models/metrics.json`.
- Script chạy thủ công và không nằm trong luồng demo.

---

## 6. API và xác thực SSO/OIDC

### 6.1. Endpoint dữ liệu

API viết bằng FastAPI, chạy ở port `8000`, đọc từ Data Mart. Mọi endpoint nhận tham số `start` và `end` (ISO 8601) để lọc theo khoảng thời gian.

| Endpoint | Pattern |
| :--- | :--- |
| `GET /api/timeseries?granularity=day\|week\|month&metric=` | Line chart, scatter |
| `GET /api/histogram?metric=` | Histogram |
| `GET /api/trend?granularity=month\|week&metric=` | Trend |
| `GET /api/seasonal?period_type=hour_of_day\|day_of_week\|month&metric=` | Seasonal |
| `GET /api/correlation` | Ma trận tương quan |
| `GET /api/clusters` | Phân cụm |
| `GET /api/forecast/continuous` | Dự báo chỉ số lưu lượng ngày mai |
| `GET /api/forecast/discrete` | Nhãn rủi ro ngày mai |
| `GET /api/status` | Lần chạy gần nhất của từng service và độ mới của dữ liệu |
| `POST /api/jobs/{analysis\|clustering\|prediction}/run` | Kích hoạt Business Logic (cần role `admin`) |

- Bảng Gold trống thì API trả **`404`** kèm thông báo rõ ràng. Đây là lỗi cần thấy ở bước 5 của demo.
- Thiếu token hoặc token sai thì trả **`401`**.

### 6.2. Luồng đăng nhập SSO

**SSO (Single Sign-On)** nghĩa là ứng dụng không tự quản lý đăng nhập mà giao cho một máy chủ xác thực chuyên dụng (**Keycloak**). **OIDC (OpenID Connect)** là giao thức chuẩn để frontend, API và Keycloak trao đổi với nhau.

```text
1. Người dùng mở dashboard → chưa đăng nhập → Next.js (Auth.js) chuyển sang trang login của Keycloak
2. Đăng nhập thành công → Keycloak trả access token (JWT) → quay về dashboard
3. Frontend gọi API kèm header:  Authorization: Bearer <access_token>
4. API xác minh chữ ký JWT bằng public key (JWKS) của Keycloak, kiểm tra issuer và hạn dùng
   → hợp lệ: trả JSON từ Data Mart
   → không hợp lệ: 401
```

**Cấu hình Keycloak** (tự import từ file `keycloak/realm-export.json` khi container khởi động):

- Realm: `cyber-radar`.
- Client: `dashboard` (OIDC, confidential, redirect về `http://localhost:3000/*`).
- Role `viewer`: được xem dashboard.
- Role `admin`: được xem dashboard và chạy job.
- User demo: `demo` (role `viewer`) và `admin` (role `admin`). Mật khẩu đặt trong `.env`.

**Công tắc phát triển:** `AUTH_ENABLED=false` trong `.env` sẽ tắt kiểm tra token, giúp phát triển các phần khác trước khi làm xong SSO.

> **Lưu ý cấu hình:** trình duyệt truy cập Keycloak qua `localhost:8080`, còn container API gọi qua `keycloak:8080`. Phải đặt `KC_HOSTNAME` (hoặc cấu hình issuer hợp lệ ở API) để trường `iss` trong token khớp với cấu hình, nếu không API sẽ trả 401.

---

## 7. Frontend và các pattern trực quan hóa

### 7.1. Công nghệ

- **Next.js (App Router)** và **Tailwind CSS** cho giao diện, có dark mode và responsive.
- **Apache ECharts** (`echarts-for-react`) cho biểu đồ, có sẵn `dataZoom` (zoom) và tooltip.
- **Auth.js (NextAuth)** với Keycloak provider để đăng nhập SSO.
- **SWR** để gọi API, tự làm mới mỗi 5 phút (`refreshInterval`).

> **Quan trọng cho demo:** dữ liệu biểu đồ được gọi **từ trình duyệt** (client component) thẳng tới API `http://localhost:8000/api/...`, để `F12 → Network` thấy rõ từng request JSON. Không fetch trong server component, vì như vậy request sẽ không hiện trong tab Network. API bật CORS cho `http://localhost:3000`.

### 7.2. Bố cục dashboard

- **Thanh trên:**
  - tên người dùng và nút đăng xuất
  - thời điểm cập nhật cuối
  - bộ lọc khoảng thời gian, chỉ số và độ phân giải (Ngày/Tuần/Tháng)
- **Hàng thẻ KPI:**
  - dự báo lưu lượng ngày mai
  - nhãn rủi ro ngày mai
  - cụm của hôm nay
  - tỉ lệ bot hiện tại
- **Lưới biểu đồ** gồm các pattern bên dưới.
- **Trang `/admin`** (role `admin`): nút **Run** cho Analysis, Clustering và Prediction, cùng bảng `service_runs`.

### 7.3. Các pattern

| # | Pattern theo đề | Biểu đồ | Nội dung |
| :--- | :--- | :--- | :--- |
| 1a | Dữ liệu theo thời gian (ngày/tuần/tháng) | Line | Chỉ số lưu lượng HTTP và tấn công L7, có tab Ngày, Tuần, Tháng |
| 1b | Dữ liệu theo thời gian (ngày/tuần/tháng) | Scatter | Lưu lượng so với tỉ lệ bot, tô màu theo cụm |
| 1c | Dữ liệu theo thời gian (ngày/tuần/tháng) | Histogram | Phân phối chỉ số tấn công L7 và tỉ lệ bot |
| 2 | Trend (re-sample theo tháng, thiếu thì tuần) | Line | Đường trend lưu lượng và tấn công |
| 3 | Seasonal | Seasonal line | Chu kỳ theo giờ trong ngày, thứ trong tuần và tháng |
| 4 | Ma trận tương quan | Heatmap | Hệ số Pearson giữa 5 biến |
| 5 | Dự đoán ngày mai (liên tục) | Thẻ KPI và forecast line | Chỉ số lưu lượng dự báo |
| 6 | Phân loại ngày mai (rời rạc) | Nhãn màu | **Cao** (đỏ) hoặc **Thấp** (xanh), kèm xác suất |
| + | Phân cụm | Timeline hoặc donut | Số ngày thuộc mỗi cụm |

---

## 8. Thông tin cấu hình hệ thống

| Thông số | Giá trị |
| :--- | :--- |
| Chu kỳ Data Ingestion | 5 phút (300 giây) |
| Độ phân giải dữ liệu | 1 giờ (`aggInterval=1h`) |
| Backfill ban đầu | 12 tháng (khoảng 8.760 mốc giờ × 5 chỉ số) |
| Thời gian lưu Bronze | 30 ngày |
| Chu kỳ Data Analysis / Prediction | 5 phút |
| Chu kỳ Clustering | 1 ngày (00:30 giờ VN) |
| Dữ liệu tối thiểu để dự báo | 7 ngày gần nhất (vì có lag 7 ngày) |
| Dữ liệu huấn luyện | khoảng 335 ngày train và 30 ngày test, chia theo thời gian |
| Thời gian huấn luyện | *(ghi số đo thực tế sau khi chạy `train_models.py`)* |
| Khi nào huấn luyện lại | Thủ công, đề xuất mỗi tháng hoặc khi MAE trên dữ liệu mới tăng quá 20% |
| Retry tối đa | Backoff đến 60 giây |
| Hạn dùng access token | 5 phút, refresh token 30 phút (mặc định Keycloak) |

---

## 9. Sơ đồ network và Docker

Tất cả container nằm chung một mạng bridge `cyber-net` và gọi nhau bằng tên service.

```text
                        Trình duyệt
              │ :3000                    │ :8080 (trang login)
              ▼                          ▼
┌─────────────────────────────── cyber-net ───────────────────────────────┐
│                                                                         │
│   ┌──────────┐  JSON + token  ┌──────────┐    JWKS     ┌──────────┐     │
│   │ frontend │──────────────► │   api    │───────────► │ keycloak │     │
│   │  :3000   │ (từ trình duyệt)│  :8000   │             │  :8080   │     │
│   └──────────┘                └────┬─────┘             └──────────┘     │
│                         trigger    │      SELECT                        │
│              ┌─────────────────────┤ ─────────────────┐                 │
│              ▼                     ▼                  ▼                 │
│   ┌────────────────────────────────────┐      ┌──────────────┐          │
│   │ analysis:8001  clustering:8002     │─────►│   mart-db    │          │
│   │ prediction:8003                    │ ghi  │    :5433     │          │
│   └───────────────▲────────────────────┘      └──────────────┘          │
│                   │ đọc Silver                                          │
│   ┌───────────┐   │      ┌──────────────┐                               │
│   │ ingestion │───┴─────►│ warehouse-db │                               │
│   └─────┬─────┘   ghi    │    :5432     │                               │
│         │                └──────────────┘                               │
└─────────┼───────────────────────────────────────────────────────────────┘
          │ HTTPS
          ▼
  api.cloudflare.com (Radar)
```

| Container | Image / Build | Port public | Phụ thuộc |
| :--- | :--- | :--- | :--- |
| `warehouse-db` | postgres:16 | 5432 | — |
| `mart-db` | postgres:16 | 5433 | — |
| `keycloak` | quay.io/keycloak/keycloak | 8080 | — |
| `ingestion` | `services/ingestion` | — | warehouse-db |
| `analysis` | `services/analysis` | 8001 | warehouse-db, mart-db |
| `clustering` | `services/clustering` | 8002 | warehouse-db, mart-db |
| `prediction` | `services/prediction` | 8003 | warehouse-db, mart-db |
| `api` | `services/api` | 8000 | mart-db, keycloak |
| `frontend` | `frontend` (Next.js) | 3000 | api, keycloak |

- Hai database dùng hai volume riêng là `warehouse-data` và `mart-data`.
- Service nào cũng có `healthcheck`; các service phụ thuộc DB chờ DB healthy rồi mới chạy.

---

## 10. Cấu trúc mã nguồn

```text
cyber-radar-vn/
├── docker-compose.yml
├── .env.example
├── README.md
├── db/
│   ├── warehouse/init.sql          # schema bronze, silver + user/quyền
│   └── mart/init.sql               # schema gold + user/quyền
├── keycloak/
│   └── realm-export.json           # realm cyber-radar, client, role, user demo
├── backend/
│   └── common/                     # package Python dùng chung
│       ├── db.py                   # kết nối warehouse / mart
│       ├── config.py               # đọc biến môi trường
│       ├── logging.py
│       └── runner.py               # khung FastAPI + APScheduler + POST /run
├── services/
│   ├── ingestion/
│   │   ├── Dockerfile
│   │   ├── main.py                 # vòng lặp 5 phút, backfill
│   │   ├── radar_client.py         # Call API, retry/backoff
│   │   ├── bronze.py               # lưu JSON thô
│   │   └── silver.py               # làm sạch + UPSERT
│   ├── analysis/      (Dockerfile, main.py, tasks.py)
│   ├── clustering/    (Dockerfile, main.py, tasks.py)
│   ├── prediction/    (Dockerfile, main.py, features.py, tasks.py)
│   └── api/
│       ├── Dockerfile
│       ├── main.py
│       ├── auth.py                 # xác minh JWT từ Keycloak
│       └── routers/                # timeseries, analysis, ml, jobs, status
├── frontend/                       # Next.js + Tailwind
│   ├── Dockerfile
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                # dashboard
│   │   ├── admin/page.tsx          # nút Run các job
│   │   └── api/auth/[...nextauth]/route.ts
│   ├── components/
│   │   ├── charts/                 # LineChart, Scatter, Histogram, Heatmap, ...
│   │   ├── kpi/                    # thẻ dự báo, nhãn rủi ro
│   │   └── filters/
│   ├── lib/api.ts                  # gọi API kèm token
│   └── tailwind.config.ts
├── models/                         # kmeans.pkl, scaler.pkl, regressor.pkl, classifier.pkl, metrics.json
├── training/
│   ├── train_models.py
│   └── eda.ipynb
└── docs/
    ├── report.pdf
    └── slides.pdf
```

---

## 11. Cài đặt và chạy

**Bước 1. Chuẩn bị file môi trường**

```bash
cp .env.example .env
# Điền CF_API_TOKEN, mật khẩu 2 database, KEYCLOAK_CLIENT_SECRET, AUTH_SECRET, mật khẩu user demo
```

**Bước 2. Chạy toàn bộ hệ thống**

```bash
docker compose up -d --build
```

| Địa chỉ | Nội dung |
| :--- | :--- |
| `http://localhost:3000` | Dashboard (đăng nhập bằng user `demo`) |
| `http://localhost:8000/docs` | Swagger của API |
| `http://localhost:8080` | Trang quản trị Keycloak |

**Bước 3 (chỉ khi cần). Huấn luyện lại mô hình**

```bash
python training/train_models.py
```

---

## 12. Kịch bản demo

| Bước | Thao tác | Kết quả mong đợi |
| :--- | :--- | :--- |
| 1 | `docker compose down`, sau đó `docker ps -a` | Không còn container nào |
| 2 | `docker compose up -d --build` | 9 container chạy |
| 3 | Mở web, đăng nhập SSO, bật `F12 → Network` | Đủ biểu đồ; thấy request `/api/...` mang header `Authorization` và trả JSON |
| 4 | Vào **Data Mart**, xóa dữ liệu Gold (lệnh ngay bên dưới) | Gold trống, **Warehouse vẫn còn nguyên** |
| 5 | Tải lại web | Biểu đồ báo "Chưa có dữ liệu", API trả 404 |
| 6 | Vào trang `/admin` bấm **Run** (hoặc gọi `POST /run` của từng service), mô hình có sẵn và không train lại; mở lại Data Mart | Bảng Gold có dữ liệu mới |
| 7 | Tải lại web | Toàn bộ biểu đồ, dự báo và nhãn rủi ro hiển thị lại |

Lệnh xóa ở bước 4:

```sql
TRUNCATE gold.timeseries_resampled, gold.histogram, gold.trend, gold.seasonal,
         gold.correlation, gold.data_freshness, gold.cluster_results,
         gold.forecast_continuous, gold.forecast_discrete;
```

> **Mẹo:** ở bước 1 dùng `docker compose down` **không kèm `-v`** để giữ volume Warehouse, tránh phải backfill 12 tháng (mất vài phút) ngay trong buổi demo.

---

## 13. Đối chiếu tiêu chí chấm điểm

| Tiêu chí | Điểm | Cách hệ thống đáp ứng |
| :--- | :--- | :--- |
| Hệ thống thiết kế giống sơ đồ khối | 3 | Đủ các khối Source, Ingestion, Database, Business Logic, API và FE; mở rộng theo bài giảng với Warehouse/Mart, Medallion và SSO |
| Đủ pattern (có xử lý và load từ API) | 3 | 6 pattern và phân cụm, tính ở backend, lưu Gold, trả qua API |
| Web đẹp | 1 | Next.js, Tailwind, ECharts, dark mode, responsive |
| Docker | 1 | `docker-compose.yml` với 9 container |
| Slide trình bày | 1 | `docs/slides.pdf` |
| Cấu trúc source code | 1 | Tách theo service, có package dùng chung `backend/common` |
| *Điểm cộng* | — | Zoom/filter; SSO/OIDC; deploy cloud (AWS: EC2, Lambda + EventBridge cho Ingestion, RDS PostgreSQL) |

**Checklist báo cáo:**

- [ ] Giao diện chương trình
- [ ] Sơ đồ khối và chức năng từng khối (mục 2)
- [ ] Sơ đồ network (mục 9)
- [ ] Thông tin cấu hình (mục 8)
- [ ] Thuật toán Clustering, Prediction (liên tục, rời rạc) (mục 5)
- [ ] Source code

---

## Tài liệu tham khảo

1. Cloudflare Radar – Vietnam. https://radar.cloudflare.com/vn
2. Cloudflare Radar API Documentation. https://developers.cloudflare.com/radar/
3. Cloudflare Radar – Normalization methods. https://developers.cloudflare.com/radar/concepts/normalization/
4. Databricks – What is a Medallion Architecture? https://www.databricks.com/glossary/medallion-architecture
5. Keycloak Documentation. https://www.keycloak.org/documentation
6. OpenID Connect Core 1.0. https://openid.net/specs/openid-connect-core-1_0.html
7. Next.js Documentation. https://nextjs.org/docs
8. Auth.js – Keycloak Provider. https://authjs.dev
9. scikit-learn. https://scikit-learn.org
