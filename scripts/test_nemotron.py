"""
test_nemotron.py

Day one check for tracker task T3. Can we reach NVIDIA Nemotron on Nebius
Token Factory, does it answer in our format, and is it fast enough for a
live call?

How it fits in: run this once your NEBIUS_API_KEY is in .env, before we build
anything else on top of Nemotron. Every check prints PASS or FAIL.

Run it from the project folder:
    python scripts/test_nemotron.py
"""

import json
import sys
import time
from pathlib import Path

# When you run "python scripts/test_nemotron.py", Python can only see the
# scripts/ folder. This line lets it see the whole project, so "from app ..." works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import find_missing_settings, get_settings  # noqa: E402
from app.detector import make_client, score_call  # noqa: E402

# Our goal for how long one Nemotron check can take during a live call.
SPEED_GOAL_SECONDS = 3.0

SAMPLE_SCAM_CALL = (
    "Caller: Grandma? It's me, Danny.\n"
    "Senior: Danny? You sound different.\n"
    "Caller: I have a cold. Grandma, I'm in trouble. I got arrested and I need bail money.\n"
    "Caller: Please don't tell Mom. Can you buy $2,000 in gift cards and read me the numbers?"
)


def report(passed: bool, check: str, detail: str = "") -> bool:
    """
    Prints one PASS or FAIL line and hands the result back.

    Input:  passed, whether the check passed
            check, what we checked
            detail, any extra info (shown in brackets)
    Output: the same True or False, so we can keep track of it

    Example:
        report(True, "Settings in .env") prints "PASS  Settings in .env"
    """
    label = "PASS" if passed else "FAIL"
    line = f"{label}  {check}"
    if detail:
        line += f"  ({detail})"
    print(line)
    return passed


def check_settings() -> bool:
    """
    Makes sure the three Nebius settings are filled in, in .env.

    Input:  nothing
    Output: True if they're all there

    Example:
        If NEBIUS_API_KEY is blank, it prints
        "FAIL  Settings in .env  (missing: NEBIUS_API_KEY)"
    """
    missing = find_missing_settings(
        get_settings(), ["NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEMOTRON_MODEL"]
    )
    if missing:
        return report(False, "Settings in .env", "missing: " + ", ".join(missing))
    return report(True, "Settings in .env")


def check_model_available() -> bool:
    """
    Asks Nebius which models we can use, prints the Nemotron ones, and checks
    that the NEMOTRON_MODEL in .env is one of them.

    Input:  nothing
    Output: True if we connected and our model is on the list

    Example:
        It prints "PASS  NEMOTRON_MODEL is available  (nvidia/Nemotron-3_5-Lightning)"
    """
    wanted = get_settings().nemotron_model
    try:
        all_models = [model.id for model in make_client().models.list()]
    except Exception as error:
        # This is usually a wrong API key or no internet. We show why and keep going.
        return report(False, "Connect to Nebius", f"{type(error).__name__}: {error}")
    report(True, "Connect to Nebius", f"{len(all_models)} models available")

    print("      Nemotron models on your account:")
    for name in all_models:
        if "nemotron" in name.lower():
            marker = "   (this is the one in your .env)" if name == wanted else ""
            print(f"        {name}{marker}")
    return report(wanted in all_models, "NEMOTRON_MODEL is available", wanted)


def check_scam_scoring() -> bool:
    """
    Scores a sample grandparent scam twice and times both.

    The first request to any server is slower because it's opening the
    connection. So we go by the second one, since that's what happens during
    a real call.

    Input:  nothing
    Output: True if Nemotron answered in our format, caught the scam, and
            was fast enough

    Example:
        It prints "PASS  Caught the scam  (score 95)"
    """
    seconds = []
    result = None
    for _ in range(2):
        started = time.perf_counter()
        result = score_call(SAMPLE_SCAM_CALL, "en")
        seconds.append(time.perf_counter() - started)

    print("      Nemotron's answer:")
    pretty = json.dumps(result, indent=2, ensure_ascii=False)
    print("      " + pretty.replace("\n", "\n      "))

    answered = result["verdict"] != "unknown"
    report(answered, "Answered in our JSON format", "" if answered else result["reasons"][0])
    caught = report(
        result["verdict"] == "likely_scam", "Caught the scam", f"score {result['risk_score']}"
    )
    fast = report(
        seconds[1] < SPEED_GOAL_SECONDS,
        f"Under {SPEED_GOAL_SECONDS:.0f} seconds",
        f"first call {seconds[0]:.2f}s, second call {seconds[1]:.2f}s",
    )
    return answered and caught and fast


def main() -> int:
    """
    Runs every check and prints the overall result.

    Input:  nothing
    Output: 0 if everything passed and 1 if anything failed (that's the
            usual way command line tools report how it went)

    Example:
        Running python scripts/test_nemotron.py ends with
        "RESULT: PASS. Nemotron is ready."
    """
    print("Day one check T3: NVIDIA Nemotron on Nebius Token Factory\n")
    if not check_settings():
        print("\nAdd your Nebius API key to .env, then run this again.")
        return 1

    model_ok = check_model_available()
    scoring_ok = check_scam_scoring()

    if model_ok and scoring_ok:
        print("\nRESULT: PASS. Nemotron is ready.")
        return 0
    print("\nRESULT: FAIL. Check the lines above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
