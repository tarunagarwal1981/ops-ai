"""Read-only SQLite MCP server (mcp SDK 2.x)."""
import os
import sqlite3

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

DB_PATH = os.environ.get("SQLITE_DB", "shop.db")
MAX_ROWS = 200
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=False)

mcp = MCPServer("sqlite-readonly")


def connect() -> sqlite3.Connection:
    # mode=ro: SQLite itself refuses writes, whatever SQL arrives.
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@mcp.tool(annotations=READ_ONLY)
def list_tables() -> list[str]:
    """List the user tables in the database."""
    with connect() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                            "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    return [r["name"] for r in rows]


@mcp.tool(annotations=READ_ONLY)
def describe_table(table: str) -> list[dict]:
    """Return column name, type, nullability and primary-key flag for one table."""
    if table not in list_tables():
        raise ToolError(f"Unknown table: {table}")
    with connect() as conn:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [{"name": r["name"], "type": r["type"],
             "notnull": bool(r["notnull"]), "pk": bool(r["pk"])} for r in rows]


@mcp.tool(annotations=READ_ONLY)
def run_query(sql: str, limit: int = 50) -> list[dict]:
    """Run a single read-only SELECT (or WITH ... SELECT). Returns at most `limit` rows (max 200)."""
    stmt = sql.strip().rstrip(";")
    if ";" in stmt or not stmt.lower().startswith(("select", "with")):
        raise ToolError("Only a single SELECT statement is allowed.")
    try:
        with connect() as conn:
            rows = conn.execute(stmt).fetchmany(max(1, min(limit, MAX_ROWS)))
    except sqlite3.Error as e:  # includes "attempt to write a readonly database"
        raise ToolError(f"SQLite error: {e}")
    return [dict(r) for r in rows]


@mcp.resource("schema://tables")
def schema() -> str:
    """CREATE statements for every table, so the model can read the schema up front."""
    with connect() as conn:
        rows = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                            "AND sql IS NOT NULL").fetchall()
    return "\n\n".join(r["sql"] for r in rows)


if __name__ == "__main__":
    mcp.run()  # stdio by default; or mcp.run(transport="streamable-http", port=8000)
