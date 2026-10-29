"""
phone_line.py

The "Test it" line. Anyone can call our Twilio number, play the
scammer, and watch Scam Shield catch them live on the page (static/try.html).

How it fits in:
  1. The page asks for a 4 digit code (POST /api/line/start). It can also
     take an email address, so the visitor gets Ana's alert for real.
  2. The visitor calls our number. Twilio asks us what to do
     (/twilio/line/incoming) and we ask for the code. Once it matches
     (/twilio/line/code), we set up the same pretend family as the demo
     player (demo_api.py) and turn on Twilio's live transcription.
  3. Every time the caller finishes a sentence, Twilio sends us the words
     (/twilio/line/transcript). We run the same checks as any protected
     call: Nemotron, Tavily and the family alert (call_monitor.py), plus
     "Is it really you?" (verify.py).
  4. While the call is going, Twilio checks back with us every couple of
     seconds (/twilio/line/loop). When it's time to warn Grandma, we say the
     warning out loud right on the call.
  5. The page asks for updates every second (GET /api/line/{ticket_id}) and
     shows everything as it happens.

The same number works for "Add Scam Shield to the call" too: during any
call, add our number as a 3 way call, type the code, and we listen in.

It only runs in demo mode, so the family is always made up and nobody gets
a text or a call from us. The only real things are the visitor's own call
and the alert email they asked for. We never save the audio, and the
visitor's phone number never goes in the database.

To keep our Twilio bill small, each visitor gets a few codes an hour, each
phone a few calls a day, and each call 5 minutes.
"""

import hashlib
import json
import secrets
import threading
import time

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Gather, Start, VoiceResponse

from app import (
    alerts,
    call_monitor,
    calls,
    consent,
    demo_api,
    detector,
    email_alerts,
    senior_warnings,
    storage,
    verify,
)
from app.config import PROJECT_ROOT, get_settings
from app.twilio_security import public_url_for

router = APIRouter()

TRY_PAGE = PROJECT_ROOT / "static" / "try.html"

# The limits that keep our Twilio and Gmail use small.
MAX_CODES_PER_HOUR = 5
MAX_CALLS_PER_PHONE_PER_DAY = 5
MAX_CALL_SECONDS = 5 * 60
MAX_EMAILS_PER_DAY = 100
ONE_DAY_SECONDS = 24 * 3600

# A code works for 15 minutes, and you get 3 tries to type it right.
CODE_EXPIRES_SECONDS = 15 * 60
MAX_CODE_TRIES = 3

# How long Twilio waits between check ins during the call. Short enough that
# Grandma's warning plays right away, long enough to not flood our server.
LOOP_PAUSE_SECONDS = 2

# We save this made up 555 number as the caller instead of the visitor's real
# number. So their number never ends up in the database or in a web search.
PRETEND_CALLER = "+13055550199"

# The languages you can speak on the call, and how Twilio writes them.
CALL_LANGUAGES = {"en": "en-US", "es": "es-US"}

# The voices that talk on the call. Joanna speaks US English and Lupe speaks
# US Spanish (they're Amazon Polly voices that Twilio has built in).
VOICES = {"en-US": "Polly.Joanna", "es-US": "Polly.Lupe"}

# Everything Scam Shield says on the call, besides Grandma's warnings.
SAYINGS = {
    "ask_code": "Hi, this is Scam Shield. Please type the 4 digit code from your screen.",
    "wrong_code": "That code didn't match. Please type the 4 digit code again.",
    "no_code": (
        "We didn't get a code. Open the Scam Shield demo page to get one, "
        "then call back. Goodbye."
    ),
    "too_many_tries": (
        "That code still didn't match. Get a new code on the Scam Shield demo page, "
        "then call back. Goodbye."
    ),
    "line_off": "The Scam Shield test line is off right now. Goodbye.",
    "too_many_calls": "You've called the test line a lot today. Please try again tomorrow. Goodbye.",
}
LISTENING = {
    "en": (
        "Got it. Scam Shield is listening now. We turn your words into text and "
        "never save the audio. Go ahead and pretend you're calling Grandma Rosa."
    ),
    "es": (
        "Listo. Scam Shield está escuchando. Convertimos sus palabras en texto y "
        "nunca guardamos el audio. Adelante, haga como si llamara a la abuela Rosa."
    ),
}
TIME_UP = {
    "en": "That's 5 minutes. Thanks for trying Scam Shield. Goodbye.",
    "es": "Ya pasaron 5 minutos. Gracias por probar Scam Shield. Adiós.",
}

# Every code the page handed out, by ticket ID. A ticket is one visitor's
# turn: their code, their call, and everything we found on it.
TICKETS: dict[str, dict] = {}

# When each phone called, so we can count calls per day. We keep a scrambled
# version of the number (a hash), never the number itself.
CALLS_BY_PHONE: dict[str, list[float]] = {}

# When we sent each alert email, so we stay under Gmail's daily limit.
EMAILS_SENT: list[float] = []

# One lock per ticket, so two checks of the same call never run at once.
# (Twilio can send us the next sentence while Nemotron is still reading.)
LOCKS: dict[str, threading.Lock] = {}


class LineStartRequest(BaseModel):
    """What the page sends for a code: the call's language, Ana's language, and maybe an email."""

    language: str = "en"
    family_language: str = "en"
    email: str = ""


def error(text: str, status_code: int) -> JSONResponse:
    """
    Sends back an error the page can show.

    Example:
        error("That code is gone.", 404) gives you a 404 with {"error": "That code is gone."}
    """
    return JSONResponse({"error": text}, status_code=status_code)


def twiml(response: VoiceResponse) -> Response:
    """
    Sends instructions back to Twilio in its own XML format (TwiML).

    Example:
        twiml(hang_up_with("Goodbye.")) tells Twilio to say goodbye and hang up
    """
    return Response(content=str(response), media_type="application/xml")


def hang_up_with(text: str, speech_language: str = "en-US") -> VoiceResponse:
    """
    Builds TwiML that says one thing and hangs up.

    Example:
        hang_up_with(SAYINGS["line_off"]) says the line is off, then hangs up
    """
    response = VoiceResponse()
    response.say(text, voice=VOICES[speech_language])
    response.hangup()
    return response


def really_from_twilio(request: Request, form: dict) -> bool:
    """
    Checks that a webhook really came from Twilio, using the signature
    Twilio adds with our auth token.

    We check even in demo mode (twilio_security.is_from_twilio skips it
    there). This line is live on the internet, and a fake request could
    burn through our Nemotron credits or send emails.

    Input:  request, the incoming web request
            form, the form fields Twilio sent
    Output: True only if the signature matches

    Example:
        A request with no X-Twilio-Signature header gives you False
    """
    settings = get_settings()
    if not settings.twilio_auth_token:
        return False
    signature = request.headers.get("X-Twilio-Signature", "")
    validator = RequestValidator(settings.twilio_auth_token)
    return validator.validate(public_url_for(request), form, signature)


async def read_twilio_form(request: Request) -> dict | None:
    """
    Reads what Twilio sent, but only if it really came from Twilio.

    Output: the form fields, or None if the signature is wrong

    Example:
        A real Twilio request gives you {"CallSid": "CA...", "From": "+1...", ...}
    """
    form = dict(await request.form())
    if not really_from_twilio(request, form):
        return None
    return form


def phone_key(phone: str) -> str:
    """
    Scrambles a phone number so we can count its calls without keeping it.

    Example:
        phone_key("+13055551234") gives you something like "9f2c1a..."
    """
    return hashlib.sha256(phone.encode()).hexdigest()[:16]


def phone_under_limit(phone: str) -> bool:
    """
    Counts one more call from a phone, if it's still under the daily limit.

    Input:  phone, the number calling us (Twilio's "From")
    Output: True if they can go ahead, False if they hit the limit

    Example:
        The 6th call today from the same phone gives you False
    """
    now = time.time()
    key = phone_key(phone)
    recent = []
    for moment in CALLS_BY_PHONE.get(key, []):
        if now - moment < ONE_DAY_SECONDS:
            recent.append(moment)

    if len(recent) >= MAX_CALLS_PER_PHONE_PER_DAY:
        CALLS_BY_PHONE[key] = recent
        return False
    recent.append(now)
    CALLS_BY_PHONE[key] = recent
    return True


def email_under_limit() -> bool:
    """
    Counts one more alert email, if we're still under today's limit.

    Example:
        The 101st email today gives you False
    """
    now = time.time()
    recent = []
    for moment in EMAILS_SENT:
        if now - moment < ONE_DAY_SECONDS:
            recent.append(moment)
    EMAILS_SENT[:] = recent

    if len(recent) >= MAX_EMAILS_PER_DAY:
        return False
    EMAILS_SENT.append(now)
    return True


def forget_old_tickets() -> None:
    """
    Marks codes nobody used as expired, and forgets tickets from more than
    two hours ago (same as the demo player forgets its calls).

    Example:
        A code from 20 minutes ago that nobody called with is now "expired"
    """
    now = time.time()
    old_ids = []
    for ticket_id, ticket in TICKETS.items():
        age = now - ticket["created"]
        if ticket["status"] == "waiting" and age > CODE_EXPIRES_SECONDS:
            ticket["status"] = "expired"
        if age > demo_api.FORGET_AFTER_SECONDS:
            old_ids.append(ticket_id)
    for ticket_id in old_ids:
        TICKETS.pop(ticket_id, None)
        LOCKS.pop(ticket_id, None)


def new_code() -> str:
    """
    Makes up a 4 digit code that no waiting ticket is using.

    Example:
        new_code() gives you something like "4821"
    """
    in_use = set()
    for ticket in TICKETS.values():
        if ticket["status"] == "waiting":
            in_use.add(ticket["code"])
    while True:
        code = f"{secrets.randbelow(10000):04d}"
        if code not in in_use:
            return code


def create_ticket(language: str, family_language: str, email: str) -> dict:
    """
    Hands out a new code for one visitor.

    Input:  language, what they'll speak on the call ("en" or "es")
            family_language, what Ana reads ("en" or "es")
            email, where Ana's alert goes, or "" for no email
    Output: the new ticket

    Example:
        create_ticket("en", "es", "") gives you a ticket with a code like "4821"
    """
    forget_old_tickets()
    ticket = {
        "id": secrets.token_urlsafe(16),
        "code": new_code(),
        "language": language if language in CALL_LANGUAGES else "en",
        "family_language": family_language if family_language in CALL_LANGUAGES else "en",
        "email": email,
        "created": time.time(),
        "status": "waiting",
        "call_id": None,
        "started": None,
        "lines": [],
        "checked": 0,
        "latest": None,
        "texts": {"family": [], "contact": []},
        "warned": False,
        "senior_warning": None,
        "warning_count": 0,
        # What Scam Shield still has to say on the call: (text, speech language)
        "to_say": [],
        "email_status": None,
        "note": None,
    }
    TICKETS[ticket["id"]] = ticket
    return ticket


def find_waiting_ticket(code: str) -> dict | None:
    """
    Finds the ticket for a code someone typed on their phone.

    Example:
        find_waiting_ticket("4821") gives you that visitor's ticket, or None
    """
    forget_old_tickets()
    for ticket in TICKETS.values():
        if ticket["status"] == "waiting" and ticket["code"] == code:
            return ticket
    return None


def start_live_call(ticket: dict, call_sid: str) -> None:
    """
    Sets up the pretend family and a protected call, once the code matches.
    It's the same setup as the demo player, so every check works the same.

    Input:  ticket, the visitor's ticket
            call_sid, Twilio's ID for this phone call
    Output: nothing, the ticket is now "live" with its call_id

    Example:
        start_live_call(ticket, "CA123") and Rosa, Ana and Danny are ready
    """
    demo_api.forget_old_sessions()
    enrollment, contacts = demo_api.demo_family({"language": ticket["language"]}, ticket["family_language"])
    storage.save_enrollment(enrollment)
    # Rosa is made up, so there's no phone of hers to ring. The visitor's own
    # call is the whole call.
    call = calls.start_protected_call(enrollment, caller=PRETEND_CALLER, call_sid=call_sid, ring_senior=False)

    # We also add the call to the demo player's sessions, so Danny's YES or
    # NO works the exact same way it does there.
    demo_api.SESSIONS[call["id"]] = {
        "script": None,
        "enrollment": enrollment,
        "contacts": contacts,
        "outbox_seen": len(alerts.DEMO_OUTBOX),
        "calls_seen": len(calls.DEMO_CALL_LOG),
        "warned": False,
        "started": time.time(),
    }
    ticket["call_id"] = call["id"]
    ticket["status"] = "live"
    ticket["started"] = time.time()


def ask_for_code(tries: int, again: bool = False) -> VoiceResponse:
    """
    Builds TwiML that asks the caller to type their 4 digit code.

    Input:  tries, how many wrong codes they typed so far
            again, True if the last code was wrong
    Output: the TwiML

    Example:
        ask_for_code(1, again=True) says "That code didn't match..." and listens for digits
    """
    response = VoiceResponse()
    gather = Gather(
        input="dtmf",
        num_digits=4,
        timeout=10,
        action=calls.public_url(f"/twilio/line/code?tries={tries}"),
        method="POST",
    )
    text = SAYINGS["wrong_code"] if again else SAYINGS["ask_code"]
    gather.say(text, voice=VOICES["en-US"])
    response.append(gather)

    # Twilio only gets here if they didn't type anything.
    response.say(SAYINGS["no_code"], voice=VOICES["en-US"])
    response.hangup()
    return response


def start_listening(ticket: dict) -> VoiceResponse:
    """
    Builds TwiML that turns on live transcription, says Scam Shield is
    listening, and then keeps the call going.

    We only transcribe the caller's side (inbound_track), so Scam Shield
    never reads its own voice back.

    Example:
        start_listening(ticket) gives you <Start><Transcription .../></Start><Say>...</Say><Redirect>...
    """
    speech_language = CALL_LANGUAGES[ticket["language"]]
    response = VoiceResponse()
    start = Start()
    start.transcription(
        name="scam-shield",
        status_callback_url=calls.public_url(f"/twilio/line/transcript?ticket={ticket['id']}"),
        track="inbound_track",
        language_code=speech_language,
        partial_results=False,
    )
    response.append(start)
    response.say(LISTENING[ticket["language"]], voice=VOICES[speech_language])
    response.redirect(calls.public_url(f"/twilio/line/loop?ticket={ticket['id']}"), method="POST")
    return response


def read_words(transcription_data: str) -> str:
    """
    Pulls the words out of what Twilio's transcription sends us.

    Input:  transcription_data, a JSON text like '{"transcript": "Hi Grandma", "confidence": 0.9}'
    Output: the words, or "" if there aren't any

    Example:
        read_words('{"transcript": " Grandma, it is me "}') gives you "Grandma, it is me"
    """
    try:
        data = json.loads(transcription_data)
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    words = str(data.get("transcript") or "").strip()
    # Nobody says more than this in one breath. It keeps a weird answer from
    # filling the page.
    return words[:500]


def end_call(ticket: dict) -> None:
    """
    Marks the call as over, on the ticket and in storage.

    Example:
        end_call(ticket) after the visitor hangs up
    """
    if ticket["status"] == "ended":
        return
    ticket["status"] = "ended"
    if ticket["call_id"]:
        storage.mark_call_ended(ticket["call_id"])


def share_warning(ticket: dict, warning: dict) -> None:
    """
    Shows Grandma's warning on the page and queues it up to say on the call.

    Example:
        share_warning(ticket, {"text": "This call looks like a scam...", "speech_language": "en-US", ...})
    """
    ticket["senior_warning"] = warning
    ticket["warning_count"] += 1
    ticket["to_say"].append((warning["text"], warning["speech_language"]))


def collect_texts(ticket: dict, session: dict) -> None:
    """
    Adds what Ana and Danny just got (her alert call, his texts) to the ticket.

    Example:
        Right after the alert, ticket["texts"]["family"] has Ana's alert call
    """
    fresh = demo_api.new_texts(session)
    ticket["texts"]["family"].extend(fresh["family"])
    ticket["texts"]["contact"].extend(fresh["contact"])


def email_the_alert(ticket: dict, enrollment: dict, detector_result: dict) -> None:
    """
    Emails Ana's alert to the visitor, if they gave us an email.

    Input:  ticket, the visitor's ticket
            enrollment, the pretend Rosa's sign-up
            detector_result, the check that crossed 70
    Output: nothing, ticket["email_status"] says how it went

    Example:
        email_the_alert(ticket, rosa, result) and the visitor gets "Scam Shield alert: ..."
    """
    if not ticket["email"]:
        return
    if not email_alerts.email_is_set_up():
        ticket["email_status"] = "not_set_up"
        return
    if not email_under_limit():
        ticket["email_status"] = "limit"
        return

    watch_link = calls.public_url(f"/try?ticket={ticket['id']}")
    subject, body = email_alerts.alert_email(
        enrollment["family_language"],
        enrollment["senior_name"],
        enrollment["family_name"],
        detector_result,
        watch_link,
    )
    ticket["email_status"] = email_alerts.send_email(ticket["email"], subject, body)


def check_once(ticket: dict) -> None:
    """
    Runs every check on the call so far, just like the demo player does after
    each line, and saves what we found on the ticket.

    Example:
        After "Grandma, I'm in jail, buy gift cards", the score jumps, Ana is
        alerted (and emailed), Danny is asked, and Grandma's warning is queued
    """
    count = len(ticket["lines"])
    session = demo_api.SESSIONS.get(ticket["call_id"])
    if session is None:
        ticket["checked"] = count
        return
    enrollment = session["enrollment"]

    turns = []
    for line in ticket["lines"][:count]:
        turns.append(f"Caller: {line['text']}")
    transcript = "\n".join(turns)

    started = time.perf_counter()
    outcome = call_monitor.check_live_call(ticket["call_id"], transcript)
    seconds = time.perf_counter() - started

    check = verify.ask_if_needed(
        ticket["call_id"], outcome["result"], enrollment["senior_name"], session["contacts"]
    )

    # Grandma gets warned once, the first time the family alert goes out.
    if outcome["alert_sent"] and not ticket["warned"]:
        ticket["warned"] = True
        share_warning(ticket, senior_warnings.senior_warning("scam_likely", enrollment["senior_language"]))

    if outcome["alert_sent_now"]:
        email_the_alert(ticket, enrollment, outcome["result"])

    collect_texts(ticket, session)
    ticket["latest"] = {
        "line": count,
        "result": outcome["result"],
        "model": detector.pick_model(enrollment["family_language"], get_settings()),
        "seconds": round(seconds, 2),
        "research": outcome["research"],
        "alert_sent": outcome["alert_sent"],
        "verify": verify.public_view(check),
    }
    ticket["checked"] = count


def check_call(ticket_id: str) -> None:
    """
    Checks a live call, again and again until we've read every sentence.
    Runs in the background after Twilio sends us new words.

    Example:
        check_call("abc") after the caller says something new
    """
    lock = LOCKS.setdefault(ticket_id, threading.Lock())
    with lock:
        ticket = TICKETS.get(ticket_id)
        while ticket is not None and ticket["checked"] < len(ticket["lines"]):
            check_once(ticket)


def public_view(ticket: dict) -> dict:
    """
    What the page gets to see about a ticket. The visitor's email stays on
    the server; the page only learns whether it went out.

    Example:
        public_view(ticket) gives you {"status": "live", "code": "4821", "lines": [...], ...}
    """
    seconds_left = None
    if ticket["started"]:
        seconds_left = max(0, int(MAX_CALL_SECONDS - (time.time() - ticket["started"])))
    return {
        "status": ticket["status"],
        "code": ticket["code"],
        "phone_number": get_settings().twilio_phone_number,
        "language": ticket["language"],
        "family_language": ticket["family_language"],
        "call_id": ticket["call_id"],
        "lines": ticket["lines"],
        "checked": ticket["checked"],
        "latest": ticket["latest"],
        "texts": ticket["texts"],
        "senior_warning": ticket["senior_warning"],
        "warning_count": ticket["warning_count"],
        "email": {"asked": bool(ticket["email"]), "status": ticket["email_status"]},
        "seconds_left": seconds_left,
        "note": ticket["note"],
    }


@router.get("/try")
def show_try_page() -> FileResponse:
    """
    Sends the "Test it" page.

    Example:
        Open http://localhost:8000/try and you see the page
    """
    return FileResponse(TRY_PAGE)


@router.post("/api/line/start")
def start_ticket(body: LineStartRequest, request: Request):
    """
    Hands the page a code to type on the phone. Counts against the visitor's hourly limit.

    Example:
        POST /api/line/start with {"language": "en", "family_language": "en", "email": ""}
        gives you {"ticket_id": "...", "code": "4821", "phone_number": "+1..."}
    """
    if not demo_api.demo_is_on():
        return error("The test line only works with DEMO_MODE=true.", 404)
    if not get_settings().twilio_phone_number:
        return error("The test line isn't set up yet. Watch a scripted call instead.", 503)

    email = body.email.strip()
    if email and not email_alerts.is_email(email):
        return error("That email doesn't look right. Check it, or leave it blank.", 400)

    if not demo_api.under_limit(demo_api.visitor_id(request), "line_codes", MAX_CODES_PER_HOUR):
        return error("You've asked for a lot of codes this hour. Please try again in a little while.", 429)

    ticket = create_ticket(body.language, body.family_language, email)
    return {"ticket_id": ticket["id"], **public_view(ticket)}


@router.get("/api/line/{ticket_id}")
def get_ticket(ticket_id: str):
    """
    Everything that happened on a visitor's call so far. The page asks every second.

    Example:
        GET /api/line/abc gives you {"status": "live", "lines": [...], "latest": {...}, ...}
    """
    forget_old_tickets()
    ticket = TICKETS.get(ticket_id)
    if ticket is None:
        return error("This code is gone. Get a new one to try again.", 404)
    return public_view(ticket)


@router.post("/api/line/{ticket_id}/answer")
def answer_as_danny(ticket_id: str, body: demo_api.AnswerRequest):
    """
    Records Danny's YES or NO for a live call, same as in the demo player.

    Example:
        POST /api/line/abc/answer with {"answer": "no"} warns Grandma on the call
    """
    ticket = TICKETS.get(ticket_id)
    if ticket is None or ticket["call_id"] is None:
        return error("There's no call to answer for yet.", 404)

    with LOCKS.setdefault(ticket_id, threading.Lock()):
        try:
            answer = demo_api.answer_demo_check(ticket["call_id"], body.answer)
        except ValueError as problem:
            return error(str(problem), 409)
        ticket["texts"]["family"].extend(answer["texts"]["family"])
        ticket["texts"]["contact"].extend(answer["texts"]["contact"])
        if answer["senior_warning"]:
            share_warning(ticket, answer["senior_warning"])
        if ticket["latest"]:
            ticket["latest"]["verify"] = answer["verify"]
    return public_view(ticket)


@router.post("/twilio/line/incoming")
async def incoming_call(request: Request):
    """
    Twilio asks this when someone calls our number. We ask for their code.

    Example:
        A call comes in, and the caller hears "Hi, this is Scam Shield. Please type the 4 digit code..."
    """
    form = await read_twilio_form(request)
    if form is None:
        return Response(status_code=403)
    # A call forwarded from a signed-up senior's phone is a real protected
    # call, not someone trying the test line. Cass's calls.py takes it from here.
    from app import live_calls
    senior = live_calls.find_forwarding_senior(form.get("ForwardedFrom"))
    if senior is not None:
        xml = calls.handle_incoming_call(
            caller=form.get("From", ""),
            call_sid=form.get("CallSid", ""),
            forwarded_from=senior["senior_phone"],
            call_token=form.get("CallToken"),
        )
        return Response(content=xml, media_type="application/xml")

    # A senior we protect calling from their own phone gets the "press 2 to
    # cancel Scam Shield" menu instead of the code question (consent.py).
    senior = consent.find_senior_calling_in(form.get("From", ""))
    if senior is not None:
        return Response(content=consent.senior_menu_twiml(senior["id"]), media_type="application/xml")

    if not demo_api.demo_is_on():
        return twiml(hang_up_with(SAYINGS["line_off"]))
    if not phone_under_limit(form.get("From", "")):
        return twiml(hang_up_with(SAYINGS["too_many_calls"]))
    return twiml(ask_for_code(tries=0))


@router.post("/twilio/line/code")
async def check_code(request: Request, tries: int = 0):
    """
    Twilio sends us the digits the caller typed. If they match a code, we start listening.

    Example:
        The caller types 4821, which matches a waiting ticket, and Scam Shield starts listening
    """
    form = await read_twilio_form(request)
    if form is None:
        return Response(status_code=403)

    ticket = find_waiting_ticket(form.get("Digits", ""))
    if ticket is None:
        tries += 1
        if tries >= MAX_CODE_TRIES:
            return twiml(hang_up_with(SAYINGS["too_many_tries"]))
        return twiml(ask_for_code(tries, again=True))

    start_live_call(ticket, form.get("CallSid", ""))
    return twiml(start_listening(ticket))


@router.post("/twilio/line/loop")
async def keep_listening(request: Request, ticket: str = ""):
    """
    Twilio checks in here every couple of seconds during the call. We say
    Grandma's warning if it's ready, hang up after 5 minutes, and otherwise
    just keep listening.

    Example:
        Right after the score hits 70, the caller hears "This call looks like a scam..."
    """
    form = await read_twilio_form(request)
    if form is None:
        return Response(status_code=403)

    found = TICKETS.get(ticket)
    if found is None or found["status"] != "live":
        response = VoiceResponse()
        response.hangup()
        return twiml(response)

    speech_language = CALL_LANGUAGES[found["language"]]
    if time.time() - found["started"] > MAX_CALL_SECONDS:
        return twiml(hang_up_with(TIME_UP[found["language"]], speech_language))

    response = VoiceResponse()
    while found["to_say"]:
        text, language = found["to_say"].pop(0)
        response.say(text, voice=VOICES.get(language, VOICES["en-US"]))
    response.pause(length=LOOP_PAUSE_SECONDS)
    response.redirect(calls.public_url(f"/twilio/line/loop?ticket={found['id']}"), method="POST")
    return twiml(response)


@router.post("/twilio/line/transcript")
async def receive_words(request: Request, background: BackgroundTasks, ticket: str = ""):
    """
    Twilio's live transcription sends the caller's words here, one sentence
    at a time. Each new sentence kicks off a check in the background, so
    Twilio isn't kept waiting on Nemotron.

    Example:
        Twilio sends {"TranscriptionEvent": "transcription-content", "Final": "true",
        "TranscriptionData": '{"transcript": "Grandma, I need bail money"}'}
        and Nemotron reads the call so far
    """
    form = await read_twilio_form(request)
    if form is None:
        return Response(status_code=403)

    found = TICKETS.get(ticket)
    if found is None:
        return Response(status_code=200)

    event = form.get("TranscriptionEvent", "")
    if event == "transcription-content" and form.get("Final", "").lower() == "true":
        words = read_words(form.get("TranscriptionData", ""))
        if words:
            found["lines"].append({"speaker": "caller", "text": words})
            background.add_task(check_call, found["id"])
    elif event == "transcription-stopped":
        # Twilio stops transcribing when the call ends.
        end_call(found)
    elif event == "transcription-error":
        found["note"] = "Twilio had trouble turning the call into text. Try speaking a little slower."
        print(f"Transcription error: {form.get('TranscriptionError', '')}")
    return Response(status_code=200)
