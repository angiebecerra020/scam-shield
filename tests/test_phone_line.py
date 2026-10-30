"""
test_phone_line.py

Tests for the "Test it" line (app/phone_line.py) and the alert
emails (app/email_alerts.py).

How it fits in: we pretend to be Twilio. We sign every request with a test
auth token, the same way Twilio signs real ones, so the signature check is
tested too. Nemotron and Tavily are pretend as well, and emails land in a
list instead of going out, so nothing here costs money or reaches a person.
"""

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app import call_monitor, calls, demo_api, detector, email_alerts, phone_line, research, storage, verify
from app.main import app

client = TestClient(app)

TEST_AUTH_TOKEN = "test-auth-token"
VISITOR_PHONE = "+15555550123"

GRANDSON_SCAM = {
    "risk_score": 92,
    "verdict": "likely_scam",
    "reasons": ["Claims to be a grandson in trouble", "Asks for gift cards"],
    "claimed_identity": "grandson Danny",
    "family_alert_message": "Your loved one may be on a scam call. The caller says they are grandson Danny and wants gift cards; call your loved one now.",
}

SAFE_CALL = {
    "risk_score": 10,
    "verdict": "safe",
    "reasons": [],
    "claimed_identity": None,
    "family_alert_message": None,
}


@pytest.fixture(autouse=True)
def fresh_phone_line(monkeypatch):
    """
    Each test starts with no codes, no calls counted, a test auth token, a
    pretend Gmail, and an empty pretend inbox.
    """
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TEST_AUTH_TOKEN)
    monkeypatch.setenv("GMAIL_ADDRESS", "scamshield.test@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    phone_line.TICKETS.clear()
    phone_line.CALLS_BY_PHONE.clear()
    phone_line.EMAILS_SENT.clear()
    phone_line.LOCKS.clear()
    demo_api.SESSIONS.clear()
    demo_api.VISITS.clear()
    verify.CHECKS_BY_CALL_ID.clear()
    call_monitor.ALERTED_CALL_IDS.clear()
    call_monitor.RESEARCH_BY_CALL_ID.clear()


@pytest.fixture
def inbox(monkeypatch):
    """
    Catches emails instead of sending them.

    Example:
        After an alert, inbox[0]["To"] is the visitor's email
    """
    sent = []
    monkeypatch.setattr(email_alerts, "deliver", sent.append)
    return sent


@pytest.fixture
def pretend_ai(monkeypatch):
    """
    Swaps Nemotron and Tavily for pretend ones.

    Set answer["result"] in a test to pick what the pretend Nemotron says.

    Example:
        pretend_ai["result"] = GRANDSON_SCAM
    """
    answer = {"result": SAFE_CALL}

    def pretend_score_call(transcript, language="en", client=None):
        return dict(answer["result"])

    def pretend_research(phone, detector_result):
        empty = {"query": "", "summary": None, "sources": [], "note": None}
        return {"caller": dict(empty, reported_as_scam=False), "news": dict(empty)}

    monkeypatch.setattr(detector, "score_call", pretend_score_call)
    monkeypatch.setattr(research, "research_call", pretend_research)
    return answer


def twilio_post(path: str, form: dict):
    """
    Sends a request the way Twilio does, signed with our test auth token.

    Example:
        twilio_post("/twilio/line/incoming", {"CallSid": "CA1", "From": "+1..."})
    """
    signature = RequestValidator(TEST_AUTH_TOKEN).compute_signature("http://testserver" + path, form)
    return client.post(path, data=form, headers={"X-Twilio-Signature": signature})


def get_code(email: str = "", language: str = "en", family_language: str = "en") -> dict:
    """
    Asks for a code like the page does and gives back the answer.

    Example:
        ticket = get_code("judge@example.com")
    """
    response = client.post(
        "/api/line/start",
        json={"language": language, "family_language": family_language, "email": email},
    )
    assert response.status_code == 200
    return response.json()


def call_and_type_code(ticket: dict) -> str:
    """
    Pretends to call our number and type the code. Gives back what Twilio heard (TwiML).

    Example:
        twiml = call_and_type_code(ticket)
    """
    twilio_post("/twilio/line/incoming", {"CallSid": "CA1", "From": VISITOR_PHONE})
    response = twilio_post("/twilio/line/code?tries=0", {"CallSid": "CA1", "Digits": ticket["code"]})
    assert response.status_code == 200
    return response.text


def say(ticket: dict, words: str, final: str = "true"):
    """
    Pretends Twilio's live transcription heard the caller say something.

    Example:
        say(ticket, "Grandma, it's me, I'm in jail")
    """
    form = {
        "CallSid": "CA1",
        "TranscriptionEvent": "transcription-content",
        "Final": final,
        "Track": "inbound_track",
        "TranscriptionData": f'{{"transcript": "{words}", "confidence": 0.95}}',
    }
    return twilio_post(f"/twilio/line/transcript?ticket={ticket['ticket_id']}", form)


def loop(ticket: dict) -> str:
    """
    Pretends Twilio checked in during the call. Gives back the TwiML.

    Example:
        loop(ticket) gives you "<Response><Pause .../><Redirect>...</Response>"
    """
    response = twilio_post(f"/twilio/line/loop?ticket={ticket['ticket_id']}", {"CallSid": "CA1"})
    assert response.status_code == 200
    return response.text


def look(ticket: dict) -> dict:
    """
    Asks for the ticket like the page does every second.

    Example:
        look(ticket)["status"] gives you "live"
    """
    return client.get(f"/api/line/{ticket['ticket_id']}").json()


def test_try_page_loads():
    """The "Test it" page opens at /try."""
    response = client.get("/try")

    assert response.status_code == 200
    assert "Test it" in response.text


def test_getting_a_code():
    """The page gets a 4 digit code and our number, and the email stays on the server."""
    ticket = get_code("judge@example.com")

    assert len(ticket["code"]) == 4 and ticket["code"].isdigit()
    assert ticket["phone_number"] == "+15555550150"
    assert ticket["status"] == "waiting"
    assert "judge@example.com" not in str(ticket)


def test_bad_email_is_refused():
    """An email that doesn't look like one gets a clear error."""
    response = client.post("/api/line/start", json={"email": "judge at example"})

    assert response.status_code == 400


def test_visitors_hit_the_hourly_code_limit(monkeypatch):
    """After too many codes in an hour, a visitor has to wait."""
    monkeypatch.setattr(phone_line, "MAX_CODES_PER_HOUR", 1)

    get_code()
    response = client.post("/api/line/start", json={})

    assert response.status_code == 429


def test_line_is_off_without_our_number(monkeypatch):
    """With no Twilio number in .env, the page says the line isn't set up."""
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "")

    response = client.post("/api/line/start", json={})

    assert response.status_code == 503


def test_fake_twilio_requests_are_refused():
    """Requests without Twilio's signature, or with a wrong one, are turned away."""
    unsigned = client.post("/twilio/line/incoming", data={"From": VISITOR_PHONE})
    wrong = client.post(
        "/twilio/line/incoming", data={"From": VISITOR_PHONE}, headers={"X-Twilio-Signature": "made-up"}
    )

    assert unsigned.status_code == 403
    assert wrong.status_code == 403


def test_incoming_call_asks_for_the_code():
    """When someone calls, Scam Shield asks for the 4 digit code."""
    response = twilio_post("/twilio/line/incoming", {"CallSid": "CA1", "From": VISITOR_PHONE})

    assert response.status_code == 200
    assert "<Gather" in response.text
    assert "type the 4 digit code" in response.text


def test_wrong_code_asks_again_then_hangs_up():
    """A wrong code gets another try, and after 3 wrong codes Scam Shield hangs up."""
    get_code()

    first = twilio_post("/twilio/line/code?tries=0", {"CallSid": "CA1", "Digits": "abcd"})
    last = twilio_post("/twilio/line/code?tries=2", {"CallSid": "CA1", "Digits": "abcd"})

    assert "didn't match" in first.text and "<Gather" in first.text
    assert "<Hangup" in last.text


def test_right_code_starts_listening():
    """The right code turns on live transcription of the caller's side and keeps the call going."""
    ticket = get_code()

    twiml = call_and_type_code(ticket)

    assert "<Transcription" in twiml
    assert 'track="inbound_track"' in twiml
    assert f"ticket={ticket['ticket_id']}" in twiml
    assert "<Redirect" in twiml
    assert look(ticket)["status"] == "live"


def test_scam_words_alert_email_and_warn_on_the_call(pretend_ai, inbox):
    """Scam words get scored, Ana's alert is emailed, Danny is asked, and Grandma hears the warning on the call."""
    pretend_ai["result"] = GRANDSON_SCAM
    ticket = get_code("judge@example.com")
    call_and_type_code(ticket)

    say(ticket, "Grandma, it's me Danny. I'm in jail and I need gift cards.")
    seen = look(ticket)

    assert seen["lines"] == [{"speaker": "caller", "text": "Grandma, it's me Danny. I'm in jail and I need gift cards."}]
    assert seen["latest"]["result"]["risk_score"] == 92
    assert seen["latest"]["alert_sent"] is True
    assert seen["latest"]["verify"]["contact_name"] == "Danny"
    assert seen["texts"]["family"][0].startswith("📞 Scam Shield ALERT call")
    assert seen["senior_warning"]["kind"] == "scam_likely"
    assert seen["email"] == {"asked": True, "status": "sent"}

    assert len(inbox) == 1
    assert inbox[0]["To"] == "judge@example.com"
    assert "Rosa" in inbox[0]["Subject"]
    assert "gift cards" in inbox[0].get_content()

    # The next check in says the warning out loud, and only once.
    assert "This is a potential spam call" in loop(ticket)
    assert "This is a potential spam call" not in loop(ticket)


def test_unfinished_sentences_are_skipped(pretend_ai):
    """Only finished sentences count, so we don't read the same words twice."""
    ticket = get_code()
    call_and_type_code(ticket)

    say(ticket, "Grandma it's", final="false")

    assert look(ticket)["lines"] == []


def test_danny_says_no_and_grandma_hears_it(pretend_ai, inbox):
    """If Danny taps NO on the page, Grandma hears it on the call."""
    pretend_ai["result"] = GRANDSON_SCAM
    ticket = get_code()
    call_and_type_code(ticket)
    say(ticket, "Grandma, it's me Danny. I'm in jail.")
    loop(ticket)

    answer = client.post(f"/api/line/{ticket['ticket_id']}/answer", json={"answer": "no"})

    assert answer.status_code == 200
    assert answer.json()["senior_warning"]["kind"] == "not_them"
    assert "Danny" in loop(ticket)


def test_safe_call_does_nothing(pretend_ai, inbox):
    """A normal call doesn't alert, email or warn anyone."""
    ticket = get_code("judge@example.com")
    call_and_type_code(ticket)

    say(ticket, "Hi Mom, I'm picking up your prescription at the pharmacy.")
    seen = look(ticket)

    assert seen["latest"]["alert_sent"] is False
    assert seen["senior_warning"] is None
    assert inbox == []
    assert "<Say" not in loop(ticket)


def test_no_email_when_gmail_isnt_set_up(pretend_ai, inbox, monkeypatch):
    """Without a Gmail in .env, the alert still works, we just skip the email."""
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "")
    pretend_ai["result"] = GRANDSON_SCAM
    ticket = get_code("judge@example.com")
    call_and_type_code(ticket)

    say(ticket, "Grandma, I'm in jail.")

    assert look(ticket)["email"]["status"] == "not_set_up"
    assert inbox == []


def test_call_ends_when_transcription_stops(pretend_ai):
    """When the caller hangs up, Twilio stops transcribing and the call shows as ended."""
    ticket = get_code()
    call_and_type_code(ticket)

    twilio_post(
        f"/twilio/line/transcript?ticket={ticket['ticket_id']}",
        {"CallSid": "CA1", "TranscriptionEvent": "transcription-stopped"},
    )

    assert look(ticket)["status"] == "ended"
    assert "<Hangup" in loop(ticket)


def test_calls_stop_after_five_minutes():
    """After 5 minutes Scam Shield says goodbye and hangs up."""
    ticket = get_code()
    call_and_type_code(ticket)
    phone_line.TICKETS[ticket["ticket_id"]]["started"] = time.time() - 400

    twiml = loop(ticket)

    assert "5 minutes" in twiml
    assert "<Hangup" in twiml


def test_each_phone_gets_a_few_calls_a_day(monkeypatch):
    """After too many calls in a day, the same phone hears "try again tomorrow"."""
    monkeypatch.setattr(phone_line, "MAX_CALLS_PER_PHONE_PER_DAY", 1)

    twilio_post("/twilio/line/incoming", {"CallSid": "CA1", "From": VISITOR_PHONE})
    second = twilio_post("/twilio/line/incoming", {"CallSid": "CA2", "From": VISITOR_PHONE})

    assert "try again tomorrow" in second.text


def test_the_visitors_number_is_never_saved(pretend_ai):
    """We save a made up 555 caller, and only a scrambled version of the visitor's number."""
    ticket = get_code()
    call_and_type_code(ticket)

    call = storage.get_call(look(ticket)["call_id"])

    assert call["caller_number"] == phone_line.PRETEND_CALLER
    assert VISITOR_PHONE not in phone_line.CALLS_BY_PHONE


def test_line_is_off_outside_demo_mode(monkeypatch):
    """Outside demo mode the line never runs, since the pretend family only exists there."""
    monkeypatch.setenv("DEMO_MODE", "false")

    page = client.post("/api/line/start", json={})
    call = twilio_post("/twilio/line/incoming", {"CallSid": "CA1", "From": VISITOR_PHONE})

    assert page.status_code == 404
    assert "test line is off" in call.text


def test_reading_words_from_twilio():
    """We pull the words out of Twilio's JSON, and shrug off anything weird."""
    assert phone_line.read_words('{"transcript": " Hi Grandma ", "confidence": 0.9}') == "Hi Grandma"
    assert phone_line.read_words("not json") == ""
    assert phone_line.read_words('["a list"]') == ""


def test_alert_email_in_english_and_spanish():
    """The alert email has the message, the top reasons, the score and the watch link."""
    subject, body = email_alerts.alert_email("en", "Rosa", "Ana", GRANDSON_SCAM, "http://testserver/try?ticket=abc")
    asunto, cuerpo = email_alerts.alert_email("es", "Rosa", "Ana", GRANDSON_SCAM, "http://testserver/try?ticket=abc")

    assert subject == "Scam Shield alert: Rosa may be on a scam call"
    assert "Asks for gift cards" in body
    assert "92 out of 100" in body
    assert "http://testserver/try?ticket=abc" in body
    assert asunto.startswith("Alerta de Scam Shield")
    assert "Hola Ana" in cuerpo


def test_failed_email_doesnt_break_anything(monkeypatch):
    """If Gmail says no, send_email tells us it failed instead of crashing the call check."""

    def gmail_says_no(message):
        raise OSError("Gmail is down")

    monkeypatch.setattr(email_alerts, "deliver", gmail_says_no)

    assert email_alerts.send_email("ana@example.com", "Hi", "Test") == "failed"


def test_email_address_check():
    """Only things that look like an email address get through."""
    assert email_alerts.is_email("ana@example.com") is True
    assert email_alerts.is_email("ana at example") is False
    assert email_alerts.is_email("") is False


def test_a_protected_senior_calling_hears_the_cancel_menu_not_the_code_question():
    """Our number may point here instead of /twilio/voice, so a senior calling
    from their own phone still gets "press 2 to cancel Scam Shield" (consent.py)."""
    client.post(
        "/api/enrollments",
        json={"senior_name": "Rosa", "senior_phone": "+15555550100", "family_name": "Ana", "family_phone": "+15555550101"},
    )
    client.post("/twilio/sms", data={"From": "+15555550100", "Body": "YES"})

    response = twilio_post("/twilio/line/incoming", {"CallSid": "CA-rosa", "From": "+15555550100"})

    assert "press 2" in response.text
    assert "code" not in response.text


def test_typing_the_code_doesnt_ring_a_made_up_phone_with_real_calls_on(monkeypatch):
    """
    The live site runs with REAL_CALLS on. The test line's Rosa is made up,
    so ringing "her" calling app always fails, and then handle_senior_status()
    hung up the visitor with "not available" right after they typed the code.
    """
    monkeypatch.setenv("REAL_CALLS", "true")
    pretend_twilio = MagicMock()
    monkeypatch.setattr(calls, "twilio_client", lambda: pretend_twilio)

    response = call_and_type_code(get_code())

    assert "<Transcription" in response
    assert "<Hangup" not in response
    # No real call to a made-up phone, and nothing that could hang the visitor up
    pretend_twilio.conferences.return_value.participants.create.assert_not_called()
    pretend_twilio.calls.return_value.update.assert_not_called()
