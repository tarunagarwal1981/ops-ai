# Safe retries for agent tool calls

Agents retry. A tool call times out, the loop tries again, and the vendor gets two emails, the customer two refunds, the warehouse two orders. The first call often *did* work; only the reply got lost.

This is a small ledger that makes a retry safe. Python 3.10+, standard library only (SQLite).

## Run it

```bash
python test_idempotent.py   # ALL PASSED
python demo.py              # naive retry sends 2 emails, call_once sends 1
```

## How it works

1. **The code makes the key, not the model.** `make_key` hashes the tool name plus the sorted payload. Same call, same key. A model-written key changes with every retry, which defeats the point.
2. **Write "started" before the call, "done" after.** The insert is atomic, so two workers can't both claim the same key.
3. **"Started but never done" means in doubt.** It may have run. Don't re-run it blind. Ask the outside world first (`already_happened`: "is there an email with this key in the outbox?"). If yes, record it and move on. If no, run it.
4. **No way to check? Stop.** An in-doubt call is reported, not re-run. A person decides.
5. **A clean failure frees the key.** If nothing happened, retrying is safe.

## Limits

- Your tool has to accept the key and the outside system has to be searchable by it (most payment and email APIs take an idempotency key or a reference). If it can't, step 4 is the best you can do.
- One SQLite file is fine for one agent process. For many workers, put the same table in Postgres.
- This guards against duplicates, not wrong calls. Pair it with an [approval gate](../agent-approval-gates/) for the verbs that matter.
