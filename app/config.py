"""
config.py — Loads Scam Shield's settings (API keys, phone numbers, model name)
from the .env file.

How it fits in: every other part of the app asks THIS file for settings instead
of reading the .env file on its own. That gives us one place to look when a key
is missing, and it keeps secrets out of the code.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# The project folder is one level above app/. We look for .env there, so the
# settings load the same way no matter which folder you run a command from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class Settings:
    """
    All of Scam Shield's settings, gathered in one object.

    Each field matches a line in .env, just in lowercase.
    For example, the field `tavily_api_key` comes from TAVILY_API_KEY.
    "frozen=True" means a setting can't be changed by accident while the app runs.

    Example:
        settings = get_settings()
        print(settings.nemotron_model)   # "nvidia/Nemotron-3_5-Lightning"
    """

    nebius_api_key: str
    nebius_base_url: str
    nemotron_model: str
    tavily_api_key: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str
    twilio_api_key_sid: str
    twilio_api_key_secret: str
    twilio_sip_domain: str
    test_sms_to_number: str
    demo_mode: bool
    public_base_url: str
    database_path: str
    # Supabase handles family logins (see auth.py). Both are optional: when
    # they're blank, login is off and the dashboard is open to anyone.
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    # The Gmail account that sends family alerts by email (email_alerts.py).
    # Both are optional: when they're blank, we skip the email.
    gmail_address: str = ""
    gmail_app_password: str = ""
    # Real "press 1 to say YES" consent calls, even in demo mode (consent.py).
    real_consent_calls: bool = False
    # Real calls for protected seniors (ringing their calling app, joining
    # the family in), even in demo mode. The demo player stays pretend.
    real_calls: bool = False


def read_text_setting(name: str, default: str = "") -> str:
    """
    Read one text setting from the environment.

    Input:  name    — the setting's name in .env, e.g. "TAVILY_API_KEY"
            default — what to use if the setting is missing (blank by default)
    Output: the setting's value, with extra spaces trimmed off.

    Example:
        read_text_setting("NEMOTRON_MODEL")  ->  "nvidia/Nemotron-3_5-Lightning"
    """
    value = os.getenv(name, default)
    # People often paste a key with a stray space at the end.
    # Trimming it means the key still works.
    return value.strip()


def read_true_false_setting(name: str, default: bool) -> bool:
    """
    Read a yes/no setting, such as DEMO_MODE.

    Input:  name    — the setting's name in .env, e.g. "DEMO_MODE"
            default — used when the setting is missing or blank
    Output: True or False. The words "true", "1", "yes" and "on"
            (in any capitalization) count as True. Anything else is False.

    Example:
        With DEMO_MODE=true in .env:
        read_true_false_setting("DEMO_MODE", default=False)  ->  True
    """
    value = read_text_setting(name)
    if value == "":
        return default
    return value.lower() in ("true", "1", "yes", "on")


def get_settings() -> Settings:
    """
    Load the .env file and return every setting in one Settings object.

    Input:  nothing (it reads the .env file in the project folder).
    Output: a Settings object. Missing values come back blank ("") so the app
            can still start; use find_missing_settings() to see what's missing.

    Example:
        settings = get_settings()
        settings.demo_mode   ->  True
    """
    # load_dotenv copies each line of .env into the environment.
    # If .env doesn't exist yet, it quietly does nothing.
    load_dotenv(ENV_FILE)

    return Settings(
        nebius_api_key=read_text_setting("NEBIUS_API_KEY"),
        nebius_base_url=read_text_setting("NEBIUS_BASE_URL"),
        nemotron_model=read_text_setting("NEMOTRON_MODEL"),
        tavily_api_key=read_text_setting("TAVILY_API_KEY"),
        twilio_account_sid=read_text_setting("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=read_text_setting("TWILIO_AUTH_TOKEN"),
        twilio_phone_number=read_text_setting("TWILIO_PHONE_NUMBER"),
        twilio_api_key_sid=read_text_setting("TWILIO_API_KEY_SID"),
        twilio_api_key_secret=read_text_setting("TWILIO_API_KEY_SECRET"),
        twilio_sip_domain=read_text_setting("TWILIO_SIP_DOMAIN"),
        test_sms_to_number=read_text_setting("TEST_SMS_TO_NUMBER"),
        # Demo mode is ON unless someone turns it off. That's the safe choice:
        # it means we never place real phone calls by accident.
        demo_mode=read_true_false_setting("DEMO_MODE", default=True),
        # On Render we don't have to type our web address: Render tells every
        # app its own address in RENDER_EXTERNAL_URL, so we use that when
        # PUBLIC_BASE_URL is blank.
        public_base_url=(
            read_text_setting("PUBLIC_BASE_URL")
            or read_text_setting("RENDER_EXTERNAL_URL")
            or "http://localhost:8000"
        ),
        # Where we save sign-ups and calls. A file next to the code, so a
        # restart doesn't forget who said YES.
        database_path=read_text_setting(
            "DATABASE_PATH", str(PROJECT_ROOT / "data" / "scam_shield.db")
        ),
        # rstrip("/") so "https://abc.supabase.co/" and "https://abc.supabase.co"
        # both work when we add "/auth/v1/user" to the end.
        supabase_url=read_text_setting("SUPABASE_URL").rstrip("/"),
        supabase_publishable_key=read_text_setting("SUPABASE_PUBLISHABLE_KEY"),
        gmail_address=read_text_setting("GMAIL_ADDRESS"),
        # Google shows the app password in groups like "abcd efgh ijkl mnop".
        # We take the spaces out so it works however you paste it.
        gmail_app_password=read_text_setting("GMAIL_APP_PASSWORD").replace(" ", ""),
        real_consent_calls=read_true_false_setting("REAL_CONSENT_CALLS", default=False),
        real_calls=read_true_false_setting("REAL_CALLS", default=False),
    )


def find_missing_settings(settings: Settings, required: list[str]) -> list[str]:
    """
    Check which required settings are still blank.

    Input:  settings — the object from get_settings()
            required — setting names as written in .env, e.g. ["NEBIUS_API_KEY"]
    Output: a list of the names that are blank. An empty list means all set.

    Example:
        find_missing_settings(settings, ["NEBIUS_API_KEY", "NEMOTRON_MODEL"])
        ->  ["NEBIUS_API_KEY"]    (if you haven't pasted your Nebius key yet)
    """
    missing = []
    for name in required:
        # Field names are the .env names in lowercase:
        # TAVILY_API_KEY -> settings.tavily_api_key
        value = getattr(settings, name.lower())
        if value == "":
            missing.append(name)
    return missing
