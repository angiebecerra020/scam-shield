"""
test_devices.py — Tests for landlines and the senior's private device
(app/devices.py, plus the landline consent call in app/consent.py).

How it fits in: the senior's number forwards to Scam Shield, so we ring them
on a private device instead: a calling app (cell) or an adapter (landline).
Landlines can't get texts, so we ask for consent with a phone call. These
tests check both paths, and that a landline senior can still call out.

Demo mode is on (see conftest.py), so no real calls are placed. Run with:  pytest
"""

import jwt
from fastapi.testclient import TestClient

from app import calls, storage
from app.alerts import DEMO_OUTBOX
from app.main import app

client = TestClient(app)

SENIOR_PHONE = "+15555550100"
FAMILY_PHONE = "+15555550101"
SCAMMER_PHONE = "+15555550199"
SIP_DOMAIN = "scamshield.sip.twilio.com"


def sign_up(phone_type: str, **changes):
    """Send the sign-up form for Rosa with the given kind of phone."""
    form = {
        "senior_name": "Rosa",
        "senior_phone": SENIOR_PHONE,
        "family_name": "Ana",
        "family_phone": FAMILY_PHONE,
        "phone_type": phone_type,
    }
    form.update(changes)
    return client.post("/api/enrollments", json=form)


def press_key(enrollment_id: str, digits: str, called: str = SENIOR_PHONE):
    """Pretend Twilio is telling us which key Rosa pressed on the consent call."""
    return client.post(
        f"/twilio/consent-answer?enrollment_id={enrollment_id}",
        data={"To": called, "Digits": digits},
    )


def status_of(enrollment_id: str) -> str:
    return client.get(f"/api/enrollments/{enrollment_id}").json()["status"]


# ----- Landline consent: by phone call, not text -----


def test_landline_senior_gets_a_phone_call_not_a_text():
    response = sign_up("landline")

    assert response.status_code == 201
    assert DEMO_OUTBOX == []  # landlines can't get texts
    assert calls.DEMO_CALL_LOG == [{"to": SENIOR_PHONE, "who": "consent", "conference": None}]


def test_consent_call_asks_them_to_press_1_or_2():
    enrollment_id = sign_up("landline").json()["id"]

    response = client.post(f"/twilio/consent-call?enrollment_id={enrollment_id}")

    assert "<Gather" in response.text
    assert "press 1" in response.text
    assert "Ana" in response.text


def test_consent_call_is_spoken_in_spanish_for_spanish_speakers():
    enrollment_id = sign_up("landline", senior_language="es").json()["id"]

    response = client.post(f"/twilio/consent-call?enrollment_id={enrollment_id}")

    assert "marque 1" in response.text
    assert 'language="es-US"' in response.text


def test_pressing_1_turns_protection_on():
    enrollment_id = sign_up("landline").json()["id"]

    response = press_key(enrollment_id, "1")

    assert status_of(enrollment_id) == "active"
    assert "Scam Shield is now on" in response.text
    assert DEMO_OUTBOX[-1]["to"] == FAMILY_PHONE
    assert "said YES" in DEMO_OUTBOX[-1]["body"]


def test_pressing_2_means_no():
    enrollment_id = sign_up("landline").json()["id"]

    press_key(enrollment_id, "2")

    assert status_of(enrollment_id) == "declined"


def test_other_keys_ask_again():
    enrollment_id = sign_up("landline").json()["id"]

    response = press_key(enrollment_id, "7")

    assert status_of(enrollment_id) == "pending"
    assert "<Redirect" in response.text


def test_key_press_on_a_call_to_a_different_number_does_nothing():
    enrollment_id = sign_up("landline").json()["id"]

    press_key(enrollment_id, "1", called=SCAMMER_PHONE)

    assert status_of(enrollment_id) == "pending"


def test_unknown_phone_type_is_rejected():
    assert sign_up("fax").status_code == 400


# ----- Ringing the senior's private device -----


def test_landline_calls_ring_the_adapter(monkeypatch):
    monkeypatch.setenv("TWILIO_SIP_DOMAIN", SIP_DOMAIN)
    enrollment_id = sign_up("landline").json()["id"]
    press_key(enrollment_id, "1")
    device_id = storage.get_enrollment(enrollment_id)["device_id"]

    client.post(
        "/twilio/voice",
        data={"From": SCAMMER_PHONE, "CallSid": "CA1", "ForwardedFrom": SENIOR_PHONE},
    )

    senior_leg = [c for c in calls.DEMO_CALL_LOG if c["who"] == "senior"][0]
    assert senior_leg["to"] == f"sip:{device_id}@{SIP_DOMAIN}"


def test_landline_without_consent_still_rings_the_adapter_without_listening(monkeypatch):
    monkeypatch.setenv("TWILIO_SIP_DOMAIN", SIP_DOMAIN)
    sign_up("landline")

    response = client.post(
        "/twilio/voice",
        data={"From": SCAMMER_PHONE, "CallSid": "CA1", "ForwardedFrom": SENIOR_PHONE},
    )

    assert "<Sip>sip:senior-" in response.text
    assert "<Conference" not in response.text


def test_dashboard_shows_setup_details_for_each_phone_type(monkeypatch):
    monkeypatch.setenv("TWILIO_SIP_DOMAIN", SIP_DOMAIN)

    cell = sign_up("cell").json()
    landline = sign_up("landline", senior_phone="+15555550102").json()

    assert cell["setup"]["forward_to"] == "+15555550150"
    assert "/phone/" in cell["setup"]["app_link"]
    assert landline["setup"]["adapter_username"].startswith("senior-")
    assert landline["setup"]["adapter_domain"] == SIP_DOMAIN
    assert "app_link" not in landline["setup"]


# ----- The calling app (cell phones) -----


def app_key(enrollment_id: str) -> str:
    return storage.get_enrollment(enrollment_id)["device_key"]


def test_calling_app_page_loads():
    response = client.get("/phone/anything")

    assert response.status_code == 200
    assert "Scam Shield" in response.text


def test_calling_app_in_demo_mode_has_no_login():
    enrollment_id = sign_up("cell").json()["id"]

    details = client.get(f"/api/phone/{app_key(enrollment_id)}").json()

    assert details == {"senior_name": "Rosa", "demo_mode": True, "token": None}


def test_calling_app_login_can_only_receive_calls_for_this_senior(monkeypatch):
    enrollment_id = sign_up("cell").json()["id"]
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACfake")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SKfake")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "fake-secret-that-is-long-enough-for-hs256")

    token = client.get(f"/api/phone/{app_key(enrollment_id)}").json()["token"]
    claims = jwt.decode(token, "fake-secret-that-is-long-enough-for-hs256", algorithms=["HS256"])

    voice = claims["grants"]["voice"]
    assert claims["grants"]["identity"] == storage.get_enrollment(enrollment_id)["device_id"]
    assert voice["incoming"]["allow"] is True
    assert "outgoing" not in voice


def test_calling_app_says_so_when_twilio_api_key_is_missing(monkeypatch):
    enrollment_id = sign_up("cell").json()["id"]
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "")

    response = client.get(f"/api/phone/{app_key(enrollment_id)}")

    assert response.status_code == 503


def test_wrong_calling_app_link_is_rejected():
    assert client.get("/api/phone/not-a-real-key").status_code == 404


def test_landline_has_no_calling_app():
    enrollment_id = sign_up("landline").json()["id"]

    assert client.get(f"/api/phone/{app_key(enrollment_id)}").status_code == 404


# ----- Landline senior calling out through the adapter -----


def adapter_dials(dialed: str, device_id: str):
    """Pretend Twilio is telling us the adapter dialed a number."""
    return client.post(
        "/twilio/adapter-call",
        data={"From": f"sip:{device_id}@{SIP_DOMAIN}", "To": f"sip:{dialed}@{SIP_DOMAIN}"},
    )


def test_landline_senior_can_call_out_and_shows_their_own_number():
    enrollment_id = sign_up("landline").json()["id"]
    device_id = storage.get_enrollment(enrollment_id)["device_id"]

    response = adapter_dials("(555) 555-0123", device_id)

    assert "<Number>+15555550123</Number>" in response.text
    assert f'callerId="{SENIOR_PHONE}"' in response.text


def test_911_always_goes_through():
    response = adapter_dials("911", "not-a-real-adapter")

    assert "<Number>911</Number>" in response.text


def test_unknown_adapter_cant_call_out():
    response = adapter_dials("5555550123", "not-a-real-adapter")

    assert "<Dial" not in response.text
