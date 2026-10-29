"""
test_profile.py

Tests for the family member's profile (app/profile.py): their own details,
typed once and used for every senior they sign up.

How it fits in: like test_auth.py, these never talk to the real Supabase.
We swap ask_supabase_who() for a fake that knows two pretend tokens, one for
Ana and one for Ben, so we can check each family only sees their own
profile. Run them with: pytest tests/test_profile.py
"""

import pytest
from fastapi.testclient import TestClient

from app import auth, storage
from app.main import app

client = TestClient(app)

# Pretend tokens and the pretend people they belong to
ANA = {"id": "user-ana", "email": "ana@example.com"}
BEN = {"id": "user-ben", "email": "ben@example.com"}
TOKENS = {"ana-token": ANA, "ben-token": BEN}
AS_ANA = {"Authorization": "Bearer ana-token"}
AS_BEN = {"Authorization": "Bearer ben-token"}

# 555-01XX numbers are reserved for fiction, so they never reach a real person
ROSA = {"senior_name": "Rosa", "senior_phone": "305-555-0100"}
JOSE = {"senior_name": "Jose", "senior_phone": "305-555-0102"}
ANA_DETAILS = {
    "family_name": "Ana",
    "family_phone": "305-555-0101",
    "family_email": "ana@example.com",
    "family_language": "es",
}


@pytest.fixture(autouse=True)
def login_on(monkeypatch):
    """Turn login on with a fake Supabase that only knows TOKENS."""
    monkeypatch.setenv("SUPABASE_URL", "https://fake-project.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_fake")
    auth.CHECKED_TOKENS.clear()
    monkeypatch.setattr(auth, "ask_supabase_who", lambda token, settings: TOKENS.get(token))


def test_profile_page_loads():
    """The profile page opens at /profile, with its form."""
    response = client.get("/profile")

    assert response.status_code == 200
    assert "profile-form" in response.text


def test_profile_needs_a_login():
    """Without a login, you can't see or change a profile."""
    assert client.get("/api/profile").status_code == 401
    assert client.put("/api/profile", json={"name": "Ana", "phone": "305-555-0101"}).status_code == 401


def test_no_profile_at_first():
    """Someone new has no profile yet, so the dashboard shows the boxes."""
    assert client.get("/api/profile", headers=AS_ANA).json() == {"profile": None}


def test_saving_and_reading_a_profile():
    """Saved details come back tidied up, with the phone in E.164."""
    response = client.put(
        "/api/profile",
        json={"name": " Ana ", "phone": "(305) 555-0101", "email": "", "language": "es"},
        headers=AS_ANA,
    )

    expected = {"name": "Ana", "phone": "+13055550101", "email": None, "language": "es"}
    assert response.json() == {"profile": expected}
    assert client.get("/api/profile", headers=AS_ANA).json() == {"profile": expected}


def test_a_bad_profile_is_turned_away():
    """A phone without its area code gets the same reminder as the sign-up form."""
    response = client.put("/api/profile", json={"name": "Ana", "phone": "555-0101"}, headers=AS_ANA)

    assert response.status_code == 400
    assert "area code" in response.json()["error"]


def test_each_family_only_sees_their_own_profile():
    """Ben can't see Ana's details."""
    client.put("/api/profile", json={"name": "Ana", "phone": "305-555-0101"}, headers=AS_ANA)

    assert client.get("/api/profile", headers=AS_BEN).json() == {"profile": None}


def test_first_signup_saves_the_profile():
    """Ana types her details once, on her first sign-up, and they become her profile."""
    response = client.post("/api/enrollments", json={**ROSA, **ANA_DETAILS}, headers=AS_ANA)

    assert response.status_code == 201
    assert client.get("/api/profile", headers=AS_ANA).json()["profile"] == {
        "name": "Ana",
        "phone": "+13055550101",
        "email": "ana@example.com",
        "language": "es",
    }


def test_next_signup_uses_the_profile():
    """After that, the form only needs the senior, and the profile fills in the rest."""
    client.post("/api/enrollments", json={**ROSA, **ANA_DETAILS}, headers=AS_ANA)

    response = client.post("/api/enrollments", json=JOSE, headers=AS_ANA)

    assert response.status_code == 201
    jose = storage.get_enrollment(response.json()["id"])
    assert jose["family_name"] == "Ana"
    assert jose["family_phone"] == "+13055550101"
    assert jose["family_email"] == "ana@example.com"
    assert jose["family_language"] == "es"


def test_signup_without_details_or_profile_asks_for_them():
    """With no profile and no details, the sign-up says what's missing."""
    response = client.post("/api/enrollments", json=ROSA, headers=AS_ANA)

    assert response.status_code == 400
    assert response.json()["error"] == "Your name is required."


def test_changing_the_profile_updates_every_senior():
    """A new phone on the profile is where Rosa's next alert goes."""
    rosa_id = client.post("/api/enrollments", json={**ROSA, **ANA_DETAILS}, headers=AS_ANA).json()["id"]

    client.put("/api/profile", json={"name": "Ana", "phone": "305-555-0199", "language": "en"}, headers=AS_ANA)

    rosa = storage.get_enrollment(rosa_id)
    assert rosa["family_phone"] == "+13055550199"
    assert rosa["family_email"] is None
    assert rosa["family_language"] == "en"


def test_changing_the_profile_leaves_other_families_alone():
    """Ana's new details never land on Ben's seniors."""
    ben_details = {"family_name": "Ben", "family_phone": "305-555-0103"}
    jose_id = client.post("/api/enrollments", json={**JOSE, **ben_details}, headers=AS_BEN).json()["id"]

    client.put("/api/profile", json={"name": "Ana", "phone": "305-555-0199"}, headers=AS_ANA)

    assert storage.get_enrollment(jose_id)["family_phone"] == "+13055550103"


def test_old_signups_become_a_profile():
    """Someone who signed a senior up before profiles existed doesn't have to type it again."""
    client.post("/api/enrollments", json={**ROSA, **ANA_DETAILS}, headers=AS_ANA)
    # Pretend that sign-up happened before profiles: no profile saved.
    with storage.connect() as db:
        db.execute("DELETE FROM profiles")

    profile = client.get("/api/profile", headers=AS_ANA).json()["profile"]

    assert profile["name"] == "Ana"
    assert profile["phone"] == "+13055550101"
