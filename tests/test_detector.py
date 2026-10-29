"""
test_detector.py

Tests for the scam detector (app/detector.py).

How it fits in: there are two kinds of tests in here.
  1. Quick tests with a FAKE Nemotron. These check our own code, like reading
     the answer, fixing bad scores, and never crashing. No API key needed.
  2. The accuracy test. This one sends every script in data/test_scripts/ to
     the REAL Nemotron and prints a table showing how it did. It only runs
     when NEBIUS_API_KEY is in .env. To see the table, run:
         pytest tests/test_detector.py -s -k accuracy
"""

import time
from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError

from app import detector
from app.config import get_settings
from app.demo_mode import list_scripts, transcript_text

SCAM_CALL = "Caller: Grandma, I'm in jail. Buy gift cards and don't tell Mom."

GOOD_SCAM_ANSWER = """{
  "risk_score": 95,
  "verdict": "likely_scam",
  "reasons": ["Asks for gift cards", "Asks to keep it secret from Mom"],
  "claimed_identity": "grandson",
  "family_alert_message": "Your loved one may be on a scam call. Call her now."
}"""


class FakeNemotron:
    """
    A pretend version of the Nebius client that answers with whatever text we pick.

    It's shaped just like the real client (client.chat.completions.create),
    and it remembers every request so the tests can check what we sent.

    Example:
        fake = FakeNemotron(['{"risk_score": 90}'])
        detector.score_call("Caller: hi", client=fake)
    """

    def __init__(self, answers):
        # Each answer is either text to reply with, or an error to raise.
        self.answers = list(answers)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        """Acts like chat.completions.create() and replies with the next answer."""
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        message = SimpleNamespace(content=answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def not_supported_error() -> BadRequestError:
    """
    Makes the error Nebius sends when it doesn't support an option (an HTTP 400).

    Example:
        FakeNemotron([not_supported_error(), GOOD_SCAM_ANSWER])
    """
    request = httpx.Request("POST", "https://api.tokenfactory.nebius.com/v1/chat/completions")
    response = httpx.Response(400, request=request)
    return BadRequestError("response_format not supported", response=response, body=None)


# Part 1: quick tests with a fake Nemotron


def test_good_answer_comes_through_cleanly():
    """A normal scam answer should come back with every field filled in."""
    result = detector.score_call(SCAM_CALL, client=FakeNemotron([GOOD_SCAM_ANSWER]))

    assert result["risk_score"] == 95
    assert result["verdict"] == "likely_scam"
    assert result["reasons"] == ["Asks for gift cards", "Asks to keep it secret from Mom"]
    assert result["claimed_identity"] == "grandson"
    assert result["family_alert_message"].startswith("Your loved one")


def test_verdict_always_matches_the_score():
    """If the model says "safe" but scores it 95, we go with the score."""
    answer = '{"risk_score": 95, "verdict": "safe", "reasons": [], "claimed_identity": null, "family_alert_message": "Call her."}'

    result = detector.score_call(SCAM_CALL, client=FakeNemotron([answer]))

    assert result["verdict"] == "likely_scam"


def test_safe_call_never_alerts_the_family():
    """A low score should never come with a family alert, even if the model wrote one."""
    answer = '{"risk_score": 10, "verdict": "safe", "reasons": ["Just chatting"], "claimed_identity": "granddaughter Sofia", "family_alert_message": "Hello!"}'

    result = detector.score_call("Caller: Hi Grandma, it's Sofia!", client=FakeNemotron([answer]))

    assert result["verdict"] == "safe"
    assert result["family_alert_message"] is None


def test_scores_outside_0_to_100_are_fixed():
    """Scores like 140 or minus 5 get squeezed back into 0 to 100."""
    assert detector.clamp_score(140) == 100
    assert detector.clamp_score("-5") == 0
    assert detector.clamp_score("85") == 85
    assert detector.clamp_score("very high") is None


def test_long_family_alert_ends_on_a_full_sentence():
    """A long alert gets cut after a full sentence, never in the middle of a word."""
    long_alert = (
        "Your loved one may be on a scam call. The caller says he is her grandson and wants gift cards. "
        "Please call her right away and tell her not to buy anything, then call your son to check on him."
    )

    short = detector.shorten_alert(long_alert)

    assert len(short) <= detector.MAX_ALERT_LENGTH
    assert short.endswith(".")


def test_json_hidden_in_extra_text_is_still_found():
    """Thinking notes, chatty sentences and ```json fences shouldn't mess us up."""
    messy = "<think>gift cards... secrecy...</think>\nSure! ```json\n" + GOOD_SCAM_ANSWER + "\n```"

    result = detector.score_call(SCAM_CALL, client=FakeNemotron([messy]))

    assert result["risk_score"] == 95


def test_garbled_answer_gives_unknown_not_safe():
    """If we can't read the answer, the score is None (unknown), never 0 (safe)."""
    result = detector.score_call(SCAM_CALL, client=FakeNemotron(["I can't help with that."]))

    assert result["verdict"] == "unknown"
    assert result["risk_score"] is None


def test_connection_problem_never_crashes():
    """No internet? We get "unknown" back instead of a crash."""
    fake = FakeNemotron([ConnectionError("no internet")])

    result = detector.score_call(SCAM_CALL, client=fake)

    assert result["verdict"] == "unknown"
    assert "ConnectionError" in result["reasons"][0]


def test_empty_call_is_not_sent_to_nemotron():
    """No words yet means there's nothing to check, so we don't spend credits."""
    fake = FakeNemotron([])

    result = detector.score_call("   ", client=fake)

    assert result["verdict"] == "unknown"
    assert fake.requests == []


def test_falls_back_when_strict_format_is_not_supported():
    """If Nebius says no to the strict JSON schema, we try the next way of asking."""
    fake = FakeNemotron([not_supported_error(), GOOD_SCAM_ANSWER])

    result = detector.score_call(SCAM_CALL, client=fake)

    assert result["risk_score"] == 95
    assert fake.requests[0]["response_format"]["type"] == "json_schema"
    assert fake.requests[1]["response_format"]["type"] == "json_object"


def test_request_asks_for_the_right_language_and_marks_the_transcript():
    """The transcript goes between tags, and we ask for the family's language."""
    fake = FakeNemotron([GOOD_SCAM_ANSWER])

    detector.score_call(SCAM_CALL, language="es", client=fake)

    user_message = fake.requests[0]["messages"][1]["content"]
    assert "Spanish" in user_message
    assert "<call_transcript>" in user_message
    assert SCAM_CALL in user_message
    # Thinking is switched off, so answers come back fast during a live call.
    assert fake.requests[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_every_language_uses_nemotron_model(monkeypatch):
    """English and Spanish calls both go to NEMOTRON_MODEL from .env."""
    monkeypatch.setenv("NEMOTRON_MODEL", "fast-model")
    fake = FakeNemotron([GOOD_SCAM_ANSWER, GOOD_SCAM_ANSWER])

    detector.score_call(SCAM_CALL, language="en", client=fake)
    detector.score_call(SCAM_CALL, language="es", client=fake)

    assert [request["model"] for request in fake.requests] == ["fast-model", "fast-model"]


def test_sample_scripts_load_and_turn_into_transcripts():
    """Every script file is valid, and we have both scams and normal calls."""
    scripts = list_scripts()

    assert len(scripts) >= 4
    assert {script["expected"] for script in scripts} == {"scam", "normal"}
    grandparent = next(s for s in scripts if s["id"] == "scam_grandparent_en")
    assert transcript_text(grandparent, up_to_line=1) == "Caller: Grandma? It's me, Danny."


# Part 2: the accuracy test with the REAL Nemotron


def is_correct(expected: str, result: dict) -> bool:
    """
    Did the detector get this script right?

    A scam counts as caught when it's at least "suspicious" (a score of 40 or more).
    A normal call only counts as right when it's "safe" (under 40).

    Examples:
        is_correct("scam", {"verdict": "likely_scam"}) gives you True
        is_correct("normal", {"verdict": "suspicious"}) gives you False
    """
    if expected == "scam":
        return result["verdict"] in ("suspicious", "likely_scam")
    return result["verdict"] == "safe"


def print_accuracy_table(rows: list[dict]) -> None:
    """
    Prints the results as a table in the terminal.

    Example of what you see:
        Script                   Lang  Expected  Score  Verdict       Time  Right?
        scam_grandparent_en      en    scam         95  likely_scam   0.9s  yes
    """
    print()
    print(f"{'Script':<30}{'Lang':<6}{'Expected':<10}{'Score':>5}  {'Verdict':<13}{'Time':>5}  Right?")
    for row in rows:
        score = "-" if row["score"] is None else row["score"]
        print(
            f"{row['id']:<30}{row['language']:<6}{row['expected']:<10}{score:>5}  "
            f"{row['verdict']:<13}{row['seconds']:>4.1f}s  {'yes' if row['correct'] else 'NO'}"
        )
    correct = sum(1 for row in rows if row["correct"])
    print(f"\nAccuracy: {correct} out of {len(rows)} ({correct / len(rows):.0%})\n")


@pytest.mark.skipif(
    not get_settings().nebius_api_key,
    reason="Add NEBIUS_API_KEY to .env to run the real accuracy test",
)
def test_accuracy_on_all_scripts():
    """Runs every sample script through the real Nemotron and prints a table."""
    rows = []
    for script in list_scripts():
        started = time.perf_counter()
        result = detector.score_call(transcript_text(script), script["language"])
        rows.append(
            {
                "id": script["id"],
                "language": script["language"],
                "expected": script["expected"],
                "score": result["risk_score"],
                "verdict": result["verdict"],
                "seconds": time.perf_counter() - started,
                "correct": is_correct(script["expected"], result),
            }
        )

    print_accuracy_table(rows)
    correct = sum(1 for row in rows if row["correct"])
    assert correct / len(rows) >= 0.75, "The detector got fewer than 75% of the calls right"
