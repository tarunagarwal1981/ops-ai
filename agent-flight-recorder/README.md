# agent-flight-recorder

**What has your Claude Code agent actually been doing on your machine?**

If you let an agent run commands for hours, most of it scrolls past. You approve some things, an allow rule approves the rest, and you find out later when something breaks.

Claude Code already saves every session on your computer. This tool reads those files and shows you the calls worth a second look. It runs locally, uploads nothing, and needs only Python 3.9+.

```bash
python recorder.py --demo          # see the report on a made-up history
python recorder.py                 # run it on your own sessions
python recorder.py --html report.html
python recorder.py --since 14      # last two weeks only
```

## What it shows

- **Risky commands:** `rm -rf`, force push, push to main, hard reset, `curl | sh`, `sudo`, `chmod 777`, `DROP TABLE` through a database client, `kill -9`, package publish, `terraform destroy`.
- **Secret files:** `.env`, `~/.aws`, `~/.ssh`, `*.pem`, `.npmrc` and similar, opened through Read or through commands like `cat` and `grep`. `.env.example` is ignored.
- **Edits outside the project folder.**
- **Who approved each call:** you clicked yes, or an allow rule did.
- **Your deny rules, replayed:** how many of those past calls your current deny rules would have blocked, and how many would have gone straight through.
- **Order of events:** if a session opened a secret file and later made a network call, it tells you. That is the order to check, not proof of a leak.
- **Session names:** every finding shows the session it came from (Claude Code's own name, plus your first prompt), so you can find it again.
- **What to do about it:** a copy-paste `deny` block for the findings you have, skipping rules you already have. It replays those rules on your own history and tells you how many past calls they would have stopped, and which spellings they miss. For things text rules can't stop (pipes, databases, branch pushes) it names the real lock instead.
- **Cost:** per session.

Likely secrets in commands (AWS keys, `sk-...`, `ghp_...`, `password=...`, passwords inside URLs) are masked in the output, so you can share a report without leaking them.

Example, from the demo:

```
7 calls worth a look:
     1  force push
     1  rm with -r/-f
     1  reads a secret-looking file
     1  pipe download into shell
     ...
5 of those ran without a click from you (an allow rule or auto mode approved them).
```

## How it avoids crying wolf

Early versions flagged far too much, so it now:

- ignores text written into files through heredocs (a README that says "never run rm -rf" is not a command)
- ignores `rm -rf` on build leftovers like `__pycache__`, `node_modules`, `dist`
- counts `DROP TABLE` only when a database client is in the command
- marks matches that sit inside quotes (often a test or an `echo`) and lists them last

## Limits, so you can trust it

- The log records what the agent was **asked to run**. A script it wrote and then ran can do more than its command line shows. Read this as "what to look at", not a full audit.
- Detection is pattern matching. It will miss unusual spellings and will sometimes flag something harmless.
- It matches on the logged command *string*, not on parsed arguments. It separates four contexts: a command that runs, text written to a file by a heredoc (ignored), text inside quotes that is only text (flagged and marked "quoted", listed last), and the payload of `bash -c`, `sh -c`, `eval`, `ssh host "..."` or a heredoc fed to a shell (these run, so they count as real). The tests in `test_recorder.py` ("synthetic corpus") pin each case. What it still cannot see: a command built from variables or a script file the agent wrote and then ran.
- The "approved by rule / you / hook" label is read from the approval field Claude Code writes in the log. It is not replayed. Only the deny-rule check is a replay.
- The deny-rule replay is an approximation of Claude Code's matching, not the real engine. It checks your rules against the logged command text.
- Transcript format can change between Claude Code versions. If a field is missing, that part shows as unknown instead of failing.
- Cost comes from the totals Claude Code records. Treat it as approximate.

## What to do with the result

A flagged call that an allow rule approved is a rule you may want to tighten. A flagged call your deny rules would **not** have blocked is the gap. Ready-made rules and tests are in [`claude-code-hooks`](../claude-code-hooks), and the lock-versus-request idea behind it is in [`agent-approval-gates`](../agent-approval-gates).

## Tests

```bash
python test_recorder.py   # builds fake transcripts, no real data
```

If it saved you from a surprise, a star on the repo helps other people find it.
