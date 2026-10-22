"""
test_auth.py

Tests for family logins (app/auth.py) and the new pages (landing, login,
dashboard).

How it fits in: these tests never talk to the real Supabase. When we need a
"logged in" person, we swap ask_supabase_who() for a fake that knows one
pretend token. Run them with: pytest tests/test_auth.py
"""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app

client = TestClient(app)

# A pretend token and the pretend person it belongs to
GOOD_TOKEN = "good-test-token"
ANA = {"id": "user-ana", "email": "ana@example.com"}

SIGNUP_FORM = {
    "senior_name": "Rosa",
    # 555-01XX numbers are reserved for fiction, so they never reach a real person
    "senior_phone": "305-555-0100",
    "family_name": "Ana",
    "family_phone": "305-555-0101",
}


@pytest.fixture
def login_on(monkeypatch):
    """
    Turn login on with fake Supabase settings, and a fake Supabase that only
    knows GOOD_TOKEN.
    """
    monkeypatch.setenv("SUPABASE_URL", "https://fake-project.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_fake")
    auth.CHECKED_TOKENS.clear()

    def fake_supabase(token, settings):
        return ANA if token == GOOD_TOKEN else None

    monkeypatch.setattr(auth, "ask_supabase_who", fake_supabase)


def test_landing_page_loads():
    """The home page is the landing page, with buttons to sign up and log in."""
    response = client.get("/")

    assert response.status_code == 200
    assert "Stop scam calls" in response.text
    assert "/login" in response.text


def test_login_and_dashboard_pages_load():
    """/login shows the login form and /dashboard shows the sign-up form."""
    assert "login-form" in client.get("/login").text
    assert "signup-form" in client.get("/dashboard").text


def test_login_is_off_without_supabase_settings(monkeypatch):
    """With no Supabase settings, login is off and family routes stay open."""
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "")

    assert client.get("/api/auth-config").json()["login_on"] is False
    assert client.post("/api/enrollments", json=SIGNUP_FORM).status_code == 201


def test_auth_config_shares_only_public_settings(login_on):
    """The browser gets the Supabase address and publishable key, nothing else."""
    config = client.get("/api/auth-config").json()

    assert config == {
        "login_on": True,
        "supabase_url": "https://fake-project.supabase.co",
        "supabase_publishable_key": "sb_publishable_fake",
    }


def test_family_routes_need_a_login(login_on):
    """With login on, family routes answer 401 when there's no token."""
    assert client.post("/api/enrollments", json=SIGNUP_FORM).status_code == 401
    assert client.get("/api/enrollments/abc").status_code == 401
    assert client.post("/api/demo/scam-call").status_code == 401
    assert client.get("/api/demo/outbox").status_code == 401


def test_a_fake_token_is_turned_away(login_on):
    """A token Supabase doesn't know gets a 401."""
    response = client.get(
        "/api/demo/outbox", headers={"Authorization": "Bearer made-up-token"}
    )

    assert response.status_code == 401


def test_a_logged_in_family_member_can_sign_someone_up(login_on):
    """A good token gets through, and the sign-up works like before."""
    response = client.post(
        "/api/enrollments",
        json=SIGNUP_FORM,
        headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending"


def test_twilio_and_join_routes_dont_need_a_login(login_on):
    """
    Twilio and the "Join call" link can't log in, so they must stay open.
    (Twilio routes check Twilio's signature instead, and join links have a
    secret token, so a made up one gives you 404, not 401.)
    """
    assert client.get("/join/not-a-real-token").status_code != 401
    assert client.get("/api/join/not-a-real-token").status_code == 404


def test_good_tokens_are_remembered_for_a_bit(login_on, monkeypatch):
    """After Supabase says yes once, we don't ask again on every request."""
    asked = []

    def counting_supabase(token, settings):
        asked.append(token)
        return ANA

    monkeypatch.setattr(auth, "ask_supabase_who", counting_supabase)
    headers = {"Authorization": f"Bearer {GOOD_TOKEN}"}

    client.get("/api/demo/outbox", headers=headers)
    client.get("/api/demo/outbox", headers=headers)

    assert asked == [GOOD_TOKEN]
