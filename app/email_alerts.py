"""
email_alerts.py

Sends the family alert by email, from our Scam Shield Gmail.

How it fits in: real texts need a US sign-up with the phone companies that
takes weeks, so for now the family gets the alert by email instead. The
phone line (phone_line.py) calls send_email() with alert_email() the moment
a call scores 70 or more.

We send through Gmail's own mail server with an app password (GMAIL_ADDRESS
and GMAIL_APP_PASSWORD in .env). If those are blank, we just skip the email.
"""

import re
import smtplib
from email.message import EmailMessage

from app.config import get_settings

# Gmail's mail server. Port 587 starts plain and then switches to a locked
# (encrypted) connection before we log in.
GMAIL_SERVER = "smtp.gmail.com"
GMAIL_PORT = 587
SEND_TIMEOUT_SECONDS = 15

# A simple check that an address looks like name@site.com. Gmail does the
# real check when it sends.
LOOKS_LIKE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LENGTH = 254

# What we say when Nemotron didn't write an alert message for some reason.
FALLBACK_MESSAGE = {
    "en": "Your loved one may be on a scam call. Call them now.",
    "es": "Su ser querido puede estar en una llamada de estafa. Llámele ahora.",
}

# The words around the alert, in the family's language.
WORDING = {
    "en": {
        "subject": "Scam Shield alert: {senior} may be on a scam call",
        "hello": "Hi {family},",
        "why": "Why we're worried:",
        "score": "Scam risk: {score} out of 100.",
        "watch": "Watch the call live: {link}",
        "join": "Join the call now: {link}",
        "footer": (
            "This is a Scam Shield test call. Rosa, Ana and Danny are made up, "
            "and only you got this email."
        ),
    },
    "es": {
        "subject": "Alerta de Scam Shield: {senior} puede estar en una llamada de estafa",
        "hello": "Hola {family}:",
        "why": "Por qué nos preocupa:",
        "score": "Riesgo de estafa: {score} de 100.",
        "watch": "Mire la llamada en vivo: {link}",
        "join": "Únase a la llamada ahora: {link}",
        "footer": (
            "Esta es una llamada de prueba de Scam Shield. Rosa, Ana y Danny son "
            "inventados, y solo usted recibió este correo."
        ),
    },
}


def is_email(address: str) -> bool:
    """
    Checks that an email address looks real enough to send to.

    Input:  address, what the visitor typed
    Output: True or False

    Example:
        is_email("ana@example.com") gives you True
        is_email("ana at example") gives you False
    """
    if not address or len(address) > MAX_EMAIL_LENGTH:
        return False
    return LOOKS_LIKE_EMAIL.match(address) is not None


def email_is_set_up() -> bool:
    """
    Checks that we have a Gmail address and app password to send from.

    Example:
        With both GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env, gives you True
    """
    settings = get_settings()
    return bool(settings.gmail_address and settings.gmail_app_password)


def alert_email(
    language: str,
    senior_name: str,
    family_name: str,
    detector_result: dict,
    watch_link: str,
    real_call: bool = False,
) -> tuple[str, str]:
    """
    Writes the alert email: the subject line and the message.

    Input:  language, the family's language ("en" or "es", others get English)
            senior_name, like "Rosa"
            family_name, who reads it, like "Ana"
            detector_result, what detector.score_call() gave back
            watch_link, where they can watch the call live (or join it, on a real call)
            real_call, True for a real protected call: the link joins the call,
                       and we leave out the "this is a test" line
    Output: (subject, body)

    Example:
        alert_email("en", "Rosa", "Ana", grandson_result, "https://.../try?ticket=abc")
        gives you ("Scam Shield alert: Rosa may be on a scam call", "Hi Ana, ...")
    """
    if language not in WORDING:
        language = "en"
    words = WORDING[language]

    message = detector_result.get("family_alert_message") or FALLBACK_MESSAGE[language]

    lines = [words["hello"].format(family=family_name), "", message, ""]

    # Two reasons keeps it short, same as the "why" text.
    reasons = detector_result.get("reasons") or []
    if reasons:
        lines.append(words["why"])
        for reason in reasons[:2]:
            lines.append(f"  * {reason}")
        lines.append("")

    score = detector_result.get("risk_score")
    if score is not None:
        lines.append(words["score"].format(score=score))
    if real_call:
        lines.append(words["join"].format(link=watch_link))
        lines.extend(["", "Scam Shield"])
    else:
        lines.append(words["watch"].format(link=watch_link))
        lines.extend(["", words["footer"], "Scam Shield"])

    subject = words["subject"].format(senior=senior_name)
    return subject, "\n".join(lines)


def deliver(message: EmailMessage) -> None:
    """
    Hands one email to Gmail's mail server. The tests swap this out, so they
    never send a real email.

    Input:  message, a finished email with From, To and Subject filled in
    Output: nothing
    Raises: an smtplib or network error if Gmail says no

    Example:
        deliver(message) and the email is on its way
    """
    settings = get_settings()
    with smtplib.SMTP(GMAIL_SERVER, GMAIL_PORT, timeout=SEND_TIMEOUT_SECONDS) as server:
        server.starttls()
        server.login(settings.gmail_address, settings.gmail_app_password)
        server.send_message(message)


def send_email(to: str, subject: str, body: str) -> str:
    """
    Sends one plain text email from our Scam Shield Gmail.

    Input:  to, the address to send it to
            subject and body, from alert_email()
    Output: what happened: "sent", "not_set_up" (no Gmail in .env),
            "bad_address" or "failed"

    Example:
        send_email("ana@example.com", "Scam Shield alert: ...", "Hi Ana, ...")
        gives you "sent"
    """
    if not email_is_set_up():
        return "not_set_up"
    if not is_email(to):
        return "bad_address"

    message = EmailMessage()
    message["From"] = f"Scam Shield <{get_settings().gmail_address}>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        deliver(message)
    except (smtplib.SMTPException, OSError) as problem:
        # We never want a failed email to stop the call check, so we just
        # note it. The page shows that the email didn't go out.
        print(f"Couldn't send the alert email: {problem}")
        return "failed"
    return "sent"
