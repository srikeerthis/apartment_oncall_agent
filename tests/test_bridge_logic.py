"""Offline tests for the bridge's decision logic: triggers and speaker mapping.

No network, no MeetStream, no Airtable. These are the two places where a silent
wrong answer is expensive -- an unmatched trigger means the agent just never
responds, and a wrong speaker match means a ticket filed against the wrong
resident.

    ./run_tests.sh -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.speaker_map import resolve  # noqa: E402
from agent.triggers import classify, normalize  # noqa: E402


# --- normalization ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("There's a leak", "there is a leak"),
        ("There’s a leak", "there is a leak"),  # smart apostrophe
        ("theres a leak", "there is a leak"),
        ("What's the status", "what is the status"),
        ("It doesn't work", "it does not work"),
        ("  MIXED   Case  ", "mixed case"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


# --- status trigger --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "What's the status of my ticket?",
        "Whats the status of my ticket",
        "What is the status of my ticket",
        "Any update on my ticket?",
        "Can you check my ticket",
        "Where's my ticket",
        "How is my ticket doing",
    ],
)
def test_status_phrases(text):
    assert classify(text) == "status"


# --- new issue trigger -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "There's a leak under my sink",
        "There is a leak under my sink",       # the variant that used to miss
        "Theres a leak under my sink",
        "There’s a leak under my sink",
        "There's also a problem with the heater",
        "I'd like to report a broken window",
        "I want to report a broken window",
        "The radiator stopped working",
        "The dishwasher is not working",
        "The disposal doesn't work",
        "Please file a ticket for the hallway light",
        "My bathroom fan is broken",
    ],
)
def test_new_issue_phrases(text):
    assert classify(text) == "new_issue"


# --- neither ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["Nice weather today", "Hello, can you hear me?", "", None, "   "],
)
def test_no_trigger(text):
    assert classify(text) is None


def test_status_wins_over_new_issue():
    # Contains "is broken" but is plainly a status question -- must not file a
    # duplicate ticket for something already on record.
    assert classify("What's the status of my ticket, is it still broken?") == "status"


# --- speaker mapping -------------------------------------------------------


def test_known_speakers_resolve():
    assert resolve("Dana Reyes") == "tenant_a"
    assert resolve("Sam Okafor") == "tenant_b"


@pytest.mark.parametrize("label", ["dana reyes", "DANA REYES", "  Dana   Reyes  "])
def test_speaker_matching_is_normalized(label):
    assert resolve(label) == "tenant_a"


@pytest.mark.parametrize("label", ["Random Person", "", None, "Dana Reyes Jr"])
def test_unknown_speaker_returns_none_never_a_guess(label):
    # A misfiled ticket is worse than a missed one.
    assert resolve(label) is None
