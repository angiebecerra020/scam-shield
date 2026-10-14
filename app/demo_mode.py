"""
demo_mode.py

This plays a scripted phone call like it's happening live.

How it fits in: this is our backup demo, and it's also what the judges will
click on. It reads the call scripts in data/test_scripts/ and feeds them into
the app one line at a time, the same way a real call gets transcribed. The
detector (detector.py), the alerts and the dashboard can't tell the difference.

Why we need it:
  - Florida law says everyone on a call has to agree before it's recorded, so
    we never use real calls. Scripted calls are always safe to show.
  - The judges test our website in December. They can't call us, but they
    can press "Play".

What's in here right now: loading the scripts and turning them into
transcript text (the detector's accuracy test uses this too).
Coming soon: playing a script line by line on the dashboard.

Demo mode is on when DEMO_MODE=true in .env.
"""

import json
from pathlib import Path

from app.config import PROJECT_ROOT

SCRIPTS_DIR = PROJECT_ROOT / "data" / "test_scripts"

# Every script file needs these fields (check out data/test_scripts/README.md).
REQUIRED_FIELDS = ("id", "title", "language", "expected", "lines")

# How we label each speaker in the transcript we send to Nemotron.
SPEAKER_LABELS = {"caller": "Caller", "senior": "Senior"}


def load_script(path: Path) -> dict:
    """
    Reads one call script file and makes sure it has everything we need.

    Input:  path, a .json file in data/test_scripts/
    Output: the script as a dict
    Raises: ValueError with a clear message if something's missing or wrong,
            so if there's a typo in a script it's easy to find

    Example:
        load_script(SCRIPTS_DIR / "scam_grandparent_en.json") gives you a dict
        with the id "scam_grandparent_en", expected "scam", and all the lines
    """
    with open(path, encoding="utf-8") as file:
        script = json.load(file)

    for field in REQUIRED_FIELDS:
        if field not in script:
            raise ValueError(f"{path.name} is missing the '{field}' field.")

    if script["expected"] not in ("scam", "normal"):
        raise ValueError(f'{path.name}: "expected" must be "scam" or "normal".')

    for number, line in enumerate(script["lines"], start=1):
        if line.get("speaker") not in SPEAKER_LABELS or not line.get("text"):
            raise ValueError(
                f"{path.name}: line {number} needs a speaker (caller or senior) and some text."
            )
    return script


def list_scripts() -> list[dict]:
    """
    Loads every call script in data/test_scripts/, sorted by file name.

    Input:  nothing
    Output: a list of scripts

    Example:
        Right now the ids you get back are normal_granddaughter_es,
        normal_pharmacy_en, scam_grandparent_en and scam_ssn_es
    """
    scripts = []
    for path in sorted(SCRIPTS_DIR.glob("*.json")):
        scripts.append(load_script(path))
    return scripts


def transcript_text(script: dict, up_to_line: int | None = None) -> str:
    """
    Turns a script into transcript text, the same way a live call looks.

    Input:  script, from load_script()
            up_to_line, only use the first few lines (so we can replay a call
            like it's happening). Leave it as None to get the whole call.
    Output: one line per turn, like "Caller: Grandma? It's me, Danny."

    Example:
        transcript_text(grandparent_script, up_to_line=2) gives you
        "Caller: Grandma? It's me, Danny.\\nSenior: Danny? You sound different, honey."
    """
    lines = script["lines"]
    if up_to_line is not None:
        lines = lines[:up_to_line]

    turns = []
    for line in lines:
        label = SPEAKER_LABELS[line["speaker"]]
        turns.append(f"{label}: {line['text']}")
    return "\n".join(turns)
