"""
live_calls.py

Listens to REAL protected calls: a senior who said YES forwards their phone
to Scam Shield, a caller rings them, and we read the call as it happens.

How it fits in:
  1. Our Twilio number's front door is phone_line.incoming_call. When a call
     was forwarded from a signed-up senior's phone, it hands the call to
     Cass's calls.handle_incoming_call instead of the "Test it" line.
  2. For a landline, calls.handle_incoming_call puts the call in a conference
     room, rings the senior's adapter, and turns on Twilio's live
     transcription with start_transcription() below.
  3. Every finished sentence comes to /twilio/protected/transcript. We run
     the same checks as everywhere else (call_monitor.check_live_call), which
     scores the call with Nemotron, searches Tavily, and alerts the family
     at 70, by email too if they gave us one.

Cell phone seniors add Scam Shield to a call themselves (Add call, then
Merge; see senior_added_us). We never ring a cell phone back. If an old
missed call forward still sends us one of their calls, the caller gets our
voicemail (voicemail_twiml). We read the message the same way, and a scam
voicemail emails the family (call_monitor.check_voicemail).

We only transcribe the caller's side (the person who called Grandma), and we
keep the words in memory while the call is going. They never go in the database.
"""

import json
import threading

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import Start, VoiceResponse

from app import call_monitor, storage
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

# Voicemails being left right now. We read them once, when the caller hangs up.
VOICEMAILS: set[str] = set()

# The longest voicemail we wait for (seconds).
VOICEMAIL_SECONDS = 60

# The scam warning everyone on the call hears, in the senior's language.
SCAM_WARNING = {
    "en": "This is a potential scam. We are notifying a family member.",
    "es": "Esta es una posible estafa. Estamos avisando a un familiar.",
}

# What the caller hears when they reach Scam Shield's voicemail, by the
# senior's language. We don't say the senior's name to a stranger.
VOICEMAIL_WORDS = {
    "en": {
        "greeting": "The person you are calling can't come to the phone right now. "
        "Please leave a short message, and hang up when you're done.",
        "goodbye": "Thank you. Goodbye.",
    },
    "es": {
        "greeting": "La persona a quien llama no puede contestar ahora. "
        "Por favor deje un mensaje corto, y cuelgue cuando termine.",
        "goodbye": "Gracias. Adiós.",
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
    VOICEMAILS.discard(call_id)


@router.post("/twilio/protected/transcript")
async def receive_words(request: Request, background: BackgroundTasks, call_id: str = ""):
    """
    Twilio's live transcription sends the caller's words here, one sentence
    at a time. Each new sentence kicks off a check in the background. A
    voicemail is read once, when the caller hangs up.

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
            # We don't print or save the words anywhere. They stay in memory
            # until the call ends (our privacy promise).
            LINES.setdefault(call_id, []).append(words)
            if call_id not in VOICEMAILS:
                background.add_task(check_call, call_id)
    elif event == "transcription-stopped":
        if call_id in VOICEMAILS:
            transcript = "\n".join(f"Caller: {words}" for words in LINES.get(call_id, []))
            background.add_task(call_monitor.check_voicemail, call_id, transcript)
        forget_call(call_id)
    return Response(status_code=200)


def scam_warning(call: dict) -> str:
    """
    The scam warning in the senior's own language (English or Spanish).

    Example:
        scam_warning(call) for Rosa, who speaks Spanish, gives you SCAM_WARNING["es"]
    """
    enrollment = storage.get_enrollment(call["enrollment_id"]) or {}
    return SCAM_WARNING.get(enrollment.get("senior_language"), SCAM_WARNING["en"])


def voicemail_twiml(enrollment: dict, caller: str, call_sid: str) -> str:
    """
    Scam Shield's voicemail, for a missed call a cell phone senior's phone
    still forwards to us. We never ring a cell phone back. Instead we read the
    message as it's left, and when the caller hangs up,
    call_monitor.check_voicemail() decides if it's a scam.

    We don't record the audio. Only the words, in memory, until the check is done.

    Input:  enrollment, the senior's active sign up
            caller, who's calling (Twilio's "From")
            call_sid, Twilio's ID for the call
    Output: TwiML: greeting, listen for up to a minute, goodbye

    Example:
        voicemail_twiml(rosa, "+13055550142", "CA123") gives you
        "The person you are calling can't come to the phone right now..."
    """
    # Imported here because calls.py imports this file too.
    from app import calls

    call = calls.start_protected_call(enrollment, caller, call_sid, ring_senior=False)
    VOICEMAILS.add(call["id"])
    words = VOICEMAIL_WORDS.get(enrollment.get("senior_language"), VOICEMAIL_WORDS["en"])

    response = VoiceResponse()
    response.say(words["greeting"])
    start_transcription(response, call["id"])
    response.pause(length=VOICEMAIL_SECONDS)
    response.say(words["goodbye"])
    response.hangup()
    return str(response)


def twiml_response(response: VoiceResponse) -> Response:
    """
    Sends TwiML back to Twilio.

    Example:
        twiml_response(VoiceResponse()) gives you an XML response
    """
    return Response(content=str(response), media_type="application/xml")


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
    link = announce_link(call_id)
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


def announce_link(call_id: str) -> str:
    """
    The web address Twilio reads the scam warning from.

    Example:
        announce_link("c1") gives you ".../twilio/protected/warning?call_id=c1"
    """
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/twilio/protected/warning?call_id={call_id}"


@router.post("/twilio/protected/warning")
async def warning_message(request: Request, call_id: str = ""):
    """
    The words Twilio plays into a call: the scam warning.

    Example:
        Rosa hears "This is a potential scam. We are notifying a family member."
    """
    form = await read_twilio_form(request)
    if form is None:
        return Response(status_code=403)
    response = VoiceResponse()
    call = storage.get_call(call_id)
    if call is not None:
        response.say(scam_warning(call))
    return twiml_response(response)


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
