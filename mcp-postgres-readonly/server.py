"""Read-only Postgres MCP server (mcp SDK 2.x, psycopg 3).

Three independent locks:
  1. Role         - DATABASE_URL logs in as a role with SELECT grants only (setup_readonly_role.sql)
  2. Transaction  - every call runs in BEGIN READ ONLY, through a server-side cursor, so the
                    query is one statement and cannot switch the transaction back to read-write
  3. Timeout      - statement_timeout on every connection, so a slow SELECT is cancelled
"""
import os
import sys

import psycopg
from psycopg.rows import dict_row
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

DATABASE_URL = os.environ.get("DATABASE_URL")  # e.g. postgresql://mcp_reader:...@host/db
if not DATABASE_URL:
    sys.exit("Set DATABASE_URL (see .env.example). Use the read-only role, never an admin.")
SCHEMAS = [s.strip() for s in os.environ.get("ALLOWED_SCHEMAS", "public").split(",") if s.strip()]
TIMEOUT_MS = int(os.environ.get("STATEMENT_TIMEOUT_MS", "5000"))
MAX_ROWS = 200
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=False)

mcp = MCPServer("postgres-readonly", log_level=os.environ.get("LOG_LEVEL", "INFO"))  # logs go to stderr


def connect() -> psycopg.Connection:
    """A fresh connection per call: no session state carries over from one query to the next."""
    conn = psycopg.connect(
        DATABASE_URL,
        autocommit=True,  # we open explicit transactions below
        row_factory=dict_row,
        connect_timeout=5,
        application_name="mcp-postgres-readonly",  # shows up in pg_stat_activity
        options=f"-c statement_timeout={TIMEOUT_MS} -c search_path={','.join(SCHEMAS)}",  # lock 3
    )
    conn.read_only = True  # lock 2: psycopg starts every transaction with BEGIN READ ONLY
    return conn


def fetch(sql: str, params=None, limit: int = MAX_ROWS) -> list[dict]:
    """Run one query in a read-only transaction and return at most `limit` rows."""
    try:
        with connect() as conn, conn.transaction():
            # A named (server-side) cursor sends DECLARE ... CURSOR FOR <sql> over the extended
            # protocol: exactly one statement, and Postgres only accepts SELECT or VALUES there.
            with conn.cursor(name="mcp_query") as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchmany(limit)]  # only `limit` rows leave the server
    except psycopg.Error as e:
        raise ToolError(f"Postgres error: {str(e).strip().splitlines()[0]}")


@mcp.tool(annotations=READ_ONLY)
def list_tables() -> list[str]:
    """List the tables you may query, as schema.table."""
    rows = fetch("SELECT table_schema || '.' || table_name AS t FROM information_schema.tables "
                 "WHERE table_schema = ANY(%s) ORDER BY 1", [SCHEMAS])
    return [r["t"] for r in rows]


@mcp.tool(annotations=READ_ONLY)
def describe_table(table: str) -> list[dict]:
    """Columns of one table (give it as schema.table or just table): name, type, nullable."""
    schema, _, name = table.rpartition(".")
    schema = schema or SCHEMAS[0]
    if f"{schema}.{name}" not in list_tables():
        raise ToolError(f"Unknown or not allowed table: {table}")
    return fetch("SELECT column_name AS name, data_type AS type, is_nullable = 'YES' AS nullable "
                 "FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                 "ORDER BY ordinal_position", [schema, name])


@mcp.tool(annotations=READ_ONLY)
def run_query(sql: str, limit: int = 50) -> list[dict]:
    """Run one read-only SELECT. Returns at most `limit` rows (max 200). Slow queries are cancelled."""
    return fetch(sql.strip().rstrip(";"), limit=max(1, min(limit, MAX_ROWS)))


@mcp.resource("schema://tables")
def schema() -> str:
    """Every allowed table with its columns, so the model can write correct SQL first time."""
    rows = fetch("SELECT table_schema || '.' || table_name AS t, "
                 "string_agg(column_name || ' ' || data_type, ', ' ORDER BY ordinal_position) AS cols "
                 "FROM information_schema.columns WHERE table_schema = ANY(%s) GROUP BY 1 ORDER BY 1",
                 [SCHEMAS])
    return "\n".join(f"{r['t']}({r['cols']})" for r in rows)


if __name__ == "__main__":
    mcp.run()  # stdio
