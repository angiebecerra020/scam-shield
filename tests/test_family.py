"""
test_family.py

Tests for the family dashboard (app/family.py): call history, call details,
pausing protection, and making sure each family only sees their own seniors.

How it fits in: these go through the web routes the dashboard uses, like a
real browser would. We use a pretend Nemotron, a pretend Tavily and a pretend
Supabase, so nothing real gets called. conftest.py gives every test its own
empty database and turns demo mode on, so texts go to the demo outbox.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import alerts, auth, call_monitor, calls, detector, research, storage
from app.main import app

client = TestClient(app)

# 555-01XX numbers are reserved for fiction, so they never reach a real person
SENIOR_PHONE = "+13055550100"
FAMILY_PHONE = "+13055550101"
SCAMMER_PHONE = "+13055550142"

# Two pretend family logins, so we can check they can't see each other's seniors
ANA = {"id": "user-ana", "email": "ana@example.com"}
BOB = {"id": "user-bob", "email": "bob@example.com"}
TOKENS = {"ana-token": ANA, "bob-token": BOB}

SCAM_RESULT = {
    "risk_score": 92,
    "verdict": "likely_scam",
    "reasons": ["Asks for gift cards", "Says don't tell Mom"],
    "claimed_identity": "grandson Danny",
    "family_alert_message": "The caller says they are grandson Danny and wants gift cards.",
}

CALMER_RESULT = {
    "risk_score": 55,
    "verdict": "suspicious",
    "reasons": ["Asks for money"],
    "claimed_identity": "grandson Danny",
    "family_alert_message": None,
}

FTC_LINK = {"title": "Grandparent scams", "url": "https://consumer.ftc.gov/grandparent-scams"}


@pytest.fixture(autouse=True)
def forget_past_calls():
    """Each test starts with no calls alerted and no searches saved."""
    call_monitor.ALERTED_CALL_IDS.clear()
    call_monitor.RESEARCH_BY_CALL_ID.clear()


@pytest.fixture
def fake_tavily(monkeypatch):
    """Swaps Tavily for a pretend one that always finds the FTC warning."""

    def pretend_research(phone, detector_result):
        return {"caller": {"sources": []}, "news": {"sources": [dict(FTC_LINK, snippet="...")]}}

    monkeypatch.setattr(research, "research_call", pretend_research)


@pytest.fixture
def login_on(monkeypatch):
    """Turn login on, with a pretend Supabase that knows Ana and Bob."""
    monkeypatch.setenv("SUPABASE_URL", "https://fake-project.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_fake")
    auth.CHECKED_TOKENS.clear()
    monkeypatch.setattr(auth, "ask_supabase_who", lambda token, settings: TOKENS.get(token))


def pretend_nemotron(monkeypatch, result: dict) -> None:
    """Makes detector.score_call give back the result we pick."""
    monkeypatch.setattr(detector, "score_call", lambda transcript, language="en", client=None: dict(result))


def as_user(token: str) -> dict:
    """The header a logged in browser sends. Example: as_user("ana-token")"""
    return {"Authorization": f"Bearer {token}"}


def sign_up_rosa(headers: dict | None = None) -> str:
    """Ana signs up Rosa, and Rosa texts YES. Gives you Rosa's enrollment ID."""
    response = client.post(
        "/api/enrollments",
        json={
            "senior_name": "Rosa",
            "senior_phone": SENIOR_PHONE,
            "family_name": "Ana",
            "family_phone": FAMILY_PHONE,
        },
        headers=headers or {},
    )
    client.post("/twilio/sms", data={"From": SENIOR_PHONE, "Body": "YES"})
    return response.json()["id"]


def scam_call_for(enrollment_id: str) -> dict:
    """Starts a call for this senior, the way calls.py does when one comes in."""
    enrollment = storage.get_enrollment(enrollment_id)
    return calls.start_protected_call(enrollment, caller=SCAMMER_PHONE, call_sid="demo")


def texts_to_family() -> list[str]:
    """Gives you every text Ana got in the demo outbox."""
    return [text["body"] for text in alerts.DEMO_OUTBOX if text["to"] == FAMILY_PHONE]


# Call history


def test_a_checked_call_shows_up_in_the_history(monkeypatch, fake_tavily):
    """After a scam call, Ana sees it with its score, and that she was alerted."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    rosa = sign_up_rosa()
    call = scam_call_for(rosa)
    call_monitor.check_live_call(call["id"], "Caller: Grandma, buy gift cards.")

    seniors = client.get("/api/family").json()["seniors"]

    assert seniors[0]["senior_name"] == "Rosa"
    assert seniors[0]["status"] == "active"
    past_call = seniors[0]["calls"][0]
    assert past_call["risk_score"] == 92
    assert past_call["verdict"] == "likely_scam"
    assert past_call["caller_number"] == SCAMMER_PHONE
    assert past_call["alerted"] is True


def test_call_details_have_the_reasons_and_the_tavily_links(monkeypatch, fake_tavily):
    """Tapping a call shows why we were worried and what Tavily found."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = scam_call_for(sign_up_rosa())
    call_monitor.check_live_call(call["id"], "Caller: Grandma, buy gift cards.")

    details = client.get(f"/api/calls/{call['id']}").json()

    assert details["reasons"] == SCAM_RESULT["reasons"]
    assert details["claimed_identity"] == "grandson Danny"
    assert details["sources"] == [FTC_LINK]
    assert details["alerted_at"] is not None


def test_the_history_keeps_the_riskiest_moment(monkeypatch, fake_tavily):
    """If the call calms down later, the history still shows how bad it got."""
    call = scam_call_for(sign_up_rosa())
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call_monitor.check_live_call(call["id"], "Caller: Buy gift cards.")
    pretend_nemotron(monkeypatch, CALMER_RESULT)
    call_monitor.check_live_call(call["id"], "Caller: Buy gift cards. Okay, never mind.")

    details = client.get(f"/api/calls/{call['id']}").json()

    assert details["risk_score"] == 92
    assert details["reasons"] == SCAM_RESULT["reasons"]


def test_a_call_the_detector_could_not_check_has_no_score(monkeypatch, fake_tavily):
    """When Nemotron is down, the call shows up with no score instead of a made-up one."""
    pretend_nemotron(monkeypatch, {"risk_score": None, "verdict": None, "reasons": []})
    call = scam_call_for(sign_up_rosa())
    call_monitor.check_live_call(call["id"], "Caller: Hello?")

    past_call = client.get("/api/family").json()["seniors"][0]["calls"][0]

    assert past_call["risk_score"] is None
    assert past_call["alerted"] is False


def test_no_seniors_yet_gives_an_empty_list():
    """A brand-new family sees nobody yet (the page shows the sign-up form)."""
    assert client.get("/api/family").json() == {"seniors": []}


def test_an_unknown_call_is_a_clear_error():
    """Asking for a call that doesn't exist gives you a 404 the page can show."""
    response = client.get("/api/calls/not-a-real-call")

    assert response.status_code == 404
    assert "couldn't find" in response.json()["error"]


# Each family only sees their own seniors


def test_families_only_see_the_seniors_they_signed_up(login_on):
    """Bob logs in and doesn't see Rosa, because Ana signed her up."""
    sign_up_rosa(as_user("ana-token"))

    ana_sees = client.get("/api/family", headers=as_user("ana-token")).json()["seniors"]
    bob_sees = client.get("/api/family", headers=as_user("bob-token")).json()["seniors"]

    assert [senior["senior_name"] for senior in ana_sees] == ["Rosa"]
    assert bob_sees == []


def test_other_families_cant_open_your_calls_or_sign_ups(login_on, monkeypatch, fake_tavily):
    """Even with the IDs, Bob can't see Rosa's call, her sign-up, or pause her."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    rosa = sign_up_rosa(as_user("ana-token"))
    call = scam_call_for(rosa)
    call_monitor.check_live_call(call["id"], "Caller: Buy gift cards.")
    bob = as_user("bob-token")

    assert client.get(f"/api/calls/{call['id']}", headers=bob).status_code == 404
    assert client.get(f"/api/enrollments/{rosa}", headers=bob).status_code == 404
    assert client.post(f"/api/enrollments/{rosa}/pause", headers=bob).status_code == 404
    assert storage.get_enrollment(rosa)["status"] == "active"


def test_the_dashboard_routes_need_a_login(login_on):
    """Nobody logged in gets a 401, so the page sends them to /login."""
    assert client.get("/api/family").status_code == 401
    assert client.get("/api/calls/anything").status_code == 401


# Pause and resume


def test_pausing_stops_the_alerts(monkeypatch, fake_tavily):
    """While Rosa is paused, a scam call scores high but Ana gets no alert."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    rosa = sign_up_rosa()
    call = scam_call_for(rosa)
    alerts.DEMO_OUTBOX.clear()

    paused = client.post(f"/api/enrollments/{rosa}/pause")
    outcome = call_monitor.check_live_call(call["id"], "Caller: Buy gift cards.")

    assert paused.json()["status"] == "paused"
    assert outcome["alert_sent"] is False
    assert texts_to_family() == []


def test_paused_calls_ring_like_normal_without_listening():
    """A call for a paused senior goes straight to her phone, with no conference room."""
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/pause")

    xml = calls.handle_incoming_call(SCAMMER_PHONE, "CA123", SENIOR_PHONE)

    assert "<Conference" not in xml
    assert "<Dial" in xml


def test_paused_senior_still_found_when_the_carrier_hides_whose_phone_it_is():
    """With no ForwardedFrom, our one paused senior still gets her call (not a hang up)."""
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/pause")

    assert calls.find_senior_for_call(None)["id"] == rosa


def test_turning_protection_back_on(monkeypatch, fake_tavily):
    """After resume, Rosa is protected again and scam calls alert Ana."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/pause")

    resumed = client.post(f"/api/enrollments/{rosa}/resume")
    call = scam_call_for(rosa)
    outcome = call_monitor.check_live_call(call["id"], "Caller: Buy gift cards.")

    assert resumed.json()["status"] == "active"
    assert outcome["alert_sent"] is True


def test_cant_pause_someone_who_never_said_yes():
    """Pausing only works once the senior said YES. Pending gives you a 409."""
    response = client.post(
        "/api/enrollments",
        json={
            "senior_name": "Rosa",
            "senior_phone": SENIOR_PHONE,
            "family_name": "Ana",
            "family_phone": FAMILY_PHONE,
        },
    )
    rosa = response.json()["id"]

    assert client.post(f"/api/enrollments/{rosa}/pause").status_code == 409
    assert client.post(f"/api/enrollments/{rosa}/resume").status_code == 409


def test_stop_still_works_while_paused():
    """Rosa can text STOP while paused, and then resume can't turn her back on."""
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/pause")

    client.post("/twilio/sms", data={"From": SENIOR_PHONE, "Body": "STOP"})

    assert storage.get_enrollment(rosa)["status"] == "revoked"
    assert client.post(f"/api/enrollments/{rosa}/resume").status_code == 409


def test_cant_sign_up_a_paused_senior_again():
    """Signing Rosa up again while she's paused says to turn her back on instead."""
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/pause")

    again = client.post(
        "/api/enrollments",
        json={
            "senior_name": "Rosa",
            "senior_phone": SENIOR_PHONE,
            "family_name": "Ana",
            "family_phone": FAMILY_PHONE,
        },
    )

    assert again.status_code == 409
    assert "paused" in again.json()["error"]


# Older databases


def test_an_older_database_gets_the_new_columns(tmp_path, monkeypatch):
    """A database made before the call history existed still works, with the new columns added."""
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE calls (id TEXT PRIMARY KEY, enrollment_id TEXT NOT NULL)")
    old.execute("INSERT INTO calls (id, enrollment_id) VALUES ('c-old', 'rosa')")
    old.commit()
    old.close()
    monkeypatch.setenv("DATABASE_PATH", str(path))

    with storage.connect() as db:
        columns = [row["name"] for row in db.execute("PRAGMA table_info(calls)").fetchall()]
        old_call = dict(db.execute("SELECT * FROM calls WHERE id = 'c-old'").fetchone())

    assert "risk_score" in columns
    assert "alerted_at" in columns
    assert old_call["risk_score"] is None
