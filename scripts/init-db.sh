#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 \
  --set=migrator_password="$(cat /run/secrets/migrator_password)" \
  --set=runtime_password="$(cat /run/secrets/runtime_password)" <<'SQL'
CREATE ROLE ut_staging_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'migrator_password';
CREATE ROLE ut_staging_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'runtime_password';
REVOKE ALL ON DATABASE unlimited_talk_staging FROM PUBLIC;
GRANT CONNECT ON DATABASE unlimited_talk_staging TO ut_staging_migrator,ut_staging_runtime;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA staging AUTHORIZATION ut_staging_migrator;
GRANT USAGE ON SCHEMA staging TO ut_staging_runtime;
ALTER ROLE ut_staging_migrator IN DATABASE unlimited_talk_staging SET search_path=staging,pg_catalog;
ALTER ROLE ut_staging_runtime IN DATABASE unlimited_talk_staging SET search_path=staging,pg_catalog;
ALTER DEFAULT PRIVILEGES FOR ROLE ut_staging_migrator IN SCHEMA staging GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO ut_staging_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE ut_staging_migrator IN SCHEMA staging GRANT USAGE,SELECT ON SEQUENCES TO ut_staging_runtime;
SQL
