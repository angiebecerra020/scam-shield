"""
test_consent_calls.py

Tests for REAL_CONSENT_CALLS: the senior's "press 1 to say YES" call can be a
real phone call on the live demo site, while everything else stays demo.

How it fits in: we swap Twilio for a pretend one, so no real phone rings.
"""

from app import calls, consent


class PretendTwilio:
    """Remembers the calls we asked Twilio to make, instead of making them."""

    def __init__(self):
        self.placed = []
        self.calls = self

    def create(self, **details):
        self.placed.append(details)


ROSA = {"id": "abc", "senior_phone": "+15555550142"}


def test_demo_mode_still_never_calls_by_default(monkeypatch):
    """With only DEMO_MODE on, the consent call just goes in the demo log."""
    monkeypatch.setenv("REAL_CONSENT_CALLS", "false")
    twilio = PretendTwilio()
    monkeypatch.setattr(consent, "twilio_client", lambda: twilio)

    consent.call_senior_for_consent(ROSA)

    assert twilio.placed == []
    assert calls.DEMO_CALL_LOG[-1]["who"] == "consent"


def test_real_consent_calls_ring_the_senior_in_demo_mode(monkeypatch):
    """With REAL_CONSENT_CALLS on, the senior's phone really rings, even in demo mode."""
    monkeypatch.setenv("REAL_CONSENT_CALLS", "true")
    twilio = PretendTwilio()
    monkeypatch.setattr(consent, "twilio_client", lambda: twilio)

    consent.call_senior_for_consent(ROSA)

    assert twilio.placed[0]["to"] == "+15555550142"
    assert "/twilio/consent-call?enrollment_id=abc" in twilio.placed[0]["url"]
