"""
demo_api.py

The web routes for the demo player (static/demo.html).

How it fits in: the demo player lets anyone watch Scam Shield catch a scam,
with no real phone call. You pick one of our test calls, and this file:
  1. sets up a pretend family with fake 555 numbers: Rosa (the grandma), Ana
     (her daughter, who gets the alerts) and Danny (her grandson), and starts
     a protected call for Rosa (calls.py)
  2. after each line, runs the real checks on the call so far: Nemotron
     (detector.py), Tavily (research.py) and the family alert (call_monitor.py)
  3. runs the "Is it really you?" check (verify.py) and Grandma's warning
     (senior_warnings.py)
  4. hands everything back to the page, including Ana's alert call and the
     texts Danny gets

It only works in demo mode, so it can never text or call a real person. And
since the hosted demo uses our real Nemotron and Tavily credits, each visitor
can only run so many demo calls an hour.
"""

import random
import secrets
import time

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app import alerts, call_monitor, calls, detector, senior_warnings, storage, verify
from app.config import PROJECT_ROOT, get_settings
from app.demo_mode import list_scripts, transcript_text
from app.languages import message, pick_language

router = APIRouter()

DEMO_PAGE = PROJECT_ROOT / "static" / "demo.html"

# How many demo calls one visitor can start in an hour, and how many lines
# they can check. Plenty for a judge, but it stops anyone from burning
# through our credits.
MAX_CALLS_PER_HOUR = 10
MAX_CHECKS_PER_HOUR = 150
ONE_HOUR_SECONDS = 3600

# We forget demo calls after this long, so the server doesn't fill up over
# the weeks the demo is online.
FORGET_AFTER_SECONDS = 2 * 3600

# When each visitor used the demo, so we can count against the limits above.
VISITS: dict[str, list[float]] = {}

# The demo calls happening right now, by call ID.
SESSIONS: dict[str, dict] = {}

# Area codes for the fake numbers. Every number ends in 555-01XX, which is
# saved for fiction, so it can never reach a real person.
FAKE_AREA_CODES = ("305", "786", "954", "561", "407")


class StartRequest(BaseModel):
    """What the page sends to start a demo call: the language Ana reads."""

    family_language: str = "en"


class CheckRequest(BaseModel):
    """What the page sends after each line: how many lines have been said so far."""

    up_to_line: int


class AnswerRequest(BaseModel):
    """Danny's answer to "Is that really you?": "yes" or "no"."""

    answer: str


def error(text: str, status_code: int) -> JSONResponse:
    """
    Sends back an error the page can show, in the same shape the rest of the app uses.

    Example:
        error("That call isn't running anymore.", 404) gives you a 404 with
        {"error": "That call isn't running anymore."}
    """
    return JSONResponse({"error": text}, status_code=status_code)


def demo_is_on() -> bool:
    """
    Checks that we're in demo mode. The demo player never runs outside it.

    Example:
        With DEMO_MODE=true in .env, demo_is_on() gives you True
    """
    return get_settings().demo_mode


def visitor_id(request: Request) -> str:
    """
    Works out who's visiting, so we can count their demo calls.

    Once the site is online, it sits behind the host's proxy, so the real
    visitor's address is in the X-Forwarded-For header. The host adds it at
    the END of the list. Anything before it came from the visitor, who could
    make it up to dodge the limits, so we take the last one.

    Example:
        A request with X-Forwarded-For "1.2.3.4, 203.0.113.7" gives you "203.0.113.7"
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    if request.client:
        return request.client.host
    return "unknown"


def under_limit(visitor: str, kind: str, limit: int) -> bool:
    """
    Counts one more use for a visitor, if they're still under the hourly limit.

    Input:  visitor, from visitor_id()
            kind, what they're doing: "calls" or "checks"
            limit, how many they get per hour
    Output: True if they can go ahead (and we count it), False if they hit the limit

    Example:
        The 11th demo call in an hour, with a limit of 10, gives you False
    """
    now = time.time()
    key = f"{visitor}:{kind}"
    recent = []
    for moment in VISITS.get(key, []):
        if now - moment < ONE_HOUR_SECONDS:
            recent.append(moment)

    if len(recent) >= limit:
        VISITS[key] = recent
        return False
    recent.append(now)
    VISITS[key] = recent
    return True


def fake_phone(taken: set[str]) -> str:
    """
    Makes up a phone number that can never reach a real person (555-01XX).

    Input:  taken, numbers we already used in this demo call, so we don't repeat one
    Output: a fake number in E.164, like "+13055550142"

    Example:
        fake_phone(set()) gives you something like "+17865550173"
    """
    while True:
        number = f"+1{random.choice(FAKE_AREA_CODES)}55501{random.randint(0, 99):02d}"
        if number not in taken:
            taken.add(number)
            return number


def find_script(script_id: str) -> dict:
    """
    Finds one of our test calls by its ID.

    Example:
        find_script("scam_grandparent_en") gives you the fake grandson call
    Raises: ValueError if there's no call with that ID
    """
    for script in list_scripts():
        if script["id"] == script_id:
            return script
    raise ValueError("We don't have a demo call with that name.")


def demo_family(script: dict, family_language: str) -> tuple[dict, list[dict]]:
    """
    Makes up the pretend family for one demo call.

    Rosa is the grandma (she speaks the call's language), Ana is her daughter
    (she gets the alerts) and Danny is her grandson (he gets the "Is it really
    you?" text). Every phone number is fake.

    Input:  script, the test call we're about to play
            family_language, the language Ana reads, "en" or "es"
    Output: (Rosa's sign-up, the contact list with Danny in it)

    Example:
        demo_family(grandparent_script, "es") gives you a sign-up where Ana
        reads Spanish, plus Danny's contact
    """
    now = storage.now_text()
    taken: set[str] = set()
    enrollment = {
        "id": secrets.token_urlsafe(16),
        "senior_name": "Rosa",
        "senior_phone": fake_phone(taken),
        "family_name": "Ana",
        "family_phone": fake_phone(taken),
        "phone_type": "cell",
        "device_id": "demo-" + secrets.token_hex(4),
        "device_key": secrets.token_urlsafe(16),
        "senior_language": pick_language(script["language"]),
        "family_language": pick_language(family_language),
        # Rosa gets her own "demo" status instead of "active". That way she never
        # shows up as a real protected senior (calls.py and the family dashboard
        # only look at "active" ones), but call_monitor.py still protects her call.
        "status": "demo",
        "created_at": now,
        "answered_at": now,
    }
    contacts = [
        {
            "name": "Danny",
            # Other names he goes by, so we spot him whichever one the caller uses.
            "other_names": ["Daniel", "grandson", "nieto"],
            "phone": fake_phone(taken),
            "language": "en",
        }
    ]
    return enrollment, contacts


def forget_old_sessions() -> None:
    """
    Forgets demo calls that started more than two hours ago, along with
    everything we saved about them.

    Example:
        A demo call from this morning is gone by the afternoon
    """
    now = time.time()
    old_ids = []
    for call_id, session in SESSIONS.items():
        if now - session["started"] > FORGET_AFTER_SECONDS:
            old_ids.append(call_id)
    for call_id in old_ids:
        SESSIONS.pop(call_id, None)
        verify.CHECKS_BY_CALL_ID.pop(call_id, None)
        call_monitor.ALERTED_CALL_IDS.discard(call_id)
        call_monitor.RESEARCH_BY_CALL_ID.pop(call_id, None)


def new_texts(session: dict) -> dict:
    """
    Gets what showed up on Ana's and Danny's phones since the last time we looked.

    In demo mode nothing really goes out. Texts are saved in the demo outbox
    (alerts.DEMO_OUTBOX), and Ana's alert call in calls.DEMO_CALL_LOG, so we
    pick out the new ones for this call's phones. The alert call shows up
    on Ana's phone with the words she'd hear.

    Input:  session, one demo call from SESSIONS
    Output: {"family": [what Ana got], "contact": [texts for Danny]}

    Example:
        Right after the alert, you get {"family": ["📞 Scam Shield ALERT call:
        “Scam Shield alert. Rosa may be on a scam call right now...”"], "contact": []}
    """
    texts = {"family": [], "contact": []}
    family_phone = session["enrollment"]["family_phone"]

    call_log = calls.DEMO_CALL_LOG
    # Same as the outbox below: start over if the tests emptied it.
    if session["calls_seen"] > len(call_log):
        session["calls_seen"] = 0
    for placed in call_log[session["calls_seen"]:]:
        if placed["who"] == "alert" and placed["to"] == family_phone:
            language = calls.alert_call_language(session["enrollment"])
            texts["family"].append(message("alert_call_demo", language, words=placed["says"]))
    session["calls_seen"] = len(call_log)

    outbox = alerts.DEMO_OUTBOX
    # If the outbox got emptied (the tests do that), start counting from the top again.
    if session["outbox_seen"] > len(outbox):
        session["outbox_seen"] = 0

    fresh = outbox[session["outbox_seen"]:]
    session["outbox_seen"] = len(outbox)

    contact_phone = session["contacts"][0]["phone"]
    for text in fresh:
        if text["to"] == family_phone:
            texts["family"].append(text["body"])
        elif text["to"] == contact_phone:
            texts["contact"].append(text["body"])
    return texts


def start_demo_call(script_id: str, family_language: str) -> dict:
    """
    Starts a demo call: makes up the family and starts a protected call for Rosa.

    Input:  script_id, which test call to play, like "scam_grandparent_en"
            family_language, the language Ana reads
    Output: everything the page needs to play the call: its ID, the title,
            the caller's number, who's who, and all the lines
    Raises: ValueError if there's no test call with that ID

    Example:
        start_demo_call("scam_grandparent_en", "en") gives you
        {"call_id": "...", "title": "Grandparent scam...", "lines": [...], ...}
    """
    forget_old_sessions()
    script = find_script(script_id)
    enrollment, contacts = demo_family(script, family_language)
    storage.save_enrollment(enrollment)
    caller = script.get("caller_number") or "+13055550199"
    # Rosa is made up, so there's no phone of hers to ring.
    call = calls.start_protected_call(enrollment, caller=caller, call_sid="demo", ring_senior=False)

    SESSIONS[call["id"]] = {
        "script": script,
        "enrollment": enrollment,
        "contacts": contacts,
        "outbox_seen": len(alerts.DEMO_OUTBOX),
        "calls_seen": len(calls.DEMO_CALL_LOG),
        "warned": False,
        "started": time.time(),
    }
    return {
        "call_id": call["id"],
        "title": script["title"],
        "caller_number": caller,
        "senior": {"name": enrollment["senior_name"], "language": enrollment["senior_language"]},
        "family": {"name": enrollment["family_name"], "language": enrollment["family_language"]},
        "contact": {"name": contacts[0]["name"], "relation": "grandson"},
        "lines": script["lines"],
    }


def find_session(call_id: str) -> dict:
    """
    Finds a demo call that's running.

    Raises: ValueError if it's not running (it ended, or it's too old)

    Example:
        find_session("abc") gives you that call's session
    """
    session = SESSIONS.get(call_id)
    if session is None:
        raise ValueError("This demo call isn't running anymore. Press Start over to play it again.")
    return session


def check_demo_line(call_id: str, up_to_line: int) -> dict:
    """
    Runs every check on the call so far, just like during a real call.

    Input:  call_id, the demo call
            up_to_line, how many lines have been said so far
    Output: the detector's answer, which model ran it and how long it took,
            what Tavily found, whether the family was alerted, the "Is it
            really you?" check, Grandma's warning (if it's time), and new texts
    Raises: ValueError if the demo call isn't running

    Example:
        check_demo_line("abc", 3) after "I got arrested, I need bail money"
        gives you a score around 85, alert_sent True, and Ana's alert call
    """
    session = find_session(call_id)
    script = session["script"]
    enrollment = session["enrollment"]
    up_to_line = max(1, min(up_to_line, len(script["lines"])))

    started = time.perf_counter()
    outcome = call_monitor.check_live_call(call_id, transcript_text(script, up_to_line))
    seconds = time.perf_counter() - started

    check = verify.ask_if_needed(call_id, outcome["result"], enrollment["senior_name"], session["contacts"])

    # Grandma gets warned once, the first time the family alert goes out.
    warning = None
    if outcome["alert_sent"] and not session["warned"]:
        warning = senior_warnings.senior_warning("scam_likely", enrollment["senior_language"])
        session["warned"] = True

    return {
        "line": up_to_line,
        "result": outcome["result"],
        "model": get_settings().nemotron_model,
        "seconds": round(seconds, 2),
        "research": outcome["research"],
        "alert_sent_now": outcome["alert_sent_now"],
        "alert_sent": outcome["alert_sent"],
        "verify": verify.public_view(check),
        "senior_warning": warning,
        "texts": new_texts(session),
    }


def answer_demo_check(call_id: str, answer: str) -> dict:
    """
    Handles Danny tapping YES or NO on "Is that really you?"

    Input:  call_id, the demo call
            answer, "yes" or "no"
    Output: the updated check, Grandma's warning if Danny said NO, and new texts
    Raises: ValueError if the call isn't running, nobody was asked, or the
            answer isn't yes or no

    Example:
        answer_demo_check("abc", "no") gives you a warning for Rosa:
        "Danny says they are NOT calling you. Hang up now."
    """
    session = find_session(call_id)
    enrollment = session["enrollment"]
    check = verify.record_answer(
        call_id,
        answer,
        enrollment["senior_name"],
        enrollment["family_phone"],
        enrollment["family_language"],
    )

    warning = None
    if check["answer"] == "no":
        warning = senior_warnings.senior_warning(
            "not_them", enrollment["senior_language"], check["contact_name"]
        )
    return {
        "verify": verify.public_view(check),
        "senior_warning": warning,
        "texts": new_texts(session),
    }


@router.get("/demo")
def show_demo_page() -> FileResponse:
    """
    Sends the demo player page.

    Example:
        Open http://localhost:8000/demo and you see the demo player
    """
    return FileResponse(DEMO_PAGE)


@router.get("/api/demo/calls")
def list_demo_calls():
    """
    Lists the test calls you can play, without the lines (those come when you start one).

    Example:
        GET /api/demo/calls gives you
        [{"id": "scam_grandparent_en", "title": "...", "language": "en", "expected": "scam", "lines": 8}, ...]
    """
    if not demo_is_on():
        return error("The demo only works with DEMO_MODE=true.", 404)
    choices = []
    for script in list_scripts():
        choices.append(
            {
                "id": script["id"],
                "title": script["title"],
                "language": script["language"],
                "expected": script["expected"],
                "lines": len(script["lines"]),
            }
        )
    return choices


@router.post("/api/demo/calls/{script_id}/start")
def start_call(script_id: str, body: StartRequest, request: Request):
    """
    Starts a demo call. Counts against the visitor's hourly limit.

    Example:
        POST /api/demo/calls/scam_grandparent_en/start with {"family_language": "en"}
    """
    if not demo_is_on():
        return error("The demo only works with DEMO_MODE=true.", 404)
    if not under_limit(visitor_id(request), "calls", MAX_CALLS_PER_HOUR):
        return error("You've played a lot of demo calls this hour. Please try again in a little while.", 429)
    try:
        return start_demo_call(script_id, body.family_language)
    except ValueError as problem:
        return error(str(problem), 404)


@router.post("/api/demo/live/{call_id}/check")
def check_line(call_id: str, body: CheckRequest, request: Request):
    """
    Checks the call after a new line. Counts against the visitor's hourly limit.

    Example:
        POST /api/demo/live/abc/check with {"up_to_line": 3}
    """
    if not demo_is_on():
        return error("The demo only works with DEMO_MODE=true.", 404)
    if not under_limit(visitor_id(request), "checks", MAX_CHECKS_PER_HOUR):
        return error("You've checked a lot of calls this hour. Please try again in a little while.", 429)
    try:
        return check_demo_line(call_id, body.up_to_line)
    except ValueError as problem:
        return error(str(problem), 404)


@router.post("/api/demo/live/{call_id}/answer")
def answer_check(call_id: str, body: AnswerRequest):
    """
    Records Danny's YES or NO.

    Example:
        POST /api/demo/live/abc/answer with {"answer": "no"}
    """
    if not demo_is_on():
        return error("The demo only works with DEMO_MODE=true.", 404)
    try:
        return answer_demo_check(call_id, body.answer)
    except ValueError as problem:
        return error(str(problem), 409)
