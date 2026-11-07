# Approval gates for AI agents

Companion code for *Your AI Agent Can Now Act Without Asking. Lock These Four Words First.*

Every tool an agent can call declares a **verb**. Three lanes:

- **Go ahead**: read, compare, draft, tag, sort. Undoable, and nobody outside sees it.
- **Ask first**: **send, spend, sign, delete, submit.** A person approves the exact action.
- **Never**: trading securities, moving money between accounts, getting into someone else's account. Refused even with approval.

The test for any new verb: *Can I undo it? Does anyone outside see it?* If "no" and "yes", it's gated.

## Run it

```bash
python test_gate.py   # ALL PASSED
python gate.py        # interactive: draft runs, send and pay ask you first
```

No dependencies. Python 3.10+.

## The point

The rule lives in `run_tool`, the only path from the model to a side effect, not in the prompt. "Never send without asking" in a prompt is a request a model can be talked out of. A gate in code is a door that stays shut until a person opens it.

Two habits that keep gates useful:

- **Gate few things.** Forty approvals a day trains people to click "approve" without reading.
- **Show the exact action.** "Send this email, to this person, with this text" gets a real decision. "Proceed?" gets a reflex. That's what `describe` is for.

## Your fifth verb

Regulated operations usually have one more: **submit**, as in a report, a filing or a declaration that someone else relies on. Found your industry's fifth verb? Open an issue.
