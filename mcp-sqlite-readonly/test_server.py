"""Talk to server.py exactly like an AI app would (over stdio), and try to break it.

Run:  python make_sample_db.py && python test_server.py
"""
import os
import sqlite3
import sys

import anyio
from mcp import Client, StdioServerParameters

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "shop.db")

ATTACKS = [
    "DELETE FROM orders",                              # stopped by the text check
    "SELECT 1; DELETE FROM orders",                    # stopped by the text check
    "WITH x AS (SELECT 1) DELETE FROM orders",         # passes the text check, stopped by mode=ro
    "WITH x AS (SELECT 1) UPDATE orders SET amount=0", # same
]


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(HERE, "server.py")],
        env={**os.environ, "SQLITE_DB": DB},
    )
    failures = 0
    async with Client(params) as client:
        tools = sorted(t.name for t in (await client.list_tools()).tools)
        print("tools:", tools)
        assert tools == ["describe_table", "list_tables", "run_query"]

        r = await client.call_tool("run_query", {"sql": (
            "SELECT c.name, SUM(o.amount) AS refunded FROM orders o "
            "JOIN customers c ON c.id = o.customer_id "
            "WHERE o.status = 'refunded' GROUP BY c.name")})
        print("refunds query ok:", not r.is_error)
        failures += r.is_error

        for sql in ATTACKS:
            r = await client.call_tool("run_query", {"sql": sql})
            msg = r.content[0].text if r.content else ""
            print(f"{'BLOCKED' if r.is_error else 'NOT BLOCKED'}: {sql}\n   -> {msg}")
            failures += not r.is_error

    count = sqlite3.connect(DB).execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    print("orders still in database:", count)
    failures += count != 7
    print("ALL PASSED" if failures == 0 else f"{failures} FAILURE(S)")
    return failures


if __name__ == "__main__":
    sys.exit(anyio.run(main))
