"""
call_again.py

Two buttons on each person in "Your family" on the dashboard:
  - "Call again": if the senior missed our "press 1 to say YES" call,
    Scam Shield rings them again.
  - "Remove": deletes the person and their call history, so the family
    can start over.

How it fits in: it adds one route next to Cass's sign-up routes in main.py.
It uses her own checks (family.find_my_enrollment makes sure it's your
senior) and her own call (consent.call_senior_for_consent), so the consent
logic stays hers. We only add limits so nobody gets called over and over.
"""

import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import consent, family, storage
from app.auth import require_login

router = APIRouter()

# At most this many extra calls per sign-up, at least a minute apart.
MAX_CALLS_AGAIN = 3
WAIT_BETWEEN_SECONDS = 60

# When we called each sign-up again, by enrollment ID.
CALLED_AGAIN: dict[str, list[float]] = {}


def error(text: str, status_code: int) -> JSONResponse:
    """
    Sends back an error the dashboard can show.

    Example:
        error("Please wait a minute.", 429) gives you a 429 with {"error": "Please wait a minute."}
    """
    return JSONResponse({"error": text}, status_code=status_code)


def call_again(enrollment_id: str, user: dict | None) -> dict:
    """
    Rings the senior again with the consent call, if it's still waiting on them.

    Input:  enrollment_id, which senior
            user, who's logged in (None when login is off)
    Output: the sign-up, as consent.public_view() shows it
    Raises: family.FamilyError if it isn't yours, isn't waiting, wasn't a call,
            or we already called again too many times or too recently

    Example:
        call_again("abc", {"id": "user-ana"}) and Grandma's phone rings again
    """
    enrollment = family.find_my_enrollment(enrollment_id, user)
    if enrollment["status"] != "pending":
        raise family.FamilyError("They already answered, so there's no need to call again.", 409)
    if consent.how_we_asked(enrollment) != "call":
        raise family.FamilyError("We asked this person by text, so there's no call to repeat.", 409)

    now = time.time()
    earlier = CALLED_AGAIN.get(enrollment_id, [])
    if len(earlier) >= MAX_CALLS_AGAIN:
        raise family.FamilyError("We've called them a few times already. Try reaching them yourself first.", 429)
    if earlier and now - earlier[-1] < WAIT_BETWEEN_SECONDS:
        raise family.FamilyError("We just called. Please wait a minute before calling again.", 429)

    consent.call_senior_for_consent(enrollment)
    CALLED_AGAIN[enrollment_id] = earlier + [now]
    return consent.public_view(enrollment)


def remove_senior(enrollment_id: str, user: dict | None) -> dict:
    """
    Deletes one senior for good: their sign-up and every call we saved for
    them. After this, the family can sign them up again from scratch.

    Input:  enrollment_id, which senior
            user, who's logged in (None when login is off)
    Output: {"removed": the senior's name}
    Raises: family.FamilyError (404) if it isn't yours

    Example:
        remove_senior("abc", {"id": "user-ana"}) gives you {"removed": "Rosa"}
    """
    enrollment = family.find_my_enrollment(enrollment_id, user)
    with storage.connect() as db:
        db.execute("DELETE FROM calls WHERE enrollment_id = ?", (enrollment_id,))
        db.execute("DELETE FROM enrollments WHERE id = ?", (enrollment_id,))
    CALLED_AGAIN.pop(enrollment_id, None)
    return {"removed": enrollment["senior_name"]}


@router.delete("/api/enrollments/{enrollment_id}")
def remove_senior_route(enrollment_id: str, user: dict | None = Depends(require_login)):
    """
    The dashboard's red Remove button.

    Example:
        DELETE /api/enrollments/abc gives you {"removed": "Rosa"}
    """
    try:
        return remove_senior(enrollment_id, user)
    except family.FamilyError as problem:
        return error(problem.text, problem.status_code)


@router.post("/api/enrollments/{enrollment_id}/call-again")
def call_again_route(enrollment_id: str, user: dict | None = Depends(require_login)):
    """
    The dashboard's "Call them again" button.

    Example:
        POST /api/enrollments/abc/call-again gives you {"status": "pending", ...}
    """
    try:
        return call_again(enrollment_id, user)
    except family.FamilyError as problem:
        return error(problem.text, problem.status_code)
