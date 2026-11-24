#!/usr/bin/env bash
# Khởi tạo Warehouse và Mart trên MỘT PostgreSQL server dùng chung (Azure Database for PostgreSQL).
# Chạy từ máy có `psql` (Azure Cloud Shell có sẵn). Chạy lại nhiều lần vẫn an toàn:
# database/role đã có thì bỏ qua, schema đã có thì không tạo lại, GRANT chạy lại không đổi gì.
#
#   PGHOST=<server>.postgres.database.azure.com PGUSER=<admin> PGPASSWORD=<mật khẩu admin> \
#   INGESTION_DB_PASSWORD=... LOGIC_DB_PASSWORD=... API_DB_PASSWORD=... \
#   bash deploy/azure/init-managed-db.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

: "${PGHOST:?thiếu PGHOST (tên server PostgreSQL)}"
: "${PGUSER:?thiếu PGUSER (tài khoản quản trị)}"
: "${PGPASSWORD:?thiếu PGPASSWORD (mật khẩu quản trị)}"
: "${INGESTION_DB_PASSWORD:?thiếu INGESTION_DB_PASSWORD}"
: "${LOGIC_DB_PASSWORD:?thiếu LOGIC_DB_PASSWORD}"
: "${API_DB_PASSWORD:?thiếu API_DB_PASSWORD}"
export PGHOST PGUSER PGPASSWORD INGESTION_DB_PASSWORD LOGIC_DB_PASSWORD API_DB_PASSWORD
export PGSSLMODE="${PGSSLMODE:-require}"
WAREHOUSE_DB="${WAREHOUSE_DB:-warehouse}"
MART_DB="${MART_DB:-mart}"

create_database() {
  psql -v ON_ERROR_STOP=1 -d postgres -v db="$1" <<'SQL'
SELECT format('CREATE DATABASE %I', :'db')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
SQL
}

apply_schema() { # $1=database $2=schema đặc trưng $3=file schema
  if [ "$(psql -d "$1" -tAc "SELECT to_regnamespace('$2') IS NOT NULL")" = "t" ]; then
    echo "[$1] schema $2 đã có, bỏ qua file schema"
  else
    psql -v ON_ERROR_STOP=1 -d "$1" -f "$3"
    echo "[$1] đã tạo schema từ $3"
  fi
}

create_database "$WAREHOUSE_DB"
create_database "$MART_DB"
apply_schema "$WAREHOUSE_DB" silver db/warehouse/init/01-schema.sql
apply_schema "$MART_DB" gold db/mart/init/01-schema.sql

# Dùng lại đúng script phân quyền của Docker Compose (nguồn duy nhất cho GRANT).
POSTGRES_USER="$PGUSER" POSTGRES_DB="$WAREHOUSE_DB" sh db/warehouse/init/02-users.sh
POSTGRES_USER="$PGUSER" POSTGRES_DB="$MART_DB" sh db/mart/init/02-users.sh
echo "Xong: $WAREHOUSE_DB và $MART_DB trên $PGHOST"
