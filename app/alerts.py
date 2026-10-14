"""
alerts.py — Sends text messages (SMS) with Twilio.

How it fits in: other parts of the app call this file whenever someone needs a
text message:
  - the consent check: "Ana wants to protect your calls. Reply YES or NO"
    (the logic lives in consent.py; this file just sends the text)
  - the family alert: "Grandma may be on a scam call right now" + a "Join call"
    link, written in the family member's own language (see calls.py)
  - the "Is it really you?" check: "Are you calling Grandma? Reply YES or NO"
    (the logic lives in verify.py)

In demo mode we never send a real text. The message goes into DEMO_OUTBOX
instead, so the demo and the tests can see exactly what would have been sent.

Note: a Twilio TRIAL account can only send Twilio's pre-written template
messages, not our own text. Real alerts need an upgraded Twilio account.
"""

from twilio.rest import Client

from app.config import get_settings

# Texts "sent" while DEMO_MODE=true, oldest first. Each one is a dict:
#   {"to": "+13055550100", "body": "..."}
DEMO_OUTBOX: list[dict] = []


def twilio_client() -> Client:
    """
    Make a Twilio client using the keys in .env.

    It's its own function so tests can swap it for a fake one.

    Example:
        twilio_client().messages.create(to=..., from_=..., body=...)
    """
    settings = get_settings()
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def send_sms(to: str, body: str) -> None:
    """
    Send one text message from our Twilio number.

    Input:  to   — the phone number to text, in E.164 format
            body — what the text says
    Output: nothing. In demo mode, the text is added to DEMO_OUTBOX instead.

    Example:
        send_sms("+13055550100", "Scam Shield is now watching your calls.")
    """
    settings = get_settings()

    if settings.demo_mode:
        DEMO_OUTBOX.append({"to": to, "body": body})
        print(f"[demo mode] text to {to}: {body}")
        return

    twilio_client().messages.create(
        to=to,
        from_=settings.twilio_phone_number,
        body=body,
    )
