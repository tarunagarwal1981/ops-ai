# Read-only Postgres MCP server

Lets Claude (or any MCP app) answer questions from a Postgres database without being able to change it, and without being able to run a query that never ends. About 90 lines of Python.

Companion code for part 2 of the MCP series, *Connect Claude to Postgres Without Giving It Write Access*. Part 1 (SQLite) is in [`../mcp-sqlite-readonly`](../mcp-sqlite-readonly).

## Three locks, each tested on its own

1. **Role.** The server logs in as `mcp_reader`, which has `SELECT` on the allowlisted schema and nothing else (`setup_readonly_role.sql`).
2. **Transaction.** Every call runs inside `BEGIN READ ONLY`, through a server-side cursor. The cursor means the query is exactly one statement, and Postgres only accepts `SELECT` or `VALUES` there, so the query cannot run `SET TRANSACTION READ WRITE` first.
3. **Timeout.** Every connection sets `statement_timeout`, so a slow `SELECT` is cancelled.

Plus: a 200-row cap (only that many rows leave the server), a schema allowlist for discovery and `search_path`, and a fresh connection per call so no session settings carry over.

The role-level `default_transaction_read_only` and `statement_timeout` in the setup script are *defaults* for other clients. Any session can `SET` them back. They are not locks.

## Tools

- `list_tables()`: allowed tables as `schema.table`
- `describe_table(table)`: column name, type, nullable
- `run_query(sql, limit=50)`: one `SELECT`, at most 200 rows
- `schema://tables` (resource): every allowed table with its columns

## Run the test (5 minutes)

You need a **throwaway** Postgres you are admin on. The test drops and recreates the sample tables.

```bash
cd mcp-postgres-readonly
uv sync                           # or: pip install "mcp[cli]>=2.3,<3" "psycopg[binary]>=3.2,<4"
export ADMIN_DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/shop
uv run test_server.py
```

No Postgres handy? `docker run --rm -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=shop -p 5432:5432 postgres:16` works.

The test loads `sample_data.sql`, runs `setup_readonly_role.sql`, starts `server.py` over stdio as `mcp_reader`, and attacks it. Expected output (trimmed):

```
--- writes, all locks in place
BLOCKED (0.0s): WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x
   -> ... DECLARE CURSOR must not contain data-modifying statements in WITH
BLOCKED (0.0s): SET TRANSACTION READ WRITE; DELETE FROM orders
   -> ... syntax error at or near "SET"
BLOCKED (0.0s): SELECT purge_order(7)
   -> ... cannot execute DELETE in a read-only transaction

--- reads outside the allowlist
BLOCKED (0.0s): SELECT * FROM internal.payroll
   -> ... permission denied for schema internal

--- slow queries, timeout 2000 ms
BLOCKED (2.0s): SELECT set_config('statement_timeout', '0', true), pg_sleep(10)
   -> ... canceling statement due to statement timeout

--- lock 1 broken (role granted ALL)
BLOCKED (0.0s): SELECT purge_order(7)
   -> ... cannot execute DELETE in a read-only transaction

--- lock 2 absent (plain client as mcp_reader)
BLOCKED (0.0s): SET TRANSACTION READ WRITE; DELETE FROM orders
   -> permission denied for table orders

orders still in database: 7

--- control: lock 1 broken, read_only=True, plain conn.execute()
orders after: 6 (one row deleted inside a 'read-only' transaction)

ALL PASSED
```

The control at the end is the reason for the server-side cursor. With psycopg's `read_only = True` and a plain `conn.execute(sql)` (no parameters), psycopg allows several statements in one string, and `SET TRANSACTION READ WRITE; DELETE ...` switches the transaction back before the `DELETE` runs. The test puts the row back afterwards.

## Use it on a real database

1. As an admin, run `psql "$ADMIN_URL" -f setup_readonly_role.sql`, then `psql "$ADMIN_URL" -c '\password mcp_reader'`. Edit the schema lines first if you allow more than `public`.
2. Point it at a **read replica** if you have one.
3. Copy `.env.example` to `.env` and fill in `DATABASE_URL` for `mcp_reader`. Never commit `.env`.

**Claude Code:**

```bash
claude mcp add --transport stdio --scope local shopdb \
  --env DATABASE_URL="postgresql://mcp_reader:...@host:5432/shop" \
  -- uv run --directory /full/path/to/mcp-postgres-readonly server.py
```

Use `--scope local` (your machine only) so the connection string stays out of the repository. `--scope project` writes it into `.mcp.json`.

**Claude Desktop:** Settings → Developer → Edit Config:

```json
{
  "mcpServers": {
    "shopdb": {
      "command": "uv",
      "args": ["--directory", "/full/path/to/mcp-postgres-readonly", "run", "server.py"],
      "env": { "DATABASE_URL": "postgresql://mcp_reader:...@host:5432/shop" }
    }
  }
}
```

## Limits

- Read-only is not "safe to read". Whatever `mcp_reader` can `SELECT`, the model can see. Grant only the tables it needs; use views or row-level security for anything finer.
- Table *names* still leak. `pg_catalog` is readable by every role: `mcp_reader` can see that `internal.payroll` exists, though not what is in it.
- A fresh connection per call costs a few milliseconds locally, more over the network. If you add a pool, reset the session between calls: a query like `SELECT set_config('statement_timeout', '0', false)` survives the commit, and the next call would inherit it.
- `statement_timeout` applies per statement, and the server sends `DECLARE` and `FETCH` as two statements. The query itself runs during `FETCH`, which is what the timeout cancels in the test.
- A read-only transaction blocks writes to tables, not every side effect. Functions that reach outside the database (`dblink`, file access) are governed by the role's privileges, so keep `mcp_reader` out of roles like `pg_read_server_files`.

Found a query that gets past all three? Open an issue.
