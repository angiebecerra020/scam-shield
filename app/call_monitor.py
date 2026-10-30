"""
call_monitor.py

This connects our brain to the family alert.

How it fits in: while a protected call is happening, the live transcript (or
the demo player) sends the call so far here, over and over as new lines come
in. Each time, we:
  1. ask Nemotron how risky the call is (detector.py)
  2. the first time it looks suspicious, ask Tavily about the caller (research.py)
  3. the first time the score hits 70 or more, phone the family: the alert
     call says WHY we're worried and lets them press 1 to join the call
     (calls.send_family_alert). If they gave an email, that gets the alert
     with a "Join call" link too.
  4. save the score, the reasons and the Tavily links with the call, so the
     family can look back at it later on the dashboard (family.py)

We only alert the family once per call, so their phone doesn't ring ten times. And we
only alert for seniors who said YES to Scam Shield (that's the consent check
in consent.py).

Heads up: we remember which calls already got an alert in memory. If the
server restarts in the middle of a call it could alert one more time, and
that's fine for now.
"""

from app import calls, detector, email_alerts, research, storage

# The sign-ups we protect. "active" means the senior said YES to Scam Shield.
# "demo" is the pretend Rosa from the demo player (demo_api.py).
PROTECTED_STATUSES = ("active", "demo")

# Calls that already got a family alert, so we never send it twice.
ALERTED_CALL_IDS: set[str] = set()

# The Tavily results for each call, so we only search once per call.
RESEARCH_BY_CALL_ID: dict[str, dict] = {}


def research_once(call: dict, detector_result: dict) -> dict | None:
    """
    Asks Tavily about the caller, but only once per call, and only once the
    call looks suspicious. Searching every safe call would waste our credits.

    Input:  call, the call from storage
            detector_result, what detector.score_call() gave back
    Output: what research.research_call() found, or None if we haven't searched

    Example:
        The first suspicious check of a call runs the search. Every check
        after that gives you the same saved result without searching again.
    """
    if call["id"] in RESEARCH_BY_CALL_ID:
        return RESEARCH_BY_CALL_ID[call["id"]]
    if detector_result.get("verdict") not in ("suspicious", "likely_scam"):
        return None

    found = research.research_call(call["caller_number"] or "", detector_result)
    RESEARCH_BY_CALL_ID[call["id"]] = found
    return found


def should_alert(call: dict, enrollment: dict | None, detector_result: dict) -> bool:
    """
    Decides if this check should send the family alert.

    We alert only when ALL of these are true:
      - the senior said YES to Scam Shield (or it's the demo player's pretend Rosa)
      - the call is still going
      - we haven't already alerted the family about this call (not even
        when the call started, for a number on their scam list in calls.py)
      - the score is 70 or more

    Input:  call, the call from storage
            enrollment, the senior's sign-up from storage
            detector_result, what detector.score_call() gave back
    Output: True or False

    Example:
        A live call that just scored 92, for a senior who said YES, gives you True
    """
    score = detector_result.get("risk_score")
    if enrollment is None or enrollment["status"] not in PROTECTED_STATUSES:
        return False
    if call["status"] != "live":
        return False
    if call["id"] in ALERTED_CALL_IDS or call["alerted_at"] is not None:
        return False
    if score is None:
        return False
    return score >= detector.ALERT_FROM


def send_alerts(call: dict, enrollment: dict, detector_result: dict) -> None:
    """
    Phones the family with the alert (press 1 to join the call), and emails
    it too if they gave us an address.

    Input:  call, enrollment, detector_result (same as should_alert)
    Output: nothing. In demo mode the call goes into calls.DEMO_CALL_LOG instead.

    Example:
        Ana's phone rings: "Scam Shield alert. Rosa may be on a scam call right
        now. Why we're worried: The caller says they are grandson Danny...
        To join the call, press 1."
    """
    calls.send_family_alert(call)
    # Email too, if the family gave us an address, with a "Join call" link.
    if enrollment.get("family_email"):
        subject, body = email_alerts.alert_email(
            enrollment["family_language"],
            enrollment["senior_name"],
            enrollment["family_name"],
            detector_result,
            calls.join_link(call),
            real_call=True,
        )
        email_alerts.send_email(enrollment["family_email"], subject, body)
    alert_other_families(call, enrollment, detector_result)
    ALERTED_CALL_IDS.add(call["id"])
    storage.mark_call_alerted(call["id"])


def alert_other_families(call: dict, enrollment: dict, detector_result: dict) -> None:
    """
    Emails every OTHER family that protects the same senior (each one got the
    senior's own YES), with the same "Join call" link. The call itself shows
    up on the dashboard of the family it belongs to.

    Input:  call, the enrollment the call belongs to, detector_result
    Output: nothing

    Example:
        Ana and her brother Luis both protect Rosa. A scam call comes in on
        Ana's sign up: Ana gets the phone alert and email, and Luis gets the email.
    """
    for other in storage.find_enrollments_for_senior(enrollment["senior_phone"]):
        if other["id"] == enrollment["id"] or other["status"] != "active" or not other.get("family_email"):
            continue
        subject, body = email_alerts.alert_email(
            other["family_language"],
            other["senior_name"],
            other["family_name"],
            detector_result,
            calls.join_link(call),
            real_call=True,
        )
        email_alerts.send_email(other["family_email"], subject, body)


def all_sources(found: dict | None) -> list[dict]:
    """
    Puts the Tavily links from both searches (the caller's number and the scam
    news) into one list, with just what the dashboard shows: the title and link.

    Input:  found, what research.research_call() gave back, or None
    Output: a list like [{"title": "FTC: grandparent scams", "url": "https://..."}]

    Example:
        all_sources(None) gives you []
    """
    if not found:
        return []
    sources = []
    for search in ("caller", "news"):
        for source in (found.get(search) or {}).get("sources", []):
            sources.append({"title": source.get("title", ""), "url": source.get("url", "")})
    return sources


def check_live_call(call_id: str, transcript: str) -> dict:
    """
    Checks a call that's happening right now, and alerts the family if needed.
    Call this every time the transcript gets a new line.

    Input:  call_id, our ID for the call (from calls.start_protected_call)
            transcript, the whole call so far, one line per turn
    Output: {"call_id", "result": <detector result>, "research": <Tavily result or None>,
             "alert_sent_now": True if we just alerted the family,
             "alert_sent": True if the family has been alerted about this call}
    Raises: ValueError if there's no call with that ID

    Example:
        check_live_call("abc", "Caller: Grandma, I'm in jail. Buy gift cards.")
        gives you a score around 90 and alert_sent_now True, and Ana gets the alert
    """
    call = storage.get_call(call_id)
    if call is None:
        raise ValueError("We couldn't find a call with that ID.")

    enrollment = storage.get_enrollment(call["enrollment_id"])
    language = "en"
    if enrollment is not None:
        language = enrollment["family_language"]

    result = detector.score_call(transcript, language)
    found = research_once(call, result)

    # Save it for the call history. We save the links every time because the
    # search might finish after the call's highest score.
    storage.save_call_score(call_id, result)
    if found:
        storage.save_call_sources(call_id, all_sources(found))

    alert_sent_now = False
    if should_alert(call, enrollment, result):
        send_alerts(call, enrollment, result)
        alert_sent_now = True

    return {
        "call_id": call_id,
        "result": result,
        "research": found,
        "alert_sent_now": alert_sent_now,
        "alert_sent": call_id in ALERTED_CALL_IDS,
    }
