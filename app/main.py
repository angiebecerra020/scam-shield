"""
main.py — The Scam Shield web server (built with FastAPI).

How it fits in: this is the program you start with
    uvicorn app.main:app --reload
It sends the family dashboard (the files in static/) to the browser, and it
will hold all of our web routes: Twilio call webhooks, demo mode, and live
dashboard updates.

Routes:
    GET  /                        -> the dashboard page (sign-up form for now)
    GET  /health                  -> a quick "is the server alive?" check

  Consent (consent.py): the senior must say YES before we listen
    POST /api/enrollments         -> family signs a senior up; we text the
                                     senior (cell) or call them (landline)
    GET  /api/enrollments/{id}    -> has the senior said YES yet?
    POST /twilio/sms              -> Twilio: the senior texted us back
    POST /twilio/consent-call     -> Twilio: what to say on the landline consent call
    POST /twilio/consent-answer   -> Twilio: the key the senior pressed

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
    POST /api/demo/scam-call      -> pretend a scam call came in; send the alert
    GET  /api/demo/outbox         -> the texts and calls we would have sent
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from twilio.twiml.messaging_response import MessagingResponse

from app import calls, consent, devices
from app.alerts import DEMO_OUTBOX
from app.config import get_settings
from app.twilio_security import is_from_twilio

# static/ sits next to app/ in the project folder.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="Scam Shield",
    description="Catches scam phone calls while they happen and alerts the family.",
)

# Serve the CSS and JavaScript files at /static/... so index.html can load them.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def show_dashboard() -> FileResponse:
    """
    Send the family dashboard page to the browser.

    Input:  nothing (someone opens http://localhost:8000/ in a browser)
    Output: the static/index.html page.

    Example:
        Open http://localhost:8000 -> you see the Scam Shield page.
    """
    return FileResponse(STATIC_DIR / "index.html")


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
def create_enrollment(form: EnrollmentForm):
    """
    Sign a senior up and text them to ask for their YES.

    Input:  the sign-up form (JSON)
    Output: the new enrollment with status "pending", or {"error": "..."}

    Example:
        POST /api/enrollments {"senior_name": "Rosa", ...}
        -> 201 {"id": "abc", "status": "pending", ...}
    """
    try:
        return consent.start_enrollment(**form.model_dump())
    except consent.EnrollmentError as problem:
        return error(problem.text, problem.status_code)


@app.get("/api/enrollments/{enrollment_id}")
def show_enrollment(enrollment_id: str):
    """
    Show whether the senior has answered yet. The dashboard asks every few seconds.

    Example:
        GET /api/enrollments/abc  ->  {"id": "abc", "status": "active", ...}
    """
    enrollment = consent.get_enrollment_status(enrollment_id)
    if enrollment is None:
        return error("We couldn't find that sign-up.", 404)
    return enrollment


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


@app.post("/api/demo/scam-call")
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


@app.get("/api/demo/outbox")
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
