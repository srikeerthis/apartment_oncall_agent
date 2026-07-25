"""
Thin wrapper around the MeetStream REST API.

Auth: Authorization: Token <MEETSTREAM_API_KEY>   (NOT "Bearer" — that's Scalekit's header)

Every path/shape below is confirmed against the live docs (docs.meetstream.ai),
not guessed:
  - create_bot          POST /api/v1/bots/create_bot
  - send_message         POST /api/v1/bots/{bot_id}/send_message
  - fetch_participants   GET  /api/v1/bots/{bot_id}/get_participants
  - get_bot_status       GET  /api/v1/bots/{bot_id}/status

create_bot payload notes:
  - Required: meeting_link, bot_name.
  - callback_url: bot lifecycle events (joining/lobby/admitted/left/error).
  - live_transcription_required: {"webhook_url": ...} ONLY — no provider flag
    goes in here. That's the mistake that caused the first two 400s.
  - The transcription provider is a SEPARATE block:
    recording_config.transcript.provider.<provider_name>, and MeetStream
    wants exactly one provider key per request. meeting_captions takes an
    empty object (no config needed); deepgram_streaming/assemblyai_streaming
    need a config object per the docs.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

MEETSTREAM_BASE_URL = "https://api.meetstream.ai/api/v1"

# Sane defaults for deepgram_streaming's required config fields (all of these
# are required by MeetStream's schema — see docs.meetstream.ai live-transcription guide).
DEFAULT_DEEPGRAM_STREAMING_CONFIG: dict[str, Any] = {
    "transcription_mode": "sentence",
    "model": "nova-2",
    "language": "en",
    "punctuate": True,
    "smart_format": True,
    "endpointing": 300,
    "vad_events": True,
    "utterance_end_ms": 1000,
    "encoding": "linear16",
    "channels": 1,
}

DEFAULT_ASSEMBLYAI_STREAMING_CONFIG: dict[str, Any] = {
    "transcription_mode": "raw",
    "sample_rate": 48000,
    "speech_model": "universal-streaming-english",
    "format_turns": False,
    "encoding": "pcm_s16le",
}


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
        agent_config_id: str | None = None,
        streaming_provider: str = "meeting_captions",
    ) -> dict[str, Any]:
        """Create a bot and have it join a live meeting.

        - webhook_url: where live transcript chunks + speaker labels get POSTed.
          Requires a streaming_provider to be set (see below) or MeetStream
          rejects the request with a 400.
        - callback_url: where bot lifecycle events (joining/lobby/admitted/
          left/error) get POSTed. Strongly recommended.
        - agent_config_id: only set this if you've configured a saved MIA
          agent (Approach A, native tool-calling). Leave it out for the
          bridge-server path (Approach B), which this project uses.
        - streaming_provider: one of meeting_captions (default — platform's
          native captions, no extra key needed), deepgram_streaming,
          assemblyai_streaming, jigsawstack, sarvam, meetstream. Only used if
          webhook_url is set.
        """
        payload: dict[str, Any] = {
            "meeting_link": meeting_link,
            "bot_name": bot_name,
        }
        if webhook_url:
            payload["live_transcription_required"] = {"webhook_url": webhook_url}
            payload["recording_config"] = {
                "transcript": {
                    "provider": {streaming_provider: self._provider_config(streaming_provider)}
                }
            }
        if callback_url:
            payload["callback_url"] = callback_url
        if agent_config_id:
            payload["agent_config_id"] = agent_config_id

        resp = self._client.post("/bots/create_bot", json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"MeetStream API returned {resp.status_code} for create_bot.\n"
                f"Request payload: {json.dumps(payload, indent=2)}\n"
                f"Response body: {resp.text}"
            )
        return resp.json()

    @staticmethod
    def _provider_config(streaming_provider: str) -> dict[str, Any]:
        if streaming_provider == "deepgram_streaming":
            return dict(DEFAULT_DEEPGRAM_STREAMING_CONFIG)
        if streaming_provider == "assemblyai_streaming":
            return dict(DEFAULT_ASSEMBLYAI_STREAMING_CONFIG)
        # meeting_captions and others take no config.
        return {}

    def send_message(self, bot_id: str, message: str) -> dict[str, Any]:
        """Speak `message` into the call via MIA."""
        resp = self._client.post(f"/bots/{bot_id}/send_message", json={"message": message})
        resp.raise_for_status()
        return resp.json()

    def fetch_participants(self, bot_id: str) -> list[dict[str, Any]]:
        """List call participants (used once per call to resolve names on the roster)."""
        resp = self._client.get(f"/bots/{bot_id}/get_participants")
        resp.raise_for_status()
        return resp.json()

    def get_bot_status(self, bot_id: str) -> dict[str, Any]:
        """Poll a bot's current status."""
        resp = self._client.get(f"/bots/{bot_id}/status")
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()
