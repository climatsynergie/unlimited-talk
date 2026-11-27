-- Run once as the database owner, before the migrator's concurrent index build.
-- This is additive: no business tables, rows, role limits or existing grants change.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;
GRANT USAGE ON SCHEMA extensions TO ut_staging_migrator,ut_staging_runtime;
