"""In-memory state backing the web UI.

Deliberately not a database. A demo session is one call on one machine, and the
durable record already exists in two places: data/*.jsonl for raw payloads and
Airtable for tickets. This is just what the browser needs to render.

Everything is guarded by a lock because FastAPI serves requests from a thread
pool, and the transcript is appended from webhook handlers while the UI reads it.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Any

_lock = threading.RLock()

_session: dict[str, Any] | None = None
_transcript: list[dict[str, Any]] = []
_chat: list[dict[str, Any]] = []
_activity: list[dict[str, Any]] = []

# Keep the browser payload bounded on a long call.
MAX_ENTRIES = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(store: list, entry: dict) -> dict:
    with _lock:
        entry = {"seq": len(store) + 1, "at": _now(), **entry}
        store.append(entry)
        if len(store) > MAX_ENTRIES:
            del store[: len(store) - MAX_ENTRIES]
        return entry


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------


def start_session(meeting_link: str, bot_id: str | None = None) -> dict:
    """Begin a new session. Clears prior transcript so two demo runs don't blur."""
    global _session
    with _lock:
        _transcript.clear()
        _activity.clear()
        _session = {
            "meeting_link": meeting_link,
            "bot_id": bot_id,
            "started_at": _now(),
            "status": "joining" if bot_id else "pending",
        }
        return dict(_session)


def update_session(**fields: Any) -> dict | None:
    global _session
    with _lock:
        if _session is None:
            return None
        _session.update(fields)
        return dict(_session)


def get_session() -> dict | None:
    with _lock:
        return dict(_session) if _session else None


# --------------------------------------------------------------------------
# chat
# --------------------------------------------------------------------------


def add_chat(role: str, text: str) -> dict:
    """role: "user" | "agent" | "system"."""
    return _append(_chat, {"role": role, "text": text})


def get_chat(since: int = 0) -> list[dict]:
    with _lock:
        return [e for e in _chat if e["seq"] > since]


# --------------------------------------------------------------------------
# transcript
# --------------------------------------------------------------------------

# The exact webhook shape differs by streaming provider (meeting_captions vs
# deepgram_streaming) and is not finalized, so pull the fields out defensively and
# keep the raw payload either way. A transcript line that renders as "(unparsed)"
# is a display bug; losing the payload would be a data bug.
# Confirmed shapes (see agent/bridge.py:_extract_utterance):
#   deepgram/assemblyai -> top-level "utterance" + "speakerName" + "end_of_turn"
#   meeting_captions    -> nested "caption": {"text", "speakerDisplayName"}
# The rest are defensive: providers vary and this must never drop a line.
_SPEAKER_KEYS = (
    "speakerName", "speakerDisplayName", "speaker", "speaker_name",
    "participant_name", "name", "from",
)
_TEXT_KEYS = ("utterance", "transcript", "text", "message", "content", "words")


def _first(payload: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            for nested in ("name", "text", "value"):
                if isinstance(v.get(nested), str) and v[nested].strip():
                    return v[nested].strip()
    return None


def normalize(payload: dict) -> dict:
    """Best-effort {speaker, text, bot_id} out of a webhook payload."""
    inner = payload
    for wrapper in ("caption", "data", "payload", "event", "transcript"):
        if isinstance(payload.get(wrapper), dict):
            # Envelope fields (bot_id, ...) stay available alongside the inner ones.
            inner = {**payload[wrapper], **{k: v for k, v in payload.items() if k != wrapper}}
            break

    speaker = _first(inner, _SPEAKER_KEYS)
    text = _first(inner, _TEXT_KEYS)

    if text is None and isinstance(inner.get("words"), list):
        parts = [w.get("word") or w.get("text") or "" for w in inner["words"] if isinstance(w, dict)]
        joined = " ".join(p for p in parts if p).strip()
        text = joined or None

    return {
        "speaker": speaker or "unknown",
        "text": text or "",
        "bot_id": inner.get("bot_id") or payload.get("bot_id"),
        "is_final": bool(inner.get("is_final", inner.get("end_of_turn", True))),
        "raw": payload if text is None else None,
    }


def record_transcript(payload: dict) -> dict:
    global _session
    entry = _append(_transcript, normalize(payload))
    with _lock:
        if _session is None:
            # Bot was started outside the UI (python -m agent.create_bot). Adopt
            # it rather than dropping the transcript on the floor -- note this
            # deliberately does NOT call start_session(), which clears the
            # transcript we just appended to.
            _session = {
                "meeting_link": None,
                "bot_id": entry.get("bot_id"),
                "started_at": _now(),
                "status": "in_call",
            }
        else:
            _session["status"] = "in_call"
            if entry.get("bot_id") and not _session.get("bot_id"):
                _session["bot_id"] = entry["bot_id"]
    return entry


def record_agent_reply(bot_id: str | None, text: str) -> dict:
    """MIA's own spoken line, so the browser transcript matches what the room heard."""
    return _append(
        _transcript,
        {"speaker": "MIA", "text": text, "bot_id": bot_id, "is_final": True,
         "raw": None, "is_agent": True},
    )


def get_transcript(since: int = 0) -> list[dict]:
    with _lock:
        return [e for e in _transcript if e["seq"] > since]


# --------------------------------------------------------------------------
# activity -- what the agent did, for the dashboard
# --------------------------------------------------------------------------


def add_activity(kind: str, tenant_id: str | None, detail: str, ok: bool = True) -> dict:
    """kind: "status_lookup" | "ticket_filed" | "error"."""
    return _append(_activity, {"kind": kind, "tenant_id": tenant_id, "detail": detail, "ok": ok})


def get_activity(since: int = 0) -> list[dict]:
    with _lock:
        return [e for e in _activity if e["seq"] > since]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

_MEET_LINK = re.compile(
    r"https?://(?:meet\.google\.com/[a-z0-9-]+"
    r"|[\w.-]*zoom\.us/j/[^\s]+"
    r"|teams\.microsoft\.com/[^\s]+)",
    re.I,
)


def extract_meeting_link(text: str) -> str | None:
    m = _MEET_LINK.search(text or "")
    if m:
        return m.group(0).rstrip(".,)")
    # Bare Meet code, e.g. "abc-defg-hij"
    bare = re.fullmatch(r"\s*([a-z]{3}-[a-z]{4}-[a-z]{3})\s*", text or "", re.I)
    return f"https://meet.google.com/{bare.group(1)}" if bare else None
