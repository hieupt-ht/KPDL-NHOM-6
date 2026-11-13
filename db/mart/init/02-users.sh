#!/bin/sh
set -eu
: "${LOGIC_DB_PASSWORD:?missing LOGIC_DB_PASSWORD}"
: "${API_DB_PASSWORD:?missing API_DB_PASSWORD}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v dbname="$POSTGRES_DB" -v logic_password="$LOGIC_DB_PASSWORD" -v api_password="$API_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE logic_user LOGIN PASSWORD %L', :'logic_password') \gexec
SELECT format('CREATE ROLE api_user LOGIN PASSWORD %L', :'api_password') \gexec
GRANT CONNECT ON DATABASE :"dbname" TO logic_user, api_user;
GRANT USAGE ON SCHEMA gold TO logic_user, api_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA gold TO logic_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA gold TO logic_user;
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO api_user;
SQL
