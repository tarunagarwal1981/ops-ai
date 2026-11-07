# ops-ai

Small, working examples for putting AI to work on real operations: code you can run in minutes, each paired with a write-up.

| Folder | What it is | Write-up |
|---|---|---|
| [`mcp-sqlite-readonly/`](mcp-sqlite-readonly/) | A read-only MCP server (~70 lines) that lets Claude answer questions from a database without ever changing it, plus a test that tries to break it | *I Tried to Trick My Own MCP Server Into Deleting a Database* |
| [`claude-code-starter/`](claude-code-starter/) | A starter `.claude/` folder: CLAUDE.md template, reviewer subagent, example skill, hooks and permissions | *The Claude Code Setup I Wish I Had on Day One* |
| [`agent-approval-gates/`](agent-approval-gates/) | Approval gates for agent tools: send, spend, sign, delete, submit need a person's yes | *How to Stop Your AI Agent From Sending, Spending or Deleting Without Asking* |
| [`claude-code-hooks/`](claude-code-hooks/) | Five Claude Code hooks: command blocker, tests before "done", desktop alert, session briefing, command log, with a 43-check test script | *5 Claude Code Hooks Worth Adding Today* |
| [`mcp-postgres-readonly/`](mcp-postgres-readonly/) | A Postgres MCP server with three independent locks (role, read-only transaction, timeout), each tested on its own | *Connect Claude to Postgres Without Giving It Write Access* |
| [`bedrock-rag-2026/`](bedrock-rag-2026/) | RAG on AWS Bedrock Knowledge Bases with S3 Vectors: cited answers, retrieve-only path, and a smoke test that checks sources | *Build a RAG Pipeline on AWS Bedrock in 2026* |
| [`local-private-ai/`](local-private-ai/) | A private AI on your laptop with Ollama: ask questions about your own files without sending them anywhere | *Run a Private AI on Your Laptop in 15 Minutes* |

## The idea running through all of them

Instructions are requests. Locks are code.

A prompt that says "never write to the database" or "never send without asking" can be talked around. A read-only connection, a hook, a deny rule or an approval gate can't. Each example here puts the rule that matters somewhere the model can't reach.

## What's here and what isn't

Methods, patterns and runnable examples are public. Production models, data and evaluation suites are not.

## Contributing

Found a way past one of the locks? A better pattern? An industry's "fifth verb"? Open an issue.

MIT licensed.
