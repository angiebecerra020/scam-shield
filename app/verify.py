"""
verify.py

This is the "Is it really you?" check.

How it fits in: if the detector (detector.py) sees that the caller is using a
family member's name ("Grandma, it's me, Danny!") and the call looks
suspicious, this file:
  1. looks for that person in the family's contact list
  2. texts the REAL person: "Someone on a call with Rosa is using your name.
     Is that really you? Reply YES or NO."
  3. remembers the question, so we only ask once per call
  4. when they answer, tells the family. If the answer is NO, the senior gets
     warned right away (senior_warnings.py).

This one check stops the most common scam on older adults, the "grandparent
scam", because the scammer can't fake the real grandkid's answer. Not even
with a cloned voice.

Right now the answer comes from the demo player's YES and NO buttons. Reading
real text replies is coming soon.
"""

import re

from app import alerts
from app.languages import pick_language

# The question we text the real family member, in their language.
QUESTIONS = {
    "en": (
        "Scam Shield: someone on a call with {senior_name} right now is using "
        "your name. Is that really you? Reply YES or NO."
    ),
    "es": (
        "Scam Shield: alguien en una llamada con {senior_name} está usando su "
        "nombre. ¿De verdad es usted? Responda SI o NO."
    ),
}

# What we text the family once the real person answers.
FAMILY_UPDATES = {
    "en": {
        "no": (
            "Scam Shield: {contact_name} says they are NOT the one calling "
            "{senior_name}. We told {senior_name} to hang up."
        ),
        "yes": "Scam Shield: {contact_name} says they really are the one calling {senior_name}.",
    },
    "es": {
        "no": (
            "Scam Shield: {contact_name} dice que NO es quien está llamando a "
            "{senior_name}. Le dijimos a {senior_name} que cuelgue."
        ),
        "yes": "Scam Shield: {contact_name} dice que sí es quien está llamando a {senior_name}.",
    },
}

# The questions we've already asked, by call ID, so we only ask once per call.
CHECKS_BY_CALL_ID: dict[str, dict] = {}


def mentions(text: str, word: str) -> bool:
    """
    Checks if a word shows up in some text as a whole word, not inside
    another word. That way "son" doesn't match "Officer Johnson".

    Input:  text, like "grandson Danny"
            word, like "Danny"
    Output: True or False

    Examples:
        mentions("grandson Danny", "danny") gives you True
        mentions("Officer Johnson", "son") gives you False
    """
    pattern = r"\b" + re.escape(word.lower()) + r"\b"
    return re.search(pattern, (text or "").lower()) is not None


def find_contact(claimed_identity: str | None, contacts: list[dict]) -> dict | None:
    """
    Finds the family member the caller is pretending to be (or using the name of).

    Each contact has a name, plus other names they go by (like "Daniel" for
    Danny) and how they're related (like "grandson" or "nieto").

    Input:  claimed_identity, who the caller says they are, from the detector
            contacts, the family's contact list
    Output: the matching contact, or None

    Example:
        find_contact("grandson Danny", [{"name": "Danny", "other_names": ["grandson"]}])
        gives you the Danny contact
    """
    if not claimed_identity:
        return None
    for contact in contacts:
        names = [contact["name"]] + contact.get("other_names", [])
        for name in names:
            if mentions(claimed_identity, name):
                return contact
    return None


def public_view(check: dict | None) -> dict | None:
    """
    The parts of a check that are safe to send to the web page (no phone numbers).

    Input:  check, from ask_if_needed() or record_answer(), or None
    Output: the same check without the phone number, or None

    Example:
        public_view({"contact_name": "Danny", "contact_phone": "+1...", ...})
        gives you the same thing without contact_phone
    """
    if check is None:
        return None
    return {
        "contact_name": check["contact_name"],
        "language": check["language"],
        "question": check["question"],
        "answer": check["answer"],
    }


def ask_if_needed(call_id: str, detector_result: dict, senior_name: str, contacts: list[dict]) -> dict | None:
    """
    Texts the real family member if the caller is using their name and the
    call looks suspicious. We only ever ask once per call.

    Input:  call_id, our ID for the call
            detector_result, what detector.score_call() gave back
            senior_name, like "Rosa"
            contacts, the family's contact list
    Output: the check (with the question and the answer so far), or None if
            we didn't need to ask

    Example:
        A call scoring 85 where the caller says "it's me, Danny" texts the real
        Danny and gives you {"contact_name": "Danny", "question": "...", "answer": None, ...}
    """
    if call_id in CHECKS_BY_CALL_ID:
        return CHECKS_BY_CALL_ID[call_id]
    if detector_result.get("verdict") not in ("suspicious", "likely_scam"):
        return None

    contact = find_contact(detector_result.get("claimed_identity"), contacts)
    if contact is None:
        return None

    language = pick_language(contact.get("language"))
    question = QUESTIONS[language].format(senior_name=senior_name)
    alerts.send_sms(contact["phone"], question)

    check = {
        "contact_name": contact["name"],
        "contact_phone": contact["phone"],
        "language": language,
        "question": question,
        "answer": None,
    }
    CHECKS_BY_CALL_ID[call_id] = check
    return check


def record_answer(call_id: str, answer: str, senior_name: str, family_phone: str, family_language: str) -> dict:
    """
    Saves the real family member's YES or NO, and texts the family what they said.

    Input:  call_id, our ID for the call
            answer, "yes" or "no"
            senior_name, like "Rosa"
            family_phone, the family member who gets the alerts
            family_language, their language
    Output: the check, with the answer filled in
    Raises: ValueError if we never asked about this call, or the answer isn't yes or no

    Example:
        record_answer("abc", "no", "Rosa", "+13055550101", "en") texts Ana
        "Scam Shield: Danny says they are NOT the one calling Rosa..."
    """
    check = CHECKS_BY_CALL_ID.get(call_id)
    if check is None:
        raise ValueError("We haven't asked anyone about this call yet.")

    answer = (answer or "").strip().lower()
    if answer not in ("yes", "no"):
        raise ValueError('The answer has to be "yes" or "no".')

    check["answer"] = answer
    update = FAMILY_UPDATES[pick_language(family_language)][answer]
    alerts.send_sms(family_phone, update.format(contact_name=check["contact_name"], senior_name=senior_name))
    return check
