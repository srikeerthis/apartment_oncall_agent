"""
Create a MeetStream bot and send it into a live meeting.

Usage:
    python -m agent.create_bot --meeting-link "https://meet.google.com/xxx-xxxx-xxx"
    python -m agent.create_bot   # falls back to MEETING_LINK in .env

Requires the bridge server (agent/bridge.py) to already be running and
publicly reachable (ngrok) at WEBHOOK_URL / CALLBACK_URL, so transcript
chunks and status events have somewhere to land.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from agent.meetstream_client import MeetStreamClient

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a MeetStream bot for a live call.")
    parser.add_argument(
        "--meeting-link",
        default=os.environ.get("MEETING_LINK"),
        help="Google Meet / Zoom link (default: MEETING_LINK from .env)",
    )
    parser.add_argument(
        "--bot-name",
        default="MIA",
        help="Display name for the bot in the call (default: MIA)",
    )
    args = parser.parse_args()

    if not args.meeting_link:
        sys.exit("No meeting link. Pass --meeting-link or set MEETING_LINK in .env.")

    webhook_url = os.environ.get("WEBHOOK_URL")
    callback_url = os.environ.get("CALLBACK_URL")

    if not webhook_url:
        print("Warning: WEBHOOK_URL is not set in .env — bot will join but you won't "
              "receive live transcript chunks.", file=sys.stderr)
    if not callback_url:
        print("Warning: CALLBACK_URL is not set in .env — you won't see join/lobby/"
              "admitted status events. (See troubleshooting: 'Bot not joining · stuck "
              "in lobby' in the hackathon guide.)", file=sys.stderr)

    client = MeetStreamClient()
    try:
        result = client.create_bot(
            meeting_link=args.meeting_link,
            webhook_url=webhook_url,
            callback_url=callback_url,
            bot_name=args.bot_name,
        )
    finally:
        client.close()

    print(json.dumps(result, indent=2))
    bot_id = result.get("bot_id") or result.get("id")
    if bot_id:
        print(f"\nbot_id: {bot_id}", file=sys.stderr)
        print("Someone in the call needs to admit the bot from the lobby.", file=sys.stderr)


if __name__ == "__main__":
    main()
