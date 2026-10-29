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


# ----- Canceling Scam Shield for good -----


def test_canceling_stops_listening_and_tells_the_senior():
    rosa = sign_up_rosa()

    response = client.post(f"/api/enrollments/{rosa}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "canceled"
    to_rosa = [text["body"] for text in alerts.DEMO_OUTBOX if text["to"] == SENIOR_PHONE]
    assert "Ana canceled Scam Shield" in to_rosa[-1]


def test_canceled_calls_ring_like_normal_without_listening():
    """Her phone may still forward to us, so her calls must still get through."""
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/cancel")

    xml = calls.handle_incoming_call(SCAMMER_PHONE, "CA123", SENIOR_PHONE)

    assert "<Conference" not in xml
    assert "<Dial" in xml


def test_canceled_senior_still_found_when_the_carrier_hides_whose_phone_it_is():
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/cancel")

    assert calls.find_senior_for_call(None)["id"] == rosa


def test_cancel_cant_be_undone_from_the_dashboard():
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/cancel")

    assert client.post(f"/api/enrollments/{rosa}/resume").status_code == 409
    assert client.post(f"/api/enrollments/{rosa}/cancel").status_code == 409


def test_canceling_a_paused_senior_works():
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/pause")

    assert client.post(f"/api/enrollments/{rosa}/cancel").json()["status"] == "canceled"


def test_canceling_before_they_answer_means_their_yes_no_longer_counts():
    response = client.post(
        "/api/enrollments",
        json={"senior_name": "Rosa", "senior_phone": SENIOR_PHONE, "family_name": "Ana", "family_phone": FAMILY_PHONE},
    )
    rosa = response.json()["id"]
    client.post(f"/api/enrollments/{rosa}/cancel")
    texts_before = len(alerts.DEMO_OUTBOX)

    client.post("/twilio/sms", data={"From": SENIOR_PHONE, "Body": "YES"})

    assert storage.get_enrollment(rosa)["status"] == "canceled"
    # Rosa never said YES, so she doesn't get a "canceled" text, and her late YES gets no answer
    assert len(alerts.DEMO_OUTBOX) == texts_before


def test_family_can_sign_them_up_again_after_canceling():
    """A new sign-up asks Rosa again, and her new YES turns protection on."""
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/cancel")

    again = sign_up_rosa()

    assert again != rosa
    assert storage.get_enrollment(again)["status"] == "active"
    # Rosa now has two sign-ups (one canceled), and her calls still find the active one
    assert calls.find_senior_for_call(None)["id"] == again


def test_other_families_cant_cancel_your_senior(login_on):
    rosa = sign_up_rosa({"Authorization": "Bearer ana-token"})

    response = client.post(f"/api/enrollments/{rosa}/cancel", headers={"Authorization": "Bearer bob-token"})

    assert response.status_code == 404
    assert storage.get_enrollment(rosa)["status"] == "active"


# ----- The senior calls our number to cancel -----


def senior_calls_us(forwarded_from: str | None = None):
    """Pretend Rosa called the Scam Shield number from her own phone."""
    data = {"From": SENIOR_PHONE, "CallSid": "CA-rosa"}
    if forwarded_from:
        data["ForwardedFrom"] = forwarded_from
    return client.post("/twilio/voice", data=data)


def senior_presses(enrollment_id: str, digits: str, from_phone: str = SENIOR_PHONE):
    """Pretend Twilio is telling us which key Rosa pressed in the menu."""
    return client.post(
        f"/twilio/senior-menu-answer?enrollment_id={enrollment_id}",
        data={"From": from_phone, "Digits": digits},
    )


def test_senior_calling_us_hears_press_2_to_cancel():
    sign_up_rosa()

    response = senior_calls_us()

    assert "<Gather" in response.text
    assert "cancel Scam Shield from listening to your conversations, press 2" in response.text
    assert "<Conference" not in response.text


def test_pressing_2_cancels_and_tells_the_family():
    rosa = sign_up_rosa()

    response = senior_presses(rosa, "2")

    assert storage.get_enrollment(rosa)["status"] == "revoked"
    assert "Scam Shield is now canceled" in response.text
    assert "turned Scam Shield off" in texts_to_family()[-1]
    # Rosa said no herself, so the family can't turn it back on
    assert client.post(f"/api/enrollments/{rosa}/resume").status_code == 409


def test_pressing_1_keeps_it_on():
    rosa = sign_up_rosa()

    response = senior_presses(rosa, "1")

    assert storage.get_enrollment(rosa)["status"] == "active"
    assert "stays on" in response.text


def test_other_keys_ask_the_senior_again():
    rosa = sign_up_rosa()

    response = senior_presses(rosa, "7")

    assert storage.get_enrollment(rosa)["status"] == "active"
    assert "<Redirect" in response.text


def test_pressing_2_from_a_different_phone_does_nothing():
    rosa = sign_up_rosa()

    senior_presses(rosa, "2", from_phone=SCAMMER_PHONE)

    assert storage.get_enrollment(rosa)["status"] == "active"


def test_a_paused_senior_can_cancel_too():
    rosa = sign_up_rosa()
    client.post(f"/api/enrollments/{rosa}/pause")

    assert "press 2" in senior_calls_us().text
    senior_presses(rosa, "2")

    assert storage.get_enrollment(rosa)["status"] == "revoked"


def test_calls_forwarded_from_the_seniors_phone_still_get_protected():
    """A scammer calling Rosa forwards to us with ForwardedFrom; that's not Rosa calling us."""
    sign_up_rosa()

    xml = client.post(
        "/twilio/voice",
        data={"From": SCAMMER_PHONE, "CallSid": "CA123", "ForwardedFrom": SENIOR_PHONE},
    ).text

    assert "press 2" not in xml
    assert "<Conference" in xml


def test_strangers_calling_us_dont_get_the_menu():
    sign_up_rosa()

    xml = client.post("/twilio/voice", data={"From": SCAMMER_PHONE, "CallSid": "CA123"}).text

    assert "press 2" not in xml


def test_the_menu_is_spoken_in_spanish_for_spanish_speakers():
    response = client.post(
        "/api/enrollments",
        json={
            "senior_name": "Rosa",
            "senior_phone": SENIOR_PHONE,
            "family_name": "Ana",
            "family_phone": FAMILY_PHONE,
            "senior_language": "es",
        },
    )
    client.post("/twilio/sms", data={"From": SENIOR_PHONE, "Body": "SI"})

    xml = senior_calls_us().text

    assert "marque 2" in xml
    assert 'language="es-US"' in xml
    assert response.status_code == 201


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


# "Was this a scam?"


def test_the_family_can_say_a_call_was_a_false_alarm(monkeypatch, fake_tavily):
    """Ana says the 92 call was a false alarm. It's saved with the call and shows in the list."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = scam_call_for(sign_up_rosa())
    call_monitor.check_live_call(call["id"], "Caller: Grandma, buy gift cards.")

    answered = client.post(f"/api/calls/{call['id']}/answer", json={"answer": "not_scam"})
    past_call = client.get("/api/family").json()["seniors"][0]["calls"][0]

    assert answered.json()["family_answer"] == "not_scam"
    assert past_call["family_answer"] == "not_scam"
    assert storage.get_call(call["id"])["family_answered_at"] is not None


def test_the_family_can_change_their_answer(monkeypatch, fake_tavily):
    """Saying "scam" after "false alarm" keeps the newest answer."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = scam_call_for(sign_up_rosa())
    call_monitor.check_live_call(call["id"], "Caller: Buy gift cards.")

    client.post(f"/api/calls/{call['id']}/answer", json={"answer": "not_scam"})
    client.post(f"/api/calls/{call['id']}/answer", json={"answer": "scam"})

    assert client.get(f"/api/calls/{call['id']}").json()["family_answer"] == "scam"


def test_a_call_starts_with_no_answer(monkeypatch, fake_tavily):
    """Until the family says something, the answer is empty (not a guess)."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = scam_call_for(sign_up_rosa())
    call_monitor.check_live_call(call["id"], "Caller: Buy gift cards.")

    assert client.get(f"/api/calls/{call['id']}").json()["family_answer"] is None


def test_only_scam_or_not_scam_is_an_answer(monkeypatch, fake_tavily):
    """Any other answer gives you a 400 and saves nothing."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = scam_call_for(sign_up_rosa())
    call_monitor.check_live_call(call["id"], "Caller: Buy gift cards.")

    response = client.post(f"/api/calls/{call['id']}/answer", json={"answer": "maybe"})

    assert response.status_code == 400
    assert storage.get_call(call["id"])["family_answer"] is None


def test_other_families_cant_answer_for_your_calls(login_on, monkeypatch, fake_tavily):
    """Bob can't answer "Was this a scam?" on Rosa's call."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    call = scam_call_for(sign_up_rosa(as_user("ana-token")))
    call_monitor.check_live_call(call["id"], "Caller: Buy gift cards.")

    response = client.post(
        f"/api/calls/{call['id']}/answer", json={"answer": "not_scam"}, headers=as_user("bob-token")
    )

    assert response.status_code == 404
    assert storage.get_call(call["id"])["family_answer"] is None


# The scam list: warn or block a number if it calls again


def checked_scam_call(monkeypatch, headers: dict | None = None) -> tuple[str, dict]:
    """Rosa gets the 92 scam call. Gives you (Rosa's ID, the call)."""
    pretend_nemotron(monkeypatch, SCAM_RESULT)
    rosa = sign_up_rosa(headers)
    call = scam_call_for(rosa)
    call_monitor.check_live_call(call["id"], "Caller: Grandma, buy gift cards.")
    return rosa, call


def test_blocked_numbers_get_a_busy_signal_and_show_in_the_history(monkeypatch, fake_tavily):
    """After Ana blocks the scammer, their next call is rejected and never rings Rosa."""
    rosa, call = checked_scam_call(monkeypatch)
    calls.DEMO_CALL_LOG.clear()

    picked = client.post(f"/api/calls/{call['id']}/scam-list", json={"choice": "block"})
    xml = calls.handle_incoming_call(SCAMMER_PHONE, "CA-again", SENIOR_PHONE)
    newest = client.get("/api/family").json()["seniors"][0]["calls"][0]

    assert picked.json()["number_on_list"] == "block"
    assert "<Reject" in xml
    assert calls.DEMO_CALL_LOG == []
    assert newest["scam_list"] == "block"
    assert newest["status"] == "ended"


def test_warned_numbers_ring_and_alert_the_family_right_away(monkeypatch, fake_tavily):
    """With "warn", the call still rings Rosa, and Ana is alerted before Nemotron says anything."""
    rosa, call = checked_scam_call(monkeypatch)
    client.post(f"/api/calls/{call['id']}/scam-list", json={"choice": "warn"})
    alerts.DEMO_OUTBOX.clear()

    xml = calls.handle_incoming_call(SCAMMER_PHONE, "CA-again", SENIOR_PHONE)

    family_texts = texts_to_family()
    assert "<Conference" in xml
    assert "/join/" in family_texts[0]
    assert "one you reported as a scam" in family_texts[1]


def test_a_warned_call_doesnt_get_a_second_alert_from_nemotron(monkeypatch, fake_tavily):
    """Once we warned Ana at the start, a high score later doesn't text her again."""
    rosa, call = checked_scam_call(monkeypatch)
    client.post(f"/api/calls/{call['id']}/scam-list", json={"choice": "warn"})
    calls.handle_incoming_call(SCAMMER_PHONE, "CA-again", SENIOR_PHONE)
    newest = client.get("/api/family").json()["seniors"][0]["calls"][0]
    alerts.DEMO_OUTBOX.clear()

    outcome = call_monitor.check_live_call(newest["id"], "Caller: Grandma, buy gift cards.")

    assert outcome["alert_sent_now"] is False
    assert texts_to_family() == []


def test_do_nothing_takes_the_number_off_the_list(monkeypatch, fake_tavily):
    """Picking "Do nothing" after "Block it" lets the number ring like any other call."""
    rosa, call = checked_scam_call(monkeypatch)
    client.post(f"/api/calls/{call['id']}/scam-list", json={"choice": "block"})

    picked = client.post(f"/api/calls/{call['id']}/scam-list", json={"choice": "none"})
    xml = calls.handle_incoming_call(SCAMMER_PHONE, "CA-again", SENIOR_PHONE)

    assert picked.json()["number_on_list"] is None
    assert "<Reject" not in xml


def test_the_list_does_nothing_while_protection_is_paused(monkeypatch, fake_tavily):
    """Paused means we stay out of Rosa's calls completely, even for blocked numbers."""
    rosa, call = checked_scam_call(monkeypatch)
    client.post(f"/api/calls/{call['id']}/scam-list", json={"choice": "block"})
    client.post(f"/api/enrollments/{rosa}/pause")

    xml = calls.handle_incoming_call(SCAMMER_PHONE, "CA-again", SENIOR_PHONE)

    assert "<Reject" not in xml


def test_one_familys_list_doesnt_block_calls_for_another(login_on, monkeypatch, fake_tavily):
    """Ana blocks the number for Rosa. When it calls Bob's grandpa, it still rings."""
    rosa, call = checked_scam_call(monkeypatch, as_user("ana-token"))
    client.post(f"/api/calls/{call['id']}/scam-list", json={"choice": "block"}, headers=as_user("ana-token"))
    # Bob protects his grandpa, who said YES too.
    client.post(
        "/api/enrollments",
        json={
            "senior_name": "Jorge",
            "senior_phone": "+13055550188",
            "family_name": "Bob",
            "family_phone": "+13055550189",
        },
        headers=as_user("bob-token"),
    )
    client.post("/twilio/sms", data={"From": "+13055550188", "Body": "YES"})

    xml = calls.handle_incoming_call(SCAMMER_PHONE, "CA-bob", "+13055550188")

    assert "<Reject" not in xml
    assert "<Conference" in xml


def test_other_families_cant_change_your_list(login_on, monkeypatch, fake_tavily):
    """Bob can't put the number from Rosa's call on any list."""
    rosa, call = checked_scam_call(monkeypatch, as_user("ana-token"))

    response = client.post(
        f"/api/calls/{call['id']}/scam-list", json={"choice": "block"}, headers=as_user("bob-token")
    )

    assert response.status_code == 404
    assert storage.find_scam_number(ANA["id"], SCAMMER_PHONE) is None


def test_only_warn_block_or_none_is_a_choice(monkeypatch, fake_tavily):
    """Any other choice gives you a 400."""
    rosa, call = checked_scam_call(monkeypatch)

    response = client.post(f"/api/calls/{call['id']}/scam-list", json={"choice": "forever"})

    assert response.status_code == 400
