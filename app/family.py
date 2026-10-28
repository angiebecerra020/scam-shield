"""
family.py

The family dashboard: the people you protect, their past calls, and the
pause button.

How it fits in: once a family member signs a senior up (consent.py), they
come back to the dashboard to see how it's going. This file answers the
dashboard's questions:
  1. who am I protecting, and are they protected right now?
  2. what calls did they get, and how risky was each one? (call_monitor.py
     saves the score, reasons and Tavily links as each call happens)
  3. pause protection, and turn it back on
  4. "Was this a scam?": the family tells us if we got a call right. We save
     the answer with the call, so we can see where the detector is wrong and
     make it smarter (see "Learning from the family's answers" in the README)
  5. the scam list: if a number calls again, warn us or block it (calls.py
     checks the list when each call comes in). Each family has their own list,
     so one family's report never blocks a number for anyone else.

Every answer only covers the seniors YOU signed up. We know who you are from
your login (auth.py), and each senior remembers whose login signed them up
(owner_id in storage.py). When login is turned off, the dashboard is open to
anyone, so it shows everyone.
"""

import json

from app import consent, storage

# How many past calls we show for each senior.
CALLS_TO_SHOW = 50

# The answers the family can give to "Was this a scam?"
FAMILY_ANSWERS = ("scam", "not_scam")

# What the family can pick for a number if it calls again. "none" takes it
# off their scam list.
SCAM_LIST_CHOICES = ("warn", "block", "none")


class FamilyError(Exception):
    """
    Something the dashboard asked for that we can't do, with a message the
    family member can read.

    status_code is the web status main.py sends back, like 404 when the call
    isn't theirs or 409 when protection is already paused.

    Example:
        raise FamilyError("We couldn't find that call.", 404)
    """

    def __init__(self, text: str, status_code: int):
        super().__init__(text)
        self.text = text
        self.status_code = status_code


def owns(enrollment: dict, user: dict | None) -> bool:
    """
    Checks if this senior belongs to the logged in family member.

    Input:  enrollment, the senior's sign-up from storage
            user, the logged in person from auth.require_login(), or None
            when login is off
    Output: True or False

    Examples:
        owns(rosa, {"id": "user-ana"}) gives you True if Ana signed Rosa up
        owns(rosa, None) gives you True, since login is off
    """
    if user is None:
        return True
    return enrollment.get("owner_id") == user["id"]


def my_enrollments(user: dict | None) -> list[dict]:
    """
    Gets every senior the logged in family member signed up, newest first.

    Input:  user, the same as owns()
    Output: a list of enrollments from storage

    Example:
        my_enrollments({"id": "user-ana"}) gives you [rosa]
    """
    if user is None:
        return storage.find_all_enrollments()
    return storage.find_enrollments_for_owner(user["id"])


def find_my_enrollment(enrollment_id: str, user: dict | None) -> dict:
    """
    Finds one senior, but only if they belong to the logged in family member.

    We give the same "couldn't find" answer when it belongs to someone else,
    so nobody can poke around to learn which IDs exist.

    Input:  enrollment_id, the senior's sign-up ID
            user, the same as owns()
    Output: the enrollment from storage
    Raises: FamilyError (404) if there's no such senior, or it isn't theirs

    Example:
        find_my_enrollment("abc", {"id": "user-ana"}) gives you Rosa's sign-up
    """
    enrollment = storage.get_enrollment(enrollment_id)
    if enrollment is None or not owns(enrollment, user):
        raise FamilyError("We couldn't find that sign-up.", 404)
    return enrollment


def read_list(saved: str | None) -> list:
    """
    Turns a list we saved as JSON text back into a list.

    Example:
        read_list('["Asks for gift cards"]') gives you ["Asks for gift cards"]
        read_list(None) gives you []
    """
    if not saved:
        return []
    return json.loads(saved)


def call_summary(call: dict) -> dict:
    """
    The short version of a call, for the call history list.

    Input:  call, a call from storage
    Output: {"id", "started_at", "caller_number", "risk_score", "verdict",
             "alerted", "status", "family_answer"}

    Example:
        call_summary(grandson_call) gives you {"id": "c1", "risk_score": 92,
        "verdict": "likely_scam", "alerted": True, ...}
    """
    return {
        "id": call["id"],
        "started_at": call["started_at"],
        # We show the whole caller number on purpose. It's who called Grandma,
        # and the family needs it to report or block a scammer.
        "caller_number": call["caller_number"],
        "risk_score": call["risk_score"],
        "verdict": call["verdict"],
        "alerted": call["alerted_at"] is not None,
        "status": call["status"],
        # "scam", "not_scam", or None if the family hasn't said
        "family_answer": call["family_answer"],
        # "warn" or "block" if the caller was on the family's scam list
        # when this call came in, or None
        "scam_list": call["scam_list"],
    }


def call_details(call: dict) -> dict:
    """
    Everything about one call, for when the family taps it.

    Input:  call, a call from storage
    Output: the call_summary() parts plus "reasons", "claimed_identity",
            "sources", "alerted_at" and "ended_at"

    Example:
        call_details(grandson_call) gives you the summary plus
        {"reasons": ["Asks for gift cards", ...], "sources": [{"title": "FTC...", "url": "..."}], ...}
    """
    details = call_summary(call)
    details["reasons"] = read_list(call["reasons"])
    details["claimed_identity"] = call["claimed_identity"]
    details["sources"] = read_list(call["sources"])
    details["alerted_at"] = call["alerted_at"]
    details["ended_at"] = call["ended_at"]
    return details


def family_overview(user: dict | None) -> dict:
    """
    Everything the dashboard shows when it opens: each senior you protect,
    whether they're protected right now, and their recent calls.

    Input:  user, the same as owns()
    Output: {"seniors": [one entry per senior, newest sign-up first]}. Each
            entry is what consent.public_view() shows, plus "senior_language",
            "family_language" and "calls" (a list of call_summary() results).

    Example:
        family_overview({"id": "user-ana"}) gives you
        {"seniors": [{"senior_name": "Rosa", "status": "active", "calls": [...]}]}
    """
    seniors = []
    for enrollment in consent.expire_old_requests(my_enrollments(user)):
        entry = consent.public_view(enrollment)
        entry["senior_language"] = enrollment["senior_language"]
        entry["family_language"] = enrollment["family_language"]
        entry["calls"] = []
        for call in storage.find_calls_for_enrollment(enrollment["id"], CALLS_TO_SHOW):
            entry["calls"].append(call_summary(call))
        seniors.append(entry)
    return {"seniors": seniors}


def get_call(call_id: str, user: dict | None) -> dict:
    """
    Gets one call's full details, if it was a call to a senior you protect.

    Input:  call_id, which call
            user, the same as owns()
    Output: call_details() for that call, plus "senior_name" and
            "number_on_list" (what the family's scam list says to do if this
            number calls again: "warn", "block", or None)
    Raises: FamilyError (404) if there's no such call, or it isn't theirs

    Example:
        get_call("c1", {"id": "user-ana"}) gives you Rosa's call with its reasons and links
    """
    call = storage.get_call(call_id)
    if call is None:
        raise FamilyError("We couldn't find that call.", 404)
    enrollment = storage.get_enrollment(call["enrollment_id"])
    if enrollment is None or not owns(enrollment, user):
        raise FamilyError("We couldn't find that call.", 404)

    details = call_details(call)
    details["senior_name"] = enrollment["senior_name"]
    details["number_on_list"] = None
    if call["caller_number"]:
        listed = storage.find_scam_number(enrollment["owner_id"], call["caller_number"])
        if listed is not None:
            details["number_on_list"] = listed["action"]
    return details


def pause_protection(enrollment_id: str, user: dict | None) -> dict:
    """
    Pauses Scam Shield for one senior. Their calls still ring them like
    normal, but we stop listening and stop sending alerts (calls.py and
    call_monitor.py only protect "active" seniors).

    Input:  enrollment_id, which senior
            user, the same as owns()
    Output: the senior, as consent.public_view() shows it, now "paused"
    Raises: FamilyError (404) if it isn't theirs, (409) if protection isn't on

    Example:
        pause_protection("abc", {"id": "user-ana"}) gives you {"status": "paused", ...}
    """
    enrollment = find_my_enrollment(enrollment_id, user)
    if enrollment["status"] != "active":
        raise FamilyError("Protection isn't on right now, so there's nothing to pause.", 409)
    storage.set_enrollment_status(enrollment_id, "paused", answered=False)
    enrollment["status"] = "paused"
    return consent.public_view(enrollment)


def resume_protection(enrollment_id: str, user: dict | None) -> dict:
    """
    Turns Scam Shield back on for a senior the family paused.

    This only works after a pause. The senior already said YES, so we don't
    need to ask again. Seniors who said NO or STOP can't be turned back on
    from here; the family has to ask them again from the sign-up form.

    Input:  enrollment_id, which senior
            user, the same as owns()
    Output: the senior, as consent.public_view() shows it, now "active"
    Raises: FamilyError (404) if it isn't theirs, (409) if it isn't paused

    Example:
        resume_protection("abc", {"id": "user-ana"}) gives you {"status": "active", ...}
    """
    enrollment = find_my_enrollment(enrollment_id, user)
    if enrollment["status"] != "paused":
        raise FamilyError("Protection isn't paused, so there's nothing to turn back on.", 409)
    storage.set_enrollment_status(enrollment_id, "active", answered=False)
    enrollment["status"] = "active"
    return consent.public_view(enrollment)


def answer_was_it_a_scam(call_id: str, answer: str, user: dict | None) -> dict:
    """
    Saves the family's answer to "Was this a scam?" for one of their calls.

    They can answer any call we checked, not just the ones we alerted about:
    a scam we missed teaches us as much as a false alarm. And they can change
    their answer later.

    Input:  call_id, which call
            answer, "scam" or "not_scam"
            user, the same as owns()
    Output: get_call() for that call, with the new answer in it
    Raises: FamilyError (400) for any other answer, (404) if it isn't their call

    Example:
        answer_was_it_a_scam("c1", "not_scam", {"id": "user-ana"}) gives you
        the call with {"family_answer": "not_scam", ...}
    """
    if answer not in FAMILY_ANSWERS:
        raise FamilyError('The answer has to be "scam" or "not_scam".', 400)
    # get_call() checks it's their call, so nobody can answer for someone else.
    get_call(call_id, user)
    storage.save_family_answer(call_id, answer)
    return get_call(call_id, user)


def set_scam_list(call_id: str, choice: str, user: dict | None) -> dict:
    """
    Decides what happens if the number from one of your calls calls again:
    "warn" (alert the family the moment it calls), "block" (it never rings),
    or "none" (take it off the list).

    The list belongs to the family who signed the senior up, and it covers
    every senior they protect.

    Input:  call_id, the call the number came from
            choice, "warn", "block" or "none"
            user, the same as owns()
    Output: get_call() for that call, with "number_on_list" updated
    Raises: FamilyError (400) for any other choice, or if we don't know the
            caller's number; (404) if it isn't their call

    Example:
        set_scam_list("c1", "block", {"id": "user-ana"}) gives you
        the call with {"number_on_list": "block", ...}, and next time
        that number calls Rosa, it gets a busy signal
    """
    if choice not in SCAM_LIST_CHOICES:
        raise FamilyError('The choice has to be "warn", "block" or "none".', 400)
    # get_call() checks it's their call, so nobody can change someone else's list.
    get_call(call_id, user)
    call = storage.get_call(call_id)
    if not call["caller_number"]:
        raise FamilyError("We don't know this caller's number, so we can't add it to your list.", 400)

    owner_id = storage.get_enrollment(call["enrollment_id"])["owner_id"]
    if choice == "none":
        storage.remove_scam_number(owner_id, call["caller_number"])
    else:
        storage.save_scam_number(owner_id, call["caller_number"], choice, call_id)
    return get_call(call_id, user)
