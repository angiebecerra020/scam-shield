"""
calls.py — Connects a protected senior's calls through a conference "room", so
a family member can join the call as a 3-way call.

How it fits in: the senior's calls forward to our Twilio number. For a senior
who said YES (see consent.py), we don't connect the two phones directly.
Instead, every phone joins the same Twilio conference room:

    caller (maybe a scammer) --\\
                                 >-- conference room "scam-shield-<id>"
    senior's device -----------/            ^
                                            |  only if the family taps
    family member's phone ------------------/  "Join call" in the alert

A plain two-person call can't take a third person later, but a conference
room can. So when the detector (detector.py) decides the call looks like a
scam, it calls send_family_alert(). That PHONES the family member (texts
from our number get blocked by the carriers), says why we're worried, and
asks them to press 1 to join. Pressing 1 puts them right in the room. The
alert email has a "Join call" link too: tapping it makes Twilio ring the
FAMILY MEMBER'S OWN phone and put them in the room. Everyone hears a short
tone when they join, so nobody is listening in secret.

We ring the senior on their private DEVICE (a calling app on a cell phone,
or an adapter on a landline; see devices.py), never on their own number:
that number forwards to us, so ringing it would loop straight back.

Seniors who haven't said YES get a normal call: we pass it straight to their
device and don't listen.

Caller ID: when we ring the senior, their phone shows the REAL caller's
number, not ours, so they can still tell their daughter from a stranger.
We also pass along the incoming call's CallToken, which is what Twilio asks
for when a forwarded call keeps the original caller ID (see caller_id_for).

Each family can also keep a list of scam numbers (see family.py). When a
number on the list calls a protected senior, we either alert the family the
moment the call starts ("warn"), or don't let it ring at all ("block").

In demo mode we never place real calls; we record what we would have done in
DEMO_CALL_LOG instead.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone

from twilio.twiml.voice_response import VoiceResponse

from app import storage
from app.alerts import twilio_client
from app.config import get_settings
from app.devices import device_address, dial_device
from app.languages import message, pick_language, spoken_language
from app.phone_numbers import normalize_phone

# Calls we "placed" while DEMO_MODE=true. Each one is a dict like
#   {"to": "+13055550101", "conference": "scam-shield-abc", "who": "family"}
DEMO_CALL_LOG: list[dict] = []

# How long to ring the senior's phone before giving up (seconds).
SENIOR_RING_SECONDS = 25

# Cell phone seniors we're ringing right now: enrollment ID gives you call ID.
# Their phone forwards calls they don't answer back to us, so if they miss
# OUR call too, it bounces right back here. This is how we spot that and
# stop it, instead of ringing them in a loop forever.
RINGING_SENIORS: dict[str, str] = {}

# Calls where we already tried the backup (ringing the senior's real phone),
# so we only try it once.
BACKUP_TRIED: set[str] = set()
# Wait this long before ringing the family again if they tap the link twice.
FAMILY_RING_COOLDOWN = timedelta(seconds=60)
# How many of the detector's reasons we read out on the alert call.
ALERT_CALL_REASONS = 2


class JoinError(Exception):
    """
    A "Join call" request we can't do, with a message the family can read.

    Example:
        raise JoinError("This call has already ended.", 410)
    """

    def __init__(self, text: str, status_code: int):
        super().__init__(text)
        self.text = text
        self.status_code = status_code


def public_url(path: str) -> str:
    """
    Make a full web address on our server, for links and Twilio callbacks.

    Example:
        PUBLIC_BASE_URL=https://abc.ngrok.app
        public_url("/join/xyz")  ->  "https://abc.ngrok.app/join/xyz"
    """
    return get_settings().public_base_url.rstrip("/") + path


# ---------------------------------------------------------------------------
# A call comes in
# ---------------------------------------------------------------------------


def find_senior_for_call(forwarded_from: str | None) -> dict | None:
    """
    Work out which senior a forwarded call belongs to.

    When a phone forwards a call, the carrier usually tells Twilio whose phone
    it was (ForwardedFrom). Not every carrier does, so if there's only ONE
    senior signed up (true for our hackathon demo), we use them.

    Input:  forwarded_from — the senior's number from Twilio, or None
    Output: that senior's newest enrollment (any status), or None

    Example:
        find_senior_for_call("+13055550100")  ->  {"senior_name": "Rosa", ...}
    """
    phone = normalize_phone(forwarded_from or "")
    if phone:
        enrollments = storage.find_enrollments_for_senior(phone)
        active = [e for e in enrollments if e["status"] == "active"]
        if active:
            return active[0]
        # A removed sign-up is only a fallback, so their calls still ring
        # through. If the family signed them up again, use the new one.
        not_removed = [e for e in enrollments if e["status"] != "removed"]
        if not_removed:
            return not_removed[0]
        if enrollments:
            return enrollments[0]
        return None

    # Paused and removed seniors count too: their calls may still come to us,
    # and we pass them straight through without listening. We count phones,
    # not sign-ups, since someone removed and signed up again has two.
    signed_up = storage.find_enrollments_with_status(("active", "paused", "removed"))
    phones = {enrollment["senior_phone"] for enrollment in signed_up}
    if len(phones) == 1:
        return find_senior_for_call(phones.pop())
    return None


def handle_incoming_call(
    caller: str,
    call_sid: str,
    forwarded_from: str | None,
    call_token: str | None = None,
) -> str:
    """
    Decide what to do with a call that reached our Twilio number.

    Input:  caller         — who is calling (Twilio's "From")
            call_sid       — Twilio's ID for this call
            forwarded_from — whose phone forwarded it (may be None)
            call_token     — Twilio's CallToken for this call, which lets the
                             senior see the real caller's number (may be None)
    Output: TwiML: the instructions Twilio follows for this call

    What happens:
      - senior said YES  -> caller goes into a conference room, and we ring
                            the senior's device into the same room
                            (a number on the family's scam list is either
                            blocked with a busy signal, or rings while we
                            alert the family right away)
      - senior hasn't said YES -> we pass the call straight to their device,
                            without a room and without listening
      - nobody signed up -> a short message, then hang up

    Example:
        handle_incoming_call("+15555550199", "CA123", "+13055550100")
        ->  '<Response><Dial><Conference ...>scam-shield-...</Conference></Dial></Response>'
    """
    enrollment = find_senior_for_call(forwarded_from)
    response = VoiceResponse()

    if enrollment is None:
        response.say("Sorry, this Scam Shield number is not set up yet. Goodbye.")
        response.hangup()
        return str(response)

    if enrollment["status"] != "active":
        # No YES (or the family paused protection), no listening: connect
        # the call like any normal phone call.
        dial_device(response, enrollment, caller)
        return str(response)

    # Is this a number the family reported as a scam?
    reported = reported_number_action(enrollment, caller)
    if reported == "block":
        record_blocked_call(enrollment, caller, call_sid)
        # Reject gives the caller a busy signal without answering, so a
        # scammer doesn't even learn the number works.
        response.reject()
        return str(response)

    if enrollment["id"] in RINGING_SENIORS:
        # This is our own call to the senior bouncing back because they
        # didn't pick up. Reject it, so our call ends as "busy" and the
        # caller hears that the senior can't come to the phone.
        response.reject()
        return str(response)

    call = start_protected_call(enrollment, caller, call_sid, call_token)
    if reported == "warn":
        warn_about_reported_number(call, enrollment)

    # Live transcription, so detector.py can read the call as it happens.
    # Only calls from seniors who said YES get it (see live_calls.py). We
    # import it here because live_calls.py uses this file too.
    from app import live_calls
    live_calls.start_transcription(response, call["id"])

    # Without this the caller hears silence while we ring the senior.
    response.say("Please hold while we connect your call.")
    dial = response.dial()
    dial.conference(
        call["conference_name"],
        # The caller waits (in silence) until the senior picks up...
        start_conference_on_enter=False,
        wait_url="",
        # ...and when the caller hangs up, the call is over for everyone.
        end_conference_on_exit=True,
        beep=False,
        status_callback=public_url("/twilio/conference-status"),
        status_callback_event="end",
    )
    return str(response)


def start_protected_call(
    enrollment: dict,
    caller: str,
    call_sid: str,
    call_token: str | None = None,
    ring_senior: bool = True,
) -> dict:
    """
    Save a new protected call and ring the senior into its conference room.

    Input:  enrollment  — the senior's active enrollment
            caller      — who is calling
            call_sid    — Twilio's ID for the caller's side of the call
            call_token  — the incoming call's CallToken (may be None)
            ring_senior — False for pretend calls (the demo player, the
                          "Test it" line), where the senior is
                          made up and there's no phone to ring. With
                          REAL_CALLS on, ringing a made-up phone fails, and
                          handle_senior_status() would then hang up the
                          real caller with "not available".
    Output: the saved call (a dict)

    Example:
        start_protected_call(rosa, "+15555550199", "CA123")
        ->  {"id": "...", "conference_name": "scam-shield-...", "status": "live", ...}
    """
    call_id = secrets.token_urlsafe(9)
    call = {
        "id": call_id,
        "call_sid": call_sid,
        "enrollment_id": enrollment["id"],
        "caller_number": caller,
        "conference_name": f"scam-shield-{call_id}",
        # The secret part of the family's "Join call" link. Long and random,
        # so nobody can guess their way into a call.
        "join_token": secrets.token_urlsafe(24),
        "status": "live",
        "started_at": storage.now_text(),
    }
    storage.save_call(call)
    if not ring_senior:
        return call

    # Cell phones ring the Scam Shield page first (the calling app). If the
    # page is closed, or they don't answer, handle_senior_status() calls
    # their real phone as a backup, so the call still gets through.

    ring_into_conference(
        to=device_address(enrollment),
        conference_name=call["conference_name"],
        who="senior",
        caller_id=caller_id_for(caller, call_token),
        # The senior starts the conversation when they pick up, and when they
        # hang up the call is over for everyone.
        start_conference_on_enter=True,
        end_conference_on_exit=True,
        beep="false",
        status_callback=public_url(f"/twilio/senior-status?call_id={call_id}"),
    )
    return call


def ring_senior_phone(call: dict, enrollment: dict, caller_id: dict) -> None:
    """
    Calls a cell phone senior's REAL phone and asks if they want Scam Shield.

    Their phone only forwards calls they decline or miss (see the setup
    steps), so ringing their real number doesn't loop back here, and they
    don't need any app or web page open. When they pick up, Twilio asks
    live_calls.py what to say: "Press 1 to answer with Scam Shield listening,
    press 2 to answer without it." Either way, the call goes through.

    Input:  call, the call we just saved
            enrollment, the senior's sign up
            caller_id, from caller_id_for(), so they see who's really calling
    Output: nothing. In demo mode, the call goes in DEMO_CALL_LOG instead.

    Example:
        ring_senior_phone(call, rosa, {"from_": "+15555550199"})
        rings Rosa's cell, and she hears the press 1 or press 2 question
    """
    settings = get_settings()
    to = enrollment["senior_phone"]

    if settings.demo_mode and not settings.real_calls:
        DEMO_CALL_LOG.append(
            {"to": to, "conference": call["conference_name"], "who": "senior", "shows": caller_id["from_"]}
        )
        print(f"[demo mode] would ring the senior at {to} for {call['conference_name']}")
        return

    RINGING_SENIORS[enrollment["id"]] = call["id"]
    twilio_client().calls.create(
        **caller_id,
        to=to,
        url=public_url(f"/twilio/protected/screen?call_id={call['id']}"),
        timeout=SENIOR_RING_SECONDS,
        status_callback=public_url(f"/twilio/senior-status?call_id={call['id']}"),
        status_callback_event=["answered", "completed"],
    )


def caller_id_for(caller: str, call_token: str | None) -> dict:
    """
    Choose the number the senior's phone shows when we ring them.

    Twilio normally only lets us show our own number. But when we pass along
    the CallToken from the incoming call, Twilio lets us show the REAL
    caller's number, because we're forwarding their call, not faking one.

    If there's no token, or the caller hid their number ("Anonymous"), we
    fall back to our own number. The call still works; the senior just sees
    the Scam Shield number.

    Input:  caller     — the incoming caller's number (Twilio's "From")
            call_token — Twilio's CallToken for the incoming call, or None
    Output: {"from_": <number to show>} plus {"call_token": ...} when used

    Examples:
        caller_id_for("+15555550199", "tok123")
        ->  {"from_": "+15555550199", "call_token": "tok123"}
        caller_id_for("Anonymous", "tok123")
        ->  {"from_": <our Twilio number>}
    """
    caller_phone = normalize_phone(caller or "")
    if call_token and caller_phone:
        return {"from_": caller_phone, "call_token": call_token}
    return {"from_": get_settings().twilio_phone_number}


def ring_into_conference(
    to: str,
    conference_name: str,
    who: str,
    start_conference_on_enter: bool,
    end_conference_on_exit: bool,
    beep: str,
    status_callback: str | None = None,
    caller_id: dict | None = None,
) -> None:
    """
    Ask Twilio to call a phone and put whoever answers into a conference room.

    Input:  to              — the phone number, calling app ("client:...")
                              or adapter ("sip:...") to ring
            conference_name — which room
            who             — "senior" or "family" (a label for logs)
            start_conference_on_enter, end_conference_on_exit, beep — Twilio's
                              conference options for this person
            status_callback — where Twilio reports how the call went
            caller_id       — the number to show, from caller_id_for();
                              our own Twilio number if left out
    Output: nothing. In demo mode, the call is added to DEMO_CALL_LOG instead.

    Example:
        ring_into_conference("+13055550101", "scam-shield-abc", "family",
                             start_conference_on_enter=True,
                             end_conference_on_exit=False, beep="onEnter")
    """
    settings = get_settings()

    if caller_id is None:
        caller_id = {"from_": settings.twilio_phone_number}

    if settings.demo_mode and not settings.real_calls:
        DEMO_CALL_LOG.append(
            {"to": to, "conference": conference_name, "who": who, "shows": caller_id["from_"]}
        )
        print(f"[demo mode] would ring {who} at {to} into {conference_name}")
        return

    options = {
        **caller_id,
        "to": to,
        "label": who,
        "beep": beep,
        "start_conference_on_enter": start_conference_on_enter,
        "end_conference_on_exit": end_conference_on_exit,
        "timeout": SENIOR_RING_SECONDS,
    }
    if status_callback:
        options["status_callback"] = status_callback
        options["status_callback_event"] = ["completed"]

    # Twilio lets us use the room's name here; it makes the room if needed.
    twilio_client().conferences(conference_name).participants.create(**options)


# ---------------------------------------------------------------------------
# Twilio tells us how the call is going
# ---------------------------------------------------------------------------


def handle_senior_status(call_id: str, call_status: str) -> None:
    """
    React when the senior's side of the call finishes ringing or ends.

    If the senior never picked up (busy, no answer, failed), the caller is
    still waiting in a silent room. We tell them, and hang up.

    Input:  call_id     — our ID for the call (we put it in the callback URL)
            call_status — Twilio's CallStatus, e.g. "no-answer" or "completed"
    Output: nothing

    Example:
        handle_senior_status("abc", "no-answer")
        ->  the caller hears "The person you are calling is not available."
    """
    call = storage.get_call(call_id)
    if call is not None:
        # Ringing is over (they picked up, or never will), so a new call
        # for this senior is a real new call again, not a bounce.
        if RINGING_SENIORS.get(call["enrollment_id"]) == call_id:
            RINGING_SENIORS.pop(call["enrollment_id"])

    if call_status not in ("busy", "no-answer", "failed", "canceled"):
        return

    if call is None or call["status"] != "live":
        return

    if call_id not in BACKUP_TRIED:
        enrollment = storage.get_enrollment(call["enrollment_id"])
        if enrollment is not None and enrollment["phone_type"] == "cell":
            # The Scam Shield page didn't answer (closed, or they rejected
            # it). Call their real phone instead: press 1 or press 2.
            BACKUP_TRIED.add(call_id)
            ring_senior_phone(call, enrollment, caller_id_for(call["caller_number"], None))
            return

    BACKUP_TRIED.discard(call_id)
    storage.mark_call_ended(call_id)
    settings = get_settings()
    if settings.demo_mode and not settings.real_calls:
        return

    goodbye = VoiceResponse()
    goodbye.say("Sorry, they can't come to the phone right now. Please try again later. Goodbye.")
    goodbye.hangup()
    twilio_client().calls(call["call_sid"]).update(twiml=str(goodbye))


def handle_conference_status(conference_name: str, event: str) -> None:
    """
    Mark a call as over when its conference room closes.

    After this, the family's "Join call" link stops working.

    Input:  conference_name — Twilio's FriendlyName for the room
            event           — Twilio's StatusCallbackEvent, e.g. "conference-end"
    Output: nothing

    Example:
        handle_conference_status("scam-shield-abc", "conference-end")
    """
    if event != "conference-end":
        return
    call = storage.get_call_by_conference_name(conference_name)
    if call and call["status"] == "live":
        storage.mark_call_ended(call["id"])


# ---------------------------------------------------------------------------
# The family alert and the "Join call" link
# ---------------------------------------------------------------------------


def join_link(call: dict) -> str:
    """
    The "Join call" link we put in the family's alert email.

    Example:
        join_link(call)  ->  "https://abc.ngrok.app/join/Xy7..."
    """
    return public_url(f"/join/{call['join_token']}")


def alert_call_language(enrollment: dict) -> str:
    """
    The language we SPEAK on the alert call: the family's.

    Example:
        alert_call_language({"family_language": "es", ...})  ->  "es"
    """
    return pick_language(enrollment["family_language"])


def alert_call_words(call: dict, enrollment: dict) -> str:
    """
    What the family member hears first on the alert call: who may be getting
    scammed, and why we think so (or that it's a number they reported).

    Input:  call — the live call (from storage), with the detector's reasons
            enrollment — the senior's sign-up
    Output: the words to say, before "To join the call, press 1..."

    Example:
        alert_call_words(call, rosa)
        ->  "Scam Shield alert. Rosa may be on a scam call right now.
             Why we're worried: Claims to be her grandson; Asks for gift cards."
    """
    language = alert_call_language(enrollment)
    name = enrollment["senior_name"]
    words = [message("alert_call_prompt", language, senior_name=name)]
    if call.get("scam_list") == "warn":
        words.append(message("alert_call_reported", language, senior_name=name))
    else:
        reasons = json.loads(call.get("reasons") or "[]")[:ALERT_CALL_REASONS]
        if reasons:
            words.append(message("alert_call_why", language, reasons="; ".join(reasons)))
    return " ".join(words)


def send_family_alert(call: dict) -> None:
    """
    Phone the family member: the senior may be on a scam call right now, and
    they can press 1 to join it. When they pick up, Twilio asks us what to
    say (family_alert_twiml).

    We call instead of texting because the carriers block texts from our
    Twilio number until it's registered.

    Input:  call — the live call (from storage)
    Output: nothing. In demo mode, and always for the demo player's made up
            Rosa, the call goes into DEMO_CALL_LOG instead, with its words.

    Example:
        send_family_alert(call)
        ->  Ana's phone rings: "Scam Shield alert. Rosa may be on a scam call
            right now... To join the call, press 1. To hang up, press 2."
    """
    # Read it again, for the reasons and scam list saved since it started.
    call = storage.get_call(call["id"]) or call
    enrollment = storage.get_enrollment(call["enrollment_id"])
    settings = get_settings()

    # The demo player's family has made up 555 numbers, so never really call them.
    if enrollment["status"] == "demo" or (settings.demo_mode and not settings.real_calls):
        language = alert_call_language(enrollment)
        DEMO_CALL_LOG.append(
            {
                "to": enrollment["family_phone"],
                "who": "alert",
                "conference": call["conference_name"],
                "says": alert_call_words(call, enrollment) + " " + message("alert_call_question", language),
            }
        )
        print(f"[demo mode] would call {enrollment['family_phone']} with the scam alert")
        return

    twilio_client().calls.create(
        to=enrollment["family_phone"],
        from_=settings.twilio_phone_number,
        url=public_url(f"/twilio/family-alert?call_id={call['id']}"),
    )


def joinable_call(call_id: str) -> tuple[dict | None, dict | None]:
    """
    The call and enrollment behind an alert call, if the family can still
    join it: the call is going, and the senior still has Scam Shield on.

    Output: (call, enrollment), or (None, None) if it can't be joined.

    Example:
        joinable_call("abc")  ->  ({"status": "live", ...}, {"senior_name": "Rosa", ...})
    """
    call = storage.get_call(call_id)
    if call is None or call["status"] != "live":
        return None, None
    enrollment = storage.get_enrollment(call["enrollment_id"])
    if enrollment is None or enrollment["status"] != "active":
        return None, None
    return call, enrollment


def family_alert_twiml(call_id: str, attempt: int = 1) -> str:
    """
    What the family member hears when they pick up the alert call.

    We ask twice. If they still don't press anything, we say goodbye (the
    alert email's "Join call" link still works after that).

    Input:  call_id — which protected call this alert is about
            attempt — 1 the first time, 2 when we ask again
    Output: TwiML that says the alert and listens for one key press

    Example:
        family_alert_twiml("abc")
        ->  '<Response><Gather numDigits="1" ...><Say>Scam Shield alert. Rosa...</Say>...'
    """
    response = VoiceResponse()
    call, enrollment = joinable_call(call_id)
    if call is None:
        # The scam call ended before they picked up. Nothing to join.
        response.say(message("alert_call_ended", "en"), language=spoken_language("en"))
        response.hangup()
        return str(response)

    language = alert_call_language(enrollment)
    voice = spoken_language(language)
    gather = response.gather(
        num_digits=1,
        timeout=8,
        action=public_url(f"/twilio/family-alert-answer?call_id={call_id}"),
    )
    gather.say(alert_call_words(call, enrollment), language=voice)
    gather.say(message("alert_call_question", language), language=voice)

    # Only reached if they didn't press anything.
    if attempt < 2:
        response.redirect(public_url(f"/twilio/family-alert?call_id={call_id}&attempt=2"))
    else:
        response.say(message("alert_call_goodbye", language), language=voice)
        response.hangup()
    return str(response)


def handle_alert_digits(call_id: str, called_phone: str, digits: str) -> str:
    """
    Act on the key the family member pressed on the alert call.

    1 puts them straight into the senior's call (a 3-way call), and everyone
    hears a tone as they join. 2 hangs up. The press only counts if it came
    on our call TO the family's own phone.

    Input:  call_id      — which protected call
            called_phone — the number we called (Twilio's "To")
            digits       — the key they pressed
    Output: TwiML: what they hear next

    Examples:
        handle_alert_digits("abc", "+13055550101", "1")  ->  "Connecting you now..." and Ana is in the call
        handle_alert_digits("abc", "+13055550101", "7")  ->  asks again
    """
    response = VoiceResponse()
    call, enrollment = joinable_call(call_id)
    if call is None:
        response.say(message("alert_call_ended", "en"), language=spoken_language("en"))
        response.hangup()
        return str(response)
    if normalize_phone(called_phone or "") != enrollment["family_phone"]:
        response.hangup()
        return str(response)

    language = alert_call_language(enrollment)
    voice = spoken_language(language)

    if digits == "1":
        response.say(message("alert_call_joining", language), language=voice)
        dial = response.dial()
        dial.conference(
            call["conference_name"],
            # Same as the "Join call" link: everyone hears a tone, and if the
            # family member hangs up, the senior's call keeps going.
            beep="onEnter",
            start_conference_on_enter=True,
            end_conference_on_exit=False,
        )
        storage.mark_family_called(call["id"])
    elif digits == "2":
        response.say(message("alert_call_bye", language), language=voice)
        response.hangup()
    else:
        response.redirect(public_url(f"/twilio/family-alert?call_id={call_id}&attempt=2"))
    return str(response)


def reported_number_action(enrollment: dict, caller: str) -> str | None:
    """
    Check if the caller is on the scam list of the family who protects this senior.

    Input:  enrollment, the senior's active enrollment
            caller, who's calling (Twilio's "From")
    Output: "warn", "block", or None if the number isn't on their list

    Example:
        reported_number_action(rosa, "+13055550142") gives you "block"
        if Ana said to block that number
    """
    phone = normalize_phone(caller or "")
    if phone is None:
        return None
    found = storage.find_scam_number(enrollment.get("owner_id"), phone)
    if found is None:
        return None
    return found["action"]


def record_blocked_call(enrollment: dict, caller: str, call_sid: str) -> dict:
    """
    Save a call we blocked, so the family sees it in the call history. Nobody
    joins it and it never rings, so it's over as soon as it's saved.

    Input:  enrollment, the senior's enrollment
            caller, the blocked number
            call_sid, Twilio's ID for the call
    Output: the saved call

    Example:
        record_blocked_call(rosa, "+13055550142", "CA123") gives you
        {"status": "ended", "scam_list": "block", ...} in the history
    """
    call_id = secrets.token_urlsafe(9)
    call = {
        "id": call_id,
        "call_sid": call_sid,
        "enrollment_id": enrollment["id"],
        "caller_number": caller,
        # The table needs a room name and a join token, but this call never
        # gets a room. The token is still random so it can't be guessed.
        "conference_name": f"blocked-{call_id}",
        "join_token": secrets.token_urlsafe(24),
        "status": "ended",
        "started_at": storage.now_text(),
    }
    storage.save_call(call)
    storage.mark_call_ended(call_id)
    storage.mark_call_scam_list(call_id, "block")
    return call


def warn_about_reported_number(call: dict, enrollment: dict) -> None:
    """
    Alert the family the moment a number they reported calls, without waiting
    for Nemotron: the alert call says it's a number they reported.

    We save that we alerted them, so call_monitor.py doesn't send the alert
    again once Nemotron scores the call.

    Input:  call, the new protected call
            enrollment, the senior's enrollment
    Output: nothing

    Example:
        Ana's phone rings: "Scam Shield alert. Rosa may be on a scam call right
        now. The number calling Rosa is one you reported as a scam..."
    """
    # Saved first, so the alert call knows to say it's a reported number.
    storage.mark_call_scam_list(call["id"], "warn")
    send_family_alert(call)
    storage.mark_call_alerted(call["id"])


def find_live_call(join_token: str) -> tuple[dict, dict]:
    """
    Find the call and enrollment behind a "Join call" link, if it can be joined.

    Input:  join_token — the secret part of the link
    Output: (call, enrollment)
    Raises: JoinError if the link is wrong, the call is over, or the senior
            turned Scam Shield off

    Example:
        find_live_call("Xy7...")  ->  ({"status": "live", ...}, {"senior_name": "Rosa", ...})
    """
    call = storage.get_call_by_join_token(join_token)
    if call is None:
        raise JoinError("This link doesn't match any call.", 404)
    if call["status"] != "live":
        raise JoinError("This call has already ended.", 410)

    enrollment = storage.get_enrollment(call["enrollment_id"])
    if enrollment is None or enrollment["status"] != "active":
        raise JoinError("Scam Shield is turned off for this person.", 403)
    return call, enrollment


def describe_call(join_token: str) -> dict:
    """
    What the "Join call" page shows before the family taps the button.

    Example:
        describe_call("Xy7...")  ->  {"senior_name": "Rosa", "status": "live"}
    """
    call, enrollment = find_live_call(join_token)
    return {"senior_name": enrollment["senior_name"], "status": call["status"]}


def join_call(join_token: str) -> dict:
    """
    Ring the family member's phone and add them to the live call (3-way call).

    We ALWAYS ring the phone number the family signed up with, never a number
    from the web page. So even if someone else got hold of the link, the only
    phone that can join is the family member's own.

    Input:  join_token — the secret part of the "Join call" link
    Output: {"status": "calling", "senior_name": ...}
    Raises: JoinError if the call can't be joined, or if we rang them less
            than a minute ago

    Example:
        join_call("Xy7...")  ->  {"status": "calling", "senior_name": "Rosa"}
        and Ana's phone rings; when she answers she's in the call with
        Rosa and the caller, and they all hear a tone as she joins.
    """
    call, enrollment = find_live_call(join_token)

    if call["family_called_at"]:
        last_rang = storage.parse_time(call["family_called_at"])
        if datetime.now(timezone.utc) - last_rang < FAMILY_RING_COOLDOWN:
            raise JoinError("We're already calling your phone. Please answer it.", 429)

    ring_into_conference(
        to=enrollment["family_phone"],
        conference_name=call["conference_name"],
        who="family",
        start_conference_on_enter=True,
        # If the family member hangs up, the senior's call keeps going.
        end_conference_on_exit=False,
        # Everyone hears a tone when the family member joins. No secret
        # listening, and it lets a scammer know someone else is on the line.
        beep="onEnter",
    )
    storage.mark_family_called(call["id"])
    return {"status": "calling", "senior_name": enrollment["senior_name"]}
