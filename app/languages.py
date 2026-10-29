"""
languages.py — Keeps track of which language each person speaks, and holds our
translations.

How it fits in: a senior might speak Spanish while their daughter reads texts in
English. This file remembers each person's language, so:
  - family alerts (alerts.py) go out in the reader's language
  - the dashboard shows labels in the viewer's language
  - the detector (detector.py) knows what language the call is in

We support English and Spanish. Each one has text messages AND spoken
phone messages: the consent check and the family alert are phone calls.

This file holds the text messages and spoken phone messages for the consent
check (consent.py) and the alert call that lets the family join (calls.py).
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
        # SPOKEN on the consent phone call (always for a landline, or when the family picks a call).
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
        # SPOKEN when a protected senior calls our number themselves.
        "consent_call_menu": (
            "Hello {senior_name}. This is Scam Shield. {family_name} set up Scam Shield "
            "to listen to your calls and warn them about scams. "
            "If you want to cancel Scam Shield from listening to your conversations, press 2. "
            "To keep it on, press 1."
        ),
        "consent_call_canceled": (
            "Scam Shield is now canceled. We will not listen to your calls anymore. "
            "We let {family_name} know. Goodbye."
        ),
        "consent_call_kept": "OK. Scam Shield stays on. Goodbye.",
        # SPOKEN on the alert call to the family member during a risky call.
        "alert_call_prompt": "Scam Shield alert. {senior_name} may be on a scam call right now.",
        "alert_call_why": "Why we're worried: {reasons}.",
        "alert_call_reported": "The number calling {senior_name} is one you reported as a scam.",
        "alert_call_question": "To join the call, press 1. To hang up, press 2.",
        "alert_call_joining": (
            "Connecting you now. Everyone on the call will hear a tone when you join."
        ),
        "alert_call_ended": "That call has already ended. Goodbye.",
        "alert_call_bye": "OK. Goodbye.",
        "alert_call_goodbye": "We didn't hear an answer. Goodbye.",
        # How the demo player shows the alert call on Ana's phone.
        "alert_call_demo": "📞 Scam Shield ALERT call: “{words}”",
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
        "consent_call_menu": (
            "Hola {senior_name}. Le habla Scam Shield. {family_name} configuró Scam Shield "
            "para escuchar sus llamadas y avisarle si hay una estafa. "
            "Si quiere cancelar Scam Shield para que deje de escuchar sus conversaciones, marque 2. "
            "Para mantenerlo activado, marque 1."
        ),
        "consent_call_canceled": (
            "Scam Shield está cancelado. Ya no escucharemos sus llamadas. "
            "Le avisamos a {family_name}. Adiós."
        ),
        "consent_call_kept": "Entendido. Scam Shield sigue activado. Adiós.",
        "alert_call_prompt": "Alerta de Scam Shield. {senior_name} puede estar en una llamada de estafa ahora mismo.",
        "alert_call_why": "Por qué nos preocupa: {reasons}.",
        "alert_call_reported": "El número que está llamando a {senior_name} es uno que usted reportó como estafa.",
        "alert_call_question": "Para unirse a la llamada, marque 1. Para colgar, marque 2.",
        "alert_call_joining": (
            "Lo estamos conectando. Todos en la llamada oirán un tono cuando usted entre."
        ),
        "alert_call_ended": "Esa llamada ya terminó. Adiós.",
        "alert_call_bye": "Entendido. Adiós.",
        "alert_call_goodbye": "No escuchamos una respuesta. Adiós.",
        "alert_call_demo": "📞 Llamada de ALERTA de Scam Shield: “{words}”",
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
    return SPOKEN_LANGUAGE.get(pick_language(language), SPOKEN_LANGUAGE[DEFAULT_LANGUAGE])
