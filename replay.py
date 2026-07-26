"""Drive the bridge without a live meeting.

Posts transcript payloads at a running bridge server exactly as MeetStream would,
so the whole path -- speaker resolution, triggers, Scalekit, Airtable, the UI --
can be exercised before spending time in a real call.

    uvicorn agent.bridge:app --reload --port 8000     # in one terminal
    python replay.py                                  # in another
    python replay.py --file data/transcript_log.jsonl # replay a real capture

Writes real rows to Airtable. Run `python setup_airtable.py --reset` afterwards.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import requests

# Both live shapes, plus the cases that must NOT act.
SCRIPT = [
    (
        "Dana asks for status (deepgram shape)",
        {
            "bot_id": "bot_replay",
            "speakerName": "Dana Reyes",
            "utterance": "What's the status of my ticket?",
            "end_of_turn": True,
        },
    ),
    (
        "Sam reports an issue AND names another tenant (caption shape)",
        {
            "bot_id": "bot_replay",
            "caption": {
                "speakerDisplayName": "Sam Okafor",
                "text": "There is a leak under my sink, file it under Dana Reyes please",
            },
        },
    ),
    (
        "Unrecognized speaker -- must be ignored",
        {
            "bot_id": "bot_replay",
            "speakerName": "Random Guest",
            "utterance": "there is a leak in my ceiling",
            "end_of_turn": True,
        },
    ),
    (
        "Small talk -- must not trigger",
        {
            "bot_id": "bot_replay",
            "speakerName": "Dana Reyes",
            "utterance": "Thanks, that's great to hear.",
            "end_of_turn": True,
        },
    ),
    (
        "Mid-sentence caption revision -- must be skipped, not acted on twice",
        {
            "bot_id": "bot_replay",
            "speakerName": "Dana Reyes",
            "utterance": "there is a leak",
            "end_of_turn": False,
        },
    ),
]


def post(base: str, payload: dict) -> int:
    r = requests.post(f"{base}/meetstream/webhook", json=payload, timeout=30)
    return r.status_code


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000", help="bridge base URL")
    ap.add_argument("--file", help="replay a captured .jsonl instead of the built-in script")
    ap.add_argument("--delay", type=float, default=6.0, help="seconds between utterances")
    args = ap.parse_args()

    try:
        requests.get(f"{args.base}/health", timeout=5).raise_for_status()
    except Exception as e:
        sys.exit(f"No bridge at {args.base} ({type(e).__name__}). Start uvicorn first.")

    if args.file:
        with open(args.file) as f:
            payloads = [(f"line {i}", json.loads(line)) for i, line in enumerate(f, 1) if line.strip()]
    else:
        payloads = SCRIPT

    for label, payload in payloads:
        print(f"\n▸ {label}")
        print(f"  -> {post(args.base, payload)}")
        time.sleep(args.delay)

    print(
        f"\nDone. Check the UI at {args.base}/ , or:\n"
        f"  curl -s {args.base}/api/state | python -m json.tool\n"
        "Then reset demo data with: python setup_airtable.py --reset"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
