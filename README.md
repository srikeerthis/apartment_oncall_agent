# apartment_oncall_agent

An on-call agent for residential rentals. Residents text it; it answers from the community rule book, drafts maintenance work orders, and routes anything it shouldn't touch to a human.

> **Status: early.** The retrieval and triage layers work. Scheduling is draft-only by design — see [Deliberate non-goals](#deliberate-non-goals).

---

## What it does

A resident sends a message. The agent:

1. Runs a **safety gate** before any model call. Gas, flooding, no heat, electrical, sewage backup, smoke → page a human immediately, no LLM in the path.
2. **Triages** the surviving message into one of four buckets: question, maintenance request, non-maintenance complaint, or human-only.
3. **Answers** questions from the community rule book, always with a citation to the clause it relied on.
4. **Drafts a work order** for maintenance requests — extracting unit, category, severity, entry permission, and availability — and checks it against open tickets before writing.
5. **Escalates** disputes, neighbor conflicts, and anything involving safety between residents to the property manager, untouched.

A human dispatcher confirms every work order before it reaches a technician's schedule.

## Deliberate non-goals

These are choices, not gaps. Each one is here because getting it wrong is worse than not doing it.

| Not doing | Why |
|---|---|
| Auto-scheduling technicians | Scheduling is constrained optimization — skill match, parts, geography, resident windows. The labor is in intake and triage; dispatch stays human. |
| Deciding who pays for a repair | Normal wear vs. resident misuse is a money determination with dispute risk. The agent records and cites; a human rules. |
| Answering in the register of legal advice | Residential tenancy is state- and city-specific. "Your lease says X, §7.3" is safe. "You're entitled to X" is not. |
| Handling harassment, threats, or discrimination claims | Straight to a human. The agent does not process these at all. |
| Troubleshooting emergencies with the resident | The safety gate fires first and cannot be reasoned around. |

## Architecture

```
resident message
      │
      ▼
┌─────────────────┐   emergency
│  safety gate    │──────────────▶ page on-call human
│  (pre-model)    │
└────────┬────────┘
         ▼
┌─────────────────┐
│     triage      │
└────────┬────────┘
         │
   ┌─────┼─────────────────┬──────────────────────┐
   ▼     ▼                 ▼                      ▼
answer   work order      manager only        human-only
(cited)  (draft)         (disputes)          (safety)
   │        │
   │        ▼
   │   dedupe check ──▶ dispatcher confirms ──▶ schedule write
   ▼
resident
```

### Authorization model

The hard problem here is not retrieval, it's scoping. A resident in 4B must be able to reach their own lease and the building rules, and must be structurally incapable of reaching 4C's anything.

Enforcement is a **metadata pre-filter on the vector query**, not a prompt instruction:

```python
retriever.search(
    query=embed(message),
    filter={"$or": [
        {"scope": "shared"},
        {"scope": "unit", "unit_id": session.unit_id},
    ]},
)
```

Documents outside that filter are never candidates. A system prompt saying "do not reveal other residents' information" is a suggestion, not an access control.

Three zones:

- **shared** — community rules, amenity policy, maintenance process. Same for every resident.
- **unit** — lease, ledger, work order history. Scoped to the requesting unit.
- **excluded** — other units, owner financials, vendor contracts, arrears reports. Never indexed into the resident-facing store at all.

### The rule book is two documents

These get conflated constantly and shouldn't be.

**`config/community_rules/`** — lease terms and community policy. Quiet hours, pet policy, guest rules, parking, and responsibility allocation. Retrieved and cited. Read-only to the agent.

**`config/runbook.yaml`** — the on-call SOP. Severity definitions, SLA per category, after-hours paging, and what the agent may resolve without a human. This is what makes it an *on-call* agent rather than a chatbot.

It lives in version control and is meant to be edited by the property manager, not by whoever owns the prompt:

```yaml
severities:
  emergency:
    triggers: [gas, flooding, no_heat_winter, electrical, sewage, smoke]
    action: page_human
    bypass_model: true
    sla_minutes: 15
  urgent:
    triggers: [no_hot_water, refrigerator_out, ac_out_heat_advisory, sole_toilet]
    action: draft_work_order
    sla_hours: 24
  routine:
    triggers: [dripping_faucet, blind_broken, cabinet_hinge, light_fixture]
    action: draft_work_order
    sla_days: 5

entry:
  notice_hours_required: 24
  emergency_exempt: true

escalate_to_manager:
  - noise_complaint
  - neighbor_dispute
  - parking_dispute
  - lease_violation_report
```

## MCP tools

The write side is exposed as an MCP server. Every tool is narrow, validated, and idempotent.

| Tool | Access | Notes |
|---|---|---|
| `search_rules` | read | Scoped to shared + requesting unit. Returns text with clause citations. |
| `get_unit_context` | read | Lease dates, balance, open tickets for the requesting unit only. |
| `check_open_orders` | read | Dedupe lookup by unit + category + open status. |
| `create_work_order` | write | Requires `dedupe_key`. Draft status only — never dispatches. |
| `propose_slot` | write | Respects `entry.notice_hours_required`. Proposal, not a booking. |
| `notify_resident` | write | Status updates on existing tickets. |
| `page_human` | write | Bypasses everything. Called by the safety gate, not by the model. |

`create_work_order` takes a client-supplied `dedupe_key` so a retried call cannot double-book. Every write carries the resident's original message and the agent's reasoning as an audit trail.

### Deduplication

The failure mode that actually bites: a resident reports a leak Monday, again Tuesday when nobody came, again Wednesday, angry. Three work orders, three dispatches, one confused technician.

Matching is on `(unit_id, category, status=open)` within a configurable window. On a match, the agent responds with a status update on the existing ticket rather than creating a new one — which is also the cheapest resident-satisfaction win in the product.

## Getting started

**Requirements:** Python 3.11+, PostgreSQL 15+ with `pgvector`, an Anthropic API key.

```bash
git clone https://github.com/<you>/apartment_oncall_agent.git
cd apartment_oncall_agent

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env      # fill in the values below
```

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://localhost:5432/oncall
TWILIO_ACCOUNT_SID=...            # SMS intake
TWILIO_AUTH_TOKEN=...
ONCALL_PAGER_NUMBER=+1...         # where the safety gate pages
```

Seed a demo building and index the rule book:

```bash
alembic upgrade head
python -m oncall.seed --building demo        # units, residents, a mock PMS
python -m oncall.index config/community_rules/
```

Run the API and the MCP server:

```bash
uvicorn oncall.api:app --reload           # intake webhook, :8000
python -m oncall.mcp_server               # MCP tools, :8081
```

Try it without SMS:

```bash
python -m oncall.cli --unit 4B "there's water coming from under the sink"
python -m oncall.cli --unit 4B "am I allowed to have a cat?"
python -m oncall.cli --unit 4B "the people upstairs are so loud"
```

The three should route to a work order draft, a cited answer, and a manager escalation respectively.

## Project layout

```
oncall/
  gate.py            safety gate — keyword + classifier, runs before any model call
  triage.py          four-bucket classifier
  retrieval.py       scoped vector search, citation extraction
  extract.py         structured work order fields from free text
  dedupe.py          open-ticket matching
  mcp_server.py      MCP tool definitions
  api.py             intake webhook
  cli.py             local harness
config/
  runbook.yaml       on-call SOP — severity, SLA, escalation
  community_rules/   lease and policy documents
evals/
  gate_cases.yaml    emergency phrasings that must never reach the model
  triage_cases.yaml  labeled routing set
tests/
```

## Evaluation

The gate and the triage classifier have their own test sets, and they are not optional. `evals/gate_cases.yaml` holds emergency phrasings — including indirect ones ("it smells weird in the kitchen", "the radiator's been cold since Friday") — that must route to `page_human`. A gate regression is the only failure in this system that can hurt someone.

```bash
pytest evals/ -v
python -m oncall.eval --report
```

Triage is scored on routing accuracy per bucket, with recall on `manager_only` and `emergency` weighted far above precision. A false escalation costs someone thirty seconds. A missed one costs much more.

## Roadmap

- [x] Scoped retrieval with clause citations
- [x] Safety gate with pre-model bypass
- [x] Four-bucket triage
- [x] Work order drafting with dedupe
- [ ] Dispatcher review UI
- [ ] Real PMS connectors (Buildium, AppFolio) — API access is partner-gated
- [ ] Multilingual intake
- [ ] Photo attachment handling for maintenance reports

## Notes on safety

This system talks to residents about their housing. Two things are worth restating:

The safety gate runs on keywords and a classifier **before** the model sees the message, and it fails open to a human. If the gate is uncertain, it pages. An agent that helpfully troubleshoots a gas leak is the single worst outcome this codebase can produce.

Entry scheduling respects statutory notice. Most jurisdictions require 24 hours' notice before non-emergency entry, and many leases restate it. Entry permission is a required field on every work order, not an afterthought — a slot proposed without it is a lease violation created on the landlord's behalf.

## License

MIT
