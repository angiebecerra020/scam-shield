"""
demo_mode.py — Plays a scripted phone call as if it were happening live.

How it fits in: this is our BACKUP DEMO, and it's what judges will click. It
reads call scripts from data/test_scripts/ and feeds them into the app one
line at a time, just like a real call being transcribed. The detector
(detector.py), alerts and dashboard can't tell the difference.

Why we need it:
  - Florida law says everyone on a call must agree before it's recorded, so
    we never use real calls. Scripted calls are always safe to show.
  - Judges test our website in December. They can't phone us, but they can
    press "Play".

What's here now: loading the scripts and turning them into transcript text
(the detector's accuracy test uses this too).
Coming soon: playing a script line by line on the dashboard.

Turned on with DEMO_MODE=true in .env.
"""

import json
from pathlib import Path

from app.config import PROJECT_ROOT

SCRIPTS_DIR = PROJECT_ROOT / "data" / "test_scripts"

# Every script file must have these fields (see data/test_scripts/README.md).
REQUIRED_FIELDS = ("id", "title", "language", "expected", "lines")

# How each speaker is labeled in the transcript we send to Nemotron.
SPEAKER_LABELS = {"caller": "Caller", "senior": "Senior"}


def load_script(path: Path) -> dict:
    """
    Read one call script file and check that it has everything we need.

    Input:  path — a .json file in data/test_scripts/
    Output: the script as a dict
    Raises: ValueError with a clear message if something is missing or
            wrong, so a typo in a script is easy to find

    Example:
        load_script(SCRIPTS_DIR / "scam_grandparent_en.json")
        ->  {"id": "scam_grandparent_en", "expected": "scam", "lines": [...], ...}
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
    Load every call script in data/test_scripts/, sorted by file name.

    Input:  nothing
    Output: a list of script dicts

    Example:
        [script["id"] for script in list_scripts()]
        ->  ["normal_granddaughter_es", "normal_pharmacy_en",
             "scam_grandparent_en", "scam_ssn_es"]
    """
    scripts = []
    for path in sorted(SCRIPTS_DIR.glob("*.json")):
        scripts.append(load_script(path))
    return scripts


def transcript_text(script: dict, up_to_line: int | None = None) -> str:
    """
    Turn a script into transcript text, in the same format a live call produces.

    Input:  script     — from load_script()
            up_to_line — only include the first N lines (to replay a call
                         "as it happens"); None means the whole call
    Output: one line per turn, like "Caller: Grandma? It's me, Danny."

    Example:
        transcript_text(grandparent_script, up_to_line=2)
        ->  "Caller: Grandma? It's me, Danny.\\nSenior: Danny? You sound different, honey."
    """
    lines = script["lines"]
    if up_to_line is not None:
        lines = lines[:up_to_line]

    turns = []
    for line in lines:
        label = SPEAKER_LABELS[line["speaker"]]
        turns.append(f"{label}: {line['text']}")
    return "\n".join(turns)
