-- ==============================================================================
-- 00_database.sql: Database Initialization
-- ==============================================================================
-- Execute as PostgreSQL superuser (e.g. postgres) to create the database.
-- NOTE: In managed environments, this may be provisioned externally.

CREATE DATABASE galaxy_sync
    WITH 
    ENCODING = 'UTF8'
    LC_COLLATE = 'C'
    LC_CTYPE = 'C'
    TEMPLATE = template1;
