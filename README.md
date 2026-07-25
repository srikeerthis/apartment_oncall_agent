# property_call_agent

A live-call maintenance agent for residential property management. It joins a tenant call as a participant, answers ticket-status questions out loud from real data, and files new maintenance requests — acting as the specific tenant who asked, not as a shared service account.

> **Status: hackathon build.** Scoped for a single demo path: one live call, two known tenants, one connector. Not a general-purpose triage system — see [Deliberate non-goals](#deliberate-non-goals).

---

## What it does

A property manager (or the tenant directly) is on a live call with MIA, the meeting agent, present as a participant.

1. MIA **joins the call** via MeetStream and listens with live, speaker-diarized transcription.
2. When a tenant asks a **status question** ("what's the status of my ticket?"), the agent reads the real record and **speaks the answer back into the call**.
3. When a tenant reports a **new issue** ("there's also a leak under the sink"), the agent identifies who's speaking, resolves their identity through Scalekit, and **files the ticket under their own account** — not a generic bot identity.
4. Every write is scoped to the tenant who asked for it. The agent cannot act as, or see the tickets of, anyone else on the call.

## Deliberate non-goals

Each of these is a scope cut made for the build window, not an oversight.

| Not doing | Why |
|---|---|
| Dynamic speaker enrollment | Speaker → tenant identity is a hardcoded map for the demo, not auto-discovered from calendar or voice ID. |
| General intent classification | Trigger detection is a small, explicit set of phrases/keywords, not an open-ended classifier. |
| Multi-connector support | One connector (Airtable) is wired end-to-end rather than several done shallowly. |
| Persistent audit ledger / postmortem generation | Out of scope for the demo; the identity-and-permission story is the point, not reporting. |
| Auto-dispatching a technician | The agent files the request; a human still schedules the work. |

## Architecture

```
live call (Zoom / Meet)
      │
      ▼
┌────────────────────┐
│   MeetStream bot    │  joins call, live diarized transcript,
│   (MIA)             │  speaks answers/confirmations back
└─────────┬───────────┘
          │ webhook: transcript chunk + speaker label
          ▼
┌────────────────────┐
│  bridge server      │  speaker → tenant identity map
│  (your glue code)   │  trigger detection: status vs. new issue
└─────────┬───────────┘
          │
          ▼
┌────────────────────┐
│     Scalekit        │  mint short-lived session token
│  Virtual MCP Server │  scoped to that tenant's connected account
└─────────┬───────────┘
          │
          ▼
┌────────────────────┐
│     Airtable        │  read: ticket status
│  (Tickets table)    │  write: new ticket record
└────────────────────┘
```

### Authorization model

The hard problem is not "call Airtable," it's scoping: a tenant on the call must be able to check or create *their own* ticket, and must be structurally incapable of touching anyone else's.

Enforcement happens at the identity layer, not the prompt layer:

- Each tenant has their **own** Scalekit-connected Airtable account, authorized once ahead of time.
- Right before any tool call, the bridge server mints a **session token scoped to the specific tenant who spoke** (`create_session_token`, short expiry, per-utterance).
- The Virtual MCP Server only exposes `list_records` / `create_record` on the Tickets table — nothing else in the base is reachable.
- A tenant's token can only resolve to their own identity. There is no shared or admin token in the request path — "acting as the tenant" is enforced by which token exists, not by an instruction telling the model to behave.

### The two systems this depends on

**MeetStream** — meeting infrastructure. Gives the agent ears (live diarized transcript via webhook) and a voice (`send_message` / MIA speech) inside the actual call. Also used once per call to resolve participant names via `fetch_participants`.

**Scalekit** — identity and authorization. Owns the per-tenant OAuth connection to Airtable, mints the short-lived per-tenant session tokens, and governs every tool call through a single Virtual MCP Server so scope enforcement lives outside the agent's own code.

## MCP tools

Exposed through Scalekit's Virtual MCP Server, backed by one Airtable connection.

| Tool | Access | Notes |
|---|---|---|
| `list_records` | read | Filtered to the requesting tenant's rows only; returns ticket status. |
| `create_record` | write | Inserts a new ticket under the calling tenant's identity; no cross-tenant write path exists. |

## Getting started

**Requirements:** a MeetStream account + API key, a Scalekit account, an Airtable base, `ngrok` (or any public webhook URL) for local testing.

```bash
git clone https://github.com/<you>/property_call_agent.git
cd property_call_agent

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # fill in the values below
```

```bash
# .env
MEETSTREAM_API_KEY=...
SCALEKIT_CLIENT_ID=skc_...
SCALEKIT_CLIENT_SECRET=...
SCALEKIT_ENV_URL=https://yourorg.scalekit.com
AIRTABLE_BASE_ID=...
AIRTABLE_CONNECTION_NAME=...
WEBHOOK_URL=https://<your-ngrok-subdomain>.ngrok.io/meetstream/webhook
```

Set up the Airtable base:

```
Base:  Maintenance Requests
Table: Tickets
  Tenant Name   (text)
  Unit          (text)
  Issue         (text)
  Status        (single select: Open / In Progress / Resolved)
  Created At    (date)
```

Seed two or three fake tickets so status lookups have something real to return.

Connect two test tenants in Scalekit (**AgentKit → Connected Accounts**), confirm both show `ACTIVE`, then create the Virtual MCP Server exposing only `list_records` and `create_record`.

Run the bridge server and start a bot:

```bash
uvicorn agent.bridge:app --reload           # webhook receiver, :8000
python -m agent.create_bot --meeting-link "https://meet.google.com/..."
```

## Project layout

```
agent/
  bridge.py           webhook receiver + orchestration loop
  speaker_map.py       hardcoded speaker → tenant identity lookup
  triggers.py          status-question / new-issue detection
  scalekit_client.py   session token minting + Virtual MCP calls
  create_bot.py        MeetStream bot creation helper
config/
  speaker_map.yaml     tenant name → Scalekit identifier
tests/
```

## Demo script

```
Tenant A: "What's the status of my ticket?"
  → agent resolves speaker → tenant A
  → reads ticket via Scalekit-governed Airtable call
  → speaks the status back into the call

Tenant B: "There's also a leak under my sink."
  → agent resolves speaker → tenant B
  → mints a session token scoped to tenant B only
  → creates a new ticket as tenant B
  → confirms out loud: "Filed — as you, [tenant B]"
```

## Roadmap

- [x] MeetStream bot join + live diarized transcript
- [x] Hardcoded speaker → tenant identity map
- [x] Status-check path (read)
- [x] New-ticket path (write, per-tenant identity)
- [ ] Dynamic speaker enrollment from calendar invite
- [ ] Persistent audit ledger of who-asked / who-acted / what-scope
- [ ] Additional connectors (Linear, Jira) alongside Airtable
- [ ] Refusal path: agent explains when a tenant lacks permission for a requested action

## Notes on scope

This project is deliberately narrow. The point being demonstrated is that an agent acting inside a live call can resolve *which specific person* is speaking and act only within their own permissions — not that it can handle arbitrary maintenance requests end to end. Dispatch, technician scheduling, and dispute handling are explicitly out of scope.

## License

MIT