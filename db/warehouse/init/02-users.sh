#!/bin/sh
set -eu
: "${INGESTION_DB_PASSWORD:?missing INGESTION_DB_PASSWORD}"
: "${LOGIC_DB_PASSWORD:?missing LOGIC_DB_PASSWORD}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v dbname="$POSTGRES_DB" -v ingestion_password="$INGESTION_DB_PASSWORD" -v logic_password="$LOGIC_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE ingestion_user LOGIN PASSWORD %L', :'ingestion_password') \gexec
SELECT format('CREATE ROLE logic_user LOGIN PASSWORD %L', :'logic_password') \gexec
GRANT CONNECT ON DATABASE :"dbname" TO ingestion_user, logic_user;
GRANT USAGE ON SCHEMA bronze, silver TO ingestion_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA bronze, silver TO ingestion_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA bronze, silver TO ingestion_user;
GRANT USAGE ON SCHEMA silver TO logic_user;
GRANT SELECT ON ALL TABLES IN SCHEMA silver TO logic_user;
SQL
