# ops-ai

**Small, working examples for making AI agents safe to run on real operations.** Each one is a few dozen lines, has a test that tries to break it, and comes with a short write-up. No frameworks, mostly standard library.

Try one in 30 seconds:

```bash
git clone https://github.com/tarunagarwal1981/ops-ai && cd ops-ai/agent-idempotency
python demo.py   # a naive retry sends 2 emails; the wrapper sends 1
```

**Start here:**
- [`agent-approval-gates/`](agent-approval-gates/): the agent can draft, but a person has to say yes before it sends, spends or deletes
- [`agent-idempotency/`](agent-idempotency/): a timed-out tool call can't turn into a duplicate email, refund or order
- [`claude-code-hooks/`](claude-code-hooks/): six hooks that stop Claude Code from skipping tests or running `rm -rf`

**Want the full library version?** [`safeact`](https://github.com/tarunagarwal1981/safeact) is the safety checkpoint every AI action passes through: checked, held when unsure, exactly-once, provable. The approval-gate and idempotency folders here are the small, readable versions of those ideas.

| Folder | What it is | Write-up |
|---|---|---|
| [`mcp-sqlite-readonly/`](mcp-sqlite-readonly/) | A read-only MCP server (~70 lines) that lets Claude answer questions from a database without ever changing it, plus a test that tries to break it | [*I Tried to Trick My Own MCP Server Into Deleting a Database*](https://pub.towardsai.net/i-tried-to-trick-my-own-mcp-server-into-deleting-a-database-the-filter-failed-7197ca5550fa) |
| [`claude-code-starter/`](claude-code-starter/) | A starter `.claude/` folder: CLAUDE.md template, reviewer subagent, example skill, hooks and permissions | [*The Claude Code Setup I Wish I Had on Day One*](https://pub.towardsai.net/the-claude-code-setup-i-wish-i-had-on-day-one-14157454a8ce) |
| [`agent-approval-gates/`](agent-approval-gates/) | Approval gates for agent tools: send, spend, sign, delete, submit need a person's yes | [*How to Stop Your AI Agent From Sending, Spending or Deleting Without Asking*](https://medium.com/p/a1416de3d8a4) |
| [`agent-idempotency/`](agent-idempotency/) | Safe retries for agent tool calls: code-made keys, a SQLite ledger, and a check before re-running anything in doubt | *coming soon* |
| [`claude-code-hooks/`](claude-code-hooks/) | Six Claude Code hooks (command blocker, secret scan, tests before "done", desktop alert, session briefing, command log), a deny rule tested against shell bypasses, and a 52-check test script | [*5 Claude Code Hooks Worth Adding Today*](https://levelup.gitconnected.com/5-claude-code-hooks-worth-adding-today-fcda93caae45) |
| [`mcp-postgres-readonly/`](mcp-postgres-readonly/) | A Postgres MCP server with three independent locks (role, read-only transaction, timeout), each tested on its own | [*Connect Claude to Postgres Without Giving It Write Access*](https://pub.towardsai.net/connect-claude-to-postgres-without-giving-it-write-access-fbe70cb66187) |
| [`bedrock-rag-2026/`](bedrock-rag-2026/) | RAG on AWS Bedrock Knowledge Bases with S3 Vectors: cited answers, retrieve-only path, and a smoke test that checks sources | *Build a RAG Pipeline on AWS Bedrock in 2026* |
| [`local-private-ai/`](local-private-ai/) | A private AI on your laptop with Ollama: ask questions about your own files without sending them anywhere | *Run a Private AI on Your Laptop in 15 Minutes* |

**Using Claude Code?** Everything in [`claude-code-hooks/`](claude-code-hooks/) is free to copy. There's also a free [one-page cheat sheet](https://tarunagarwal.gumroad.com/l/claude-code-free) of what to type. The [Claude Code Starter Kit](https://tarunagarwal.gumroad.com/l/claude-code-starter-kit) is the full version of `claude-code-starter/` and `claude-code-hooks/`: a one-command installer, 10 tested hooks, 5 subagents and 5 CLAUDE.md templates. Everything in this repo stays free.

## The idea running through all of them

Instructions are requests. Locks are code.

A prompt that says "never write to the database" or "never send without asking" can be talked around. A read-only connection, a hook, a deny rule or an approval gate can't. Each example here puts the rule that matters somewhere the model can't reach.

## What's here and what isn't

Methods, patterns and runnable examples are public. Production models, data and evaluation suites are not.

## Contributing

Found a way past one of the locks? A better pattern? An industry's "fifth verb"? Open an issue.

MIT licensed.

If something here saved you time, a ⭐ on the repo helps other people find it.
