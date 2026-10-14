"""
test_detector.py — Tests for the scam detector (app/detector.py).

How it fits in: two kinds of tests live here.
  1. Quick tests with a FAKE Nemotron. They check our own code: reading the
     answer, fixing bad scores, and never crashing. No API key needed.
  2. The accuracy test. It sends every script in data/test_scripts/ to the
     REAL Nemotron and prints a table of how it did. It only runs when
     NEBIUS_API_KEY is in .env. To see the table, run:
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
    A stand-in for the Nebius client that answers with text we choose.

    It copies the shape of the real client (client.chat.completions.create)
    and remembers every request, so tests can check what we sent.

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
        """Pretend to be chat.completions.create(): reply with the next answer."""
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        message = SimpleNamespace(content=answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def not_supported_error() -> BadRequestError:
    """
    Build the error Nebius sends when it doesn't support an option (HTTP 400).

    Example:
        FakeNemotron([not_supported_error(), GOOD_SCAM_ANSWER])
    """
    request = httpx.Request("POST", "https://api.tokenfactory.nebius.com/v1/chat/completions")
    response = httpx.Response(400, request=request)
    return BadRequestError("response_format not supported", response=response, body=None)


# ---------------------------------------------------------------------------
# 1. Quick tests with a fake Nemotron
# ---------------------------------------------------------------------------


def test_good_answer_comes_through_cleanly():
    """A normal scam answer should come back with every field filled in."""
    result = detector.score_call(SCAM_CALL, client=FakeNemotron([GOOD_SCAM_ANSWER]))

    assert result["risk_score"] == 95
    assert result["verdict"] == "likely_scam"
    assert result["reasons"] == ["Asks for gift cards", "Asks to keep it secret from Mom"]
    assert result["claimed_identity"] == "grandson"
    assert result["family_alert_message"].startswith("Your loved one")


def test_verdict_always_matches_the_score():
    """If the model says "safe" but scores 95, we trust the score."""
    answer = '{"risk_score": 95, "verdict": "safe", "reasons": [], "claimed_identity": null, "family_alert_message": "Call her."}'

    result = detector.score_call(SCAM_CALL, client=FakeNemotron([answer]))

    assert result["verdict"] == "likely_scam"


def test_safe_call_never_alerts_the_family():
    """A low score should never carry a family alert, even if the model wrote one."""
    answer = '{"risk_score": 10, "verdict": "safe", "reasons": ["Just chatting"], "claimed_identity": "granddaughter Sofia", "family_alert_message": "Hello!"}'

    result = detector.score_call("Caller: Hi Grandma, it's Sofia!", client=FakeNemotron([answer]))

    assert result["verdict"] == "safe"
    assert result["family_alert_message"] is None


def test_scores_outside_0_to_100_are_fixed():
    """Scores like 140 or "-5" get squeezed into 0-100."""
    assert detector.clamp_score(140) == 100
    assert detector.clamp_score("-5") == 0
    assert detector.clamp_score("85") == 85
    assert detector.clamp_score("very high") is None


def test_json_hidden_in_extra_text_is_still_found():
    """Thinking notes, chatty sentences and ```json fences shouldn't break us."""
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
    """No words yet means nothing to check, and no credits spent."""
    fake = FakeNemotron([])

    result = detector.score_call("   ", client=fake)

    assert result["verdict"] == "unknown"
    assert fake.requests == []


def test_falls_back_when_strict_format_is_not_supported():
    """If Nebius rejects the strict JSON schema, we try the next way of asking."""
    fake = FakeNemotron([not_supported_error(), GOOD_SCAM_ANSWER])

    result = detector.score_call(SCAM_CALL, client=fake)

    assert result["risk_score"] == 95
    assert fake.requests[0]["response_format"]["type"] == "json_schema"
    assert fake.requests[1]["response_format"]["type"] == "json_object"


def test_request_asks_for_the_right_language_and_marks_the_transcript():
    """The transcript goes between markers, and we ask for the family's language."""
    fake = FakeNemotron([GOOD_SCAM_ANSWER])

    detector.score_call(SCAM_CALL, language="es", client=fake)

    user_message = fake.requests[0]["messages"][1]["content"]
    assert "Spanish" in user_message
    assert "<call_transcript>" in user_message
    assert SCAM_CALL in user_message
    # Thinking is switched off, so answers come back fast during a live call.
    assert fake.requests[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_sample_scripts_load_and_turn_into_transcripts():
    """Every script file is valid, and we have both scams and normal calls."""
    scripts = list_scripts()

    assert len(scripts) >= 4
    assert {script["expected"] for script in scripts} == {"scam", "normal"}
    grandparent = next(s for s in scripts if s["id"] == "scam_grandparent_en")
    assert transcript_text(grandparent, up_to_line=1) == "Caller: Grandma? It's me, Danny."


# ---------------------------------------------------------------------------
# 2. Accuracy test with the REAL Nemotron
# ---------------------------------------------------------------------------


def is_correct(expected: str, result: dict) -> bool:
    """
    Did the detector get this script right?

    A scam counts as caught when it's at least "suspicious" (score 40+).
    A normal call counts as right only when it's "safe" (under 40).

    Example:
        is_correct("scam", {"verdict": "likely_scam"})  ->  True
        is_correct("normal", {"verdict": "suspicious"}) ->  False
    """
    if expected == "scam":
        return result["verdict"] in ("suspicious", "likely_scam")
    return result["verdict"] == "safe"


def print_accuracy_table(rows: list[dict]) -> None:
    """
    Print the results as a table in the terminal.

    Example output:
        Script                   Lang  Expected  Score  Verdict       Time  Right?
        scam_grandparent_en      en    scam         95  likely_scam   0.9s  yes
    """
    print()
    print(f"{'Script':<25}{'Lang':<6}{'Expected':<10}{'Score':>5}  {'Verdict':<13}{'Time':>5}  Right?")
    print("-" * 75)
    for row in rows:
        score = "-" if row["score"] is None else row["score"]
        print(
            f"{row['id']:<25}{row['language']:<6}{row['expected']:<10}{score:>5}  "
            f"{row['verdict']:<13}{row['seconds']:>4.1f}s  {'yes' if row['correct'] else 'NO'}"
        )
    correct = sum(1 for row in rows if row["correct"])
    print("-" * 75)
    print(f"Accuracy: {correct}/{len(rows)} = {correct / len(rows):.0%}\n")


@pytest.mark.skipif(
    not get_settings().nebius_api_key,
    reason="Add NEBIUS_API_KEY to .env to run the real accuracy test",
)
def test_accuracy_on_all_scripts():
    """Run every sample script through the real Nemotron and print a table."""
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
    assert correct / len(rows) >= 0.75, "Detector got fewer than 3 out of 4 calls right"
