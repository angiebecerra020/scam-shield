"""
test_calls.py — Tests for 3-way calls (app/calls.py).

How it fits in: when a call looks like a scam, the family gets a "Join call"
link that rings their phone into the call. These tests check that:
  - only seniors who said YES get their calls put in a conference room
  - the link rings the family's OWN phone, and stops working when the call ends

Demo mode is on (see conftest.py), so no real calls are placed. Run with:  pytest
"""

from fastapi.testclient import TestClient

from app import calls, storage
from app.alerts import DEMO_OUTBOX
from app.main import app

client = TestClient(app)

SENIOR_PHONE = "+15555550100"
FAMILY_PHONE = "+15555550101"
SCAMMER_PHONE = "+15555550199"
SCAM_SHIELD_NUMBER = "+15555550150"  # set in conftest.py


def sign_up_senior(say_yes: bool = True) -> str:
    """Sign up Rosa (and have her text YES, unless say_yes=False). Returns the ID."""
    response = client.post(
        "/api/enrollments",
        json={
            "senior_name": "Rosa",
            "senior_phone": SENIOR_PHONE,
            "family_name": "Ana",
            "family_phone": FAMILY_PHONE,
        },
    )
    if say_yes:
        client.post("/twilio/sms", data={"From": SENIOR_PHONE, "Body": "YES"})
    return response.json()["id"]


def call_comes_in(**extra):
    """
    Pretend Twilio is telling us a call was forwarded from Rosa's phone.

    Input: extra — more form fields, e.g. CallToken="tok123"
    """
    form = {"From": SCAMMER_PHONE, "CallSid": "CA123", "ForwardedFrom": SENIOR_PHONE}
    form.update(extra)
    return client.post("/twilio/voice", data=form)


def token_from_alert() -> str:
    """Pull the secret token out of the "Join call" link in the family's text."""
    return DEMO_OUTBOX[-1]["body"].rsplit("/join/", 1)[1]


def test_protected_call_goes_into_a_conference_room_and_rings_the_senior():
    sign_up_senior()

    response = call_comes_in()

    assert "<Conference" in response.text
    assert 'endConferenceOnExit="true"' in response.text
    assert len(calls.DEMO_CALL_LOG) == 1
    assert calls.DEMO_CALL_LOG[0]["to"] == SENIOR_PHONE
    assert calls.DEMO_CALL_LOG[0]["who"] == "senior"


def test_senior_sees_the_real_callers_number_when_twilio_sends_a_call_token():
    sign_up_senior()

    call_comes_in(CallToken="tok123")

    assert calls.DEMO_CALL_LOG[0]["shows"] == SCAMMER_PHONE


def test_senior_sees_our_number_without_a_call_token():
    sign_up_senior()

    call_comes_in()

    assert calls.DEMO_CALL_LOG[0]["shows"] == SCAM_SHIELD_NUMBER


def test_hidden_caller_falls_back_to_our_number():
    sign_up_senior()

    call_comes_in(From="Anonymous", CallToken="tok123")

    assert calls.DEMO_CALL_LOG[0]["shows"] == SCAM_SHIELD_NUMBER


def test_live_mode_passes_the_call_token_to_twilio(monkeypatch):
    """
    Outside demo mode, check exactly what we ask Twilio to do, using a fake
    Twilio client that just remembers what it was given.
    """
    sign_up_senior()
    enrollment = storage.find_active_enrollments()[0]
    sent = {}

    class FakeParticipants:
        def create(self, **options):
            sent.update(options)

    class FakeTwilio:
        def conferences(self, name):
            sent["conference"] = name
            fake = type("FakeConference", (), {})()
            fake.participants = FakeParticipants()
            return fake

    monkeypatch.setattr(calls, "twilio_client", lambda: FakeTwilio())
    monkeypatch.setenv("DEMO_MODE", "false")

    calls.start_protected_call(enrollment, SCAMMER_PHONE, "CA123", call_token="tok123")

    assert sent["to"] == SENIOR_PHONE
    assert sent["from_"] == SCAMMER_PHONE
    assert sent["call_token"] == "tok123"


def test_senior_who_hasnt_said_yes_gets_a_normal_call():
    sign_up_senior(say_yes=False)

    response = call_comes_in()

    assert "<Conference" not in response.text
    assert SENIOR_PHONE in response.text
    assert calls.DEMO_CALL_LOG == []


def test_unknown_number_hears_a_message_and_hangs_up():
    response = call_comes_in()

    assert "not set up" in response.text
    assert "<Hangup" in response.text


def test_family_alert_has_a_join_link_that_rings_the_familys_phone():
    sign_up_senior()
    started = client.post("/api/demo/scam-call").json()
    assert DEMO_OUTBOX[-1]["to"] == FAMILY_PHONE
    assert started["join_link"] in DEMO_OUTBOX[-1]["body"]
    token = token_from_alert()

    info = client.get(f"/api/join/{token}").json()
    joined = client.post(f"/api/join/{token}")

    assert info == {"senior_name": "Rosa", "status": "live"}
    assert joined.json()["status"] == "calling"
    family_leg = calls.DEMO_CALL_LOG[-1]
    assert family_leg["to"] == FAMILY_PHONE
    assert family_leg["who"] == "family"
    # The family joins the SAME room the senior is in.
    assert family_leg["conference"] == calls.DEMO_CALL_LOG[0]["conference"]


def test_join_page_loads():
    response = client.get("/join/anything")

    assert response.status_code == 200
    assert "Join" in response.text


def test_tapping_join_twice_quickly_rings_only_once():
    sign_up_senior()
    client.post("/api/demo/scam-call")
    token = token_from_alert()

    client.post(f"/api/join/{token}")
    second = client.post(f"/api/join/{token}")

    assert second.status_code == 429
    assert [c["who"] for c in calls.DEMO_CALL_LOG] == ["senior", "family"]


def test_link_stops_working_when_the_call_ends():
    sign_up_senior()
    started = client.post("/api/demo/scam-call").json()
    token = token_from_alert()
    call = storage.get_call(started["call_id"])

    client.post(
        "/twilio/conference-status",
        data={"FriendlyName": call["conference_name"], "StatusCallbackEvent": "conference-end"},
    )

    assert client.post(f"/api/join/{token}").status_code == 410


def test_link_stops_working_if_senior_turns_scam_shield_off():
    sign_up_senior()
    client.post("/api/demo/scam-call")
    token = token_from_alert()

    client.post("/twilio/sms", data={"From": SENIOR_PHONE, "Body": "STOP"})

    assert client.post(f"/api/join/{token}").status_code == 403


def test_senior_not_answering_ends_the_call():
    sign_up_senior()
    started = client.post("/api/demo/scam-call").json()

    client.post(
        f"/twilio/senior-status?call_id={started['call_id']}",
        data={"CallStatus": "no-answer"},
    )

    assert storage.get_call(started["call_id"])["status"] == "ended"


def test_wrong_link_is_rejected():
    assert client.post("/api/join/not-a-real-token").status_code == 404


def test_demo_routes_are_off_in_live_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")

    assert client.post("/api/demo/scam-call").status_code == 404
    assert client.get("/api/demo/outbox").status_code == 404
