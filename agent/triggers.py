"""Trigger phrase detection for tenant utterances.

An explicit keyword set, not a classifier -- see the README's "Deliberate
non-goals: General intent classification". Two categories:

  status     -- tenant is asking about an existing ticket
  new_issue  -- tenant is reporting something that needs a new ticket

classify() returns None when neither matches, which the bridge treats as
"not a trigger, take no action."

Utterances are NORMALIZED before matching, so the phrase lists below are written
one way only. Listing surface variants instead ("there's a leak" / "theres a
leak" / "there is a leak") guarantees gaps: transcription providers differ on
apostrophes, and the missing twin is silent -- the agent just never responds.
"""

from __future__ import annotations

import re

# Applied in order, on word boundaries. Expansions only -- never contractions --
# so every phrase list entry can be written in long form.
_EXPANSIONS = (
    (r"\bthere\s*'?s\b", "there is"),
    (r"\bwhat\s*'?s\b", "what is"),
    (r"\bwhere\s*'?s\b", "where is"),
    (r"\bhow\s*'?s\b", "how is"),
    (r"\bit\s*'?s\b", "it is"),
    (r"\bthat\s*'?s\b", "that is"),
    (r"\bi\s*'?d\b", "i would"),
    (r"\bi\s*'?ve\b", "i have"),
    (r"\bi\s*'?m\b", "i am"),
    (r"\bdoes\s*n\s*'?t\b", "does not"),
    (r"\bdo\s*n\s*'?t\b", "do not"),
    (r"\bis\s*n\s*'?t\b", "is not"),
    (r"\bwo\s*n\s*'?t\b", "will not"),
    (r"\bca\s*n\s*'?t\b", "cannot"),
    (r"\bhas\s*n\s*'?t\b", "has not"),
)


def normalize(text: str) -> str:
    """Lowercase, straighten smart quotes, expand contractions, collapse space."""
    t = text.lower().replace("’", "'").replace("‘", "'")
    for pattern, replacement in _EXPANSIONS:
        t = re.sub(pattern, replacement, t)
    return " ".join(t.split())


# Checked FIRST: a status question ("is my ticket still broken") must not fall
# through to a new_issue match on "broken".
_STATUS_PHRASES = (
    "status of my ticket",
    "status of the ticket",
    "status on my ticket",
    "what is the status",
    "what is happening with my ticket",
    "any update",
    "any updates",
    "check my ticket",
    "check on my ticket",
    "where is my ticket",
    "my ticket status",
    "how is my ticket",
    "is my ticket",
    "did my ticket",
    "has my ticket",
    "open tickets",
    "my tickets",
    "my requests",
)

_NEW_ISSUE_PHRASES = (
    # explicit asks
    "i would like to report",
    "i want to report",
    "i need to report",
    "can you file",
    "please file",
    "file a ticket",
    "file this",
    "raise a ticket",
    "raise a request",
    "raise a service request",
    "service request",
    "maintenance request",
    "put in a request",
    "open a ticket",
    "new issue",
    "new request",
    # natural reports
    "there is a leak",
    "there is also",
    "there is a problem",
    "there is an issue",
    "i also have",
    "i have a problem",
    "i have an issue",
    "is broken",
    "is leaking",
    "is clogged",
    "will not turn on",
    "will not work",
    "stopped working",
    "not working",
    "does not work",
    "is not working",
)


def classify(text: str | None) -> str | None:
    """text -> "status" | "new_issue" | None."""
    if not text:
        return None
    normalized = normalize(text)
    if any(phrase in normalized for phrase in _STATUS_PHRASES):
        return "status"
    if any(phrase in normalized for phrase in _NEW_ISSUE_PHRASES):
        return "new_issue"
    return None
