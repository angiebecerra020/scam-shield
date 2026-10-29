"""
test_call_again.py

Tests for the dashboard's "Call them again" button (app/call_again.py).

How it fits in: demo mode is on (conftest.py), so the consent call only goes
in the demo log and no phone rings.
"""

import pytest
from fastapi.testclient import TestClient

from app import call_again, calls, storage
from app.main import app

client = TestClient(app)


def save_senior(status: str = "pending", ask_by: str = "call") -> str:
    """
    Saves a pretend senior we asked for their YES, and gives back their ID.

    Example:
        enrollment_id = save_senior()
    """
    enrollment_id = f"rosa-{status}-{ask_by}"
    storage.save_enrollment(
        {
            "id": enrollment_id,
            "senior_name": "Rosa",
            "senior_phone": "+15555550142",
            "family_name": "Ana",
            "family_phone": "+15555550143",
            "phone_type": "cell",
            "device_id": "senior-test",
            "device_key": "key-test",
            "senior_language": "en",
            "family_language": "en",
            "status": status,
            "created_at": storage.now_text(),
            "answered_at": None,
            "ask_by": ask_by,
        }
    )
    return enrollment_id


@pytest.fixture(autouse=True)
def fresh_counts(monkeypatch):
    """Each test starts with nobody called again, and real consent calls off."""
    monkeypatch.setenv("REAL_CONSENT_CALLS", "false")
    call_again.CALLED_AGAIN.clear()


def test_calling_again_rings_the_senior():
    """The button places the consent call again."""
    enrollment_id = save_senior()

    response = client.post(f"/api/enrollments/{enrollment_id}/call-again")

    assert response.status_code == 200
    assert calls.DEMO_CALL_LOG[-1] == {"to": "+15555550142", "who": "consent", "conference": None}


def test_not_twice_in_a_minute():
    """A second tap right away asks the family to wait."""
    enrollment_id = save_senior()
    client.post(f"/api/enrollments/{enrollment_id}/call-again")

    response = client.post(f"/api/enrollments/{enrollment_id}/call-again")

    assert response.status_code == 429


def test_no_call_after_they_answered():
    """Once they said YES, there's nothing to call about."""
    enrollment_id = save_senior(status="active")

    response = client.post(f"/api/enrollments/{enrollment_id}/call-again")

    assert response.status_code == 409


def test_no_call_when_we_asked_by_text():
    """If we asked by text, the button doesn't call them."""
    enrollment_id = save_senior(ask_by="text")

    response = client.post(f"/api/enrollments/{enrollment_id}/call-again")

    assert response.status_code == 409


def test_remove_deletes_the_senior_and_their_calls():
    """The red Remove button deletes the person and every call we saved for them."""
    enrollment_id = save_senior()
    with storage.connect() as db:
        db.execute(
            "INSERT INTO calls (id, enrollment_id, conference_name, join_token, status, started_at) "
            "VALUES ('c1', ?, 'room', 'token', 'ended', ?)",
            (enrollment_id, storage.now_text()),
        )

    response = client.delete(f"/api/enrollments/{enrollment_id}")

    assert response.json() == {"removed": "Rosa"}
    assert storage.get_enrollment(enrollment_id) is None
    assert storage.get_call("c1") is None


def test_removed_senior_can_be_asked_again():
    """After Remove, the same phone isn't blocked by "we already asked this person"."""
    enrollment_id = save_senior()
    client.delete(f"/api/enrollments/{enrollment_id}")

    assert storage.find_enrollments_for_senior("+15555550142") == []
