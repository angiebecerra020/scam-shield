"""
main.py — The Scam Shield web server (built with FastAPI).

How it fits in: this is the program you start with
    uvicorn app.main:app --reload
It sends the family dashboard (the files in static/) to the browser, and it
will hold all of our web routes: Twilio call webhooks, demo mode, and live
dashboard updates.

Routes:
    GET  /                        -> the landing page (what Scam Shield is)
    GET  /health                  -> a quick "is the server alive?" check

  Family logins (auth.py): routes marked [login] need a logged in family member
    GET  /login                   -> the log in and sign up page
    GET  /dashboard               -> the family dashboard
    GET  /api/auth-config         -> what the browser needs to talk to Supabase

  Consent (consent.py): the senior must say YES before we listen
    POST /api/enrollments         -> [login] family signs a senior up; we text
                                     the senior (cell) or call them (landline)
    GET  /api/enrollments/{id}    -> [login] has the senior said YES yet?
    POST /twilio/sms              -> Twilio: the senior texted us back
    POST /twilio/consent-call     -> Twilio: what to say on the landline consent call
    POST /twilio/consent-answer   -> Twilio: the key the senior pressed

  Family dashboard (family.py): each family only sees the seniors they signed up
    GET  /api/family              -> [login] the seniors you protect and their recent calls
    GET  /api/calls/{id}          -> [login] one past call: score, reasons and Tavily links
    POST /api/calls/{id}/answer   -> [login] the family's "Was this a scam?" answer
    POST /api/calls/{id}/scam-list -> [login] if this number calls again: warn, block, or none
    POST /api/enrollments/{id}/pause  -> [login] stop listening for now
    POST /api/enrollments/{id}/resume -> [login] turn protection back on

  The senior's device (devices.py): how we ring them without a loop
    GET  /phone/{key}             -> the calling app for a cell phone
    GET  /api/phone/{key}         -> the calling app's login
    POST /twilio/adapter-call     -> Twilio: a landline senior dialed a number

  3-way calls (calls.py): the family can join a risky call
    POST /twilio/voice            -> Twilio: a call reached our number
    POST /twilio/senior-status    -> Twilio: how ringing the senior went
    POST /twilio/conference-status -> Twilio: the call's conference room closed
    GET  /join/{token}            -> the "Join call" page from the family alert
    GET  /api/join/{token}        -> who the call is for, and is it still live?
    POST /api/join/{token}        -> ring the family member into the call

  Demo mode only
    POST /api/demo/scam-call      -> [login] pretend a scam call came in; send the alert
    GET  /api/demo/outbox         -> [login] the texts and calls we would have sent
"""

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from twilio.twiml.messaging_response import MessagingResponse

from app import calls, consent, devices, family
from app.alerts import DEMO_OUTBOX
from app.auth import login_is_on, require_login
from app.config import get_settings
from app.twilio_security import is_from_twilio
from app import demo_api, phone_line, site_pages

# static/ sits next to app/ in the project folder.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="Scam Shield",
    description="Catches scam phone calls while they happen and alerts the family.",
)

# Serve the CSS and JavaScript files at /static/... so index.html can load them.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# The demo player's page and its routes live in demo_api.py.
app.include_router(demo_api.router)

# The "Call it yourself" phone line and its page live in phone_line.py.
app.include_router(phone_line.router)

# Privacy, terms, the tab icon, robots.txt, the sitemap, the friendly 404
# page and the safety headers live in site_pages.py.
app.include_router(site_pages.router)
site_pages.add_site_extras(app)


@app.get("/")
def show_landing_page() -> FileResponse:
    """
    Send the landing page: what Scam Shield does, with buttons to sign up or log in.

    Input:  nothing (someone opens http://localhost:8000/ in a browser)
    Output: the static/landing.html page.

    Example:
        Open http://localhost:8000 -> you see "Stop scam calls while they happen".
    """
    return FileResponse(STATIC_DIR / "landing.html")


@app.get("/login")
def show_login_page() -> FileResponse:
    """
    Send the page where families log in or make an account.

    Example:
        Open http://localhost:8000/login -> you see the email and password form.
    """
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/dashboard")
def show_dashboard() -> FileResponse:
    """
    Send the family dashboard page. The page itself sends people who aren't
    logged in to /login (see static/auth.js), and the API routes it uses
    check the login again on the server, so nobody can skip it.

    Example:
        Open http://localhost:8000/dashboard -> you see the sign-up form.
    """
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/auth-config")
def show_auth_config() -> dict:
    """
    Tell the browser how to reach Supabase, so the login page can work.

    The publishable key is made to be public (Supabase's own rules decide what
    it can do), so it's safe to send. We never send secret keys here.

    Example:
        GET /api/auth-config
        -> {"login_on": true, "supabase_url": "https://abc.supabase.co", "supabase_publishable_key": "sb_publishable_..."}
    """
    settings = get_settings()
    return {
        "login_on": login_is_on(settings),
        "supabase_url": settings.supabase_url,
        "supabase_publishable_key": settings.supabase_publishable_key,
    }


@app.get("/health")
def health_check() -> dict:
    """
    Report that the server is running, and whether demo mode is on.

    We use this to check the server quickly, and later hosting services
    can call it to make sure the app is still up. It never shows secrets.

    Input:  nothing
    Output: a small dictionary, e.g. {"status": "ok", "demo_mode": True}

    Example:
        curl http://localhost:8000/health
        -> {"status":"ok","demo_mode":true}
    """
    settings = get_settings()
    return {"status": "ok", "demo_mode": settings.demo_mode}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def error(text: str, status_code: int) -> JSONResponse:
    """
    Send an error the dashboard can show to the person, e.g. {"error": "..."}.

    Example:
        error("That phone number doesn't look right.", 400)
    """
    return JSONResponse({"error": text}, status_code=status_code)


def twiml(xml: str) -> Response:
    """
    Send TwiML (Twilio's instructions) back to Twilio, labeled as XML.

    Example:
        twiml("<Response><Hangup/></Response>")
    """
    return Response(content=xml, media_type="application/xml")


async def read_twilio_form(request: Request) -> dict | None:
    """
    Read the form Twilio sent us, but only if it really came from Twilio.

    Input:  request — the incoming webhook request
    Output: the form fields as a dict, or None if the signature is wrong

    Example:
        form = await read_twilio_form(request)
        form["From"]  ->  "+13055550100"
    """
    form = dict(await request.form())
    if not is_from_twilio(request, form):
        return None
    return form


# ---------------------------------------------------------------------------
# Consent: the senior must say YES before we listen
# ---------------------------------------------------------------------------


class EnrollmentForm(BaseModel):
    """
    What the family member fills in on the sign-up form.

    Example:
        {"senior_name": "Rosa", "senior_phone": "305-555-0100",
         "family_name": "Ana", "family_phone": "305-555-0101",
         "senior_language": "es", "family_language": "en",
         "phone_type": "landline"}
    """

    senior_name: str
    senior_phone: str
    family_name: str
    family_phone: str
    senior_language: str = "en"
    family_language: str = "en"
    phone_type: str = "cell"


@app.post("/api/enrollments", status_code=201)
def create_enrollment(form: EnrollmentForm, user: dict | None = Depends(require_login)):
    """
    Sign a senior up and text them to ask for their YES.

    We save whose login signed them up, so only that family sees them on the
    dashboard (family.py).

    Input:  the sign-up form (JSON), and the logged in user (None when login is off)
    Output: the new enrollment with status "pending", or {"error": "..."}

    Example:
        POST /api/enrollments {"senior_name": "Rosa", ...}
        -> 201 {"id": "abc", "status": "pending", ...}
    """
    try:
        owner_id = user["id"] if user else None
        return consent.start_enrollment(**form.model_dump(), owner_id=owner_id)
    except consent.EnrollmentError as problem:
        return error(problem.text, problem.status_code)


@app.get("/api/enrollments/{enrollment_id}")
def show_enrollment(enrollment_id: str, user: dict | None = Depends(require_login)):
    """
    Show whether the senior has answered yet. The dashboard asks every few seconds.
    Only the family who signed them up can see it.

    Example:
        GET /api/enrollments/abc  ->  {"id": "abc", "status": "active", ...}
    """
    try:
        family.find_my_enrollment(enrollment_id, user)
    except family.FamilyError as problem:
        return error(problem.text, problem.status_code)
    return consent.get_enrollment_status(enrollment_id)


@app.get("/api/family")
def show_family(user: dict | None = Depends(require_login)):
    """
    Show the seniors this family protects, and each one's recent calls.

    Example:
        GET /api/family gives you
        {"seniors": [{"senior_name": "Rosa", "status": "active", "calls": [...]}]}
    """
    return family.family_overview(user)


@app.get("/api/calls/{call_id}")
def show_call(call_id: str, user: dict | None = Depends(require_login)):
    """
    Show one past call: its score, the reasons, and the Tavily links.

    Example:
        GET /api/calls/c1 gives you {"risk_score": 92, "reasons": [...], "sources": [...]}
    """
    try:
        return family.get_call(call_id, user)
    except family.FamilyError as problem:
        return error(problem.text, problem.status_code)


class ScamAnswer(BaseModel):
    """
    The family's answer to "Was this a scam?"

    Example:
        {"answer": "scam"} or {"answer": "not_scam"}
    """

    answer: str


@app.post("/api/calls/{call_id}/answer")
def answer_was_it_a_scam(call_id: str, body: ScamAnswer, user: dict | None = Depends(require_login)):
    """
    Save the family's answer to "Was this a scam?" for one of their calls.

    Example:
        POST /api/calls/c1/answer {"answer": "not_scam"}
        gives you the call with {"family_answer": "not_scam", ...}
    """
    try:
        return family.answer_was_it_a_scam(call_id, body.answer, user)
    except family.FamilyError as problem:
        return error(problem.text, problem.status_code)


class ScamListChoice(BaseModel):
    """
    What to do if a number calls again.

    Example:
        {"choice": "block"}  (or "warn", or "none" to take it off the list)
    """

    choice: str


@app.post("/api/calls/{call_id}/scam-list")
def set_scam_list(call_id: str, body: ScamListChoice, user: dict | None = Depends(require_login)):
    """
    Put the number from one of your calls on your scam list (or take it off).

    Example:
        POST /api/calls/c1/scam-list {"choice": "block"}
        gives you the call with {"number_on_list": "block", ...}
    """
    try:
        return family.set_scam_list(call_id, body.choice, user)
    except family.FamilyError as problem:
        return error(problem.text, problem.status_code)


@app.post("/api/enrollments/{enrollment_id}/pause")
def pause_protection(enrollment_id: str, user: dict | None = Depends(require_login)):
    """
    Pause Scam Shield for one senior. Their calls ring like normal, unwatched.

    Example:
        POST /api/enrollments/abc/pause gives you {"status": "paused", ...}
    """
    try:
        return family.pause_protection(enrollment_id, user)
    except family.FamilyError as problem:
        return error(problem.text, problem.status_code)


@app.post("/api/enrollments/{enrollment_id}/resume")
def resume_protection(enrollment_id: str, user: dict | None = Depends(require_login)):
    """
    Turn Scam Shield back on for a senior the family paused.

    Example:
        POST /api/enrollments/abc/resume gives you {"status": "active", ...}
    """
    try:
        return family.resume_protection(enrollment_id, user)
    except family.FamilyError as problem:
        return error(problem.text, problem.status_code)


@app.post("/twilio/sms")
async def receive_text(request: Request):
    """
    Twilio sends us every text our number receives. Seniors answer YES/NO here.

    Input:  Twilio's form (From = who texted, Body = what they wrote)
    Output: TwiML with our reply text, or an empty reply

    Example (demo mode, pretending to be the senior):
        curl -X POST localhost:8000/twilio/sms -d From=+13055550100 -d Body=YES
    """
    form = await read_twilio_form(request)
    if form is None:
        return error("This request didn't come from Twilio.", 403)

    reply = consent.handle_senior_reply(form.get("From", ""), form.get("Body", ""))
    response = MessagingResponse()
    if reply:
        response.message(reply)
    return twiml(str(response))


@app.post("/twilio/consent-call")
async def speak_consent_question(request: Request, enrollment_id: str, attempt: int = 1):
    """
    Twilio asks what to say when a landline senior picks up our consent call.

    Example:
        POST /twilio/consent-call?enrollment_id=abc
        ->  <Response><Gather ...><Say>Hello Rosa... press 1...</Say></Gather>...
    """
    form = await read_twilio_form(request)
    if form is None:
        return error("This request didn't come from Twilio.", 403)

    return twiml(consent.consent_call_twiml(enrollment_id, attempt))


@app.post("/twilio/consent-answer")
async def receive_consent_key(request: Request, enrollment_id: str):
    """
    Twilio tells us which key the landline senior pressed on the consent call.

    Example (demo mode, pretending to be Twilio):
        curl -X POST "localhost:8000/twilio/consent-answer?enrollment_id=abc" \\
             -d To=+13055550100 -d Digits=1
    """
    form = await read_twilio_form(request)
    if form is None:
        return error("This request didn't come from Twilio.", 403)

    xml = consent.handle_consent_digits(
        enrollment_id, form.get("To", ""), form.get("Digits", "")
    )
    return twiml(xml)


# ---------------------------------------------------------------------------
# The senior's device: calling app (cell) and adapter (landline)
# ---------------------------------------------------------------------------


@app.get("/phone/{device_key}")
def show_calling_app(device_key: str) -> FileResponse:
    """
    The calling app a cell-phone senior keeps open. Its JavaScript (phone.js)
    reads the key from the address and logs in to Twilio.

    Example:
        Open http://localhost:8000/phone/Xy7...  ->  "Scam Shield is ready for calls"
    """
    return FileResponse(STATIC_DIR / "phone.html")


@app.get("/api/phone/{device_key}")
def get_calling_app_login(device_key: str):
    """
    Give the calling app its Twilio login, so incoming calls can ring it.

    Example:
        GET /api/phone/Xy7...  ->  {"senior_name": "Rosa", "demo_mode": false, "token": "eyJ..."}
    """
    try:
        return devices.app_details(device_key)
    except devices.DeviceError as problem:
        return error(problem.text, problem.status_code)


@app.post("/twilio/adapter-call")
async def receive_adapter_call(request: Request):
    """
    Twilio asks where to send a call a landline senior dialed on their own
    phone (which is plugged into the adapter).

    Example:
        POST /twilio/adapter-call From=sip:senior-1a2b@... To=sip:3055550123@...
        ->  <Response><Dial callerId="..."><Number>+13055550123</Number></Dial></Response>
    """
    form = await read_twilio_form(request)
    if form is None:
        return error("This request didn't come from Twilio.", 403)

    return twiml(devices.handle_adapter_call(form.get("From", ""), form.get("To", "")))


# ---------------------------------------------------------------------------
# 3-way calls: the family can join a risky call
# ---------------------------------------------------------------------------


@app.post("/twilio/voice")
async def receive_call(request: Request):
    """
    Twilio asks us what to do when a call reaches our number.

    Input:  Twilio's form (From, CallSid, CallToken, and ForwardedFrom when
            the carrier sends it)
    Output: TwiML telling Twilio how to connect the call (see calls.py)

    Example:
        POST /twilio/voice From=+15555550199 CallSid=CA123 ForwardedFrom=+13055550100
        ->  <Response><Dial><Conference ...>scam-shield-...</Conference></Dial></Response>
    """
    form = await read_twilio_form(request)
    if form is None:
        return error("This request didn't come from Twilio.", 403)

    xml = calls.handle_incoming_call(
        caller=form.get("From", ""),
        call_sid=form.get("CallSid", ""),
        forwarded_from=form.get("ForwardedFrom"),
        # Lets the senior's phone show the real caller's number (see calls.py).
        # Twilio only sends it because our voice webhook uses POST.
        call_token=form.get("CallToken"),
    )
    return twiml(xml)


@app.post("/twilio/senior-status")
async def receive_senior_status(request: Request, call_id: str):
    """
    Twilio tells us how ringing the senior went (answered, busy, no answer...).

    Example:
        POST /twilio/senior-status?call_id=abc  CallStatus=no-answer
    """
    form = await read_twilio_form(request)
    if form is None:
        return error("This request didn't come from Twilio.", 403)

    calls.handle_senior_status(call_id, form.get("CallStatus", ""))
    return Response(status_code=204)


@app.post("/twilio/conference-status")
async def receive_conference_status(request: Request):
    """
    Twilio tells us a call's conference room closed, so the call is over.

    Example:
        POST /twilio/conference-status FriendlyName=scam-shield-abc
             StatusCallbackEvent=conference-end
    """
    form = await read_twilio_form(request)
    if form is None:
        return error("This request didn't come from Twilio.", 403)

    calls.handle_conference_status(
        form.get("FriendlyName", ""), form.get("StatusCallbackEvent", "")
    )
    return Response(status_code=204)


@app.get("/join/{join_token}")
def show_join_page(join_token: str) -> FileResponse:
    """
    The page the family's "Join call" link opens. Its JavaScript (join.js)
    reads the token from the address and does the rest.

    Example:
        Open http://localhost:8000/join/Xy7...  ->  "Join Rosa's call" button
    """
    return FileResponse(STATIC_DIR / "join.html")


@app.get("/api/join/{join_token}")
def show_call_to_join(join_token: str):
    """
    Tell the "Join call" page whose call it is and whether it's still going.

    Example:
        GET /api/join/Xy7...  ->  {"senior_name": "Rosa", "status": "live"}
    """
    try:
        return calls.describe_call(join_token)
    except calls.JoinError as problem:
        return error(problem.text, problem.status_code)


@app.post("/api/join/{join_token}")
def join_call(join_token: str):
    """
    Ring the family member's phone and add them to the call.

    Example:
        POST /api/join/Xy7...  ->  {"status": "calling", "senior_name": "Rosa"}
    """
    try:
        return calls.join_call(join_token)
    except calls.JoinError as problem:
        return error(problem.text, problem.status_code)


# ---------------------------------------------------------------------------
# Demo mode only
# ---------------------------------------------------------------------------


@app.post("/api/demo/scam-call", dependencies=[Depends(require_login)])
def start_demo_scam_call():
    """
    Pretend a scam call came in for the senior who said YES, and send the
    family alert with its "Join call" link. Turned off outside demo mode.

    Example:
        POST /api/demo/scam-call  ->  {"call_id": "abc", "join_link": "http://.../join/Xy7..."}
    """
    if not get_settings().demo_mode:
        return error("Demo calls only work with DEMO_MODE=true.", 404)
    try:
        return calls.start_demo_call()
    except calls.JoinError as problem:
        return error(problem.text, problem.status_code)


@app.get("/api/demo/outbox", dependencies=[Depends(require_login)])
def show_demo_outbox():
    """
    Show the texts and calls we would have sent, newest first. Demo mode only,
    because it shows whole phone numbers and message text.

    Example:
        GET /api/demo/outbox  ->  {"texts": [{"to": "...", "body": "..."}], "calls": [...]}
    """
    if not get_settings().demo_mode:
        return error("The outbox only exists with DEMO_MODE=true.", 404)
    return {
        "texts": list(reversed(DEMO_OUTBOX)),
        "calls": list(reversed(calls.DEMO_CALL_LOG)),
    }
