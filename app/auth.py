"""
auth.py — Checks that the person using the family dashboard is logged in.

How it fits in: families sign up and log in on the /login page. Supabase (a
free hosted service) keeps their email and password, so accounts are never
lost, even when our own database gets wiped (on Vercel that happens often).

When someone logs in, Supabase gives their browser an "access token", a long
random string that proves who they are. The dashboard sends it with every
request in a header:

    Authorization: Bearer <the token>

Before main.py runs a family route (like signing a senior up), it calls
require_login() below. That asks Supabase "whose token is this?" If Supabase
doesn't know the token, we answer 401 and the dashboard sends the person back
to the login page.

Twilio routes and the senior's calling app don't use this. Twilio proves
itself with a signature (twilio_security.py), and the "Join call" and calling
app links have their own secret part in the URL.

If SUPABASE_URL or SUPABASE_PUBLISHABLE_KEY is blank, login is turned off and
every route stays open. That keeps local testing simple.
"""

import time

import httpx
from fastapi import HTTPException, Request

from app.config import Settings, get_settings

# Once Supabase says a token is good, we trust it for this many seconds. The
# dashboard asks the server something every 3 seconds, and this saves us
# from asking Supabase every single time.
TRUST_TOKEN_SECONDS = 60

# token: (the user, the time we stop trusting it). Only kept while the server
# runs, which is fine: if it's forgotten, we just ask Supabase again.
CHECKED_TOKENS: dict[str, tuple[dict, float]] = {}


def login_is_on(settings: Settings) -> bool:
    """
    Say whether logins are set up.

    Input:  settings from get_settings()
    Output: True when both Supabase settings are filled in, otherwise False.

    Example:
        With SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY in .env:
        login_is_on(get_settings())  gives you  True
    """
    return settings.supabase_url != "" and settings.supabase_publishable_key != ""


def ask_supabase_who(token: str, settings: Settings) -> dict | None:
    """
    Ask Supabase which user an access token belongs to.

    Input:  token    — the access token the browser sent
            settings — where to find Supabase and our publishable key
    Output: the user (a dictionary with "id", "email" and more), or None if
            Supabase says the token is fake or expired, or can't be reached.

    Example:
        ask_supabase_who("eyJhbGci...", settings)  gives you  {"id": "4f1...", "email": "ana@example.com", ...}
    """
    try:
        response = httpx.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                # Supabase wants our project's key AND the person's token.
                "apikey": settings.supabase_publishable_key,
                "Authorization": f"Bearer {token}",
            },
            timeout=5,
        )
    except httpx.HTTPError:
        # If Supabase is down we can't prove who they are, so we say no.
        # Letting people in when we can't check would defeat the point.
        return None
    if response.status_code != 200:
        return None
    return response.json()


def find_user(token: str, settings: Settings) -> dict | None:
    """
    Find who a token belongs to, using our short memory before asking Supabase.

    Input:  token and settings, the same as ask_supabase_who()
    Output: the user dictionary, or None if the token isn't good.

    Example:
        find_user("eyJhbGci...", settings)  gives you  {"id": "4f1...", "email": "ana@example.com", ...}
    """
    remembered = CHECKED_TOKENS.get(token)
    if remembered is not None:
        user, trust_until = remembered
        if time.time() < trust_until:
            return user

    user = ask_supabase_who(token, settings)
    if user is None:
        CHECKED_TOKENS.pop(token, None)
        return None
    CHECKED_TOKENS[token] = (user, time.time() + TRUST_TOKEN_SECONDS)
    return user


def read_token(request: Request) -> str:
    """
    Pull the access token out of the request's Authorization header.

    Input:  request — the request from the browser
    Output: the token, or "" if there isn't one.

    Example:
        Header "Authorization: Bearer eyJhbGci..."  gives you  "eyJhbGci..."
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return ""
    return header.removeprefix("Bearer ").strip()


def require_login(request: Request) -> dict | None:
    """
    Stop the request unless the person is logged in. main.py adds this to the
    family routes with Depends(require_login).

    Input:  request — the request from the browser
    Output: the logged in user, or None when login is turned off.
            If they aren't logged in, it stops the request with a 401 error.

    Example:
        A request with no token, while login is on, gives you
        401 {"detail": "Please log in first."}
    """
    settings = get_settings()
    if not login_is_on(settings):
        return None

    token = read_token(request)
    if token == "":
        raise HTTPException(status_code=401, detail="Please log in first.")

    user = find_user(token, settings)
    if user is None:
        raise HTTPException(
            status_code=401, detail="Your login ran out. Please log in again."
        )
    return user
