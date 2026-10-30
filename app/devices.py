"""
devices.py — How Scam Shield reaches a landline senior's phone.

How it fits in: a landline senior's number forwards to our Scam Shield
number. So we can NOT ring the senior back on that number: the call would
just forward to us again, in a loop. Instead, we ring a small adapter
between their home phone and the internet, which Twilio rings as
"sip:<device_id>@<our SIP domain>".

Cell phones are never rung back: the senior adds Scam Shield to a call
themselves (Add call, then Merge; see live_calls.py).

calls.py uses device_address() whenever it rings the senior. This file also
connects the landline adapter's OUTGOING calls (handle_adapter_call), since
a landline whose phone is plugged into the adapter makes every call through us.
"""

from twilio.twiml.voice_response import VoiceResponse

from app import storage
from app.config import get_settings
from app.phone_numbers import normalize_phone

# Numbers that must always go through, even if nothing else is set up.
EMERGENCY_NUMBERS = ("911", "933")  # 933 is the US emergency-calling test line


class DeviceError(Exception):
    """
    An adapter request we can't do, with a message we can show.

    Example:
        raise DeviceError("This adapter doesn't match any phone.", 404)
    """

    def __init__(self, text: str, status_code: int):
        super().__init__(text)
        self.text = text
        self.status_code = status_code


def device_address(enrollment: dict) -> str:
    """
    The private address Twilio rings to reach a landline senior's phone.

    Input:  enrollment — the senior's (landline) enrollment
    Output: "sip:<id>@<domain>", their adapter

    Example:
        device_address(rosa_landline)  ->  "sip:senior-1a2b3c4d@scamshield.sip.twilio.com"
    """
    return f"sip:{enrollment['device_id']}@{get_settings().twilio_sip_domain}"


def dial_device(response: VoiceResponse, enrollment: dict, caller: str) -> None:
    """
    Add "connect this call to the senior's adapter" to a TwiML response.

    Used for seniors who haven't said YES: a plain call, no listening.

    Input:  response   — the TwiML we're building
            enrollment — the senior's enrollment
            caller     — the caller's number, shown on the senior's phone
    Output: nothing (it adds to response)

    Example:
        dial_device(response, rosa_landline, "+15555550199")
        ->  <Dial callerId="+15555550199"><Sip>sip:senior-1a2b3c4d@...</Sip></Dial>
    """
    dial = response.dial(caller_id=caller)
    dial.sip(device_address(enrollment))


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
