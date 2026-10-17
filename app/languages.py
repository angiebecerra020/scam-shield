"""
languages.py — Keeps track of which language each person speaks, and holds our
translations.

How it fits in: a senior might speak Spanish while their daughter reads texts in
English. This file remembers each person's language, so:
  - family alerts (alerts.py) go out in the reader's language
  - the dashboard shows labels in the viewer's language
  - the detector (detector.py) knows what language the call is in

We start with English and Spanish. Haitian Creole is next (it's widely spoken
in Florida), and we test it in Step 2.

Right now this file holds the text messages and spoken phone messages for the
consent check (consent.py) and the family alert with the "Join call" link
(calls.py). The rest is coming soon.
"""

SUPPORTED_LANGUAGES = ("en", "es")
DEFAULT_LANGUAGE = "en"

# The voice Twilio uses to read our spoken messages, for each language.
SPOKEN_LANGUAGE = {"en": "en-US", "es": "es-US"}

# Every text message we send, in every language. {curly} words are filled in
# by message() below. Keep each message short: a text over 160 characters is
# split into pieces, and seniors may read them out of order.
MESSAGES = {
    "en": {
        # Sent to the senior when a family member signs them up.
        "consent_request": (
            "Scam Shield: {family_name} wants to protect your phone calls from "
            "scammers. We would listen to your calls and alert {family_name} if "
            "one looks like a scam. Reply YES to allow it or NO to say no."
        ),
        "consent_yes": (
            "Thank you, {senior_name}. Scam Shield is now watching your calls. "
            "Reply STOP at any time to turn it off."
        ),
        "consent_no": "OK. Scam Shield will NOT listen to your calls.",
        "consent_revoked": "Scam Shield is now off. We will not listen to your calls.",
        "consent_unclear": "Please reply YES to allow Scam Shield, or NO to say no.",
        # Sent to the family member when the senior answers.
        "family_told_yes": "Scam Shield: {senior_name} said YES. Their calls are now protected.",
        "family_told_no": "Scam Shield: {senior_name} said NO, so we will not watch their calls.",
        "family_told_off": "Scam Shield: {senior_name} turned Scam Shield off. We stopped watching their calls.",
        # Sent to the family member during a risky call.
        "family_alert": (
            "Scam Shield ALERT: {senior_name} may be on a scam call right now. "
            "Tap to join the call: {join_link}"
        ),
        # SPOKEN on the consent phone call to a landline (landlines can't get texts).
        "consent_call_prompt": (
            "Hello {senior_name}. This is Scam Shield. {family_name} wants to "
            "protect your phone calls from scammers. We would listen to your calls, "
            "and alert {family_name} if one sounds like a scam. "
            "To allow it, press 1. To say no, press 2."
        ),
        "consent_call_yes": (
            "Thank you. Scam Shield is now on. {family_name} will finish setting it up. Goodbye."
        ),
        "consent_call_no": "OK. Scam Shield will not listen to your calls. Goodbye.",
        "consent_call_goodbye": "We didn't hear an answer. Goodbye.",
    },
    "es": {
        "consent_request": (
            "Scam Shield: {family_name} quiere proteger sus llamadas contra "
            "estafadores. Escucharíamos sus llamadas y avisaríamos a {family_name} "
            "si una parece una estafa. Responda SI para permitirlo o NO para negarlo."
        ),
        "consent_yes": (
            "Gracias, {senior_name}. Scam Shield ahora protege sus llamadas. "
            "Responda STOP en cualquier momento para apagarlo."
        ),
        "consent_no": "Entendido. Scam Shield NO escuchará sus llamadas.",
        "consent_revoked": "Scam Shield está apagado. No escucharemos sus llamadas.",
        "consent_unclear": "Por favor responda SI para permitir Scam Shield, o NO para negarlo.",
        "family_told_yes": "Scam Shield: {senior_name} dijo SÍ. Sus llamadas ahora están protegidas.",
        "family_told_no": "Scam Shield: {senior_name} dijo NO, así que no vigilaremos sus llamadas.",
        "family_told_off": "Scam Shield: {senior_name} apagó Scam Shield. Ya no vigilamos sus llamadas.",
        "family_alert": (
            "ALERTA de Scam Shield: {senior_name} puede estar en una llamada de "
            "estafa ahora mismo. Toque para unirse a la llamada: {join_link}"
        ),
        "consent_call_prompt": (
            "Hola {senior_name}. Le habla Scam Shield. {family_name} quiere "
            "proteger sus llamadas contra estafadores. Escucharíamos sus llamadas, "
            "y avisaríamos a {family_name} si una parece una estafa. "
            "Para permitirlo, marque 1. Para negarlo, marque 2."
        ),
        "consent_call_yes": (
            "Gracias. Scam Shield ya está activado. {family_name} terminará de configurarlo. Adiós."
        ),
        "consent_call_no": "Entendido. Scam Shield no escuchará sus llamadas. Adiós.",
        "consent_call_goodbye": "No escuchamos una respuesta. Adiós.",
    },
}


def pick_language(code: str | None) -> str:
    """
    Make sure a language code is one we support, falling back to English.

    Input:  code — e.g. "es", "ES", "fr" or None
    Output: "en" or "es"

    Examples:
        pick_language("ES")  ->  "es"
        pick_language("fr")  ->  "en"    (not supported yet)
    """
    if code and code.strip().lower() in SUPPORTED_LANGUAGES:
        return code.strip().lower()
    return DEFAULT_LANGUAGE


def message(key: str, language: str, **details: str) -> str:
    """
    Get one text message in a person's language, with the blanks filled in.

    Input:  key      — which message, e.g. "consent_request"
            language — "en" or "es"
            details  — the words to fill in, e.g. family_name="Ana"
    Output: the finished message

    Example:
        message("consent_no", "es")  ->  "Entendido. Scam Shield NO escuchará sus llamadas."
    """
    template = MESSAGES[pick_language(language)][key]
    return template.format(**details)


def spoken_language(language: str) -> str:
    """
    The language code Twilio needs to read a message out loud.

    Example:
        spoken_language("es")  ->  "es-US"
    """
    return SPOKEN_LANGUAGE[pick_language(language)]
