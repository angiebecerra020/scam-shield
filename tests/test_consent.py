"""
test_consent.py — Tests for the consent check (app/consent.py).

How it fits in: Scam Shield must NEVER listen to someone's calls unless they
said YES from their own phone. These tests sign up a fake senior (we call
them to ask), pretend to be them answering, and check that only a YES turns
protection on. Text replies still count too: older sign-ups were asked by
text, and STOP by text works any time.

All numbers are 555-01XX numbers, which are reserved for fiction. Demo mode is
on (see conftest.py), so no real texts are sent. Run with:  pytest
"""

from datetime import timedelta

import pytest

from fastapi.testclient import TestClient

from app import consent, storage
from app.alerts import DEMO_OUTBOX
from app.calls import DEMO_CALL_LOG
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


def test_sign_up_calls_the_senior_and_waits_for_their_answer():
    response = sign_up()

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["ask_by"] == "call"
    # Exactly one call, to the SENIOR, and no text.
    assert DEMO_CALL_LOG == [{"to": SENIOR_PHONE, "who": "consent", "conference": None}]
    assert DEMO_OUTBOX == []


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


def test_spanish_speaking_senior_can_answer_si():
    enrollment_id = sign_up(senior_language="es").json()["id"]

    response = senior_texts("Sí")

    assert status_of(enrollment_id) == "active"
    assert "Gracias" in response.text
    # Ana chose English, so her update is in English.
    assert "said YES" in DEMO_OUTBOX[-1]["body"]


def test_cant_ask_again_while_waiting_for_an_answer():
    sign_up()

    second = sign_up(family_name="Luis", family_phone="555-555-0102")

    assert second.status_code == 409
    assert len(DEMO_CALL_LOG) == 1  # no second call to the senior


def test_family_can_ask_again_after_one_no():
    """A NO can be a mistake, so the family gets to ask again."""
    sign_up()
    senior_texts("NO")

    again = sign_up()

    assert again.status_code == 201


def test_after_three_nos_we_wait_30_days_and_point_to_our_email():
    for _ in range(3):
        assert sign_up().status_code == 201
        senior_texts("NO")

    fourth = sign_up()

    assert fourth.status_code == 409
    assert "said no 3 times" in fourth.json()["error"]
    assert "scam.shield.demo@gmail.com" in fourth.json()["error"]


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


def test_senior_phone_without_an_area_code_is_stopped_with_a_reminder():
    response = sign_up(senior_phone="555-0100")

    assert response.status_code == 400
    assert "area code" in response.json()["error"]
    # Nobody is called, and nothing is saved.
    assert DEMO_CALL_LOG == []
    assert storage.find_all_enrollments() == []


def test_family_phone_without_an_area_code_is_stopped_with_a_reminder():
    response = sign_up(family_phone="5550101")

    assert response.status_code == 400
    assert "Your phone is missing the area code" in response.json()["error"]
    assert DEMO_CALL_LOG == []


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


# We only speak English and Spanish. Anything else becomes English.


def test_other_languages_fall_back_to_english():
    """A sign-up that asks for a language we don't have (like Creole) gets English."""
    response = sign_up(senior_language="ht", family_language="ht")

    assert response.status_code == 201
    senior_texts("YES")
    assert "said YES" in DEMO_OUTBOX[-1]["body"]


# ----- We always ask with a phone call -----


def test_cell_phone_is_called():
    response = sign_up(phone_type="cell")

    assert response.json()["ask_by"] == "call"
    assert DEMO_CALL_LOG[0]["to"] == SENIOR_PHONE


def test_landline_is_called():
    response = sign_up(phone_type="landline")

    assert response.json()["ask_by"] == "call"


def test_asking_by_text_is_turned_away():
    """Texts from our number weren't arriving, so we don't offer them anymore."""
    for phone_type in ("cell", "landline"):
        response = sign_up(phone_type=phone_type, ask_by="text")

        assert response.status_code == 400
        assert "phone call" in response.json()["error"]
    assert DEMO_OUTBOX == []
    assert DEMO_CALL_LOG == []


def test_pressing_1_on_the_call_turns_protection_on():
    enrollment_id = sign_up().json()["id"]

    client.post(
        f"/twilio/consent-answer?enrollment_id={enrollment_id}",
        data={"To": SENIOR_PHONE, "Digits": "1"},
    )

    assert status_of(enrollment_id) == "active"


def test_unknown_way_to_ask_is_rejected():
    assert sign_up(ask_by="carrier pigeon").status_code == 400


def test_old_sign_ups_without_ask_by_still_show_how_we_asked():
    """Sign-ups saved before families could pick have no ask_by saved."""
    from app.consent import how_we_asked

    assert how_we_asked({"ask_by": None, "phone_type": "cell"}) == "text"
    assert how_we_asked({"ask_by": None, "phone_type": "landline"}) == "call"


def test_every_spanish_message_matches_english():
    """Every message we send or say has a Spanish version, with the same blanks to fill in."""
    from string import Formatter

    from app.languages import MESSAGES, SPOKEN_LANGUAGE

    def blanks(text):
        return {name for _, name, _, _ in Formatter().parse(text) if name}

    assert set(MESSAGES) == {"en", "es"} == set(SPOKEN_LANGUAGE)
    for key, english in MESSAGES["en"].items():
        assert blanks(MESSAGES["es"][key]) == blanks(english), key


def test_two_families_can_protect_the_same_senior():
    """Ana protects Rosa. Her brother Luis can too (Rosa gets asked again)."""
    ana = consent.start_enrollment("Rosa", "305-555-0100", "Ana", "305-555-0101", owner_id="ana")
    storage.set_enrollment_status(ana["id"], "active", answered=True)

    luis = consent.start_enrollment("Rosa", "305-555-0100", "Luis", "305-555-0102", owner_id="luis")

    assert luis["status"] == "pending"


def test_the_same_family_cant_sign_up_the_same_senior_twice():
    ana = consent.start_enrollment("Rosa", "305-555-0100", "Ana", "305-555-0101", owner_id="ana")
    storage.set_enrollment_status(ana["id"], "active", answered=True)

    with pytest.raises(consent.EnrollmentError, match="already protect"):
        consent.start_enrollment("Rosa", "305-555-0100", "Ana", "305-555-0101", owner_id="ana")
