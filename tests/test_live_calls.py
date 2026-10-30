"""
test_live_calls.py

Tests for real protected calls (app/live_calls.py): a call forwarded from a
landline senior who said YES gets the protected flow with live transcription,
every sentence is scored, and the family gets the alert by email. A call
forwarded from a cell phone gets our voicemail, and a scam voicemail emails
the family.

How it fits in: we pretend to be Twilio (signed requests), Nemotron and
Tavily are pretend, and emails land in a list. Demo mode is on, so no real
phone rings.
"""

import json

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app import call_monitor, calls, detector, email_alerts, live_calls, phone_line, research, storage
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


def save_grandma(status: str = "active", phone_type: str = "landline") -> None:
    """Saves Grandma, who said YES, with Ana's email for alerts."""
    storage.save_enrollment(
        {
            "id": "rosa",
            "senior_name": "Rosa",
            "senior_phone": GRANDMA,
            "family_name": "Ana",
            "family_phone": "+15555550143",
            "phone_type": phone_type,
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


def test_grandma_adding_scam_shield_to_a_call_starts_listening():
    """Grandma taps Add call and Merge: we listen right away and put her in a room."""
    save_grandma()

    response = twilio_post("/twilio/line/incoming", {"CallSid": "CA5", "From": GRANDMA})

    assert "<Transcription" in response.text
    assert "Scam Shield is joining your call" in response.text
    assert "press 2" in response.text
    assert "<Conference" in response.text
    call = storage.find_calls_for_enrollment("rosa")[0]
    assert call["caller_number"] == live_calls.ADDED_CALLER


def test_scam_words_on_an_added_call_email_the_family(inbox):
    """The merged call gets scored like any protected call."""
    save_grandma()
    twilio_post("/twilio/line/incoming", {"CallSid": "CA5", "From": GRANDMA})
    call = storage.find_calls_for_enrollment("rosa")[0]

    twilio_post(
        f"/twilio/protected/transcript?call_id={call['id']}",
        {
            "TranscriptionEvent": "transcription-content",
            "Final": "true",
            "TranscriptionData": json.dumps({"transcript": "Grandma, it's me. I'm in jail. Buy gift cards and don't tell Mom."}),
        },
    )

    assert len(inbox) == 1
    assert "/join/" in inbox[0].get_content()


def test_a_paused_grandma_calling_in_still_gets_the_menu():
    """Paused means we don't listen, so she hears Cass's menu instead."""
    save_grandma(status="paused")

    response = twilio_post("/twilio/line/incoming", {"CallSid": "CA6", "From": GRANDMA})

    assert "<Transcription" not in response.text
    assert "<Gather" in response.text


def test_signing_someone_up_sends_a_welcome_email_with_the_setup_video(inbox):
    """The family gets "Welcome to Scam Shield" with the how to set up link."""
    rosa = {"family_email": "ana@example.com", "family_name": "Ana", "senior_name": "Rosa", "family_language": "en"}

    result = email_alerts.send_welcome_email(rosa)

    assert result == "sent"
    assert inbox[0]["Subject"] == "Welcome to Scam Shield"
    assert "/how-to" in inbox[0].get_content()


def test_no_email_means_no_welcome_email(inbox):
    assert email_alerts.send_welcome_email({"family_email": None}) == "no_email"
    assert inbox == []


def test_with_real_calls_on_fake_twilio_requests_are_refused(monkeypatch):
    """The live site is in demo mode with real calls on. A request without
    Twilio's signature must not be able to cancel a senior or fake their YES."""
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("REAL_CALLS", "true")
    save_grandma()

    fake = client.post("/twilio/line/incoming", data={"CallSid": "CA1", "From": GRANDMA})
    real = twilio_post("/twilio/line/incoming", {"CallSid": "CA1", "From": GRANDMA})

    assert fake.status_code == 403
    assert real.status_code == 200


def test_a_stray_key_on_an_added_call_keeps_scam_shield_listening():
    """Our first real merge test got cut off: a tone counted as "not 2" and we
    hung up. Now any key other than 2 keeps us in the call."""
    save_grandma()
    twilio_post("/twilio/line/incoming", {"CallSid": "CA5", "From": GRANDMA})
    call = storage.find_calls_for_enrollment("rosa")[0]

    response = twilio_post(f"/twilio/protected/added-choice?call_id={call['id']}", {"Digits": "1", "From": GRANDMA})

    assert "<Hangup" not in response.text
    assert call["conference_name"] in response.text
    assert storage.get_enrollment("rosa")["status"] == "active"


def test_pressing_2_on_an_added_call_removes_us_from_that_call():
    """Grandma hears we left, we hang up our side, and the call isn't kept."""
    save_grandma()
    twilio_post("/twilio/line/incoming", {"CallSid": "CA5", "From": GRANDMA})
    call = storage.find_calls_for_enrollment("rosa")[0]

    response = twilio_post(f"/twilio/protected/added-choice?call_id={call['id']}", {"Digits": "2", "From": GRANDMA})

    assert "Scam Shield was removed from this call. We are not listening." in response.text
    assert "<Hangup" in response.text
    assert "<Conference" not in response.text
    assert storage.find_calls_for_enrollment("rosa") == []
    # Only this call: she stays protected for the next one
    assert storage.get_enrollment("rosa")["status"] == "active"


def test_words_after_pressing_2_on_an_added_call_are_ignored():
    save_grandma()
    twilio_post("/twilio/line/incoming", {"CallSid": "CA5", "From": GRANDMA})
    call = storage.find_calls_for_enrollment("rosa")[0]
    twilio_post(f"/twilio/protected/added-choice?call_id={call['id']}", {"Digits": "2", "From": GRANDMA})

    twilio_post(
        f"/twilio/protected/transcript?call_id={call['id']}",
        {
            "TranscriptionEvent": "transcription-content",
            "Final": "true",
            "TranscriptionData": json.dumps({"transcript": "Grandma, buy gift cards and don't tell Mom."}),
        },
    )

    assert live_calls.LINES.get(call["id"]) is None


def test_adding_us_to_a_call_says_how_to_remove_us():
    save_grandma()

    response = twilio_post("/twilio/line/incoming", {"CallSid": "CA5", "From": GRANDMA})

    assert "To remove Scam Shield from this call, press 2." in response.text


def test_an_added_call_has_no_hold_music():
    """Twilio plays music to anyone alone in a room. On a merged call that
    played over Grandma's conversation, so the room has to be silent."""
    save_grandma()

    response = twilio_post("/twilio/line/incoming", {"CallSid": "CA5", "From": GRANDMA})

    assert 'waitUrl=""' in response.text


def test_when_the_family_is_alerted_the_senior_hears_the_warning_too(inbox, monkeypatch):
    """The alert goes to the family AND Scam Shield says it out loud on the call."""
    warned = []
    monkeypatch.setattr(live_calls, "warn_senior", warned.append)
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

    assert warned == [call["id"]]


def test_the_warning_plays_as_the_family_call_goes_out(inbox, monkeypatch):
    """The senior hears it right after the family's phone starts ringing,
    before the alert emails and the Tavily search."""
    happened = []
    monkeypatch.setattr(calls, "send_family_alert", lambda call: happened.append("family call"))
    monkeypatch.setattr(live_calls, "warn_senior", lambda call_id: happened.append("warning"))
    monkeypatch.setattr(email_alerts, "deliver", lambda message: happened.append("email"))
    monkeypatch.setattr(research, "research_call", lambda *args: happened.append("search") or {})
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

    assert happened[:2] == ["family call", "warning"]


def test_the_scam_warning_words():
    save_grandma()
    twilio_post("/twilio/line/incoming", {"CallSid": "CA1", "From": SCAMMER, "ForwardedFrom": GRANDMA})
    call = storage.find_calls_for_enrollment("rosa")[0]

    response = twilio_post(f"/twilio/protected/warning?call_id={call['id']}", {})

    assert "This is a potential scam. We are notifying a family member." in response.text


# ----- Cell phones: missed calls get our voicemail -----


def voicemail_is_left(words: str, caller: str = SCAMMER) -> dict:
    """A missed call forwarded from Grandma's cell: the caller leaves `words` and hangs up."""
    save_grandma(phone_type="cell")
    response = twilio_post(
        "/twilio/line/incoming", {"CallSid": "CA1", "From": caller, "ForwardedFrom": GRANDMA}
    )
    call = storage.find_calls_for_enrollment("rosa")[0]
    path = f"/twilio/protected/transcript?call_id={call['id']}"
    twilio_post(
        path,
        {
            "TranscriptionEvent": "transcription-content",
            "Final": "true",
            "TranscriptionData": json.dumps({"transcript": words}),
        },
    )
    twilio_post(path, {"TranscriptionEvent": "transcription-stopped"})
    return {"call": call, "twiml": response.text}


SCAM_VOICEMAIL = "Grandma, it's me Danny. I'm in jail. Buy gift cards and call me back, don't tell Mom."


def test_a_missed_call_on_a_cell_gets_our_voicemail_not_a_ring_back():
    """We never ring a cell phone back: the caller gets voicemail, and we transcribe it."""
    left = voicemail_is_left("Hi Rosa, call me back.")

    assert "can't come to the phone" in left["twiml"]
    assert "<Transcription" in left["twiml"]
    assert "<Conference" not in left["twiml"]
    assert "<Record" not in left["twiml"]
    assert calls.DEMO_CALL_LOG == []


def test_a_scam_voicemail_emails_the_family_with_the_number_and_what_they_wanted(inbox):
    left = voicemail_is_left(SCAM_VOICEMAIL)

    assert len(inbox) == 1
    assert inbox[0]["To"] == "ana@example.com"
    assert "voicemail" in inbox[0]["Subject"]
    body = inbox[0].get_content()
    assert SCAMMER in body
    assert "Asks for gift cards" in body
    assert "grandson Danny" in body
    assert storage.get_call(left["call"]["id"])["status"] == "ended"
    # Nobody gets an alert call: there's no call to join.
    assert calls.DEMO_CALL_LOG == []


def test_a_scam_voicemail_puts_the_number_on_the_list_as_a_potential_scam(inbox):
    voicemail_is_left(SCAM_VOICEMAIL)

    listed = storage.find_scam_number(None, SCAMMER)

    assert listed is not None
    assert listed["action"] == "potential"


def test_a_number_the_family_blocked_or_warned_about_stays_that_way(inbox):
    storage.save_scam_number(None, SCAMMER, "warn", "old-call")

    voicemail_is_left(SCAM_VOICEMAIL)

    assert storage.find_scam_number(None, SCAMMER)["action"] == "warn"


def test_a_voicemail_is_read_once_when_the_caller_hangs_up(inbox):
    """No email while they're still talking, so we read the whole message first."""
    save_grandma(phone_type="cell")
    twilio_post("/twilio/line/incoming", {"CallSid": "CA1", "From": SCAMMER, "ForwardedFrom": GRANDMA})
    call = storage.find_calls_for_enrollment("rosa")[0]

    twilio_post(
        f"/twilio/protected/transcript?call_id={call['id']}",
        {
            "TranscriptionEvent": "transcription-content",
            "Final": "true",
            "TranscriptionData": json.dumps({"transcript": SCAM_VOICEMAIL}),
        },
    )

    assert inbox == []


def test_a_safe_voicemail_sends_nothing(inbox, monkeypatch):
    safe = {**SCAM, "risk_score": 5, "verdict": "safe", "reasons": [], "family_alert_message": None}
    monkeypatch.setattr(detector, "score_call", lambda transcript, language="en", client=None: dict(safe))

    voicemail_is_left("Hi Rosa, it's the pharmacy. Your prescription is ready.")

    assert inbox == []
    assert storage.find_scam_number(None, SCAMMER) is None


def test_a_hidden_number_still_emails_but_cant_go_on_the_list(inbox):
    voicemail_is_left(SCAM_VOICEMAIL, caller="Anonymous")

    assert len(inbox) == 1
    assert "scam list" not in inbox[0].get_content()
    assert storage.find_scam_number(None, "Anonymous") is None


def test_a_paused_cell_senior_gets_no_ring_back_and_no_voicemail(inbox):
    save_grandma(status="paused", phone_type="cell")

    response = twilio_post(
        "/twilio/line/incoming", {"CallSid": "CA1", "From": SCAMMER, "ForwardedFrom": GRANDMA}
    )

    assert "can't come to the phone" in response.text
    assert "<Dial" not in response.text
    assert "<Transcription" not in response.text
