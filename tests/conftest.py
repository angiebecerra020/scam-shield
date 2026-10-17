"""
conftest.py — Shared setup that pytest runs before every test.

How it fits in: the consent and call tests save things in a database and
"send" texts. This file gives every test its own empty database file and
turns demo mode on, so tests never touch your real data/scam_shield.db and
never send a real text or place a real call.
"""

import pytest

from app import alerts, calls


@pytest.fixture(autouse=True)
def fresh_demo_setup(tmp_path, monkeypatch):
    """
    Before each test: a brand-new database, demo mode on, empty outboxes.

    tmp_path is a fresh folder pytest makes for each test and cleans up after.
    """
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    # Our fake Scam Shield number (555-01XX numbers are reserved for fiction)
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15555550150")
    # Login off, even if your .env has Supabase keys. Tests that need login
    # turn it on themselves (see test_auth.py).
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "")
    alerts.DEMO_OUTBOX.clear()
    calls.DEMO_CALL_LOG.clear()
