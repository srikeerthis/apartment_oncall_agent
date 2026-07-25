"""Trigger phrase detection for tenant utterances.

An explicit keyword set, not a classifier -- see the README's "Deliberate
non-goals: General intent classification". Two categories:

  status     -- tenant is asking about an existing ticket
  new_issue  -- tenant is reporting something that needs a new ticket

classify() returns None when neither matches, which the bridge treats as
"not a trigger, take no action."
"""

from __future__ import annotations

# Checked first: a status question ("is it still broken") shouldn't fall
# through to a new_issue match on "broken".
_STATUS_PHRASES = (
    "status of my ticket",
    "status of the ticket",
    "what's the status",
    "whats the status",
    "any update on my ticket",
    "any updates on my ticket",
    "check my ticket",
    "check on my ticket",
    "where's my ticket",
    "wheres my ticket",
    "my ticket status",
)

_NEW_ISSUE_PHRASES = (
    "there's also",
    "theres also",
    "there is also",
    "i also have",
    "i'd like to report",
    "id like to report",
    "i want to report",
    "i need to report",
    "there's a leak",
    "theres a leak",
    "there's a problem",
    "theres a problem",
    "can you file",
    "please file",
    "file a ticket",
    "file this",
    "new issue",
    "also broken",
    "is broken",
    "is leaking",
    "stopped working",
    "not working",
)


def classify(text: str | None) -> str | None:
    """text -> "status" | "new_issue" | None."""
    if not text:
        return None
    lowered = text.lower()
    if any(phrase in lowered for phrase in _STATUS_PHRASES):
        return "status"
    if any(phrase in lowered for phrase in _NEW_ISSUE_PHRASES):
        return "new_issue"
    return None
