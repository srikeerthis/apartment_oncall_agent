"""Meeting speaker label -> tenant_id resolution.

MeetStream reports whatever a participant's Google/Zoom account displays
("Sam Okafor", "sam okafor", "Sam's iPhone") -- that's a different string
from the Airtable "Tenant Name" join key in tickets.py, so this is a
separate lookup, not a reuse of display_name.

Never guesses: an unrecognized speaker resolves to None, not the closest
match. A misfiled ticket is worse than a missed one.
"""

from __future__ import annotations

import os

import yaml

TENANTS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "tenants.yaml")


def _normalize(label: str) -> str:
    return " ".join(label.strip().lower().split())


def _load_labels() -> dict[str, str]:
    with open(TENANTS_PATH) as f:
        config = yaml.safe_load(f)

    labels: dict[str, str] = {}
    for tenant_id, tenant in config["tenants"].items():
        for label in tenant.get("speaker_labels", []):
            labels[_normalize(label)] = tenant_id
    return labels


def resolve(speaker_label: str | None) -> str | None:
    """MeetStream's speakerName/speakerDisplayName -> tenant_id, or None if
    the speaker isn't a recognized resident. Reloads tenants.yaml per call --
    the file is tiny and this keeps config edits live without a restart."""
    if not speaker_label:
        return None
    return _load_labels().get(_normalize(speaker_label))
