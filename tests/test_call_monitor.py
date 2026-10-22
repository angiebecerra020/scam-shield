"""
test_call_monitor.py

Tests for connecting the brain to the family alert (app/call_monitor.py).

How it fits in: these make sure the family gets the alert (with the "Join
call" link) when a call scores 70 or more, that they only get it once, and
that we never alert for a senior who didn't say YES. We use a pretend
Nemotron and a pretend Tavily, so nothing real gets called. The shared setup
in conftest.py gives every test its own empty database and turns demo mode on,
so texts go to the demo outbox instead of real phones.
"""

import pytest

from app import alerts, call_monitor, calls, detector, research, storage

SCAM_RESULT = {
    "risk_score": 92,
    "verdict": "likely_scam",
    "reasons": ["Asks for gift cards", "Says don't tell Mom"],
    "claimed_identity": "grandson Danny",
    "family_alert_message": "The caller says they are grandson Danny and wants gift cards.",
}

SAFE_RESULT = {
    "risk_score": 10,
    "verdict": "safe",
    "reasons": ["Just chatting"],
    "claimed_identity": None,
    "family_alert_message": None,
}


@pytest.fixture(autouse=True)
def forget_past_calls():
    """Each test starts with no calls alerted and no searches saved."""
    call_monitor.ALERTED_CALL_IDS.clear()
    call_monitor.RESEARCH_BY_CALL_ID.clear()


@pytest.fixture
def fake_tavily(monkeypatch):
    """
    Swaps Tavily for a pretend one and counts how many times we searched.

    Example:
        fake_tavily["searches"] gives you how many times research ran
    """
    counter = {"searches": 0}

    def pretend_research(phone, detector_result):
        counter["searches"] += 1
        return {"caller": {"sources": []}, "news": {"sources": []}}

    monkeypatch.setattr(research, "research_call", pretend_research)
    return counter


def pretend_nemotron(monkeypatch, result: dict) -> list:
    """
    Makes detector.score_call give back the result we pick, and remembers
    which language it was asked for.

    Example:
        languages = pretend_nemotron(monkeypatch, SCAM_RESULT)
    """
    languages_asked = []

    def pretend_score_call(transcript, language="en", client=None):
        languages_asked.append(language)
        return dict(result)

    monkeypatch.setattr(detector, "score_call", pretend_score_call)
    return languages_asked


def make_protected_call(status: str = "active", family_language: str = "en") -> dict:
    """
    Saves a senior (Rosa) and family member (Ana), and starts a call for Rosa.

    Input:  status, Rosa's consent status ("active" means she said YES)
            family_language, Ana's language
    Output: the call, saved in the test database

    Example:
        call = make_protected_call()
    """
    enrollment = {
        "id": "rosa-test",
        "senior_name": "Rosa",
        "senior_phone": "+13055550100",
        "family_name": "Ana",
        "family_phone": "+13055550101",
        "phone_type": "cell",
        "device_id": "senior-rosatest",
        "device_key": "rosa-test-key",
        "senior_language": "es",
        "family_language": family_language,
        "status": status,
        "created_at": storage.now_text(),
        "answered_at": storage.now_text(),
    }
    storage.save_enrollment(enrollment)
    return calls.start_protected_call(enrollment, caller="+13055550142", call_sid="demo")


def texts_to_family() -> list[str]:
    """Gives you every text the family (Ana) got in the demo outbox."""
    return [text["body"] for text in alerts.DEMO_OUTBOX if text["to"] == "+13055550101"]


def test_high_score_sends_the_join_call_alert_and_the_why_text(monkeypatch, fake_tavily):
    """A score of 92 sends Ana the alert with the Join call link, then the reason."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = make_protected_call()

    outcome = call_monitor.check_live_call(call["id"], "Caller: Grandma, buy gift cards.")

    family_texts = texts_to_family()
    assert outcome["alert_sent_now"] is True
    assert "/join/" in family_texts[0]
    assert family_texts[1].startswith("Why we're worried: ")


def test_family_only_gets_the_alert_once(monkeypatch, fake_tavily):
    """Checking the same scam call again doesn't text the family again."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = make_protected_call()

    call_monitor.check_live_call(call["id"], "Caller: Grandma, buy gift cards.")
    second = call_monitor.check_live_call(call["id"], "Caller: Hurry, Grandma!")

    assert second["alert_sent_now"] is False
    assert second["alert_sent"] is True
    assert len(texts_to_family()) == 2


def test_safe_call_sends_nothing_and_skips_tavily(monkeypatch, fake_tavily):
    """A safe call doesn't alert anyone or use up Tavily searches."""
    pretend_nemotron(monkeypatch, SAFE_RESULT)
    call = make_protected_call()

    outcome = call_monitor.check_live_call(call["id"], "Caller: Hi Grandma, it's Sofia!")

    assert outcome["alert_sent_now"] is False
    assert texts_to_family() == []
    assert fake_tavily["searches"] == 0


def test_no_alert_if_the_senior_never_said_yes(monkeypatch, fake_tavily):
    """Privacy first: if Rosa didn't say YES, we never alert about her calls."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = make_protected_call(status="pending")

    outcome = call_monitor.check_live_call(call["id"], "Caller: Grandma, buy gift cards.")

    assert outcome["alert_sent_now"] is False
    assert texts_to_family() == []


def test_no_alert_after_the_call_ended(monkeypatch, fake_tavily):
    """Once the call is over, the Join call link is useless, so we don't send it."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = make_protected_call()
    storage.mark_call_ended(call["id"])

    outcome = call_monitor.check_live_call(call["id"], "Caller: Grandma, buy gift cards.")

    assert outcome["alert_sent_now"] is False


def test_unknown_score_never_alerts(monkeypatch, fake_tavily):
    """If Nemotron couldn't check the call, we don't guess and we don't alert."""
    pretend_nemotron(monkeypatch, detector.unknown_result("No internet"))
    call = make_protected_call()

    outcome = call_monitor.check_live_call(call["id"], "Caller: Grandma, buy gift cards.")

    assert outcome["alert_sent_now"] is False


def test_tavily_only_searches_once_per_call(monkeypatch, fake_tavily):
    """We search the caller once, then reuse the result for the rest of the call."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = make_protected_call()

    call_monitor.check_live_call(call["id"], "Caller: line one")
    call_monitor.check_live_call(call["id"], "Caller: line one\nCaller: line two")

    assert fake_tavily["searches"] == 1


def test_spanish_family_gets_spanish(monkeypatch, fake_tavily):
    """If Ana reads Spanish, Nemotron writes in Spanish and the why text is in Spanish."""
    languages_asked = pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = make_protected_call(family_language="es")

    call_monitor.check_live_call(call["id"], "Caller: Abuela, compra tarjetas de regalo.")

    assert languages_asked == ["es"]
    assert texts_to_family()[1].startswith("Por qué nos preocupa: ")


def test_unknown_call_id_gives_a_clear_error():
    """Asking about a call that doesn't exist gives a clear error."""
    with pytest.raises(ValueError):
        call_monitor.check_live_call("no-such-call", "Caller: hi")


def test_the_why_text_is_in_creole_for_a_creole_family():
    """A family member who reads Creole gets "Poukisa nou enkyete" with the red flags."""
    assert call_monitor.why_text(SCAM_RESULT, "ht").startswith("Poukisa nou enkyete: ")
