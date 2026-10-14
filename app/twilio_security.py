"""
twilio_security.py — Checks that a webhook really came from Twilio.

How it fits in: Twilio tells us about texts and calls by sending requests to
our server (webhooks). Our server is on the public internet, so ANYONE could
send a fake "the senior replied YES" request. Twilio signs every real request
with our auth token; this file checks that signature before main.py trusts
the request.

In demo mode we skip the check, so the demo and the tests can pretend to be
Twilio. Demo mode never sends real texts or calls, so nothing real is at risk.
"""

from fastapi import Request
from twilio.request_validator import RequestValidator

from app.config import get_settings


def public_url_for(request: Request) -> str:
    """
    Rebuild the exact web address Twilio used to reach us.

    Twilio signs the PUBLIC address (for example our ngrok URL), but behind
    ngrok our server sees "http://localhost:8000/...". So we put the path on
    the end of PUBLIC_BASE_URL instead of trusting the address we see.

    Input:  request — the incoming web request
    Output: the full public URL, including any ?query part

    Example:
        PUBLIC_BASE_URL=https://abc.ngrok.app, request to /twilio/sms
        ->  "https://abc.ngrok.app/twilio/sms"
    """
    url = get_settings().public_base_url.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    return url


def is_from_twilio(request: Request, form: dict) -> bool:
    """
    Decide whether to trust a webhook request.

    Input:  request — the incoming web request
            form    — the form fields Twilio sent (From, Body, CallSid, ...)
    Output: True if it's safe to act on the request

    Examples:
        DEMO_MODE=true                               ->  True
        live mode, real Twilio signature             ->  True
        live mode, missing or wrong signature        ->  False
    """
    settings = get_settings()

    if settings.demo_mode:
        return True

    # Without an auth token we can't check anything, so we refuse.
    if not settings.twilio_auth_token:
        return False

    signature = request.headers.get("X-Twilio-Signature", "")
    validator = RequestValidator(settings.twilio_auth_token)
    return validator.validate(public_url_for(request), form, signature)
