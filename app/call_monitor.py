"""
call_monitor.py

This connects our brain to the family alert.

How it fits in: while a protected call is happening, the live transcript (or
the demo player) sends the call so far here, over and over as new lines come
in. Each time, we:
  1. ask Nemotron how risky the call is (detector.py)
  2. the first time it looks suspicious, ask Tavily about the caller (research.py)
  3. the first time the score hits 70 or more, send the family alert with the
     "Join call" link (calls.send_family_alert), plus a short text that says
     WHY we're worried
  4. save the score, the reasons and the Tavily links with the call, so the
     family can look back at it later on the dashboard (family.py)

We only alert the family once per call, so they don't get ten texts. And we
only alert for seniors who said YES to Scam Shield (that's the consent check
in consent.py).

Heads up: we remember which calls already got an alert in memory. If the
server restarts in the middle of a call it could alert one more time, and
that's fine for now.
"""

from app import alerts, calls, detector, research, storage

# Calls that already got a family alert, so we never send it twice.
ALERTED_CALL_IDS: set[str] = set()

# The Tavily results for each call, so we only search once per call.
RESEARCH_BY_CALL_ID: dict[str, dict] = {}

# How the "why we're worried" text starts, in the family's language.
WHY_START = {
    "en": "Why we're worried: ",
    "es": "Por qué nos preocupa: ",
}


# How many red flags we list in the "why" text. Two keeps it short like a text.
WHY_REASONS = 2


def why_text(detector_result: dict, language: str) -> str | None:
    """
    Writes the short text that tells the family WHY we think it's a scam.

    The family alert already says "may be on a scam call", so here we list the
    actual red flags instead of repeating that. If there are no reasons, we
    use Nemotron's family alert message.

    Input:  detector_result, what detector.score_call() gave back
            language, the family's language, "en" or "es"
    Output: the text, or None if there's nothing to explain

    Example:
        why_text({"reasons": ["Claims to be a grandson in trouble", "Asks for gift cards"]}, "en")
        gives you "Why we're worried: Claims to be a grandson in trouble; Asks for gift cards."
    """
    start = WHY_START.get(language, WHY_START["en"])
    reasons = detector_result.get("reasons") or []
    if reasons:
        return start + "; ".join(reasons[:WHY_REASONS]) + "."

    message = detector_result.get("family_alert_message")
    if message:
        return start + message
    return None


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
      - the senior said YES to Scam Shield
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
    if enrollment is None or enrollment["status"] != "active":
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
    Sends the family alert with the "Join call" link, then the "why" text.

    Input:  call, enrollment, detector_result (same as should_alert)
    Output: nothing. In demo mode the texts go to the demo outbox instead.

    Example:
        Ana gets "Scam Shield ALERT: Rosa may be on a scam call right now..."
        and then "Why we're worried: The caller says they are grandson Danny..."
    """
    calls.send_family_alert(call)
    extra = why_text(detector_result, enrollment["family_language"])
    if extra:
        alerts.send_sms(enrollment["family_phone"], extra)
    ALERTED_CALL_IDS.add(call["id"])
    storage.mark_call_alerted(call["id"])


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
