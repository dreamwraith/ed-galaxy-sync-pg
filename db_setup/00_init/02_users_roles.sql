-- ==============================================================================
-- 02_users_roles.sql: User Roles & Permission Grants
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1. Read-Only Analytical User: galaxy_searcher
-- ------------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'galaxy_searcher') THEN
        CREATE ROLE galaxy_searcher WITH LOGIN PASSWORD '{{GALAXY_SEARCHER_PASSWORD}}';
    ELSE
        ALTER ROLE galaxy_searcher WITH PASSWORD '{{GALAXY_SEARCHER_PASSWORD}}';
    END IF;
END
$$;

-- Grant database connection and schema usage
GRANT CONNECT ON DATABASE galaxy_sync TO galaxy_searcher;
GRANT USAGE ON SCHEMA public TO galaxy_searcher;

-- Grant read-only access to all current and future tables/views
GRANT SELECT ON ALL TABLES IN SCHEMA public TO galaxy_searcher;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO galaxy_searcher;

-- Explicitly isolate internal pipeline tracking, DLQ, and debug tables from read-only searcher
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = '_ingested_tables') THEN
        REVOKE SELECT ON TABLE _ingested_tables FROM galaxy_searcher;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = '_raw_debug_log') THEN
        REVOKE SELECT ON TABLE _raw_debug_log FROM galaxy_searcher;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'eddn_unhandled_events') THEN
        REVOKE SELECT ON TABLE eddn_unhandled_events FROM galaxy_searcher;
    END IF;
END
$$;

-- Grant execute on pure functions (e.g. system_distance_3d)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'system_distance_3d') THEN
        GRANT EXECUTE ON FUNCTION system_distance_3d(cube, cube) TO galaxy_searcher;
    END IF;
END
$$;

-- ------------------------------------------------------------------------------
-- 2. Read/Write DML-Only Ingestion Daemon: galaxy_updater
-- ------------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'galaxy_updater') THEN
        CREATE ROLE galaxy_updater WITH LOGIN PASSWORD '{{GALAXY_UPDATER_PASSWORD}}';
    ELSE
        ALTER ROLE galaxy_updater WITH PASSWORD '{{GALAXY_UPDATER_PASSWORD}}';
    END IF;
END
$$;

-- Grant database connection and schema usage
GRANT CONNECT ON DATABASE galaxy_sync TO galaxy_updater;
GRANT USAGE ON SCHEMA public TO galaxy_updater;

-- Revoke schema-level DDL rights (cannot CREATE tables, types, or schemas)
REVOKE CREATE ON SCHEMA public FROM galaxy_updater;

-- Grant full DML permissions (SELECT, INSERT, UPDATE, DELETE) on all tables
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO galaxy_updater;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO galaxy_updater;

-- Grant sequence usage for auto-incrementing surrogate keys
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO galaxy_updater;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO galaxy_updater;

-- ------------------------------------------------------------------------------
-- 3. Stored Procedure Security Isolation
-- ------------------------------------------------------------------------------
-- By default, restrict execution of data-modifying procedures
REVOKE EXECUTE ON ALL PROCEDURES IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL PROCEDURES IN SCHEMA public FROM galaxy_searcher;

-- Explicitly grant DML procedure execution strictly to galaxy_updater
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'sp_normalize_galaxy_data') THEN
        GRANT EXECUTE ON PROCEDURE sp_normalize_galaxy_data(INT) TO galaxy_updater;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'sp_process_eddn_dlq') THEN
        GRANT EXECUTE ON PROCEDURE sp_process_eddn_dlq(INT, TEXT, BOOLEAN, BOOLEAN) TO galaxy_updater;
    END IF;
END
$$;
