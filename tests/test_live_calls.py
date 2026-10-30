"""
test_live_calls.py

Tests for real protected calls (app/live_calls.py): a call forwarded from a
senior who said YES gets the protected flow with live transcription, every
sentence is scored, and the family gets the alert by email.

How it fits in: we pretend to be Twilio (signed requests), Nemotron and
Tavily are pretend, and emails land in a list. Demo mode is on, so no real
phone rings.
"""

import json

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app import call_monitor, detector, email_alerts, live_calls, phone_line, research, storage
from app.main import app

client = TestClient(app)

TOKEN = "test-auth-token"
GRANDMA = "+15555550142"
SCAMMER = "+15555550199"

SCAM = {
    "risk_score": 91,
    "verdict": "likely_scam",
    "reasons": ["Claims to be a grandson in trouble", "Asks for gift cards"],
    "claimed_identity": "grandson Danny",
    "family_alert_message": "The caller says they are grandson Danny and wants gift cards.",
}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    """Test token, pretend Gmail, pretend AI, and a clean slate."""
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("GMAIL_ADDRESS", "scamshield.test@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd")
    monkeypatch.setenv("REAL_CALLS", "false")
    monkeypatch.setenv("REAL_CONSENT_CALLS", "false")
    monkeypatch.setattr(detector, "score_call", lambda transcript, language="en", client=None: dict(SCAM))
    monkeypatch.setattr(
        research,
        "research_call",
        lambda phone, result: {"caller": {"sources": [], "reported_as_scam": False}, "news": {"sources": []}},
    )
    call_monitor.ALERTED_CALL_IDS.clear()
    call_monitor.RESEARCH_BY_CALL_ID.clear()
    live_calls.LINES.clear()
    live_calls.CHECKED.clear()
    phone_line.CALLS_BY_PHONE.clear()


@pytest.fixture
def inbox(monkeypatch):
    """Catches emails instead of sending them."""
    sent = []
    monkeypatch.setattr(email_alerts, "deliver", sent.append)
    return sent


def twilio_post(path: str, form: dict):
    """Sends a request signed like Twilio's."""
    signature = RequestValidator(TOKEN).compute_signature("http://testserver" + path, form)
    return client.post(path, data=form, headers={"X-Twilio-Signature": signature})


def save_grandma(status: str = "active") -> None:
    """Saves Grandma, who said YES, with Ana's email for alerts."""
    storage.save_enrollment(
        {
            "id": "rosa",
            "senior_name": "Rosa",
            "senior_phone": GRANDMA,
            "family_name": "Ana",
            "family_phone": "+15555550143",
            "phone_type": "cell",
            "device_id": "senior-test",
            "device_key": "key-test",
            "senior_language": "en",
            "family_language": "en",
            "status": status,
            "created_at": storage.now_text(),
            "answered_at": storage.now_text(),
            "family_email": "ana@example.com",
        }
    )


def test_forwarded_call_gets_protected_and_transcribed():
    """A call forwarded from Grandma's phone goes in the protected room, with live transcription."""
    save_grandma()

    response = twilio_post(
        "/twilio/line/incoming", {"CallSid": "CA1", "From": SCAMMER, "ForwardedFrom": GRANDMA}
    )

    assert "<Conference" in response.text
    assert "<Transcription" in response.text
    assert "/twilio/protected/transcript?call_id=" in response.text


def test_calls_that_werent_forwarded_still_get_the_test_line():
    """Someone calling our number directly still gets "type your code"."""
    save_grandma()

    response = twilio_post("/twilio/line/incoming", {"CallSid": "CA2", "From": SCAMMER})

    assert "type the 4 digit code" in response.text


def test_scam_words_on_a_real_call_email_the_family(inbox):
    """The scammer's words get scored, and Ana gets the alert by email with the Join link."""
    save_grandma()
    twilio_post("/twilio/line/incoming", {"CallSid": "CA1", "From": SCAMMER, "ForwardedFrom": GRANDMA})
    call = storage.find_calls_for_enrollment("rosa")[0]

    twilio_post(
        f"/twilio/protected/transcript?call_id={call['id']}",
        {
            "TranscriptionEvent": "transcription-content",
            "Final": "true",
            "TranscriptionData": json.dumps({"transcript": "Grandma, it's me. I'm in jail. Buy gift cards and don't tell Mom."}),
        },
    )

    assert storage.get_call(call["id"])["risk_score"] == 91
    assert len(inbox) == 1
    assert inbox[0]["To"] == "ana@example.com"
    assert "/join/" in inbox[0].get_content()
    assert "made up" not in inbox[0].get_content()


def test_a_few_words_dont_set_off_an_alert(inbox):
    """A quiet call ("Hello? Hi") doesn't get scored, so noise can't email the family."""
    save_grandma()
    twilio_post("/twilio/line/incoming", {"CallSid": "CA1", "From": SCAMMER, "ForwardedFrom": GRANDMA})
    call = storage.find_calls_for_enrollment("rosa")[0]

    twilio_post(
        f"/twilio/protected/transcript?call_id={call['id']}",
        {
            "TranscriptionEvent": "transcription-content",
            "Final": "true",
            "TranscriptionData": json.dumps({"transcript": "Hello? Hi."}),
        },
    )

    assert storage.get_call(call["id"]).get("risk_score") is None
    assert inbox == []


def test_fake_transcripts_are_refused():
    """Without Twilio's signature, nobody can send us words."""
    response = client.post("/twilio/protected/transcript?call_id=x", data={"TranscriptionEvent": "transcription-content"})

    assert response.status_code == 403


def test_sign_up_takes_an_optional_email():
    """The sign-up form saves the family's email, and refuses one that looks wrong."""
    form = {
        "senior_name": "Rosa",
        "senior_phone": "3055550101",
        "family_name": "Ana",
        "family_phone": "3055550102",
        "ask_by": "call",
    }

    good = client.post("/api/enrollments", json={**form, "family_email": "ana@example.com"})
    bad = client.post("/api/enrollments", json={**form, "senior_phone": "3055550103", "family_email": "ana at example"})

    assert good.status_code == 201
    assert storage.get_enrollment(good.json()["id"])["family_email"] == "ana@example.com"
    assert bad.status_code == 400
