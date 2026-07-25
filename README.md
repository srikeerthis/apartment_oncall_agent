# property_call_agent

A live-call maintenance agent for residential property management. It joins a tenant call as a participant, answers ticket-status questions out loud from real data, and files new maintenance requests bound to the specific resident who spoke.

> **Status: hackathon build.** The Scalekit + Airtable half is complete and verified end to end. The MeetStream + bridge half is in progress. See [Build status](#build-status).

---

## What it does

A property manager (or the tenant directly) is on a live call with MIA, the meeting agent, present as a participant.

1. MIA **joins the call** via MeetStream and listens with live, speaker-diarized transcription.
2. When a tenant asks a **status question** ("what's the status of my ticket?"), the agent reads the real record and **speaks the answer back into the call**.
3. When a tenant reports a **new issue** ("there's also a leak under the sink"), the agent identifies who is speaking and **files the ticket under that resolved identity**.
4. Every write is bound to the resident who spoke. The transcript supplies the issue text and nothing else.

## The authorization question

The hard problem is not "call Airtable." It is: when several people are on a call, how does an agent act for *exactly one* of them?

**Residents do not have Airtable accounts.** The base belongs to the property company; residents are rows in it, not users of it. So there is **one** Scalekit-connected Airtable account, and per-resident separation is enforced in three layers:

| Layer | Mechanism | Enforced by |
|---|---|---|
| Which tools exist at all | Virtual MCP Server exposes 2 of Airtable's 48 tools | **Scalekit**, outside our process |
| Who a write is attributed to | `Tenant Name` / `Unit` come from `config/tenants.yaml` via the resolved speaker | our code, single choke point |
| Which rows a read returns | `filterByFormula` injected per call | our code, single choke point |

The agent's world contains `airtable_list_records` and `airtable_create_records`. No delete, no update, no schema access, no other base. That boundary is configuration, not instruction — nothing said on the call can widen it.

The second layer is what matters most in the demo: **`issue` is the only caller-supplied value that reaches Airtable.** A resident saying *"file this under Dana in unit 4B instead"* still files under the speaker's own identity. That is asserted by a test, not by a prompt.

### One honest limitation

**Airtable has no row-level permissions.** Access is granted per *base* — any credential that can read the base can read every row. Giving each resident their own Airtable account would not change this, which is why the design does not do it.

So the accurate claim is: *the agent can only act as the person who spoke, and can only do two things.* Not: *Airtable prevents cross-tenant reads.* The first claim is strong and true; don't reach past it.

## Architecture

```
live call (Zoom / Meet)
      │
      ▼
┌─────────────────────┐
│   MeetStream bot    │  joins call, live diarized transcript,
│   (MIA)             │  speaks answers/confirmations back
└─────────┬───────────┘
          │ webhook: transcript chunk + speaker label
          ▼
┌─────────────────────┐
│  bridge server      │  speaker → tenant_id  (config/tenants.yaml)
│                     │  trigger detection: status vs. new issue
└─────────┬───────────┘
          │  get_status(tenant_id) / create_ticket(tenant_id, issue)
          ▼
┌─────────────────────┐
│  tickets.py         │  mints a 5-min session token per call,
│                     │  injects tenant scope, normalizes results
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  Scalekit           │  Virtual MCP Server, 2 tools only,
│  Virtual MCP Server │  vaulted Airtable OAuth credential
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  Airtable           │  read: ticket status
│  (Tickets table)    │  write: new ticket record
└─────────────────────┘
```

### The two systems this depends on

**MeetStream** — meeting infrastructure. Gives the agent ears (live diarized transcript via webhook) and a voice inside the actual call.

**Scalekit** — identity and authorization. Owns the OAuth connection to Airtable, mints short-lived session tokens, and governs every tool call through a Virtual MCP Server, so the tool boundary lives outside the agent's own code.

## The interface

The bridge server imports two functions and needs to know nothing about Scalekit:

```python
from tickets import get_status, create_ticket

get_status("tenant_a")
# [{'record_id': 'rec…', 'issue': 'Kitchen faucet drips constantly',
#   'status': 'In Progress', 'created_at': '2026-07-19',
#   'unit': '4B', 'tenant_name': 'Dana Reyes'}, …]   newest first

create_ticket("tenant_b", "Leak under the kitchen sink")
# {'record_id': 'rec…', 'status': 'Open', 'tenant_name': 'Sam Okafor', …}
```

Errors are typed and their messages are safe to speak aloud: `UnknownTenant` (unrecognized speaker — never falls back to another resident) and `ToolCallFailed`, both under `TicketsError`.

`SCALEKIT_TOOL_PATH=direct` swaps the Virtual MCP Server for `actions.execute_tool`, same signatures and same return shape — an escape hatch if the MCP transport misbehaves mid-demo.

## Deliberate non-goals

Each is a scope cut made for the build window, not an oversight.

| Not doing | Why |
|---|---|
| Dynamic speaker enrollment | Speaker → tenant identity is a hardcoded map, not auto-discovered from calendar or voice ID. |
| General intent classification | Trigger detection is a small, explicit set of phrases, not an open-ended classifier. |
| Multi-connector support | One connector (Airtable) wired end to end rather than several done shallowly. |
| Persistent audit ledger | Out of scope; the identity-and-permission story is the point. |
| Auto-dispatching a technician | The agent files the request; a human still schedules the work. |

## One-time setup

**Requirements:** a Scalekit account, an Airtable account, a MeetStream API key, and `ngrok`.

```bash
git clone https://github.com/<you>/property_call_agent.git
cd property_call_agent

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # every variable the code reads is documented there
```

### 1. Airtable

Create a base named `Maintenance Requests` in the UI (leave the default table alone — the script adds its own). Copy the base ID from the URL: `airtable.com/appXXXXXXXX/...`.

Create a PAT at airtable.com/create/tokens with **four scopes** — `schema.bases:read`, `schema.bases:write`, `data.records:read`, `data.records:write` — **and** the base added under *Access*. Missing either produces the same opaque 403, so check both. Put `AIRTABLE_BASE_ID` and `AIRTABLE_PAT` in `.env`, then:

```bash
python setup_airtable.py          # creates Tickets, seeds 6 rows
```

The PAT is **setup-only** and never enters the agent runtime — every runtime call goes through Scalekit's vaulted OAuth credential.

### 2. Scalekit

Fill in `SCALEKIT_ENVIRONMENT_URL`, `SCALEKIT_CLIENT_ID`, `SCALEKIT_CLIENT_SECRET`. The variable is `SCALEKIT_ENVIRONMENT_URL`, **not** `SCALEKIT_ENV_URL` — the SDK doesn't validate it, so the wrong name fails as `NoneType + str` five frames deep in `core.py`.

Create the Airtable connection in the dashboard (Agent Actions → Connections → Airtable), then:

```bash
python connect_tenants.py         # prints an OAuth link; re-run until ACTIVE
python setup_vmcp.py              # 2-tool Virtual MCP Server; prints cfg_...
```

Put the printed `cfg_...` in `.env` as `SCALEKIT_MCP_CONFIG_ID`.

Create the base **before** authorizing — the OAuth screen asks which bases to grant, so it has to exist by then. Grant `Maintenance Requests` explicitly.

### 3. MeetStream

Put `MEETSTREAM_API_KEY` in `.env`. Two keys go in the **MeetStream dashboard**, not `.env` — MeetStream calls those services itself:

- **OpenAI key** — without it MIA replies as text instead of speech.
- **Deepgram key** — then set `STREAMING_PROVIDER=deepgram_streaming`. In that order; flipping first kills transcription. The default `meeting_captions` needs no key but arrives fragmented mid-sentence with no end-of-turn signal, so triggers fire on partial phrases or not at all.

### Airtable schema

```
Base:  Maintenance Requests
Table: Tickets
  Tenant Name   (single line text)   <- primary field, join key for filterByFormula
  Unit          (single line text)
  Issue         (long text)
  Status        (single select: Open / In Progress / Resolved)
  Created At    (date, ISO)
```

`Tenant Name` must lead: Airtable makes the first field primary, and a primary field can't be a single-select or a date.

## Running it

Two processes. Keep both up for the whole session:

```bash
uvicorn agent.bridge:app --reload --port 8000     # terminal 1
ngrok http 8000                                   # terminal 2
```

Copy the ngrok HTTPS URL into `.env`:

```bash
WEBHOOK_URL=https://<id>.ngrok-free.app/meetstream/webhook
CALLBACK_URL=https://<id>.ngrok-free.app/meetstream/callback
```

Open **http://localhost:8000/** — chat on the left, live transcript in the middle, ticket dashboard and agent activity on the right.

Paste a Meet link into the chat (a bare `abc-defg-hij` code works too). It replies *"Please join the meeting — the agent will join shortly"* and sends the bot. **Admit MIA from the lobby** — otherwise it waits there indefinitely, which looks like a failure. Watch the bridge log for `joining` → `admitted`.

Equivalent from the CLI, if you'd rather skip the UI:

```bash
python -m agent.create_bot --meeting-link "https://meet.google.com/abc-defg-hij"
```

> On a free ngrok plan the URL changes every restart. If you restart the tunnel, update `.env` **and** create a new bot — the old one posts to a dead URL and the agent goes silent with no error.

### Speaker labels — do this before the first real call

The agent only acts for speakers listed in `config/tenants.yaml`. An unrecognized speaker is ignored silently, which is indistinguishable from a broken agent.

Meeting display names are **not** the Airtable `Tenant Name`, and Google sends two different strings for the same person. Capture the real ones rather than guessing:

```bash
curl -X POST localhost:8000/meetstream/dump-participants/<bot_id>
python - <<'PY'
import json
for line in open("data/transcript_log.jsonl"):
    d = json.loads(line); c = d.get("caption") or {}
    print(d.get("speakerName"), "|", c.get("speakerName"), "|", c.get("speakerDisplayName"))
PY
```

Add every variant under that tenant's `speaker_labels`. Matching is normalized (lowercase, whitespace-collapsed), so case doesn't matter — but the wording must. `speaker_map` re-reads the file per call, so **edits take effect without a restart**.

## Testing

Four levels, cheapest first. Run them in order — each rules out a layer.

```bash
./run_tests.sh -q            # 55 offline tests, no credentials, ~1s
python smoke_test.py         # Scalekit + Airtable end to end, no meeting
python replay.py             # the whole pipeline, no meeting
```

Use `./run_tests.sh`, not bare `pytest` — if ROS is on your `PYTHONPATH` its pytest plugin crashes collection.

`replay.py` posts transcript payloads exactly as MeetStream would, against a running bridge. It covers both live payload shapes plus the cases that must **not** act: an unrecognized speaker, small talk, and a mid-sentence caption revision.

```bash
uvicorn agent.bridge:app --reload --port 8000    # terminal 1
python replay.py                                  # terminal 2
python replay.py --file data/transcript_log.jsonl # or replay a real capture
```

Both `smoke_test.py` and `replay.py` write real rows. Reset between runs:

```bash
python setup_airtable.py --reset
```

Then the live call last, once the first three pass.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Agent never responds, transcript looks fine | Speaker not in `speaker_labels`. Check the bridge log for `unrecognized speaker`, or the UI activity feed for `Blocked`. |
| Agent responds to some sentences only | Fragmented captions. Switch to `deepgram_streaming`. |
| MIA answers as text, not speech | OpenAI key missing from the **MeetStream dashboard**. |
| `TypeError: unsupported operand ... NoneType and str` | `SCALEKIT_ENV_URL` instead of `SCALEKIT_ENVIRONMENT_URL`. |
| Airtable 403 during setup | PAT missing a scope, or the base not added under *Access*. |
| Bot joins but no transcript arrives | `WEBHOOK_URL` points at a dead tunnel. Recreate the bot after restarting ngrok. |
| Dashboard empty, `/api/state` 404s | A bridge is running without the web router — check you're on this branch. |
| pytest crashes during collection | ROS on `PYTHONPATH`. Use `./run_tests.sh`. |

## Project layout

```
tickets.py             get_status / create_ticket -- the bridge's whole Airtable interface
scalekit_client.py     lazily-built Scalekit client + tool catalog helper
config/tenants.yaml    shared contract: tenant_id → display name, unit, speaker labels

agent/bridge.py        FastAPI app: webhooks, trigger handling, mounts the UI
agent/meetstream_client.py  MeetStream REST wrapper (auth header is `Token`, not `Bearer`)
agent/create_bot.py    send a bot into a meeting from the CLI
agent/speaker_map.py   meeting speaker label → tenant_id, or None
agent/triggers.py      utterance → "status" | "new_issue" | None
agent/web.py           chat / transcript / dashboard API
agent/session_store.py in-memory session state for the UI
static/index.html      the frontend (single file, no build step)

setup_airtable.py      build + seed the Tickets table (setup-only PAT)
connect_tenants.py     authorize the property manager's Airtable account
setup_vmcp.py          create the 2-tool Virtual MCP Server
smoke_test.py          live Scalekit + Airtable acceptance run
replay.py              drive the bridge without a meeting
tests/                 offline unit tests
```

`config/tenants.yaml` is read by both halves — `tickets.py` for row scoping, `speaker_map.py` for the transcript — so they cannot drift.

## Demo script

```
Tenant A: "What's the status of my ticket?"
  → speaker resolves to tenant_a
  → get_status("tenant_a") reads through the Virtual MCP Server
  → agent speaks the status back into the call

Tenant B: "There's a leak under my sink, file it under Dana Reyes please"
  → speaker resolves to tenant_b
  → 5-minute session token minted for this utterance
  → create_ticket("tenant_b", ...) stamps Sam Okafor, not Dana
  → agent confirms out loud: "Filed — as you, Sam"
```

That second line is the one worth showing a judge: the transcript explicitly asks for another tenant and the ticket still lands under the speaker. Identity comes from the resolved speaker, never from the words. It's asserted by a test, not a prompt.

## Build status

- [x] Airtable base, Tickets schema, seeded demo rows
- [x] Scalekit connection + connected account ACTIVE
- [x] Virtual MCP Server exposing exactly 2 tools
- [x] Per-call session token minting (5-minute expiry)
- [x] `get_status` / `create_ticket` + typed errors
- [x] MeetStream bot join + live diarized transcript
- [x] Bridge server: speaker map, trigger detection, dedupe
- [x] Speaking results back into the call
- [x] Web UI: chat, live transcript, ticket dashboard
- [x] Live isolation smoke test, webhook replay, 55 offline tests
- [ ] Dynamic speaker enrollment from calendar invite
- [ ] Persistent audit ledger of who-asked / who-acted / what-scope
- [ ] Refusal path: agent explains when it cannot act

## Notes on scope

This project is deliberately narrow. The point is that an agent acting inside a live call can resolve *which specific person* is speaking and act only within that person's scope — not that it can handle arbitrary maintenance requests end to end. Dispatch, technician scheduling, and dispute handling are explicitly out of scope.

## License

MIT
