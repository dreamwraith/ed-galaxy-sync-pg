-- ==============================================================================
-- 03_optional_pg_duckdb.sql: Optional pg_duckdb Extension & Role Setup
-- ==============================================================================
-- Execute as PostgreSQL superuser (e.g. postgres) if pg_duckdb is installed on
-- the database cluster.
--
-- This script:
--   1. Installs the pg_duckdb extension in galaxy_sync.
--   2. Provisions the unprivileged duckdb_users execution role.
--   3. Grants SELECT-only permissions across all tables/views.
--   4. Adds galaxy_searcher and galaxy_updater to duckdb_users.
--
-- After running this script, set the cluster configuration as superuser:
--   ALTER SYSTEM SET duckdb.postgres_role = 'duckdb_users';
--   SELECT pg_reload_conf();
-- ==============================================================================

-- 1. Create pg_duckdb extension
CREATE EXTENSION IF NOT EXISTS pg_duckdb;

-- 2. Create duckdb_users execution role
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'duckdb_users') THEN
        CREATE ROLE duckdb_users WITH
            NOLOGIN
            NOSUPERUSER
            INHERIT
            NOCREATEDB
            NOCREATEROLE
            NOREPLICATION
            NOBYPASSRLS;
    END IF;
END
$$;

-- 3. Grant connection and schema usage
GRANT CONNECT ON DATABASE galaxy_sync TO duckdb_users;
GRANT USAGE ON SCHEMA public TO duckdb_users;

-- 4. Grant SELECT-only privileges on all tables & future tables
GRANT SELECT ON ALL TABLES IN SCHEMA public TO duckdb_users;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO duckdb_users;

-- 5. Add database users to duckdb_users role
GRANT duckdb_users TO galaxy_searcher;
GRANT duckdb_users TO galaxy_updater;

-- 6. Restrict stored procedure execution
REVOKE EXECUTE ON ALL PROCEDURES IN SCHEMA public FROM duckdb_users;
