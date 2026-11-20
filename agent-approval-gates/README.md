# Approval gates for AI agents

Companion code for *Your AI Agent Can Now Act Without Asking. Lock These Four Words First.*

Every tool an agent can call declares a **verb**. Three lanes:

- **Go ahead**: read, compare, draft, tag, sort. Undoable, and nobody outside sees it.
- **Ask first**: **send, spend, sign, delete, submit, publish, grant.** A person approves the exact action.
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

## A cap, like a capped card

Some tools should have a hard limit that no approval can override. Give the tool an `allowed` check: here, `send_email` only accepts recipients on an allowlist. Anything else is refused before it ever reaches a person.

## When the yes comes back later

If approval goes through Slack or a ticket, the details can change while it waits. Bind the approval to the exact action:

```python
ask = request_approval(send_email, to="a@b.example", body=text)   # shows the preview, returns a fingerprint
# ...a person approves ask["preview"]...
run_approved(send_email, ask["fingerprint"], to="a@b.example", body=text)   # runs only if nothing changed
```

Change one word of the body, or the recipient, and `run_approved` refuses: the old yes no longer counts. (Suggested by a reader on r/AI_Agents.)

## Your fifth verb (and sixth, and seventh)

Regulated operations usually have one more: **submit**, as in a report, a filing or a declaration that someone else relies on.

Two more came from readers of an r/AI_Agents thread, and both are now gated in `gate.py`:

- **publish**: anything that changes what someone else relies on, like a shared doc or a setting. It looks reversible until someone has already acted on the old version.
- **grant**: anything that changes who can do what: sharing a folder, adding a user, or editing the agent's own tool list. It undoes in one click, but nobody notices it happened, so it never gets undone.

Found your industry's next verb? Open an issue.
