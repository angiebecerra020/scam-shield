"""
phone_numbers.py — Cleans up phone numbers so they all look the same.

How it fits in: people type phone numbers many ways ("(305) 555-0100",
"305.555.0100", "+1 305 555 0100"), but Twilio always writes them as
"+13055550100" (the E.164 format). If we save every number in that one format,
a text reply from Twilio matches the number the family typed in the sign-up form.
"""

import re


def normalize_phone(raw: str) -> str | None:
    """
    Turn a phone number typed by a person into Twilio's +1XXXXXXXXXX format.

    Input:  raw — a phone number as someone typed it
    Output: the number in E.164 format, or None if it doesn't look like a
            phone number.

    We assume US numbers when there's no "+" (we're a US hackathon project).
    A number that starts with "+" keeps its country code.

    Examples:
        normalize_phone("(305) 555-0100")   ->  "+13055550100"
        normalize_phone("1-305-555-0100")   ->  "+13055550100"
        normalize_phone("+44 20 7946 0958") ->  "+442079460958"
        normalize_phone("hello")            ->  None
    """
    if raw is None:
        return None

    text = raw.strip()
    digits = re.sub(r"\D", "", text)

    if text.startswith("+"):
        # International numbers are 8 to 15 digits long, country code included.
        if 8 <= len(digits) <= 15:
            return "+" + digits
        return None

    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


def missing_area_code(raw: str) -> bool:
    """
    Did someone type a US phone number but leave off the area code?

    A US number without its area code is 7 digits ("555-0100"). We can't
    guess the area code, so the sign-up form asks them to add it.

    Input:  raw — a phone number as someone typed it
    Output: True if it looks like a 7-digit number with no area code

    Examples:
        missing_area_code("555-0100")        ->  True
        missing_area_code("(305) 555-0100")  ->  False
        missing_area_code("+44 20 7946 0958") ->  False
    """
    text = (raw or "").strip()
    return not text.startswith("+") and len(re.sub(r"\D", "", text)) == 7


def mask_phone(phone: str) -> str:
    """
    Hide most of a phone number, so the dashboard never shows the whole thing.

    Input:  phone — a number in E.164 format
    Output: the same number with only the last 4 digits showing

    Example:
        mask_phone("+13055550100")  ->  "•••-•••-0100"
    """
    return "•••-•••-" + phone[-4:]
