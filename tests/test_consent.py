"""
test_consent.py — Tests for the consent check (app/consent.py).

How it fits in: Scam Shield must NEVER listen to someone's calls unless they
said YES from their own phone. These tests sign up a fake senior, pretend to
be them texting back, and check that only a YES turns protection on.

All numbers are 555-01XX numbers, which are reserved for fiction. Demo mode is
on (see conftest.py), so no real texts are sent. Run with:  pytest
"""

from datetime import timedelta

from fastapi.testclient import TestClient

from app import storage
from app.alerts import DEMO_OUTBOX
from app.consent import read_answer
from app.main import app

client = TestClient(app)

SENIOR_PHONE = "+15555550100"
FAMILY_PHONE = "+15555550101"


def sign_up(**changes):
    """
    Send the sign-up form, like the family member would on the dashboard.

    Input:  changes — any form fields to change, e.g. senior_language="es"
    Output: the web response
    """
    form = {
        "senior_name": "Rosa",
        "senior_phone": "(555) 555-0100",
        "family_name": "Ana",
        "family_phone": "555.555.0101",
        "senior_language": "en",
        "family_language": "en",
    }
    form.update(changes)
    return client.post("/api/enrollments", json=form)


def senior_texts(body: str, from_phone: str = SENIOR_PHONE):
    """Pretend to be Twilio passing on a text the senior sent us."""
    return client.post("/twilio/sms", data={"From": from_phone, "Body": body})


def status_of(enrollment_id: str) -> str:
    """Ask the dashboard route for an enrollment's status."""
    return client.get(f"/api/enrollments/{enrollment_id}").json()["status"]


def test_sign_up_texts_the_senior_and_waits_for_their_answer():
    response = sign_up()

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    # Exactly one text, to the SENIOR, naming who asked.
    assert len(DEMO_OUTBOX) == 1
    assert DEMO_OUTBOX[0]["to"] == SENIOR_PHONE
    assert "Ana" in DEMO_OUTBOX[0]["body"]
    assert "YES" in DEMO_OUTBOX[0]["body"]


def test_dashboard_hides_most_of_each_phone_number():
    body = sign_up().json()

    assert body["senior_phone"] == "•••-•••-0100"
    assert "5555550100" not in str(body)


def test_yes_from_the_seniors_phone_turns_protection_on():
    enrollment_id = sign_up().json()["id"]

    response = senior_texts("Yes!")

    assert status_of(enrollment_id) == "active"
    assert "watching your calls" in response.text
    # The family member hears the good news.
    assert DEMO_OUTBOX[-1]["to"] == FAMILY_PHONE
    assert "said YES" in DEMO_OUTBOX[-1]["body"]


def test_yes_from_a_different_phone_does_nothing():
    enrollment_id = sign_up().json()["id"]

    response = senior_texts("YES", from_phone="+15555550199")

    assert status_of(enrollment_id) == "pending"
    # We don't answer strangers.
    assert "<Message>" not in response.text


def test_no_means_no():
    enrollment_id = sign_up().json()["id"]

    senior_texts("no")

    assert status_of(enrollment_id) == "declined"
    assert "said NO" in DEMO_OUTBOX[-1]["body"]


def test_unclear_reply_asks_again_and_stays_pending():
    enrollment_id = sign_up().json()["id"]

    response = senior_texts("who is this?")

    assert status_of(enrollment_id) == "pending"
    assert "Please reply YES" in response.text


def test_stop_turns_protection_off_later():
    enrollment_id = sign_up().json()["id"]
    senior_texts("YES")

    senior_texts("STOP")

    assert status_of(enrollment_id) == "revoked"
    assert "turned Scam Shield off" in DEMO_OUTBOX[-1]["body"]


def test_spanish_speaking_senior_gets_spanish_texts_and_can_answer_si():
    enrollment_id = sign_up(senior_language="es").json()["id"]
    assert "Responda SI" in DEMO_OUTBOX[0]["body"]

    response = senior_texts("Sí")

    assert status_of(enrollment_id) == "active"
    assert "Gracias" in response.text
    # Ana chose English, so her update is in English.
    assert "said YES" in DEMO_OUTBOX[-1]["body"]


def test_cant_ask_again_while_waiting_for_an_answer():
    sign_up()

    second = sign_up(family_name="Luis", family_phone="555-555-0102")

    assert second.status_code == 409
    assert len(DEMO_OUTBOX) == 1  # no second text to the senior


def test_cant_ask_again_soon_after_a_no():
    sign_up()
    senior_texts("NO")

    again = sign_up()

    assert again.status_code == 409
    assert "said no recently" in again.json()["error"]


def test_request_expires_after_24_hours_and_yes_no_longer_counts():
    enrollment_id = sign_up().json()["id"]
    # Move the sign-up back in time by 25 hours.
    old_time = (storage.parse_time(storage.now_text()) - timedelta(hours=25)).isoformat()
    with storage.connect() as db:
        db.execute("UPDATE enrollments SET created_at = ?", (old_time,))

    senior_texts("YES")

    assert status_of(enrollment_id) == "expired"
    # And the family can ask again.
    assert sign_up().status_code == 201


def test_names_with_links_are_rejected():
    response = sign_up(family_name="Visit scam.com now")

    assert response.status_code == 400
    assert DEMO_OUTBOX == []


def test_bad_phone_number_is_rejected():
    response = sign_up(senior_phone="12345")

    assert response.status_code == 400
    assert "phone" in response.json()["error"]


def test_reply_words_are_understood():
    assert read_answer("YES") == "yes"
    assert read_answer(" sí, claro ") == "yes"
    assert read_answer("No thanks") == "no"
    assert read_answer("Stop") == "stop"
    assert read_answer("") == "unclear"


def test_fake_twilio_requests_are_refused_in_live_mode(monkeypatch):
    """Outside demo mode, a text webhook without Twilio's signature is ignored."""
    enrollment_id = sign_up().json()["id"]
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "fake-token")

    response = senior_texts("YES")

    assert response.status_code == 403
    monkeypatch.setenv("DEMO_MODE", "true")
    assert status_of(enrollment_id) == "pending"
