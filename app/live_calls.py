"""
live_calls.py

Listens to REAL protected calls: a senior who said YES forwards their phone
to Scam Shield, a caller rings them, and we read the call as it happens.

How it fits in:
  1. Our Twilio number's front door is phone_line.incoming_call. When a call
     was forwarded from a signed-up senior's phone, it hands the call to
     Cass's calls.handle_incoming_call instead of the "Call it yourself" line.
  2. calls.handle_incoming_call puts the call in a conference room, rings the
     senior's calling app, and turns on Twilio's live transcription with
     start_transcription() below.
  3. Every finished sentence comes to /twilio/protected/transcript. We run
     the same checks as everywhere else (call_monitor.check_live_call), which
     scores the call with Nemotron, searches Tavily, and alerts the family
     at 70, by email too if they gave us one.

We only transcribe the caller's side (the person who called Grandma), and we
keep the words in memory while the call is going. They never go in the database.
"""

import json
import threading

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import Start, VoiceResponse

from app import call_monitor, storage
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
                call_monitor.check_live_call(call_id, "\n".join(turns))
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
        if words:
            # Shows up in the Render logs, so we can check what Twilio heard.
            # Fine for now because our test calls are acted, never real people.
            print(f"[live call {call_id}] Caller said: {words}")
            LINES.setdefault(call_id, []).append(words)
            background.add_task(check_call, call_id)
    elif event == "transcription-stopped":
        forget_call(call_id)
    return Response(status_code=200)
