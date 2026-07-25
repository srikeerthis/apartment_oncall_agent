"""
Webhook receiver for the MeetStream bot.

Run:
    uvicorn agent.bridge:app --reload --port 8000
    ngrok http 8000

Then point .env's WEBHOOK_URL / CALLBACK_URL at the ngrok https URL
(e.g. https://abcd1234.ngrok-free.app/meetstream/webhook) and create a bot
with agent/create_bot.py.

on_transcript resolves the speaker, checks for a trigger phrase, calls
tickets.get_status/create_ticket, and speaks the result back into the call.
Every raw payload also gets appended to data/*.jsonl.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request

import tickets
from agent.meetstream_client import MeetStreamClient
from agent.speaker_map import resolve as resolve_speaker
from agent.triggers import classify

load_dotenv()

app = FastAPI(title="property_call_agent bridge")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
TRANSCRIPT_LOG = DATA_DIR / "transcript_log.jsonl"
CALLBACK_LOG = DATA_DIR / "callback_log.jsonl"

# Recently-handled (bot_id, speaker, text) triples. MeetStream may retry a
# webhook it considers slow; this stops a retry (or an accidental duplicate
# delivery) from filing the same ticket twice.
_RECENT = deque(maxlen=200)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    record = {"logged_at": datetime.now(timezone.utc).isoformat(), **record}
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _extract_utterance(payload: dict[str, Any]) -> tuple[str, str] | None:
    """(speaker_label, text) for a complete utterance, or None if this
    payload isn't one (a mid-sentence caption revision, an empty turn, ...).

    Two shapes depending on STREAMING_PROVIDER:
      - deepgram/assemblyai streaming: top-level "utterance" + "end_of_turn"
        (MeetStreamClient always requests transcription_mode="sentence", so
        this already arrives as one complete sentence per call).
      - meeting_captions: nested under "caption".
    """
    if "utterance" in payload:
        if not payload.get("end_of_turn", True):
            return None
        text = (payload.get("utterance") or "").strip()
        speaker = payload.get("speakerName") or ""
        return (speaker, text) if text else None

    caption = payload.get("caption")
    if caption:
        text = (caption.get("text") or "").strip()
        speaker = caption.get("speakerDisplayName") or caption.get("speakerName") or ""
        return (speaker, text) if text else None

    return None


def _dedupe(key: tuple[str, str, str]) -> bool:
    """True if `key` was already handled recently."""
    if key in _RECENT:
        return True
    _RECENT.append(key)
    return False


def _status_message(tickets_list: list[dict[str, Any]]) -> str:
    if not tickets_list:
        return "You don't have any tickets on file right now."
    latest = tickets_list[0]
    return f"Your most recent ticket — {latest['issue']} — is {latest['status']}."


async def _handle_utterance(bot_id: str, speaker_label: str, text: str) -> None:
    """Runs after the webhook response is already sent, so a slow Airtable
    round trip can't make MeetStream think the webhook is unhealthy."""
    trigger = classify(text)
    if trigger is None:
        return

    tenant_id = resolve_speaker(speaker_label)
    if tenant_id is None:
        print(f"[trigger] unrecognized speaker {speaker_label!r}, ignoring")
        return

    try:
        if trigger == "status":
            tickets_list = await asyncio.to_thread(tickets.get_status, tenant_id)
            message = _status_message(tickets_list)
        else:
            ticket = await asyncio.to_thread(tickets.create_ticket, tenant_id, text)
            message = f"Filed — as you, {ticket['tenant_name'].split()[0]}."
    except tickets.TicketsError as e:
        # TicketsError messages are written to be spoken aloud as-is.
        message = str(e)
    except Exception as e:
        print(f"[trigger] unexpected error handling utterance: {e!r}")
        return

    print(f"[trigger] {trigger} for {speaker_label!r} -> {tenant_id}: {message!r}")

    client = MeetStreamClient()
    try:
        await asyncio.to_thread(client.send_message, bot_id, message)
    except Exception as e:
        print(f"[trigger] failed to speak result: {e!r}")
    finally:
        client.close()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/meetstream/webhook")
async def on_transcript(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Live transcript chunk + speaker label, one call per utterance."""
    payload = await request.json()
    print(f"[transcript] {json.dumps(payload)[:300]}")
    _append_jsonl(TRANSCRIPT_LOG, payload)

    bot_id = payload.get("bot_id")
    extracted = _extract_utterance(payload)
    if bot_id and extracted is not None:
        speaker_label, text = extracted
        if not _dedupe((bot_id, speaker_label, text)):
            background_tasks.add_task(_handle_utterance, bot_id, speaker_label, text)

    return {"status": "received"}


@app.post("/meetstream/callback")
async def on_bot_status(request: Request) -> dict[str, str]:
    """Bot lifecycle events: joining / waiting_room / in_call / left / error."""
    payload = await request.json()
    print(f"[status] {json.dumps(payload)[:300]}")
    _append_jsonl(CALLBACK_LOG, payload)
    return {"status": "received"}


@app.post("/meetstream/dump-participants/{bot_id}")
async def dump_participants(bot_id: str) -> dict[str, Any]:
    """Manual trigger: fetch the participant roster for a live bot and save it
    to data/participants_sample.json — this is the other half of the
    deliverable to share with the partner (exact shape of fetch_participants).
    """
    client = MeetStreamClient()
    try:
        result = client.fetch_participants(bot_id)
    finally:
        client.close()

    (DATA_DIR / "participants_sample.json").write_text(json.dumps(result, indent=2))
    return result


@app.post("/meetstream/speak/{bot_id}")
async def speak(bot_id: str, body: dict[str, str]) -> dict[str, Any]:
    """Manual trigger to test MIA's voice: {"message": "..."} -> spoken into the call."""
    client = MeetStreamClient()
    try:
        result = client.send_message(bot_id, body["message"])
    finally:
        client.close()
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("agent.bridge:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
