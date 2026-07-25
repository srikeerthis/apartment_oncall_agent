"""
Thin wrapper around the MeetStream REST API.

Auth: Authorization: Token <MEETSTREAM_API_KEY>   (NOT "Bearer" — that's Scalekit's header)

Confirmed against the hackathon integration guide:
  - create_bot     POST /api/v1/bots/create_bot
  - send_message   POST /api/v1/bots/{bot_id}/send_message

Not given verbatim in the guide — paths below are best-effort based on MeetStream's
REST conventions. If either 404s, check https://docs.meetstream.ai (or run
`/plugin install meetstream` in Claude Code and ask it — the plugin is
live-tested against the real API) and fix the path here in one place:
  - fetch_participants
  - get_bot_status
"""

from __future__ import annotations

import os
from typing import Any

import httpx

MEETSTREAM_BASE_URL = "https://api.meetstream.ai/api/v1"


class MeetStreamClient:
    def __init__(self, api_key: str | None = None, base_url: str = MEETSTREAM_BASE_URL):
        self.api_key = api_key or os.environ["MEETSTREAM_API_KEY"]
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Token {self.api_key}"},
            timeout=30.0,
        )

    def create_bot(
        self,
        meeting_link: str,
        webhook_url: str | None = None,
        callback_url: str | None = None,
        bot_name: str = "MIA",
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a bot and have it join a live meeting.

        - webhook_url: where live transcript chunks + speaker labels get POSTed
          (live_transcription_required). Use this for the "listen" path.
        - callback_url: where bot status events (joining/lobby/admitted/left) get
          POSTed. Strongly recommended — otherwise you're guessing why a bot is
          stuck in the lobby.
        - agent_id: only set this if you've configured a saved MIA agent
          (Approach A, native tool-calling). Leave it out for the bridge-server
          path (Approach B), which this project uses.
        """
        payload: dict[str, Any] = {
            "meeting_link": meeting_link,
            "bot_name": bot_name,
        }
        if webhook_url:
            payload["live_transcription_required"] = {"webhook_url": webhook_url}
        if callback_url:
            payload["callback_url"] = callback_url
        if agent_id:
            payload["agent_id"] = agent_id

        resp = self._client.post("/bots/create_bot", json=payload)
        resp.raise_for_status()
        return resp.json()

    def send_message(self, bot_id: str, message: str) -> dict[str, Any]:
        """Speak `message` into the call via MIA."""
        resp = self._client.post(f"/bots/{bot_id}/send_message", json={"message": message})
        resp.raise_for_status()
        return resp.json()

    def fetch_participants(self, bot_id: str) -> dict[str, Any]:
        """List call participants (used once per call to resolve names on the roster).

        Path unverified against live docs — check docs.meetstream.ai if this 404s.
        """
        resp = self._client.get(f"/bots/{bot_id}/participants")
        resp.raise_for_status()
        return resp.json()

    def get_bot_status(self, bot_id: str) -> dict[str, Any]:
        """Poll a bot's current status (joining / in_call / left / error).

        Path unverified against live docs — check docs.meetstream.ai if this 404s.
        """
        resp = self._client.get(f"/bots/{bot_id}")
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()
