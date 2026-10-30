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


# The scam voicemail email, in the family's language (voicemail_email).
VOICEMAIL_WORDING = {
    "en": {
        "subject": "Scam Shield alert: a scam voicemail was left for {senior}",
        "hello": "Hi {family},",
        "intro": "Someone left {senior} a voicemail that looks like a scam.",
        "number": "Number that called: {number}",
        "who": "They said they were: {who}",
        "why": "What they were after:",
        "score": "Scam risk: {score} out of 100.",
        "listed": (
            "We added this number to your scam list as a potential scam. You can "
            "choose to warn or block it from the call in your Call Log."
        ),
        "advice": (
            "Please don't call this number back. If you're not sure, call {senior} "
            "on a number you know and check that they're OK."
        ),
    },
    "es": {
        "subject": "Alerta de Scam Shield: dejaron un mensaje de voz de estafa para {senior}",
        "hello": "Hola {family}:",
        "intro": "Alguien le dejó a {senior} un mensaje de voz que parece una estafa.",
        "number": "Número que llamó: {number}",
        "who": "Dijo ser: {who}",
        "why": "Lo que buscaba:",
        "score": "Riesgo de estafa: {score} de 100.",
        "listed": (
            "Agregamos este número a su lista de estafas como posible estafa. Puede "
            "elegir avisar o bloquearlo desde la llamada en su Registro de llamadas."
        ),
        "advice": (
            "Por favor no le devuelva la llamada a este número. Si tiene dudas, llame a "
            "{senior} a un número que usted conozca y confirme que está bien."
        ),
    },
}


def voicemail_email(
    language: str,
    senior_name: str,
    family_name: str,
    detector_result: dict,
    caller_number: str,
    on_list: bool = True,
) -> tuple[str, str]:
    """
    Writes the email for a scam voicemail: who called, and what they were after.

    Input:  language, the family's language ("en" or "es", others get English)
            senior_name, like "Rosa"
            family_name, who reads it, like "Ana"
            detector_result, what detector.score_call() gave back for the voicemail
            caller_number, the number that left it, like "+13055550142"
            on_list, False when the number is hidden, so it couldn't go on their list
    Output: (subject, body)

    Example:
        voicemail_email("en", "Rosa", "Ana", grandson_result, "+13055550142")
        gives you ("Scam Shield alert: a scam voicemail was left for Rosa", "Hi Ana, ...")
    """
    if language not in VOICEMAIL_WORDING:
        language = "en"
    words = VOICEMAIL_WORDING[language]

    lines = [
        words["hello"].format(family=family_name),
        "",
        words["intro"].format(senior=senior_name),
        "",
        words["number"].format(number=caller_number),
    ]
    if detector_result.get("claimed_identity"):
        lines.append(words["who"].format(who=detector_result["claimed_identity"]))
    lines.append("")

    reasons = detector_result.get("reasons") or []
    if reasons:
        lines.append(words["why"])
        for reason in reasons[:3]:
            lines.append(f"  * {reason}")
        lines.append("")

    score = detector_result.get("risk_score")
    if score is not None:
        lines.append(words["score"].format(score=score))
    if on_list:
        lines.append(words["listed"])
    lines.extend(["", words["advice"].format(senior=senior_name), "", "Scam Shield"])

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


# The welcome email, in the family's language. {name} is the family member,
# {senior} the person they're protecting, {link} the how to set up page.
WELCOME_WORDS = {
    "en": {
        "subject": "Welcome to Scam Shield",
        "body": (
            "Hi {name},\n\n"
            "Welcome to Scam Shield! Thank you for looking out for {senior}.\n\n"
            "Here's what happens next:\n"
            "1. We call {senior} to ask for their OK. They press 1 to say yes.\n"
            "2. Then you finish setting up their phone. It takes under 5 minutes.\n\n"
            "Watch our step by step video, with every code to dial:\n{link}\n\n"
            "We're here to help,\nAngie and Cass, Scam Shield"
        ),
    },
    "es": {
        "subject": "Bienvenido a Scam Shield",
        "body": (
            "Hola {name}:\n\n"
            "¡Bienvenido a Scam Shield! Gracias por cuidar a {senior}.\n\n"
            "Lo que sigue:\n"
            "1. Llamamos a {senior} para pedirle su permiso. Marca 1 para decir que sí.\n"
            "2. Después usted termina de configurar su teléfono. Toma menos de 5 minutos.\n\n"
            "Vea nuestro video paso a paso, con cada código para marcar:\n{link}\n\n"
            "Estamos para ayudarle,\nAngie y Cass, Scam Shield"
        ),
    },
}


def send_welcome_email(enrollment: dict) -> str:
    """
    Sends the family a welcome email with the how to set up video, right
    after they sign someone up. It never stops the sign up if it fails.

    Input:  enrollment, the new sign up (needs family_email to send anything)
    Output: what happened, like send_email(): "sent", "not_set_up",
            "bad_address", "failed", or "no_email" if they didn't give one

    Example:
        send_welcome_email(rosa) gives you "sent", and Ana gets
        "Welcome to Scam Shield" with the video link
    """
    address = enrollment.get("family_email")
    if not address:
        return "no_email"
    words = WELCOME_WORDS.get(enrollment.get("family_language"), WELCOME_WORDS["en"])
    link = get_settings().public_base_url.rstrip("/") + "/how-to"
    body = words["body"].format(
        name=enrollment.get("family_name", ""), senior=enrollment.get("senior_name", ""), link=link
    )
    return send_email(address, words["subject"], body)


# The email the family gets when the senior turns Scam Shield off themselves.
# {name} is the family member, {senior} the person they were protecting,
# {forwarding} how to turn off call forwarding on their kind of phone (the
# same codes the dashboard shows after Remove).
REMOVED_WORDS = {
    "en": {
        "subject": "{senior} removed you from Scam Shield",
        "body": (
            "Hi {name},\n\n"
            "{senior} called Scam Shield and turned it off, which removed you "
            "as their contact. We no longer monitor their calls, and we deleted "
            "their details and call history.\n\n"
            "Their calls keep ringing like normal. {forwarding}\n\n"
            "Angie and Cass, Scam Shield"
        ),
        "cell": "To stop forwarding calls to Scam Shield, dial ##002# on their phone (Verizon: *73).",
        "landline": (
            "To finish, plug their phone back into the wall jack and dial *73 "
            "to turn off call forwarding."
        ),
    },
    "es": {
        "subject": "{senior} lo quitó de Scam Shield",
        "body": (
            "Hola {name}:\n\n"
            "{senior} llamó a Scam Shield y lo apagó, así que usted ya no es su "
            "contacto. Ya no vigilamos sus llamadas, y borramos sus datos y su "
            "historial de llamadas.\n\n"
            "Sus llamadas siguen sonando como siempre. {forwarding}\n\n"
            "Angie y Cass, Scam Shield"
        ),
        "cell": "Para dejar de desviar llamadas a Scam Shield, marque ##002# en su teléfono (Verizon: *73).",
        "landline": (
            "Para terminar, conecte su teléfono otra vez al enchufe de la pared "
            "y marque *73 para apagar el desvío de llamadas."
        ),
    },
}


def send_removed_email(enrollment: dict) -> str:
    """
    Tells the family by email that the senior turned Scam Shield off and
    removed them as their contact. Send it BEFORE we wipe the sign-up
    (storage.forget_enrollment), since that deletes the family's email.

    Input:  enrollment, the senior's sign-up (needs family_email to send anything)
    Output: what happened, like send_welcome_email()

    Example:
        send_removed_email(rosa) gives you "sent", and Ana gets
        "Rosa removed you from Scam Shield"
    """
    address = enrollment.get("family_email")
    if not address:
        return "no_email"
    words = REMOVED_WORDS.get(enrollment.get("family_language"), REMOVED_WORDS["en"])
    forwarding = words["landline" if enrollment.get("phone_type") == "landline" else "cell"]
    senior = enrollment.get("senior_name", "")
    body = words["body"].format(name=enrollment.get("family_name", ""), senior=senior, forwarding=forwarding)
    return send_email(address, words["subject"].format(senior=senior), body)
