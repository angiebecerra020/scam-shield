"""
senior_warnings.py

The warnings we show (and say out loud) to the senior during a risky call.

How it fits in: the family gets a text when a call looks like a scam, but the
senior is the one actually on the phone. So we warn them directly too, in
their own language. The demo player shows these on Grandma's phone and reads
them out loud with the browser's voice.

There are two warnings:
  - "scam_likely": the score hit 70, so this looks like a scam
  - "not_them": the real family member said they are NOT the one calling
"""

from app.languages import pick_language

# The words for each warning, in each language. We keep them short and plain,
# so they're easy to read and easy to understand when they're read out loud.
WARNINGS = {
    "en": {
        "scam_likely": "This is a potential scam. We are notifying a family member.",
        "not_them": "{contact_name} says they are NOT calling you. Hang up now.",
    },
    "es": {
        "scam_likely": "Esta es una posible estafa. Estamos avisando a un familiar.",
        "not_them": "{contact_name} dice que NO le está llamando. Cuelgue ahora.",
    },
}

# The voice the browser uses to read each language out loud.
SPEECH_LANGUAGE = {"en": "en-US", "es": "es-US"}


def senior_warning(kind: str, language: str, contact_name: str = "") -> dict:
    """
    Gets one warning for the senior, in their language.

    Input:  kind, which warning: "scam_likely" or "not_them"
            language, the senior's language, "en" or "es" (anything else uses English)
            contact_name, the family member's name, for the "not_them" warning
    Output: {"kind", "text", "speech_language"}

    Example:
        senior_warning("not_them", "es", "Danny") gives you
        {"kind": "not_them", "text": "Danny dice que NO le está llamando. Cuelgue ahora.",
         "speech_language": "es-US"}
    """
    language = pick_language(language)
    text = WARNINGS[language][kind].format(contact_name=contact_name)
    return {"kind": kind, "text": text, "speech_language": SPEECH_LANGUAGE[language]}
