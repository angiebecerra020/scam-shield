"""
profile.py

The family member's profile: their own name, phone, email and language,
typed once and used everywhere in Scam Shield.

How it fits in: every senior a family member signs up (consent.py) needs to
know who gets the alerts. Before profiles, the sign-up form asked for "Your
name", "Your phone" and the rest every single time. Now:
  1. the first sign-up saves those details as the family member's profile
  2. after that, the dashboard skips those boxes, and create_enrollment() in
     main.py fills them in from the profile (fill_in_family below)
  3. the /profile page lets them change their details. A change is copied
     onto every senior they protect, so the next alert goes to the new phone
     or email (storage.update_family_details)

Each profile belongs to one login (owner_id, like the seniors in family.py).
When login is turned off, there's one shared profile for everyone.

Family members who signed seniors up before profiles existed get one made
for them from their newest sign-up, so they never have to type it again.

Routes:
    GET /profile      -> the profile page (static/profile.html)
    GET /api/profile  -> [login] your saved details, or {"profile": null}
    PUT /api/profile  -> [login] save your details
"""

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app import consent, family, storage
from app.auth import require_login
from app.languages import pick_language

router = APIRouter()

# static/ sits next to app/ in the project folder.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def owner_of(user: dict | None) -> str | None:
    """
    The login a profile belongs to.

    Example:
        owner_of({"id": "user-ana"}) gives you "user-ana"
        owner_of(None) gives you None, since login is off
    """
    return user["id"] if user else None


def clean_profile(name: str, phone: str, email: str | None, language: str) -> dict:
    """
    Check a family member's details, the same way the sign-up form does.

    Input:  what they typed
    Output: {"name", "phone", "email", "language"}, tidied up
    Raises: consent.EnrollmentError if something is wrong, like a phone with
            no area code

    Example:
        clean_profile("Ana", "305-555-0101", "", "en") gives you
        {"name": "Ana", "phone": "+13055550101", "email": None, "language": "en"}
    """
    return {
        "name": consent.clean_name(name, "Your name"),
        "phone": consent.clean_phone(phone, "Your phone"),
        "email": consent.clean_email(email),
        "language": pick_language(language),
    }


def profile_from_old_signup(user: dict) -> dict | None:
    """
    Make a profile from someone's newest sign-up, for family members who
    signed seniors up before profiles existed.

    Input:  user, who's logged in
    Output: their details, or None if they haven't signed anyone up

    Example:
        Ana signed Rosa up last week  gives you
        {"name": "Ana", "phone": "+13055550101", "email": None, "language": "en"}
    """
    for enrollment in family.my_enrollments(user):
        if enrollment["family_name"] and enrollment["family_phone"]:
            return {
                "name": enrollment["family_name"],
                "phone": enrollment["family_phone"],
                "email": enrollment["family_email"],
                "language": enrollment["family_language"],
            }
    return None


def get_profile(user: dict | None) -> dict | None:
    """
    Find the logged in family member's details.

    Input:  user, who's logged in (None when login is off)
    Output: {"name", "phone", "email", "language"}, or None if we don't have them yet

    Example:
        get_profile({"id": "user-ana"}) gives you {"name": "Ana", "phone": "+13055550101", ...}
    """
    saved = storage.get_profile(owner_of(user))
    if saved is None and user is not None:
        # Only with a login: when login is off, every sign-up (even the demo's
        # made up family) is everyone's, so an old one isn't really yours.
        saved = profile_from_old_signup(user)
        if saved is not None:
            storage.save_profile(owner_of(user), saved)
    if saved is None:
        return None
    return {key: saved[key] for key in ("name", "phone", "email", "language")}


def save_profile(user: dict | None, name: str, phone: str, email: str | None, language: str) -> dict:
    """
    Save the family member's details, and use them for every senior they protect.

    Input:  user, who's logged in (None when login is off)
            name, phone, email, language, what they typed
    Output: the saved details
    Raises: consent.EnrollmentError if something is wrong

    Example:
        save_profile({"id": "user-ana"}, "Ana", "305-555-0199", "", "en")
        gives you {"name": "Ana", "phone": "+13055550199", ...}
        and Rosa's next alert rings 305-555-0199
    """
    profile = clean_profile(name, phone, email, language)
    storage.save_profile(owner_of(user), profile)
    if user is not None:
        # When login is off, nobody owns the sign-ups, so we leave them alone.
        storage.update_family_details(owner_of(user), profile)
    return profile


def fill_in_family(fields: dict, user: dict | None) -> dict:
    """
    Fill in the "who gets the alerts" part of a sign-up from the profile, when
    the form left it out.

    Input:  fields, the sign-up form
            user, who's logged in (None when login is off)
    Output: the form with family_name, family_phone, family_email and
            family_language filled in. If they typed their details, or
            there's no profile, the form comes back as it was.

    Example:
        fill_in_family({"senior_name": "Rosa", ..., "family_name": ""}, {"id": "user-ana"})
        gives you {"senior_name": "Rosa", ..., "family_name": "Ana", "family_phone": "+13055550101", ...}
    """
    if fields.get("family_name") or fields.get("family_phone"):
        return fields
    profile = get_profile(user)
    if profile is None:
        return fields
    return {
        **fields,
        "family_name": profile["name"],
        "family_phone": profile["phone"],
        "family_email": profile["email"],
        "family_language": profile["language"],
    }


def remember_from_signup(fields: dict, user: dict | None) -> None:
    """
    After someone's first sign-up, save the details they typed as their
    profile, so they don't type them again next time.

    Input:  fields, the sign-up form (it already passed consent.py's checks)
            user, who's logged in (None when login is off)
    Output: nothing

    Example:
        Ana signs Rosa up for the first time  gives you  a profile for Ana
    """
    if storage.get_profile(owner_of(user)) is not None:
        return
    storage.save_profile(
        owner_of(user),
        clean_profile(
            fields["family_name"],
            fields["family_phone"],
            fields.get("family_email"),
            fields.get("family_language", "en"),
        ),
    )


class ProfileForm(BaseModel):
    """
    What the family member fills in on the profile page.

    Example:
        {"name": "Ana", "phone": "305-555-0101", "email": "ana@example.com", "language": "en"}
    """

    name: str
    phone: str
    email: str | None = None
    language: str = "en"


@router.get("/profile")
def show_profile_page() -> FileResponse:
    """
    Send the profile page. Like the dashboard, the page sends people who
    aren't logged in to /login, and the API routes check the login again.

    Example:
        Open http://localhost:8000/profile -> you see "Your profile".
    """
    return FileResponse(STATIC_DIR / "profile.html")


@router.get("/api/profile")
def show_profile(user: dict | None = Depends(require_login)):
    """
    Your saved details, for the profile page and the dashboard's sign-up form.

    Example:
        GET /api/profile gives you {"profile": {"name": "Ana", "phone": "+13055550101", ...}}
        or {"profile": null} before they've saved anything
    """
    return {"profile": get_profile(user)}


@router.put("/api/profile")
def update_profile(form: ProfileForm, user: dict | None = Depends(require_login)):
    """
    The profile page's Save button.

    Example:
        PUT /api/profile {"name": "Ana", "phone": "305-555-0101"}
        gives you {"profile": {"name": "Ana", "phone": "+13055550101", ...}}
    """
    try:
        return {"profile": save_profile(user, **form.model_dump())}
    except consent.EnrollmentError as problem:
        return JSONResponse({"error": problem.text}, status_code=problem.status_code)
