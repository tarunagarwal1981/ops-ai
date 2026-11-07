-- Lock 1: a role that can only read, and only the schemas you choose.
-- Run as an admin in the target database:  psql "$ADMIN_DATABASE_URL" -f setup_readonly_role.sql
-- Then set the password outside this file:  psql "$ADMIN_DATABASE_URL" -c '\password mcp_reader'

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mcp_reader') THEN
    CREATE ROLE mcp_reader LOGIN;  -- keep it a member of no other role
  END IF;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO mcp_reader', current_database());
END
$$;

-- Read access to the allowlisted schema only. Repeat these three lines per schema you allow.
GRANT USAGE ON SCHEMA public TO mcp_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_reader;
-- Note: ALTER DEFAULT PRIVILEGES covers tables created later by the role running this script.
-- Add FOR ROLE <owner> if another role creates your tables.

-- Defaults for any client that logs in as mcp_reader (psql, a BI tool, this server).
-- These are defaults, not locks: a session can SET them back. The server enforces its own.
ALTER ROLE mcp_reader SET default_transaction_read_only = on;
ALTER ROLE mcp_reader SET statement_timeout = '5s';
ALTER ROLE mcp_reader SET idle_in_transaction_session_timeout = '10s';
