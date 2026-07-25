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

## Getting started

**Requirements:** a Scalekit account, an Airtable account + base, a MeetStream API key, and `ngrok` for the bridge webhook.

```bash
git clone https://github.com/<you>/property_call_agent.git
cd property_call_agent

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # fill in the values below
```

```bash
# .env
SCALEKIT_ENVIRONMENT_URL=https://<yourorg>.scalekit.dev
SCALEKIT_CLIENT_ID=skc_...
SCALEKIT_CLIENT_SECRET=...
SCALEKIT_MCP_CONFIG_ID=cfg_...      # printed by setup_vmcp.py
AIRTABLE_BASE_ID=app...
AIRTABLE_PAT=pat...                 # SETUP ONLY -- never used at runtime
```

The Airtable PAT builds and seeds the table. It never enters the agent runtime — every runtime call uses Scalekit's vaulted OAuth credential instead. It needs four scopes (`schema.bases:read`, `schema.bases:write`, `data.records:read`, `data.records:write`) **and** the base added under the token's Access section; missing either produces the same opaque 403.

Then, in order:

```bash
python setup_airtable.py     # create Tickets table + seed 3 rows (--reset to re-seed)
python connect_tenants.py    # prints an OAuth link; re-run until ACTIVE
python setup_vmcp.py         # create the 2-tool Virtual MCP Server
python smoke_test.py         # prove it works, outside any meeting
./run_tests.sh -q            # offline unit tests
```

Create the Airtable base **before** authorizing — the OAuth consent screen asks which bases to grant, so the base has to exist by then.

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

`setup_airtable.py` creates this for you. `Tenant Name` must lead — Airtable makes the first field primary, and a primary field cannot be a single-select or a date.

## Project layout

```
tickets.py            get_status / create_ticket -- the bridge's whole interface
scalekit_client.py    lazily-built Scalekit client + tool catalog helper
config/tenants.yaml   shared contract: tenant_id → display name, unit
setup_airtable.py     build + seed the Tickets table (setup-only PAT)
connect_tenants.py    authorize the property manager's Airtable account
setup_vmcp.py         create the 2-tool Virtual MCP Server
smoke_test.py         live end-to-end acceptance run
tests/                offline unit tests
```

`config/tenants.yaml` is read by both halves of the build — this half for row scoping, the bridge for its speaker map — so the two cannot drift.

## Demo script

```
Tenant A: "What's the status of my ticket?"
  → speaker resolves to tenant_a
  → get_status("tenant_a") reads through the Virtual MCP Server
  → agent speaks the status back into the call

Tenant B: "There's also a leak under my sink."
  → speaker resolves to tenant_b
  → 5-minute session token minted for this utterance
  → create_ticket("tenant_b", "leak under my sink")
  → agent confirms out loud: "Filed — as you, Sam"
```

The moment worth showing a judge: as tenant B, say *"file this one under Dana instead."* The ticket still lands under Sam. Identity comes from the resolved speaker, never from the words.

## Build status

- [x] Airtable base, Tickets schema, seeded demo rows
- [x] Scalekit connection + connected account ACTIVE
- [x] Virtual MCP Server exposing exactly 2 tools
- [x] Per-call session token minting (5-minute expiry)
- [x] `get_status` / `create_ticket` + typed errors
- [x] Live isolation smoke test + 16 offline unit tests
- [ ] MeetStream bot join + live diarized transcript
- [ ] Bridge server: speaker map + trigger detection
- [ ] Speaking results back into the call
- [ ] Dynamic speaker enrollment from calendar invite
- [ ] Persistent audit ledger of who-asked / who-acted / what-scope
- [ ] Refusal path: agent explains when it cannot act

## Notes on scope

This project is deliberately narrow. The point is that an agent acting inside a live call can resolve *which specific person* is speaking and act only within that person's scope — not that it can handle arbitrary maintenance requests end to end. Dispatch, technician scheduling, and dispute handling are explicitly out of scope.

## License

MIT
