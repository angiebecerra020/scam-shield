"""
live_calls.py

Listens to REAL protected calls: a senior who said YES forwards their phone
to Scam Shield, a caller rings them, and we read the call as it happens.

How it fits in:
  1. Our Twilio number's front door is phone_line.incoming_call. When a call
     was forwarded from a signed-up senior's phone, it hands the call to
     Cass's calls.handle_incoming_call instead of the "Test it" line.
  2. calls.handle_incoming_call puts the call in a conference room, rings the
     senior's calling app, and turns on Twilio's live transcription with
     start_transcription() below.
  3. Every finished sentence comes to /twilio/protected/transcript. We run
     the same checks as everywhere else (call_monitor.check_live_call), which
     scores the call with Nemotron, searches Tavily, and alerts the family
     at 70, by email too if they gave us one.

Cell phone seniors get a choice first. Their phone only forwards calls they
decline or miss, and calls.ring_senior_phone rings their real phone back.
When they pick up, screen_call() asks "Press 1 to answer with Scam Shield
listening, press 2 to answer without it." Either way the call goes through.
Press 2 (or a family that paused protection) means we ignore every word.

Silent calls: robocallers and voice cloners often stay quiet, hoping the
senior talks first (about 3 seconds of someone's voice is enough to clone
it). If the caller hasn't said a word 10 seconds after the senior picks up,
we warn the senior. At 20 seconds we hang up and email the family.

We only transcribe the caller's side (the person who called Grandma), and we
keep the words in memory while the call is going. They never go in the database.
"""

import json
import threading

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import Start, VoiceResponse

from app import call_monitor, email_alerts, storage
from app.alerts import twilio_client
from app.config import get_settings
from app.phone_line import read_twilio_form
from app.phone_numbers import normalize_phone

router = APIRouter()

# What the caller said on each live call, by our call ID.
LINES: dict[str, list[str]] = {}

# How many sentences we've checked on each call, and a lock per call so two
# checks of the same call never run at the same time.
CHECKED: dict[str, int] = {}
LOCKS: dict[str, threading.Lock] = {}

# We wait until the caller has said at least this many words before scoring.
# With only "Hello? Hi" (or a bit of noise Twilio misheard), Nemotron has to
# guess, and it guessed "grandparent scam" on a quiet test call. 10 words is
# about one real sentence, so real scams still get caught fast.
MIN_WORDS = 10

# Calls where the senior pressed 2: we don't score them or log their words.
UNPROTECTED: set[str] = set()

# Silent calls: warn the senior after this long, then hang up (seconds).
SILENCE_WARNING_SECONDS = 10
SILENCE_HANGUP_SECONDS = 20

# The two timers waiting on each silent call, so the caller's first words
# can cancel them.
SILENCE_TIMERS: dict[str, list[threading.Timer]] = {}

# What the senior hears when we ring them, by language.
SCREEN_WORDS = {
    "en": {
        "question": "Hi, this is Scam Shield. You have a call from {caller}. "
        "Press 1 to answer with Scam Shield listening. Press 2 to answer without it.",
        "protected": "Scam Shield is listening. Connecting you now.",
        "unprotected": "Connecting you now.",
        "silence": "Careful. This caller hasn't said anything. Silent calls are often scams. "
        "Please don't talk to them. We'll end this call soon.",
        "scam": "This is a potential scam. We are notifying a family member.",
    },
    "es": {
        "question": "Hola, habla Scam Shield. Tiene una llamada del {caller}. "
        "Marque 1 para contestar con Scam Shield escuchando. Marque 2 para contestar sin Scam Shield.",
        "protected": "Scam Shield está escuchando. Le conectamos ahora.",
        "unprotected": "Le conectamos ahora.",
        "silence": "Cuidado. Esta persona no ha dicho nada. Las llamadas en silencio suelen ser estafas. "
        "Por favor no hable con ella. Vamos a terminar esta llamada pronto.",
        "scam": "Esta es una posible estafa. Estamos avisando a un familiar.",
    },
}

# Sign-ups whose calls really get forwarded to us. Demo sign-ups never do.
REAL_STATUSES = ("active", "paused", "pending")


def find_forwarding_senior(forwarded_from: str | None) -> dict | None:
    """
    Finds the signed-up senior whose phone forwarded this call to us.

    Input:  forwarded_from, Twilio's "ForwardedFrom" (the senior's number), or None
    Output: their sign-up, or None if it wasn't forwarded by one of our seniors

    Example:
        find_forwarding_senior("+13055619356") gives you {"senior_name": "Rosa", ...}
        find_forwarding_senior(None) gives you None
    """
    phone = normalize_phone(forwarded_from or "")
    if not phone:
        return None
    for enrollment in storage.find_enrollments_for_senior(phone):
        if enrollment["status"] in REAL_STATUSES:
            return enrollment
    return None


def start_transcription(response: VoiceResponse, call_id: str) -> None:
    """
    Adds Twilio's live transcription to a protected call's TwiML.

    Input:  response, the TwiML calls.handle_incoming_call is building
            call_id, our ID for the call
    Output: nothing (it adds to response)

    Example:
        start_transcription(response, "c1") adds
        <Start><Transcription track="inbound_track" statusCallbackUrl=".../twilio/protected/transcript?call_id=c1"/></Start>
    """
    base = get_settings().public_base_url.rstrip("/")
    start = Start()
    start.transcription(
        name="scam-shield",
        status_callback_url=f"{base}/twilio/protected/transcript?call_id={call_id}",
        track="inbound_track",
        partial_results=False,
    )
    response.append(start)


def read_words(transcription_data: str) -> str:
    """
    Pulls the words out of what Twilio's transcription sends us.

    Example:
        read_words('{"transcript": " Grandma, it is me "}') gives you "Grandma, it is me"
    """
    try:
        data = json.loads(transcription_data)
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("transcript") or "").strip()[:500]


def check_call(call_id: str) -> None:
    """
    Reads the call so far with every check, again until we've read every
    sentence. Runs in the background after Twilio sends us new words.
    Skips the check until the caller has said MIN_WORDS words in all.

    Example:
        check_call("c1") after the caller says "I'm in jail, I need bail money"
    """
    lock = LOCKS.setdefault(call_id, threading.Lock())
    with lock:
        while CHECKED.get(call_id, 0) < len(LINES.get(call_id, [])):
            count = len(LINES[call_id])
            turns = []
            word_count = 0
            for words in LINES[call_id][:count]:
                turns.append(f"Caller: {words}")
                word_count += len(words.split())
            if word_count < MIN_WORDS:
                # Not enough to judge yet. The next sentence brings us back here.
                return
            try:
                # The moment the family's phone starts ringing, the senior
                # hears the warning too, right on the call (warn_senior).
                call_monitor.check_live_call(call_id, "\n".join(turns), warn_senior=warn_senior)
            except ValueError:
                # The call isn't in storage anymore (the family removed the senior).
                pass
            CHECKED[call_id] = count


def forget_call(call_id: str) -> None:
    """
    Lets go of a call's words once the call is over.

    Example:
        forget_call("c1")
    """
    LINES.pop(call_id, None)
    CHECKED.pop(call_id, None)
    LOCKS.pop(call_id, None)
    UNPROTECTED.discard(call_id)
    stop_silence_watch(call_id)


@router.post("/twilio/protected/transcript")
async def receive_words(request: Request, background: BackgroundTasks, call_id: str = ""):
    """
    Twilio's live transcription sends the caller's words here, one sentence
    at a time. Each new sentence kicks off a check in the background.

    Example:
        Twilio sends {"TranscriptionEvent": "transcription-content", "Final": "true",
        "TranscriptionData": '{"transcript": "Grandma, I need bail money"}'}
    """
    form = await read_twilio_form(request)
    if form is None:
        return Response(status_code=403)

    event = form.get("TranscriptionEvent", "")
    if event == "transcription-content" and form.get("Final", "").lower() == "true":
        words = read_words(form.get("TranscriptionData", ""))
        if words and call_id in UNPROTECTED:
            # The senior pressed 2, so we don't read or keep anything.
            words = ""
        if words:
            # The caller is talking, so this isn't a silent call.
            stop_silence_watch(call_id)
            # We don't print or save the words anywhere. They stay in memory
            # until the call ends (our privacy promise).
            LINES.setdefault(call_id, []).append(words)
            background.add_task(check_call, call_id)
    elif event == "transcription-stopped":
        forget_call(call_id)
    return Response(status_code=200)


def screen_words(call: dict) -> dict:
    """
    Picks what the senior hears in their own language (English or Spanish).

    Example:
        screen_words(call) for Rosa, who speaks Spanish, gives you SCREEN_WORDS["es"]
    """
    enrollment = storage.get_enrollment(call["enrollment_id"]) or {}
    return SCREEN_WORDS.get(enrollment.get("senior_language"), SCREEN_WORDS["en"])


def say_phone_number(phone: str) -> str:
    """
    Spaces out a phone number so Twilio reads it digit by digit.

    Example:
        say_phone_number("+15615842403") gives you "5 6 1, 5 8 4, 2 4 0 3"
    """
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return "an unknown number"
    parts = [digits[:3], digits[3:6], digits[6:]]
    return ", ".join(" ".join(part) for part in parts)


@router.post("/twilio/protected/screen")
async def screen_call(request: Request, call_id: str = ""):
    """
    The senior picked up our call. Asks them: press 1 for Scam Shield, 2 for no.

    If they don't press anything, we keep them protected. That's the safe
    choice, and the call still goes through.

    Example:
        Rosa answers and hears "You have a call from 5 6 1... Press 1..."
    """
    form = await read_twilio_form(request)
    if form is None:
        return Response(status_code=403)

    call = storage.get_call(call_id)
    response = VoiceResponse()
    if call is None or call["status"] != "live":
        # The caller already hung up while we were ringing.
        response.hangup()
        return twiml_response(response)

    words = screen_words(call)
    choice_url = f"/twilio/protected/choice?call_id={call_id}"
    gather = response.gather(num_digits=1, timeout=6, action=choice_url)
    gather.say(words["question"].format(caller=say_phone_number(call["caller_number"])))
    # No key pressed: same as pressing 1.
    response.redirect(f"{choice_url}&Digits=1")
    return twiml_response(response)


@router.post("/twilio/protected/choice")
async def senior_choice(request: Request, call_id: str = "", Digits: str = ""):
    """
    Puts the senior in the call, with or without Scam Shield listening.

    Example:
        Rosa presses 1, hears "Scam Shield is listening", and talks to the caller
    """
    form = await read_twilio_form(request)
    if form is None:
        return Response(status_code=403)

    call = storage.get_call(call_id)
    response = VoiceResponse()
    if call is None or call["status"] != "live":
        response.hangup()
        return twiml_response(response)

    words = screen_words(call)
    digit = form.get("Digits") or Digits or "1"
    if digit == "2":
        UNPROTECTED.add(call_id)
        response.say(words["unprotected"])
    else:
        response.say(words["protected"])
        start_silence_watch(call_id)

    dial = response.dial()
    dial.conference(
        call["conference_name"],
        # Same as Cass's calling app: the senior starts the conversation,
        # and when they hang up the call is over for everyone.
        start_conference_on_enter=True,
        end_conference_on_exit=True,
        beep=False,
    )
    return twiml_response(response)


def twiml_response(response: VoiceResponse) -> Response:
    """
    Sends TwiML back to Twilio.

    Example:
        twiml_response(VoiceResponse()) gives you an XML response
    """
    return Response(content=str(response), media_type="application/xml")


def start_silence_watch(call_id: str) -> None:
    """
    Starts the silent call timers: a warning at 10 seconds, hang up at 20.

    The caller's first words stop both (see receive_words).

    Example:
        start_silence_watch("c1") right after Rosa presses 1
    """
    stop_silence_watch(call_id)
    warning = threading.Timer(SILENCE_WARNING_SECONDS, warn_about_silence, args=[call_id])
    hang_up = threading.Timer(SILENCE_HANGUP_SECONDS, end_silent_call, args=[call_id])
    # Daemon timers never keep the server from shutting down.
    warning.daemon = True
    hang_up.daemon = True
    SILENCE_TIMERS[call_id] = [warning, hang_up]
    warning.start()
    hang_up.start()


def stop_silence_watch(call_id: str) -> None:
    """
    Cancels the silent call timers, because the caller spoke or the call ended.

    Example:
        stop_silence_watch("c1")
    """
    for timer in SILENCE_TIMERS.pop(call_id, []):
        timer.cancel()


def find_conference(call: dict):
    """
    Finds the Twilio conference room for a live call, or None if it's closed.

    Example:
        find_conference(call) gives you Twilio's conference, so we can talk in it
    """
    # A room with only the senior in it hasn't "started" yet in Twilio's eyes
    # (status "init"), but we still need to talk in it, so we take any room
    # that isn't over.
    rooms = twilio_client().conferences.list(friendly_name=call["conference_name"], limit=5)
    for room in rooms:
        if room.status != "completed":
            return room
    return None


def warn_about_silence(call_id: str) -> None:
    """
    Tells everyone on a silent call: "This caller hasn't said anything..."

    Example:
        warn_about_silence("c1") 10 seconds into a silent call
    """
    call = storage.get_call(call_id)
    if call is None or call["status"] != "live":
        return
    try:
        room = find_conference(call)
        if room is not None:
            # Twilio plays whatever silence_message() says to everyone in the room.
            room.update(announce_url=announce_link(call_id))
    except Exception as problem:
        # A failed warning should never crash the server mid call.
        print(f"[live call {call_id}] Couldn't play the silence warning: {problem}")


def warn_senior(call_id: str) -> None:
    """
    Says the scam warning out loud to everyone on the call, the moment the
    family's alert call goes out: "This is a potential scam. We are notifying a family member."

    Example:
        warn_senior("c1") right after Nemotron scores the call 92
    """
    call = storage.get_call(call_id)
    if call is None or call["status"] != "live":
        return
    link = announce_link(call_id, "scam")
    try:
        room = find_conference(call)
    except Exception as problem:
        print(f"[live call {call_id}] Couldn't find the room for the scam warning: {problem}")
        return
    if room is None:
        return
    try:
        # Everyone in the room hears it.
        room.update(announce_url=link)
        return
    except Exception as problem:
        print(f"[live call {call_id}] Room announcement didn't work, trying the senior's line: {problem}")
    try:
        # A room that hasn't started can't take an announcement, so we play it
        # straight to the line that called us. On an added call that's the
        # senior (and on a merged call the other person hears it too).
        room.participants(call["call_sid"]).update(announce_url=link)
    except Exception as problem:
        # A failed warning should never crash the server mid call.
        print(f"[live call {call_id}] Couldn't play the scam warning: {problem}")


def announce_link(call_id: str, kind: str = "silence") -> str:
    """
    The web address Twilio reads a warning from: "silence" or "scam".

    Example:
        announce_link("c1") gives you ".../twilio/protected/silence?call_id=c1"
        announce_link("c1", "scam") gives you ".../twilio/protected/silence?call_id=c1&kind=scam"
    """
    base = get_settings().public_base_url.rstrip("/")
    link = f"{base}/twilio/protected/silence?call_id={call_id}"
    if kind != "silence":
        link += f"&kind={kind}"
    return link


@router.post("/twilio/protected/silence")
async def silence_message(request: Request, call_id: str = "", kind: str = "silence"):
    """
    The words Twilio plays into a call: the silent call warning, or (with
    kind=scam) the scam warning.

    Example:
        Rosa hears "Careful. This caller hasn't said anything..."
        with kind=scam, Rosa hears "This is a potential scam. We are notifying a family member."
    """
    form = await read_twilio_form(request)
    if form is None:
        return Response(status_code=403)
    response = VoiceResponse()
    call = storage.get_call(call_id)
    if call is not None:
        words = screen_words(call)
        response.say(words["scam"] if kind == "scam" else words["silence"])
    return twiml_response(response)


def end_silent_call(call_id: str) -> None:
    """
    Hangs up a call where the caller never said a word, and emails the family.

    Example:
        end_silent_call("c1") 20 seconds into a silent call
    """
    SILENCE_TIMERS.pop(call_id, None)
    call = storage.get_call(call_id)
    if call is None or call["status"] != "live":
        return

    storage.mark_call_ended(call_id)
    try:
        room = find_conference(call)
        if room is not None:
            room.update(status="completed")
    except Exception as problem:
        print(f"[live call {call_id}] Couldn't hang up the silent call: {problem}")

    enrollment = storage.get_enrollment(call["enrollment_id"]) or {}
    if enrollment.get("family_email"):
        email_alerts.send_email(
            enrollment["family_email"],
            f"Scam Shield ended a silent call to {enrollment.get('senior_name', 'your family member')}",
            f"Hi {enrollment.get('family_name', '')},\n\n"
            f"Someone at {call['caller_number']} called {enrollment.get('senior_name', 'your family member')} "
            "and didn't say a word for 20 seconds. Silent calls are often scammers checking if a "
            "number works, or trying to record a voice. We ended the call to keep them safe.\n\n"
            "Scam Shield",
        )


# What the senior hears when they add Scam Shield to a call, by language.
ADDED_WORDS = {
    "en": {
        "joining": "Scam Shield is joining your call. To remove Scam Shield from this call, press 2.",
        "listening": "Scam Shield is listening.",
        "removed": "Scam Shield was removed from this call. We are not listening. Goodbye.",
    },
    "es": {
        "joining": "Scam Shield se está uniendo a su llamada. Para quitar Scam Shield de esta llamada, marque 2.",
        "listening": "Scam Shield está escuchando.",
        "removed": "Se quitó Scam Shield de esta llamada. No estamos escuchando. Adiós.",
    },
}

# Who the "caller" is when the senior adds us to a call. We don't know the
# other person's number, so research.py skips the number check.
ADDED_CALLER = "Unknown"


def senior_added_us(enrollment: dict, call_sid: str) -> str:
    """
    The senior called our number, usually by tapping "Add call" and "Merge"
    during a call that feels wrong. We start listening right away.

    On a merged call, the senior's phone sends us BOTH voices, so the caller
    gets transcribed too. The senior's side goes in a conference room, so the
    family's "Join call" link works just like on a forwarded call.

    For the first few seconds they can still press 2 to take Scam Shield off
    this call (added_choice). After that, keys do nothing, so the other
    person on the call can't turn us off.

    Input:  enrollment, the senior's active sign up
            call_sid, Twilio's ID for the senior's call to us
    Output: TwiML: listen, offer press 2, then join the room

    Example:
        Rosa taps Add call, picks Scam Shield, taps Merge, and hears
        "Scam Shield is joining your call..." then "Scam Shield is listening."
    """
    # Imported here because calls.py imports this file too.
    from app import calls

    call = calls.start_protected_call(enrollment, ADDED_CALLER, call_sid, ring_senior=False)
    words = ADDED_WORDS.get(enrollment.get("senior_language"), ADDED_WORDS["en"])
    base = get_settings().public_base_url.rstrip("/")

    response = VoiceResponse()
    start_transcription(response, call["id"])
    # Our own menu, not Cass's: only 2 cancels. On a merged call the phone
    # can send a tone by itself, and Cass's menu hangs up on any other key,
    # which cut our first real test off after 14 seconds.
    gather = response.gather(
        num_digits=1,
        timeout=6,
        action=f"{base}/twilio/protected/added-choice?call_id={call['id']}",
    )
    gather.say(words["joining"])
    add_listening(response, call, words)
    return str(response)


def add_listening(response: VoiceResponse, call: dict, words: dict) -> None:
    """
    Says "Scam Shield is listening" and puts the senior's side in the call's
    conference room, so the family's "Join call" link works.

    Example:
        add_listening(response, call, ADDED_WORDS["en"])
    """
    base = get_settings().public_base_url.rstrip("/")
    response.say(words["listening"])
    dial = response.dial()
    dial.conference(
        call["conference_name"],
        # Silence instead of Twilio's hold music. On a merged call the senior's
        # line is alone in the room until the family joins, and Twilio plays
        # music to anyone waiting alone, right over the conversation.
        wait_url="",
        start_conference_on_enter=True,
        # When the senior hangs up, the call is over for everyone.
        end_conference_on_exit=True,
        beep=False,
        status_callback=f"{base}/twilio/conference-status",
        status_callback_event="end",
    )


@router.post("/twilio/protected/added-choice")
async def added_choice(request: Request, call_id: str = ""):
    """
    The senior added Scam Shield to a call and a key was pressed during
    "press 2 to remove Scam Shield from this call". Only 2 removes us. Any
    other key, like a stray tone from the merge, keeps us listening.

    Pressing 2 only takes us off THIS call: we stop reading the words, delete
    the call, and hang up our side, so the senior and the other person keep
    talking without us. Their protection stays on for later calls. To cancel
    Scam Shield for good, they call our number by itself (consent.py).

    It used to run the full cancel, which texts and emails the family before
    answering. That could take longer than the 15 seconds Twilio waits, so
    the senior never heard back.

    Example:
        Digits=2 gives you "Scam Shield was removed from this call..."
        Digits=1 gives you "Scam Shield is listening." and the call goes on
    """
    form = await read_twilio_form(request)
    if form is None:
        return Response(status_code=403)

    call = storage.get_call(call_id)
    response = VoiceResponse()
    if call is None:
        response.hangup()
        return twiml_response(response)

    enrollment = storage.get_enrollment(call["enrollment_id"]) or {}
    words = ADDED_WORDS.get(enrollment.get("senior_language"), ADDED_WORDS["en"])

    if form.get("Digits", "") == "2":
        # Any words still on their way from Twilio get thrown away.
        UNPROTECTED.add(call_id)
        LINES.pop(call_id, None)
        storage.delete_call(call_id)
        response.say(words["removed"])
        # Hanging up our side drops Scam Shield out of the merged call.
        response.hangup()
        return twiml_response(response)

    add_listening(response, call, words)
    return twiml_response(response)
