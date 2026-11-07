"""Load sample data, create the read-only role, then attack each lock on its own.

Needs a THROWAWAY Postgres you are admin on. It drops and recreates the sample tables.

  export ADMIN_DATABASE_URL=postgresql://postgres:...@localhost:5432/shop
  python test_server.py
"""
import os
import sys
import time
from pathlib import Path

import anyio
import psycopg
from psycopg.conninfo import make_conninfo
from mcp import Client, StdioServerParameters

HERE = Path(__file__).parent
ADMIN_URL = os.environ["ADMIN_DATABASE_URL"]
READER_PASSWORD = os.environ.get("MCP_READER_PASSWORD", "test-only-password")
READER_URL = make_conninfo(ADMIN_URL, user="mcp_reader", password=READER_PASSWORD)
TIMEOUT_MS = 2000  # short so the test runs fast; the server default is 5000

SHAPES = [  # write attempts that are not a plain SELECT
    "DELETE FROM orders",
    "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
    "WITH x AS (SELECT 1) DELETE FROM orders",  # the query from part 1
    "SET TRANSACTION READ WRITE; DELETE FROM orders",
]
SELECT_WRITE = "SELECT purge_order(7)"  # a write that IS a plain SELECT
OUTSIDE = ["SELECT * FROM pg_shadow", "SELECT * FROM internal.payroll"]
SLOW = ["SELECT pg_sleep(10)", "SELECT set_config('statement_timeout', '0', true), pg_sleep(10)"]


def admin(sql: str) -> list:
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        cur = c.execute(sql)
        return cur.fetchall() if cur.description else []


def orders() -> int:
    return admin("SELECT count(*) FROM public.orders")[0][0]


def show(ok_blocked: bool, secs: float, sql: str, msg: str) -> int:
    print(f"{'BLOCKED' if ok_blocked else 'NOT BLOCKED'} ({secs:.1f}s): {sql}\n   -> {msg}")
    return not ok_blocked


async def via_server(client, sqls, label) -> int:
    print(f"\n--- {label}")
    misses = 0
    for sql in sqls:
        t0 = time.monotonic()
        r = await client.call_tool("run_query", {"sql": sql})
        misses += show(r.is_error, time.monotonic() - t0, sql, r.content[0].text if r.content else "")
    return misses


def direct(sqls, label) -> int:
    """Log in as mcp_reader with plain psycopg: no READ ONLY, no cursor. Only the role is left."""
    print(f"\n--- {label}")
    misses = 0
    for sql in sqls:
        t0 = time.monotonic()
        try:
            with psycopg.connect(READER_URL, autocommit=True) as c:
                msg = c.execute(sql).statusmessage
            misses += show(False, time.monotonic() - t0, sql, msg)
        except psycopg.Error as e:
            show(True, time.monotonic() - t0, sql, str(e).strip().splitlines()[0])
    return misses


async def main() -> int:
    admin((HERE / "sample_data.sql").read_text())
    admin((HERE / "setup_readonly_role.sql").read_text())
    admin(f"ALTER ROLE mcp_reader PASSWORD '{READER_PASSWORD}'")  # test only; use \password for real

    params = StdioServerParameters(
        command=sys.executable, args=[str(HERE / "server.py")],
        env={**os.environ, "DATABASE_URL": READER_URL, "STATEMENT_TIMEOUT_MS": str(TIMEOUT_MS),
             "LOG_LEVEL": "WARNING"})
    fails = 0
    async with Client(params) as client:
        print("tools:", sorted(t.name for t in (await client.list_tools()).tools))
        print("tables:", (await client.call_tool("list_tables", {})).structured_content["result"])
        cols = (await client.call_tool("describe_table", {"table": "orders"})).structured_content
        print("orders columns:", [c["name"] for c in cols["result"]])
        res = await client.read_resource("schema://tables")
        print("schema resource:", res.contents[0].text.splitlines()[0])
        r = await client.call_tool("run_query", {"sql": (
            "SELECT c.name, SUM(o.amount) AS refunded FROM orders o "
            "JOIN customers c ON c.id = o.customer_id "
            "WHERE o.status = 'refunded' GROUP BY c.name ORDER BY c.name")})
        print("refunds:", r.structured_content["result"])
        fails += r.is_error
        r = await client.call_tool("run_query", {
            "sql": "SELECT g FROM generate_series(1, 100000) g", "limit": 5000})
        n = len(r.structured_content["result"])
        print("row cap: asked for 5000, got", n)
        fails += n != 200
        r = await client.call_tool("run_query", {"sql": (
            "SELECT current_user, current_setting('transaction_read_only') AS read_only, "
            "current_setting('statement_timeout') AS timeout")})
        print("session:", r.structured_content["result"][0])

        # All locks in place.
        fails += await via_server(client, SHAPES + [SELECT_WRITE], "writes, all locks in place")
        fails += await via_server(client, OUTSIDE, "reads outside the allowlist")
        fails += await via_server(client, SLOW, f"slow queries, timeout {TIMEOUT_MS} ms")

        # Lock 1 broken on purpose: a rushed GRANT ALL. Only the transaction stands in the way.
        admin("GRANT ALL ON ALL TABLES IN SCHEMA public TO mcp_reader")
        fails += await via_server(client, [SELECT_WRITE], "lock 1 broken (role granted ALL)")
        admin("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM mcp_reader; "
              "GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_reader")

    # Lock 2 absent: any other client that logs in as the role and lifts the read-only default.
    fails += direct([
        "SET TRANSACTION READ WRITE; DELETE FROM orders",
        "SET TRANSACTION READ WRITE; " + SELECT_WRITE,
    ], "lock 2 absent (plain client as mcp_reader)")
    print("role defaults are not locks:", direct_setting())

    count = orders()
    print("\norders still in database:", count)
    fails += count != 7

    # Control: why the server uses a server-side cursor. Broken role + read_only=True +
    # plain conn.execute(sql) with no parameters, which allows several statements.
    print("\n--- control: lock 1 broken, read_only=True, plain conn.execute()")
    admin("GRANT DELETE ON public.orders TO mcp_reader")
    with psycopg.connect(READER_URL, autocommit=True) as c:
        c.read_only = True
        with c.transaction():
            c.execute("SET TRANSACTION READ WRITE; DELETE FROM orders WHERE id = 7")
    print("orders after:", orders(), "(one row deleted inside a 'read-only' transaction)")
    admin("REVOKE DELETE ON public.orders FROM mcp_reader; INSERT INTO public.orders VALUES "
          "(7, 3, 640.00, 'paid', '2026-11-02', NULL) ON CONFLICT DO NOTHING")

    print("\nALL PASSED" if fails == 0 else f"\n{fails} FAILURE(S)")
    return fails


def direct_setting() -> str:
    with psycopg.connect(READER_URL, autocommit=True) as c:
        before = c.execute("SHOW statement_timeout").fetchone()[0]
        c.execute("SET statement_timeout = 0")
        return f"statement_timeout {before} -> {c.execute('SHOW statement_timeout').fetchone()[0]}"


if __name__ == "__main__":
    sys.exit(anyio.run(main))
