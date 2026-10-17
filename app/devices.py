"""
devices.py — How Scam Shield reaches the senior's phone, for cell phones and
landlines alike.

How it fits in: every senior's number forwards to our Scam Shield number. So
we can NOT ring the senior back on that number: the call would just forward
to us again, in a loop. Instead, we ring a private "device" that only Scam
Shield can reach:

  - cell phone -> our calling app on their phone (static/phone.html), which
                  Twilio rings over the internet as "client:<device_id>"
  - landline   -> a small adapter between their home phone and the internet,
                  which Twilio rings as "sip:<device_id>@<our SIP domain>"

calls.py uses device_address() whenever it rings the senior. This file also
gives the calling app its login (app_details) and connects the landline
adapter's OUTGOING calls (handle_adapter_call), since a landline whose phone
is plugged into the adapter makes every call through us.
"""

from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import VoiceResponse

from app import storage
from app.config import get_settings
from app.phone_numbers import normalize_phone

# How long a calling-app login lasts before the app asks for a new one (seconds).
APP_TOKEN_SECONDS = 3600
# Numbers that must always go through, even if nothing else is set up.
EMERGENCY_NUMBERS = ("911", "933")  # 933 is the US emergency-calling test line


class DeviceError(Exception):
    """
    A calling-app request we can't do, with a message the page can show.

    Example:
        raise DeviceError("This link doesn't match any phone.", 404)
    """

    def __init__(self, text: str, status_code: int):
        super().__init__(text)
        self.text = text
        self.status_code = status_code


def device_address(enrollment: dict) -> str:
    """
    The private address Twilio rings to reach the senior's phone.

    Input:  enrollment — the senior's enrollment
    Output: "client:<id>" for a cell phone's calling app, or
            "sip:<id>@<domain>" for a landline's adapter

    Examples:
        device_address(rosa_cell)      ->  "client:senior-1a2b3c4d"
        device_address(rosa_landline)  ->  "sip:senior-1a2b3c4d@scamshield.sip.twilio.com"
    """
    if enrollment["phone_type"] == "landline":
        return f"sip:{enrollment['device_id']}@{get_settings().twilio_sip_domain}"
    return f"client:{enrollment['device_id']}"


def dial_device(response: VoiceResponse, enrollment: dict, caller: str) -> None:
    """
    Add "connect this call to the senior's device" to a TwiML response.

    Used for seniors who haven't said YES: a plain call, no listening.

    Input:  response   — the TwiML we're building
            enrollment — the senior's enrollment
            caller     — the caller's number, shown on the senior's phone
    Output: nothing (it adds to response)

    Example:
        dial_device(response, rosa_cell, "+15555550199")
        ->  <Dial callerId="+15555550199"><Client>senior-1a2b3c4d</Client></Dial>
    """
    dial = response.dial(caller_id=caller)
    address = device_address(enrollment)
    if address.startswith("sip:"):
        dial.sip(address)
    else:
        dial.client(enrollment["device_id"])


# ---------------------------------------------------------------------------
# Cell phones: the calling app
# ---------------------------------------------------------------------------


def find_cell_enrollment(device_key: str) -> dict:
    """
    Find the cell-phone senior a calling-app link belongs to.

    Raises: DeviceError if the link is wrong or belongs to a landline

    Example:
        find_cell_enrollment("Xy7...")  ->  {"senior_name": "Rosa", ...}
    """
    enrollment = storage.find_enrollment_by_device("device_key", device_key)
    if enrollment is None or enrollment["phone_type"] != "cell":
        raise DeviceError("This link doesn't match any phone.", 404)
    return enrollment


def app_details(device_key: str) -> dict:
    """
    What the calling app needs to start: whose phone it is, and a login
    (access token) that lets Twilio ring it.

    The app only RECEIVES calls, so the login can't be used to call anyone.
    Demo mode skips the login: no real calls ring in demo mode.

    Input:  device_key — the secret part of the calling-app link
    Output: {"senior_name": ..., "demo_mode": ..., "token": ... or None}
    Raises: DeviceError if the link is wrong or Twilio isn't set up

    Example:
        app_details("Xy7...")  ->  {"senior_name": "Rosa", "demo_mode": False, "token": "eyJ..."}
    """
    enrollment = find_cell_enrollment(device_key)
    settings = get_settings()
    details = {
        "senior_name": enrollment["senior_name"],
        "demo_mode": settings.demo_mode,
        "token": None,
    }
    if settings.demo_mode:
        return details

    if not (settings.twilio_api_key_sid and settings.twilio_api_key_secret):
        raise DeviceError("Scam Shield isn't fully set up yet (missing Twilio API key).", 503)

    token = AccessToken(
        settings.twilio_account_sid,
        settings.twilio_api_key_sid,
        settings.twilio_api_key_secret,
        identity=enrollment["device_id"],
        ttl=APP_TOKEN_SECONDS,
    )
    token.add_grant(VoiceGrant(incoming_allow=True))
    details["token"] = token.to_jwt()
    return details


# ---------------------------------------------------------------------------
# Landlines: calls the senior makes through the adapter
# ---------------------------------------------------------------------------


def sip_user(address: str) -> str:
    """
    Pull the user part out of a SIP address.

    Example:
        sip_user("sip:+13055550123@scamshield.sip.twilio.com;user=phone")  ->  "+13055550123"
    """
    without_scheme = (address or "").removeprefix("sip:")
    return without_scheme.split("@", 1)[0]


def handle_adapter_call(from_address: str, to_address: str) -> str:
    """
    Connect a call the landline senior dials on their own phone.

    Their phone is plugged into the adapter, so Twilio asks us where to send
    each call they make. Outgoing calls are theirs: we connect them and don't
    listen.

    The senior's own number shows as caller ID, which Twilio only allows after
    the number is verified in Twilio (see README). Emergency calls show our
    Twilio number instead, because that's the number with the senior's home
    address registered for 911.

    Input:  from_address — the adapter that's calling, "sip:senior-...@domain"
            to_address   — what they dialed, "sip:3055550123@domain"
    Output: TwiML that connects the call

    Examples:
        handle_adapter_call("sip:senior-1a2b@d", "sip:3055550123@d")
        ->  <Dial callerId="+15555550100"><Number>+13055550123</Number></Dial>
        handle_adapter_call("sip:senior-1a2b@d", "sip:911@d")
        ->  <Dial callerId="<our number>"><Number>911</Number></Dial>
    """
    response = VoiceResponse()
    enrollment = storage.find_enrollment_by_device("device_id", sip_user(from_address))
    dialed = sip_user(to_address)

    if dialed in EMERGENCY_NUMBERS:
        response.dial(caller_id=get_settings().twilio_phone_number).number(dialed)
        return str(response)

    if enrollment is None or enrollment["phone_type"] != "landline":
        response.say("Sorry, this phone is not set up for Scam Shield. Goodbye.")
        response.hangup()
        return str(response)

    number = normalize_phone(dialed)
    if number is None:
        response.say("Sorry, that number can't be dialed. Please hang up and try again.")
        response.hangup()
        return str(response)

    response.dial(caller_id=enrollment["senior_phone"]).number(number)
    return str(response)
