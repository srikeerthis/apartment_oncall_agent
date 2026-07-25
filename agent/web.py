"""Web UI: chat to start a call, live transcript, ticket dashboard.

Mounted by agent/bridge.py. Kept in its own router so the bridge's webhook
handling and this stay out of each other's way.

    uvicorn agent.bridge:app --reload --port 8000
    open http://localhost:8000/

NOTE ON THE DASHBOARD: it shows every tenant's tickets, which is correct and not
a contradiction of the isolation story -- this is the property manager's own view
of their own base. The scoped path is what the AGENT does per utterance: resolve
one speaker, read only their rows, write only as them. Two different viewers with
two different legitimate scopes.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Body
from fastapi.responses import FileResponse, JSONResponse

from agent import session_store as store

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
TENANTS_PATH = Path(__file__).resolve().parent.parent / "config" / "tenants.yaml"

JOIN_REPLY = "Please join the meeting — the agent will join shortly."


def _roster() -> dict[str, Any]:
    with open(TENANTS_PATH) as f:
        return yaml.safe_load(f)["tenants"]


@router.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.post("/api/chat")
async def chat(body: dict = Body(...)) -> dict:
    """One turn of the setup chat. A message containing a meeting link starts a
    session and sends the bot; anything else gets a nudge for the link."""
    message = (body.get("message") or "").strip()
    if not message:
        return {"ok": False, "error": "empty message"}

    store.add_chat("user", message)

    link = store.extract_meeting_link(message)
    if not link:
        store.add_chat(
            "agent",
            "Send me the Google Meet link for the call and I'll have MIA join "
            "(a bare code like abc-defg-hij works too).",
        )
        return {"ok": True}

    store.start_session(link)
    store.add_chat("agent", JOIN_REPLY)

    # Bot creation is a blocking HTTP call; keep it off the event loop.
    try:
        bot = await asyncio.to_thread(_create_bot, link)
    except Exception as e:  # surfaced into the chat, not a 500
        store.update_session(status="error")
        store.add_chat(
            "system",
            f"MIA could not join: {type(e).__name__}: {str(e)[:400]}",
        )
        return {"ok": False, "error": str(e)}

    bot_id = bot.get("bot_id") or bot.get("id")
    store.update_session(bot_id=bot_id, status="joining")
    store.add_chat("system", f"Bot created ({bot_id}). Admit MIA from the meeting lobby.")
    return {"ok": True, "bot_id": bot_id}


def _create_bot(meeting_link: str) -> dict:
    from agent.meetstream_client import MeetStreamClient

    client = MeetStreamClient()
    try:
        return client.create_bot(
            meeting_link=meeting_link,
            webhook_url=os.environ.get("WEBHOOK_URL"),
            callback_url=os.environ.get("CALLBACK_URL"),
            streaming_provider=os.environ.get("STREAMING_PROVIDER", "meeting_captions"),
        )
    finally:
        client.close()


@router.get("/api/state")
async def state(chat_since: int = 0, transcript_since: int = 0, activity_since: int = 0) -> dict:
    """Everything the UI needs per tick, incremental via cursors."""
    return {
        "session": store.get_session(),
        "chat": store.get_chat(chat_since),
        "transcript": store.get_transcript(transcript_since),
        "activity": store.get_activity(activity_since),
    }


@router.get("/api/tickets")
async def tickets() -> JSONResponse:
    """Every tenant's tickets, for the property manager's dashboard.

    Polled less often than /api/state -- each tenant is a separate Airtable round
    trip through the Virtual MCP Server.
    """
    result = await asyncio.to_thread(_fetch_all_tickets)
    return JSONResponse(result)


def _fetch_all_tickets() -> dict:
    from tickets import TicketsError, get_status

    rows: list[dict] = []
    errors: list[str] = []
    for tenant_id, cfg in _roster().items():
        try:
            for t in get_status(tenant_id):
                rows.append({**t, "tenant_id": tenant_id})
        except TicketsError as e:
            errors.append(f"{tenant_id}: {e}")
        except Exception as e:
            errors.append(f"{tenant_id}: {type(e).__name__}: {e}")

    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("status") or "Unknown"] = counts.get(r.get("status") or "Unknown", 0) + 1

    return {
        "tickets": rows,
        "counts": counts,
        "total": len(rows),
        "tenants": {tid: c.get("display_name") for tid, c in _roster().items()},
        "errors": errors,
    }


@router.post("/api/session/end")
async def end_session() -> dict:
    store.update_session(status="ended")
    store.add_chat("system", "Session ended.")
    return {"ok": True}
