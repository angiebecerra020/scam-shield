"""
test_languages.py

Day one check for tracker task T6. Can Nemotron catch a scam call in Spanish,
and explain it in Spanish?

How it fits in: lots of older adults in Florida speak Spanish, so Scam Shield
has to work for them too. This sends a scam (a fake grandson who needs bail
money in gift cards) to the detector (app/detector.py) and prints what comes
back.

Run it from the project folder:
    python scripts/test_languages.py
"""

import sys
import time
from pathlib import Path

# When you run "python scripts/test_languages.py", Python can only see the
# scripts/ folder. This line lets it see the whole project, so "from app ..." works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import find_missing_settings, get_settings  # noqa: E402
from app.detector import score_call  # noqa: E402

# The same grandparent scam, written in each language.
# Each one is: (language code, the call)
SCAM_CALLS = {
    "Spanish": (
        "es",
        "Caller: ¿Abuela? Soy yo, tu nieto Daniel.\n"
        "Senior: ¿Daniel? Suenas diferente.\n"
        "Caller: Estoy resfriado. Abuela, tuve un accidente y la policía me arrestó. "
        "Necesito dinero para la fianza hoy.\n"
        "Caller: Por favor no le digas nada a mi mamá. ¿Puedes comprar 2,000 dólares "
        "en tarjetas de regalo y leerme los números?",
    ),
}


def report(passed: bool, check: str, detail: str = "") -> bool:
    """
    Prints one PASS or FAIL line and hands the result back.

    Input:  passed, whether the check passed
            check, what we checked
            detail, any extra info (shown in brackets)
    Output: the same True or False

    Example:
        report(True, "Caught the scam in Spanish") prints "PASS  Caught the scam in Spanish"
    """
    label = "PASS" if passed else "FAIL"
    line = f"{label}  {check}"
    if detail:
        line += f"  ({detail})"
    print(line)
    return passed


def check_language(name: str, code: str, call: str) -> bool:
    """
    Sends one scam call to the detector and prints what it says.

    Input:  name, the language's name, like "Spanish"
            code, the language code, like "es"
            call, the scam call written in that language
    Output: True if Nemotron called it a likely scam

    Example:
        check_language("Spanish", "es", "Caller: ¿Abuela? ...") prints the
        score, the reasons in Spanish, and the family alert in Spanish
    """
    started = time.perf_counter()
    result = score_call(call, code)
    seconds = time.perf_counter() - started

    caught = report(
        result["verdict"] == "likely_scam",
        f"Caught the scam in {name}",
        f"score {result['risk_score']}, {seconds:.1f}s",
    )
    print(f"      Who the caller says they are: {result['claimed_identity']}")
    print("      Reasons:")
    for reason in result["reasons"]:
        print(f"        * {reason}")
    print(f"      Family alert: {result['family_alert_message']}\n")
    return caught


def main() -> int:
    """
    Runs the check for every language and prints the overall result.

    Input:  nothing
    Output: 0 if every language passed and 1 if any failed

    Example:
        Running python scripts/test_languages.py ends with
        "RESULT: PASS. Nemotron catches scams in Spanish."
    """
    print("Day one check T6: scam calls in Spanish\n")
    missing = find_missing_settings(get_settings(), ["NEBIUS_API_KEY"])
    if missing:
        report(False, "Nebius key in .env")
        print("\nAdd your Nebius key to .env, then run this again.")
        return 1

    all_passed = True
    for name, (code, call) in SCAM_CALLS.items():
        if not check_language(name, code, call):
            all_passed = False

    if all_passed:
        print("RESULT: PASS. Nemotron catches scams in Spanish.")
        return 0
    print("RESULT: FAIL. Check the lines above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
