"""
test_config.py — Tests for the settings loader (app/config.py).

How it fits in: every part of Scam Shield gets its API keys and options from
config.py, so we make sure it reads yes/no settings correctly and spots
missing keys. These tests use fake values, never real keys. Run with:  pytest
"""

from app.config import Settings, find_missing_settings, read_true_false_setting


def make_fake_settings(**changes) -> Settings:
    """
    Build a Settings object filled with fake values, for testing.

    Input:  changes — any fields to change, e.g. nebius_api_key=""
    Output: a Settings object
    Example:
        make_fake_settings(tavily_api_key="")  ->  settings with no Tavily key
    """
    values = {
        "nebius_api_key": "fake-nebius-key",
        "nebius_base_url": "https://api.tokenfactory.nebius.com/v1/",
        "nemotron_model": "nvidia/Nemotron-3_5-Lightning",
        "tavily_api_key": "fake-tavily-key",
        "twilio_account_sid": "fake-sid",
        "twilio_auth_token": "fake-token",
        # 555-01XX numbers are reserved for fiction, so they never reach a real person
        "twilio_phone_number": "+15555550100",
        "test_sms_to_number": "+15555550101",
        "demo_mode": True,
        "public_base_url": "http://localhost:8000",
    }
    values.update(changes)
    return Settings(**values)


def test_missing_settings_are_listed_by_their_env_name():
    """Blank keys should be reported using the names people see in .env."""
    settings = make_fake_settings(nebius_api_key="", tavily_api_key="")

    missing = find_missing_settings(
        settings, ["NEBIUS_API_KEY", "TAVILY_API_KEY", "NEMOTRON_MODEL"]
    )

    assert missing == ["NEBIUS_API_KEY", "TAVILY_API_KEY"]


def test_nothing_missing_when_all_settings_are_filled_in():
    """When every required key has a value, the missing list is empty."""
    settings = make_fake_settings()

    missing = find_missing_settings(settings, ["NEBIUS_API_KEY", "TWILIO_AUTH_TOKEN"])

    assert missing == []


def test_yes_no_setting_understands_common_words(monkeypatch):
    """
    "true", "TRUE", "1", "yes" and "on" should all mean True; "false" means False.

    monkeypatch lets a test set an environment variable just for this test.
    """
    for word in ["true", "TRUE", "1", "yes", "on"]:
        monkeypatch.setenv("DEMO_MODE", word)
        assert read_true_false_setting("DEMO_MODE", default=False) is True

    monkeypatch.setenv("DEMO_MODE", "false")
    assert read_true_false_setting("DEMO_MODE", default=True) is False


def test_yes_no_setting_uses_default_when_blank(monkeypatch):
    """A blank setting should fall back to the default value."""
    monkeypatch.setenv("DEMO_MODE", "")

    assert read_true_false_setting("DEMO_MODE", default=True) is True
