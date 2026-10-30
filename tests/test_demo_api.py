"""
test_demo_api.py

Tests for the demo player's routes (app/demo_api.py), the "Is it really you?"
check (app/verify.py) and Grandma's warnings (app/senior_warnings.py).

How it fits in: we use a pretend Nemotron and a pretend Tavily, so these run
fast, work without internet, and don't use up our credits. The shared setup
in conftest.py turns demo mode on and gives every test its own empty database.
"""

import pytest
from fastapi.testclient import TestClient

from app import call_monitor, demo_api, detector, research, senior_warnings, storage, verify
from app.main import app

client = TestClient(app)

GRANDSON_SCAM = {
    "risk_score": 92,
    "verdict": "likely_scam",
    "reasons": ["Claims to be a grandson in trouble", "Asks for gift cards"],
    "claimed_identity": "grandson Danny",
    "family_alert_message": "The caller says they are grandson Danny and wants gift cards.",
}

OFFICER_SCAM = {
    "risk_score": 88,
    "verdict": "likely_scam",
    "reasons": ["Dice que su número de Seguro Social fue suspendido"],
    "claimed_identity": "oficial Ramírez del Seguro Social",
    "family_alert_message": "Su ser querido puede estar en una llamada de estafa.",
}

SAFE_CALL = {
    "risk_score": 10,
    "verdict": "safe",
    "reasons": [],
    "claimed_identity": None,
    "family_alert_message": None,
}


@pytest.fixture(autouse=True)
def forget_old_demo_calls():
    """Each test starts with no demo calls, no visits counted, and nobody asked."""
    demo_api.SESSIONS.clear()
    demo_api.VISITS.clear()
    verify.CHECKS_BY_CALL_ID.clear()
    call_monitor.ALERTED_CALL_IDS.clear()
    call_monitor.RESEARCH_BY_CALL_ID.clear()


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


def start(script_id: str = "scam_grandparent_en", family_language: str = "en") -> dict:
    """
    Starts a demo call and gives back what the server said.

    Example:
        call = start("scam_ssn_es", "es")
    """
    response = client.post(f"/api/demo/calls/{script_id}/start", json={"family_language": family_language})
    assert response.status_code == 200
    return response.json()


def check(call_id: str, line: int) -> dict:
    """
    Checks a demo call up to a line and gives back what the server said.

    Example:
        result = check(call["call_id"], 3)
    """
    response = client.post(f"/api/demo/live/{call_id}/check", json={"up_to_line": line})
    assert response.status_code == 200
    return response.json()


def test_demo_page_loads():
    """The demo player page opens at /demo."""
    response = client.get("/demo")

    assert response.status_code == 200
    assert "Watch a scam get caught" in response.text


def test_demo_page_has_every_demo_in_tabs():
    """The scam call and the walkthroughs (add, pause, remove, turn off) are all on /demo."""
    page = client.get("/demo").text
    script = client.get("/static/demo-walkthroughs.js").text

    for scene in ("call", "add", "pause", "remove", "optout"):
        assert f'data-scene="{scene}"' in page
    for scene in ("add", "pause", "remove", "optout"):
        assert f"\n  {scene}: {{" in script
    assert page.index("/static/demo.js") < page.index("/static/demo-walkthroughs.js")


def test_the_dashboard_has_no_demo_buttons():
    """Demos only live on /demo, so the real dashboard never pretends anything."""
    page = client.get("/dashboard").text
    script = client.get("/static/app.js").text

    assert "demo-tools" not in page
    assert "Pretend" not in page
    assert "/api/demo/" not in script


def test_lists_all_our_test_calls():
    """The picker gets all 20 test calls."""
    calls = client.get("/api/demo/calls").json()

    assert len(calls) == 20
    assert "scam_grandparent_en" in [call["id"] for call in calls]


def test_starting_a_call_gives_the_lines_and_the_pretend_family():
    """Starting the fake grandson call gives its 8 lines, with Rosa, Ana and Danny."""
    call = start()

    assert len(call["lines"]) == 8
    assert call["senior"]["name"] == "Rosa"
    assert call["family"]["name"] == "Ana"
    assert call["contact"]["name"] == "Danny"
    # Only the fake caller number goes to the page, never the family's numbers.
    assert "phone" not in str(call["family"])


def test_unknown_call_is_a_clear_error():
    """Asking for a call we don't have gives a 404 with a message."""
    response = client.post("/api/demo/calls/not_a_real_call/start", json={})

    assert response.status_code == 404
    assert "error" in response.json()


def test_scam_line_alerts_ana_asks_danny_and_warns_rosa(pretend_ai):
    """When the score hits 70: Ana gets the alert, Danny gets asked, and Rosa gets warned."""
    pretend_ai["result"] = GRANDSON_SCAM
    call = start()

    result = check(call["call_id"], 3)

    assert result["alert_sent_now"] is True
    # Ana's alert is a phone call now, shown on her phone with what she hears.
    assert result["texts"]["family"][0].startswith("📞 Scam Shield ALERT call: ")
    assert "Why we're worried: " in result["texts"]["family"][0]
    assert "press 1" in result["texts"]["family"][0]
    assert result["verify"]["contact_name"] == "Danny"
    assert result["verify"]["answer"] is None
    assert "Is that really you?" in result["texts"]["contact"][0]
    assert result["senior_warning"]["kind"] == "scam_likely"
    assert result["senior_warning"]["speech_language"] == "en-US"


def test_rosa_is_only_warned_once(pretend_ai):
    """The next lines don't warn Rosa again or call Ana again."""
    pretend_ai["result"] = GRANDSON_SCAM
    call = start()

    check(call["call_id"], 3)
    later = check(call["call_id"], 5)

    assert later["senior_warning"] is None
    assert later["texts"]["family"] == []


def test_danny_says_no_warns_rosa_and_tells_ana(pretend_ai):
    """If the real Danny says NO, Rosa hears it right away and Ana gets a text."""
    pretend_ai["result"] = GRANDSON_SCAM
    call = start()
    check(call["call_id"], 3)

    response = client.post(f"/api/demo/live/{call['call_id']}/answer", json={"answer": "no"})
    answer = response.json()

    assert response.status_code == 200
    assert answer["senior_warning"]["kind"] == "not_them"
    assert "Danny" in answer["senior_warning"]["text"]
    assert "NOT" in answer["texts"]["family"][0]


def test_danny_says_yes_means_no_warning(pretend_ai):
    """If the real Danny says YES, we tell Ana but don't scare Rosa."""
    pretend_ai["result"] = GRANDSON_SCAM
    call = start()
    check(call["call_id"], 3)

    answer = client.post(f"/api/demo/live/{call['call_id']}/answer", json={"answer": "yes"}).json()

    assert answer["senior_warning"] is None
    assert "really are" in answer["texts"]["family"][0]


def test_answering_before_anyone_was_asked_is_an_error(pretend_ai):
    """Danny can't answer a question we never sent him."""
    call = start()

    response = client.post(f"/api/demo/live/{call['call_id']}/answer", json={"answer": "no"})

    assert response.status_code == 409


def test_safe_call_does_nothing(pretend_ai):
    """A safe call doesn't alert Ana, ask Danny, or warn Rosa."""
    call = start("normal_pharmacy_en")

    result = check(call["call_id"], 1)

    assert result["alert_sent"] is False
    assert result["verify"] is None
    assert result["senior_warning"] is None
    assert result["texts"] == {"family": [], "contact": []}


def test_spanish_call_warns_rosa_in_spanish(pretend_ai):
    """A Spanish call means Rosa speaks Spanish, so her warning is in Spanish too."""
    pretend_ai["result"] = OFFICER_SCAM
    call = start("scam_ssn_es", "es")

    result = check(call["call_id"], 3)

    assert result["senior_warning"]["text"].startswith("Esta es una posible llamada fraudulenta")
    assert result["senior_warning"]["speech_language"] == "es-US"
    assert result["texts"]["family"][0].startswith("📞 Llamada de ALERTA")
    # The fake officer isn't using a family member's name, so Danny isn't asked.
    assert result["verify"] is None


def test_demo_is_off_outside_demo_mode(monkeypatch):
    """The demo never runs with real phones."""
    monkeypatch.setenv("DEMO_MODE", "false")

    assert client.get("/api/demo/calls").status_code == 404
    assert client.post("/api/demo/calls/scam_grandparent_en/start", json={}).status_code == 404


def test_visitors_hit_the_hourly_limit(monkeypatch):
    """After too many demo calls in an hour, a visitor has to wait."""
    monkeypatch.setattr(demo_api, "MAX_CALLS_PER_HOUR", 2)

    start()
    start()
    response = client.post("/api/demo/calls/scam_grandparent_en/start", json={})

    assert response.status_code == 429


def test_demo_rosa_is_never_a_real_protected_senior(pretend_ai):
    """The pretend Rosa is saved as "demo", so real calls and the dashboard skip her, but she still gets protected."""
    pretend_ai["result"] = GRANDSON_SCAM
    call = start()

    assert storage.find_active_enrollments() == []
    assert check(call["call_id"], 3)["alert_sent_now"] is True


def test_visitors_cant_fake_their_address_to_skip_the_limit(monkeypatch):
    """Making up the start of X-Forwarded-For doesn't give a visitor a fresh limit."""
    monkeypatch.setattr(demo_api, "MAX_CALLS_PER_HOUR", 1)

    first = client.post(
        "/api/demo/calls/scam_grandparent_en/start",
        json={},
        headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.7"},
    )
    faked = client.post(
        "/api/demo/calls/scam_grandparent_en/start",
        json={},
        headers={"X-Forwarded-For": "2.2.2.2, 203.0.113.7"},
    )

    assert first.status_code == 200
    assert faked.status_code == 429


def test_contact_names_match_whole_words_only():
    """"son" doesn't match "Johnson", but "Daniel" finds Danny."""
    danny = {"name": "Danny", "other_names": ["Daniel", "son"]}

    assert verify.mentions("Officer Johnson", "son") is False
    assert verify.find_contact("abogado de su nieto Daniel", [danny]) == danny
    assert verify.find_contact("Officer Johnson", [danny]) is None


def test_warnings_fall_back_to_english():
    """A language we don't support yet gets the English warning."""
    warning = senior_warnings.senior_warning("scam_likely", "fr")

    assert warning["text"].startswith("This is a potential spam call")
    assert warning["speech_language"] == "en-US"
