"""
Webhook receiver for the MeetStream bot.

Run:
    uvicorn agent.bridge:app --reload --port 8000
    ngrok http 8000

Then point .env's WEBHOOK_URL / CALLBACK_URL at the ngrok https URL
(e.g. https://abcd1234.ngrok-free.app/meetstream/webhook) and create a bot
with agent/create_bot.py.

Right now this just listens, logs, and can speak back — no Scalekit/Airtable
wiring yet (that's the merge step, once the partner's get_status/create_ticket
functions are ready). Every raw payload also gets appended to data/*.jsonl so
the exact JSON shape can be shared with the partner.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request

from agent.meetstream_client import MeetStreamClient

load_dotenv()

app = FastAPI(title="property_call_agent bridge")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
TRANSCRIPT_LOG = DATA_DIR / "transcript_log.jsonl"
CALLBACK_LOG = DATA_DIR / "callback_log.jsonl"


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    record = {"logged_at": datetime.now(timezone.utc).isoformat(), **record}
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/meetstream/webhook")
async def on_transcript(request: Request) -> dict[str, str]:
    """Live transcript chunk + speaker label, one call per utterance.

    Shape isn't finalized until we see a real payload — logging the raw body
    is the point here. Once confirmed, drop the exact JSON in the partner
    deliverable notes (README / shared doc) and tighten this into a typed
    model.
    """
    payload = await request.json()
    print(f"[transcript] {json.dumps(payload)[:300]}")
    _append_jsonl(TRANSCRIPT_LOG, payload)

    # Placeholder for the merge step: speaker -> tenant lookup + trigger
    # detection + Scalekit call go here once agent/speaker_map.py and
    # agent/triggers.py exist and the partner's get_status/create_ticket
    # functions are ready.

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
