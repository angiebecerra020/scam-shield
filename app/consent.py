"""
consent.py — Makes sure the senior agrees before we ever listen to their calls.

How it fits in: when a family member sets up Scam Shield, we don't start
listening right away. We ask the SENIOR, on their own phone, with a phone
call: "Ana wants to protect your phone calls... press 1 to allow, 2 to say no."
We used to offer a text instead, but texts from our number weren't arriving
(US carriers block texts from numbers that aren't registered with them), so
now every senior gets a call. Only a YES from that phone turns protection on. That way a stranger who types
in someone else's number can't start listening to their calls: they would
need the senior's phone to say YES.

The steps:
  1. start_enrollment()      — family signs up; we call the senior
                               (status "pending")
  2. handle_consent_digits() — the senior presses a key on our call
     handle_senior_reply()   — or texts us back (older sign-ups were asked
                               by text, and STOP by text still works)
       YES / 1 -> "active"   (calls.py will now protect their calls)
       NO / 2  -> "declined"
       STOP    -> "revoked"  (texts only; works any time, even months later,
                              and even while the family has protection paused)
  3. No answer within 24 hours -> "expired"; the family can ask again.

After a YES, the family can pause protection from the dashboard ("paused")
and turn it back on later (family.py), or remove them (call_again.py).
Pausing doesn't need the senior's OK, since it means we listen LESS.
Turning it back on only works if they already said YES.

The senior can turn it off themselves too, without a text: they call our
Scam Shield number from their own phone, and we say "To cancel Scam Shield,
press 2." Pressing 2 works like texting STOP ("revoked").

Ask BEFORE turning on call forwarding: once the senior's number forwards to
us, our consent call would come straight back to us instead of ringing them.

To keep people from using us to spam strangers, we don't re-ask someone who
is already waiting to answer, and we wait 30 days before asking someone who
said NO again.
"""

import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from twilio.twiml.voice_response import VoiceResponse

from app import storage
from app.alerts import send_sms, twilio_client
from app.email_alerts import is_email
from app.calls import DEMO_CALL_LOG, public_url
from app.config import get_settings
from app.languages import message, pick_language, spoken_language
from app.phone_numbers import mask_phone, missing_area_code, normalize_phone

PHONE_TYPES = ("cell", "landline")
# Who the senior can be to the family member, for the "Who are they to you?"
# list on the sign-up form. Anyone else is "other". The dashboard groups
# "Your family" in this order (family.js).
RELATIONSHIPS = (
    "mom",
    "dad",
    "grandma",
    "grandpa",
    "wife",
    "husband",
    "daughter",
    "son",
    "sister",
    "brother",
    "aunt",
    "uncle",
    "other",
)
# The ways we can ask the senior for their YES. Only a call for now: see the
# note at the top of this file.
ASK_WAYS = ("call",)

# How long the senior has to answer the first text.
ANSWER_WINDOW = timedelta(hours=24)
# How long we wait before asking someone who said NO (or STOP) again.
ASK_AGAIN_AFTER_NO = timedelta(days=30)

# Words we accept as an answer. Replies are cleaned up first (see clean_reply),
# so "Yes!", "  yes " and "Sí" all match.
YES_WORDS = {"yes", "y", "yeah", "yep", "ok", "okay", "si", "s"}
NO_WORDS = {"no", "n", "nope"}
# STOP and friends are the standard US words for "stop texting me". Twilio
# also handles them itself, but we use them to turn protection off.
STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "parar", "alto"}

# Names go into a text message sent to the senior, so we only allow letters,
# spaces, and a few name characters. This blocks someone from slipping a link
# or a long ad into the text through the "name" box. A dot must be followed by
# a space ("J. Smith"), so web addresses like "scam.com" don't fit.
NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:(?:\. |[ '\-])[^\W\d_]+)*\.?$")
MAX_NAME_LENGTH = 40


class EnrollmentError(Exception):
    """
    A sign-up we can't accept, with a message the family member can read.

    status_code is the web status main.py sends back, e.g. 400 for a typo in
    a phone number or 409 when the senior is already signed up.

    Example:
        raise EnrollmentError("That phone number doesn't look right.", 400)
    """

    def __init__(self, text: str, status_code: int):
        super().__init__(text)
        self.text = text
        self.status_code = status_code


def clean_name(raw: str, label: str) -> str:
    """
    Check a person's name from the sign-up form and tidy up its spaces.

    Input:  raw   — the name as typed, e.g. "  Rosa  María "
            label — what to call the box in an error, e.g. "Senior's name"
    Output: the tidy name, e.g. "Rosa María"
    Raises: EnrollmentError if the name is blank, too long, or has
            characters a name shouldn't have (digits, links, ...)

    Example:
        clean_name("Rosa", "Senior's name")         ->  "Rosa"
        clean_name("visit scam.com", "Your name")   ->  EnrollmentError
    """
    name = " ".join((raw or "").split())
    if not name:
        raise EnrollmentError(f"{label} is required.", 400)
    if len(name) > MAX_NAME_LENGTH:
        raise EnrollmentError(f"{label} must be {MAX_NAME_LENGTH} characters or fewer.", 400)
    if not NAME_PATTERN.match(name):
        raise EnrollmentError(f"{label} can only use letters, spaces, ' - and .", 400)
    return name


def clean_phone(raw: str, label: str) -> str:
    """
    Check a phone number from the sign-up form and put it in E.164 format.

    A US number typed without its area code ("555-0100") is a common slip, so
    it gets its own message reminding them to add it, and isn't accepted.

    Examples:
        clean_phone("(305) 555-0100", "Senior's phone")  ->  "+13055550100"
        clean_phone("555-0100", "Senior's phone")        ->  EnrollmentError
            ("Senior's phone is missing the area code...")
    """
    if missing_area_code(raw or ""):
        raise EnrollmentError(
            f"{label} is missing the area code. Please type all 10 digits, like 305-555-0100.",
            400,
        )
    phone = normalize_phone(raw or "")
    if phone is None:
        raise EnrollmentError(f"{label} doesn't look like a phone number.", 400)
    return phone


def is_expired(enrollment: dict, now: datetime) -> bool:
    """
    Has a "pending" enrollment run out of time for the senior to answer?

    Example:
        created 25 hours ago, still pending  ->  True
    """
    created = storage.parse_time(enrollment["created_at"])
    return enrollment["status"] == "pending" and now - created > ANSWER_WINDOW


def expire_old_requests(enrollments: list[dict]) -> list[dict]:
    """
    Mark pending enrollments past the 24-hour window as "expired".

    We do this whenever we look at a senior's enrollments, instead of running
    a separate timer job. Simpler, and the result is the same.

    Input:  enrollments — one senior's enrollments
    Output: the same list, with any expired ones updated

    Example:
        [{"status": "pending", created 2 days ago}]  ->  [{"status": "expired", ...}]
    """
    now = datetime.now(timezone.utc)
    for enrollment in enrollments:
        if is_expired(enrollment, now):
            storage.set_enrollment_status(enrollment["id"], "expired", answered=False)
            enrollment["status"] = "expired"
    return enrollments


def check_allowed_to_ask(senior_phone: str) -> None:
    """
    Make sure we're allowed to ask this senior for their YES right now.

    Input:  senior_phone — E.164 number
    Output: nothing if it's fine
    Raises: EnrollmentError when the senior is already protected, is already
            waiting to answer, or said NO in the last 30 days

    Example:
        check_allowed_to_ask("+13055550100")  ->  (nothing: OK to ask)
    """
    now = datetime.now(timezone.utc)
    enrollments = expire_old_requests(storage.find_enrollments_for_senior(senior_phone))

    for enrollment in enrollments:
        if enrollment["status"] == "active":
            raise EnrollmentError("This person is already protected by Scam Shield.", 409)
        if enrollment["status"] == "paused":
            raise EnrollmentError(
                "This person is already signed up, but protection is paused. "
                "You can turn it back on from the dashboard.",
                409,
            )
        if enrollment["status"] == "pending":
            raise EnrollmentError(
                "We already asked this person. They have 24 hours to answer.", 409
            )
        if enrollment["status"] in ("declined", "revoked"):
            answered = storage.parse_time(enrollment["answered_at"])
            if now - answered < ASK_AGAIN_AFTER_NO:
                raise EnrollmentError(
                    "This person said no recently, so we won't ask them again yet.", 409
                )


def start_enrollment(
    senior_name: str,
    senior_phone: str,
    family_name: str,
    family_phone: str,
    senior_language: str = "en",
    family_language: str = "en",
    phone_type: str = "cell",
    ask_by: str | None = None,
    owner_id: str | None = None,
    family_email: str | None = None,
    relationship: str | None = None,
) -> dict:
    """
    Sign a senior up for Scam Shield and call them to ask for their YES.

    Nothing is listened to yet: the enrollment starts as "pending".

    Input:  senior_name, senior_phone — the person whose calls we'd protect
            family_name, family_phone — the person signing up, who gets alerts
            senior_language, family_language — "en" or "es"
            phone_type — "cell" or "landline": the kind of phone senior_phone is
            ask_by — "call", or left out (we always call now)
            owner_id — the logged in family member's Supabase user ID, so only
                       they see this senior on their dashboard (None when login is off)
            relationship — who the senior is to them, like "grandma" (left out: "other")
    Output: the new enrollment (as public_view() shows it)
    Raises: EnrollmentError if something in the form is wrong, or if we
            aren't allowed to ask this senior right now

    Example:
        start_enrollment("Rosa", "305-555-0100", "Ana", "305-555-0101", "es", "en")
        ->  {"id": "...", "status": "pending", ...}
        and Rosa's phone rings: "...marque 1 para permitirlo, 2 para decir que no."
    """
    clean_type = clean_phone_type(phone_type)
    enrollment = {
        # A long random ID, because it appears in the dashboard's web address.
        # Counting 1, 2, 3... would let anyone peek at other families.
        "id": secrets.token_urlsafe(16),
        "senior_name": clean_name(senior_name, "Senior's name"),
        "senior_phone": clean_phone(senior_phone, "Senior's phone"),
        "family_name": clean_name(family_name, "Your name"),
        "family_phone": clean_phone(family_phone, "Your phone"),
        "phone_type": clean_type,
        "ask_by": clean_ask_by(ask_by, clean_type),
        # The name Twilio knows the senior's calling app or phone adapter by.
        "device_id": "senior-" + secrets.token_hex(4),
        # The secret part of the calling-app link. Long and random, because
        # anyone with the link could answer the senior's calls.
        "device_key": secrets.token_urlsafe(24),
        "senior_language": pick_language(senior_language),
        "family_language": pick_language(family_language),
        "status": "pending",
        "created_at": storage.now_text(),
        "answered_at": None,
        "owner_id": owner_id,
        "family_email": clean_email(family_email),
        "relationship": clean_relationship(relationship),
    }

    if enrollment["senior_phone"] == enrollment["family_phone"]:
        raise EnrollmentError("The senior's phone and your phone must be different.", 400)

    check_allowed_to_ask(enrollment["senior_phone"])
    storage.save_enrollment(enrollment)
    call_senior_for_consent(enrollment)
    return public_view(enrollment)


def clean_email(raw: str | None) -> str | None:
    """
    Check the family's email for alerts. It's optional.

    Example:
        clean_email(" ana@example.com ") gives you "ana@example.com"
        clean_email("") gives you None
    Raises: EnrollmentError if it doesn't look like an email
    """
    email = (raw or "").strip()
    if not email:
        return None
    if not is_email(email):
        raise EnrollmentError("That email doesn't look right. Check it, or leave it blank.", 400)
    return email


def clean_relationship(raw: str | None) -> str:
    """
    Check the "Who are they to you?" answer. Left blank means "other".

    Examples:
        clean_relationship("Grandma")  ->  "grandma"
        clean_relationship("")         ->  "other"
        clean_relationship("boss")     ->  EnrollmentError
    """
    relationship = (raw or "").strip().lower()
    if not relationship:
        return "other"
    if relationship not in RELATIONSHIPS:
        raise EnrollmentError("Please pick who they are to you from the list.", 400)
    return relationship


def clean_phone_type(raw: str) -> str:
    """
    Check the "What kind of phone?" answer from the sign-up form.

    Example:
        clean_phone_type("Landline")  ->  "landline"
        clean_phone_type("fax")       ->  EnrollmentError
    """
    phone_type = (raw or "").strip().lower()
    if phone_type not in PHONE_TYPES:
        raise EnrollmentError("Please choose cell phone or landline.", 400)
    return phone_type


def clean_ask_by(raw: str | None, phone_type: str) -> str:
    """
    Check how the sign-up asks us to reach the senior.

    We only ask by phone call now (see the note at the top of this file), so
    left blank means "call", and "text" is turned away.

    Input:  raw        — "call" or None
            phone_type — "cell" or "landline", already checked
    Output: "call"
    Raises: EnrollmentError for anything else, including "text"

    Examples:
        clean_ask_by("Call", "cell")  ->  "call"
        clean_ask_by(None, "cell")    ->  "call"
        clean_ask_by("text", "cell")  ->  EnrollmentError
    """
    if raw is None or raw.strip() == "":
        return "call"
    ask_by = raw.strip().lower()
    if ask_by not in ASK_WAYS:
        raise EnrollmentError("We ask by phone call only for now.", 400)
    return ask_by


def how_we_asked(enrollment: dict) -> str:
    """
    Say how we asked a senior for their YES: "text" or "call".

    Sign-ups saved before families could choose have no ask_by, so we work it
    out the old way: landlines were called, cell phones were texted.

    Example:
        how_we_asked({"ask_by": None, "phone_type": "landline"})  ->  "call"
    """
    return enrollment.get("ask_by") or ("call" if enrollment["phone_type"] == "landline" else "text")


# ---------------------------------------------------------------------------
# Asking for consent with a phone call
# ---------------------------------------------------------------------------


def call_senior_for_consent(enrollment: dict) -> None:
    """
    Phone the senior to ask for their YES. Landlines are always asked this
    way (they can't get texts); cell phones are when the family picks it.

    When they pick up, Twilio asks us what to say (consent_call_twiml).

    Input:  enrollment — the new, pending enrollment
    Output: nothing. In demo mode, the call goes into DEMO_CALL_LOG instead.

    Example:
        call_senior_for_consent(rosa)  ->  Rosa's phone rings
    """
    settings = get_settings()
    url = public_url(f"/twilio/consent-call?enrollment_id={enrollment['id']}")

    # REAL_CONSENT_CALLS lets the live demo site place this one real call
    # (texts need carrier sign-up, calls don't), while everything else stays demo.
    if settings.demo_mode and not (settings.real_consent_calls or settings.real_calls):
        DEMO_CALL_LOG.append(
            {"to": enrollment["senior_phone"], "who": "consent", "conference": None}
        )
        print(f"[demo mode] would call {enrollment['senior_phone']} to ask for consent")
        return

    twilio_client().calls.create(
        to=enrollment["senior_phone"],
        from_=settings.twilio_phone_number,
        url=url,
    )


def consent_call_twiml(enrollment_id: str, attempt: int = 1) -> str:
    """
    What the senior hears on the consent call, in their language.

    We ask twice. If they still don't press anything, we say goodbye and the
    enrollment stays pending (and expires after 24 hours).

    Input:  enrollment_id — whose call this is
            attempt       — 1 the first time, 2 when we ask again
    Output: TwiML that reads the question and listens for one key press

    Example:
        consent_call_twiml("abc")
        ->  '<Response><Gather numDigits="1" ...><Say>Hello Rosa...</Say></Gather>...'
    """
    response = VoiceResponse()
    enrollment = storage.get_enrollment(enrollment_id)
    if enrollment is None or enrollment["status"] != "pending":
        response.hangup()
        return str(response)

    language = enrollment["senior_language"]
    gather = response.gather(
        num_digits=1,
        timeout=8,
        action=public_url(f"/twilio/consent-answer?enrollment_id={enrollment_id}"),
    )
    gather.say(
        message(
            "consent_call_prompt",
            language,
            senior_name=enrollment["senior_name"],
            family_name=enrollment["family_name"],
        ),
        language=spoken_language(language),
    )

    # Only reached if they didn't press anything.
    if attempt < 2:
        response.redirect(
            public_url(f"/twilio/consent-call?enrollment_id={enrollment_id}&attempt=2")
        )
    else:
        response.say(message("consent_call_goodbye", language), language=spoken_language(language))
        response.hangup()
    return str(response)


def handle_consent_digits(enrollment_id: str, called_phone: str, digits: str) -> str:
    """
    Act on the key the senior pressed during the consent call.

    The answer only counts if it came on OUR call TO the senior's phone, so we
    check the number Twilio says it called.

    Input:  enrollment_id — whose consent call this is
            called_phone  — the number we called (Twilio's "To")
            digits        — the key they pressed, e.g. "1"
    Output: TwiML: what they hear next

    Examples:
        handle_consent_digits("abc", "+15555550100", "1")  ->  "Thank you. Scam Shield is now on..."
        handle_consent_digits("abc", "+15555550100", "7")  ->  asks the question again
    """
    response = VoiceResponse()
    enrollment = storage.get_enrollment(enrollment_id)
    if (
        enrollment is None
        or enrollment["status"] != "pending"
        or normalize_phone(called_phone or "") != enrollment["senior_phone"]
    ):
        response.hangup()
        return str(response)

    language = enrollment["senior_language"]
    voice = spoken_language(language)

    if digits == "1":
        storage.set_enrollment_status(enrollment_id, "active", answered=True)
        tell_family(enrollment, "family_told_yes")
        response.say(
            message("consent_call_yes", language, family_name=enrollment["family_name"]),
            language=voice,
        )
    elif digits == "2":
        storage.set_enrollment_status(enrollment_id, "declined", answered=True)
        tell_family(enrollment, "family_told_no")
        response.say(message("consent_call_no", language), language=voice)
    else:
        # A different key: ask again.
        response.redirect(
            public_url(f"/twilio/consent-call?enrollment_id={enrollment_id}&attempt=2")
        )
        return str(response)

    response.hangup()
    return str(response)


# ---------------------------------------------------------------------------
# The senior calls us to turn Scam Shield off
# ---------------------------------------------------------------------------


def find_senior_calling_in(from_phone: str) -> dict | None:
    """
    Is this call to our number coming from a senior we're protecting?

    If it is, main.py plays them the cancel menu (senior_menu_twiml) instead
    of treating them like a caller to protect them from.

    Input:  from_phone — who is calling (Twilio's "From")
    Output: their newest "active" or "paused" enrollment, or None

    Example:
        find_senior_calling_in("+13055550100")  ->  {"senior_name": "Rosa", "status": "active", ...}
        find_senior_calling_in("+15555550199")  ->  None (not a senior we protect)
    """
    phone = normalize_phone(from_phone or "")
    if phone is None:
        return None
    for enrollment in storage.find_enrollments_for_senior(phone):
        if enrollment["status"] in ("active", "paused"):
            return enrollment
    return None


def senior_menu_twiml(enrollment_id: str, attempt: int = 1) -> str:
    """
    What the senior hears when they call our number: Scam Shield is on, and
    they can press 2 to cancel it.

    We ask twice. If they don't press anything, nothing changes.

    Input:  enrollment_id — the senior who called
            attempt       — 1 the first time, 2 when we ask again
    Output: TwiML that reads the menu and listens for one key press

    Example:
        senior_menu_twiml("abc")
        ->  '<Response><Gather numDigits="1" ...><Say>Hello Rosa. This is Scam Shield...</Say>...'
    """
    response = VoiceResponse()
    enrollment = storage.get_enrollment(enrollment_id)
    if enrollment is None or enrollment["status"] not in ("active", "paused"):
        response.hangup()
        return str(response)

    language = enrollment["senior_language"]
    voice = spoken_language(language)
    gather = response.gather(
        num_digits=1,
        timeout=8,
        action=public_url(f"/twilio/senior-menu-answer?enrollment_id={enrollment_id}"),
    )
    gather.say(
        message(
            "consent_call_menu",
            language,
            senior_name=enrollment["senior_name"],
            family_name=enrollment["family_name"],
        ),
        language=voice,
    )

    if attempt < 2:
        response.redirect(
            public_url(f"/twilio/senior-menu?enrollment_id={enrollment_id}&attempt=2")
        )
    else:
        response.say(message("consent_call_kept", language), language=voice)
        response.hangup()
    return str(response)


def handle_senior_menu_digits(enrollment_id: str, from_phone: str, digits: str) -> str:
    """
    Act on the key the senior pressed in the cancel menu.

    It only counts if the call came FROM the senior's own phone, so we check
    the number Twilio says is calling.

    Input:  enrollment_id — the senior who called
            from_phone    — who is calling (Twilio's "From")
            digits        — the key they pressed: "2" cancels, "1" keeps it on
    Output: TwiML: what they hear next

    Examples:
        handle_senior_menu_digits("abc", "+13055550100", "2")
        ->  "Scam Shield is now canceled..." and Ana gets "Rosa turned Scam Shield off"
        handle_senior_menu_digits("abc", "+13055550100", "1")
        ->  "OK. Scam Shield stays on..."
    """
    response = VoiceResponse()
    enrollment = storage.get_enrollment(enrollment_id)
    if (
        enrollment is None
        or enrollment["status"] not in ("active", "paused")
        or normalize_phone(from_phone or "") != enrollment["senior_phone"]
    ):
        response.hangup()
        return str(response)

    language = enrollment["senior_language"]
    voice = spoken_language(language)

    if digits == "2":
        # The same as texting STOP: the senior said no, so the family can't
        # turn it back on, and can't ask again for 30 days.
        storage.set_enrollment_status(enrollment_id, "revoked", answered=True)
        tell_family(enrollment, "family_told_off")
        response.say(
            message("consent_call_canceled", language, family_name=enrollment["family_name"]),
            language=voice,
        )
    elif digits == "1":
        response.say(message("consent_call_kept", language), language=voice)
    else:
        response.redirect(
            public_url(f"/twilio/senior-menu?enrollment_id={enrollment_id}&attempt=2")
        )
        return str(response)

    response.hangup()
    return str(response)


def clean_reply(body: str) -> str:
    """
    Simplify a text reply so we can match it against our answer words.

    Lowercases it, removes accents (so "Sí" becomes "si"), and keeps only the
    first word, without punctuation.

    Examples:
        clean_reply("Yes!")          ->  "yes"
        clean_reply("Sí, claro")     ->  "si"
        clean_reply("   ")           ->  ""
    """
    without_accents = unicodedata.normalize("NFKD", body or "")
    without_accents = "".join(c for c in without_accents if not unicodedata.combining(c))
    words = re.findall(r"[a-z]+", without_accents.lower())
    return words[0] if words else ""


def read_answer(body: str) -> str:
    """
    Work out what the senior meant by their reply.

    Output: "yes", "no", "stop", or "unclear"

    Examples:
        read_answer("YES")       ->  "yes"
        read_answer("Si")        ->  "yes"
        read_answer("no thanks") ->  "no"
        read_answer("STOP")      ->  "stop"
        read_answer("who is this?") -> "unclear"
    """
    word = clean_reply(body)
    if word in YES_WORDS:
        return "yes"
    if word in NO_WORDS:
        return "no"
    if word in STOP_WORDS:
        return "stop"
    return "unclear"


def handle_senior_reply(from_phone: str, body: str) -> str | None:
    """
    Act on a text a senior sent to our Twilio number.

    Twilio sends every text our number receives to main.py, which hands it
    here. The reply only counts because it came FROM the senior's phone.

    Input:  from_phone — who sent the text (Twilio gives E.164)
            body       — what the text says
    Output: the text to send back to the senior, or None to stay quiet
            (we don't answer numbers that never signed up)

    Examples:
        Rosa is pending and replies "Sí"   ->  "Gracias, Rosa. Scam Shield ahora protege..."
                                               (and Ana gets "Rosa said YES")
        Rosa is active and replies "STOP"  ->  "Scam Shield está apagado..."
        a stranger texts "hi"              ->  None
    """
    phone = normalize_phone(from_phone or "")
    if phone is None:
        return None

    enrollments = expire_old_requests(storage.find_enrollments_for_senior(phone))
    answer = read_answer(body)

    # STOP turns off everything for this senior, whatever state it's in.
    if answer == "stop":
        turned_off = [e for e in enrollments if e["status"] in ("pending", "active", "paused")]
        if not turned_off:
            return None
        for enrollment in turned_off:
            storage.set_enrollment_status(enrollment["id"], "revoked", answered=True)
            if enrollment["status"] in ("active", "paused"):
                tell_family(enrollment, "family_told_off")
        return message("consent_revoked", turned_off[0]["senior_language"])

    pending = [e for e in enrollments if e["status"] == "pending"]
    if not pending:
        return None
    enrollment = pending[0]
    language = enrollment["senior_language"]

    if answer == "yes":
        storage.set_enrollment_status(enrollment["id"], "active", answered=True)
        tell_family(enrollment, "family_told_yes")
        return message("consent_yes", language, senior_name=enrollment["senior_name"])

    if answer == "no":
        storage.set_enrollment_status(enrollment["id"], "declined", answered=True)
        tell_family(enrollment, "family_told_no")
        return message("consent_no", language)

    return message("consent_unclear", language)


def tell_family(enrollment: dict, message_key: str) -> None:
    """
    Text the family member what the senior decided, in the family's language.

    Example:
        tell_family(rosa_enrollment, "family_told_yes")
        ->  Ana gets "Scam Shield: Rosa said YES. Their calls are now protected."
    """
    send_sms(
        enrollment["family_phone"],
        message(
            message_key,
            enrollment["family_language"],
            senior_name=enrollment["senior_name"],
        ),
    )


def get_enrollment_status(enrollment_id: str) -> dict | None:
    """
    Look up an enrollment for the dashboard, marking it expired if it timed out.

    Example:
        get_enrollment_status("abc")  ->  {"status": "active", ...}
    """
    enrollment = storage.get_enrollment(enrollment_id)
    if enrollment is None:
        return None
    expire_old_requests([enrollment])
    return public_view(enrollment)


def public_view(enrollment: dict) -> dict:
    """
    The parts of an enrollment that are safe to show on the dashboard,
    including what the family needs to finish setting up the senior's phone.

    We hide most of each phone number, so a leaked dashboard link doesn't
    give away the family's numbers.

    Example:
        public_view(rosa)  ->  {"id": "abc", "senior_name": "Rosa",
                                "senior_phone": "•••-•••-0100", "relationship": "grandma",
                                "status": "pending",
                                "phone_type": "cell", "ask_by": "text", "setup": {...}}
    """
    return {
        "id": enrollment["id"],
        "senior_name": enrollment["senior_name"],
        "senior_phone": mask_phone(enrollment["senior_phone"]),
        "family_name": enrollment["family_name"],
        "family_phone": mask_phone(enrollment["family_phone"]),
        # Sign-ups from before we asked have no relationship saved.
        "relationship": enrollment.get("relationship") or "other",
        "status": enrollment["status"],
        "phone_type": enrollment["phone_type"],
        "ask_by": how_we_asked(enrollment),
        "setup": setup_details(enrollment),
    }


def setup_details(enrollment: dict) -> dict:
    """
    What the family needs to finish setup once the senior says YES.

    Every senior's number forwards to our Scam Shield number. Then:
      - cell phone: the senior's phone runs our calling app (the app_link page)
      - landline:  the senior's phone plugs into an adapter that signs in to
                   our SIP domain with this username

    Example:
        setup_details(rosa)  ->  {"forward_to": "+15555550150",
                                  "app_link": "http://.../phone/Xy7..."}
    """
    settings = get_settings()
    details = {"forward_to": settings.twilio_phone_number}
    if enrollment["phone_type"] == "landline":
        details["adapter_username"] = enrollment["device_id"]
        details["adapter_domain"] = settings.twilio_sip_domain
    else:
        details["app_link"] = public_url(f"/phone/{enrollment['device_key']}")
    return details
