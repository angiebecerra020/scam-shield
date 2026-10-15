"""
test_tavily.py

Day one check for tracker task T4. Does our Tavily key work, and do the
results look useful for a family trying to figure out if a call is a scam?

How it fits in: this runs the same searches the app will run during a call
(app/research.py). It looks up 3 phone numbers and 1 scam story and prints
what it found. Every check prints PASS or FAIL, plus a note about quality.

About the 3 numbers: they're REAL government numbers (Social Security, the
IRS and Medicare). Scammers love to fake these on caller ID, so a good search
should warn us about that.

Run it from the project folder:
    python scripts/test_tavily.py
"""

import sys
import time
from pathlib import Path

# When you run "python scripts/test_tavily.py", Python can only see the
# scripts/ folder. This line lets it see the whole project, so "from app ..." works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import find_missing_settings, get_settings  # noqa: E402
from app.research import check_caller_number, find_scam_warnings  # noqa: E402

PHONE_NUMBERS = {
    "Social Security": "+18007721213",
    "IRS": "+18008291040",
    "Medicare": "+18006334227",
}

SCAM_STORY = "grandparent scam grandson in jail needs gift cards for bail"

# Sites we trust most for scam warnings.
TRUSTED_SITES = (".gov", "aarp.org", "bbb.org", "consumerreports.org")


def report(passed: bool, check: str, detail: str = "") -> bool:
    """
    Prints one PASS or FAIL line and hands the result back.

    Input:  passed, whether the check passed
            check, what we checked
            detail, any extra info (shown in brackets)
    Output: the same True or False

    Example:
        report(True, "Tavily key in .env") prints "PASS  Tavily key in .env"
    """
    label = "PASS" if passed else "FAIL"
    line = f"{label}  {check}"
    if detail:
        line += f"  ({detail})"
    print(line)
    return passed


def is_trusted(url: str) -> bool:
    """
    Checks if a link comes from a site we trust for scam warnings.

    Input:  url, a web address
    Output: True or False

    Example:
        is_trusted("https://www.fcc.gov/consumers/...") gives you True
    """
    for site in TRUSTED_SITES:
        if site in url:
            return True
    return False


def count_trusted(result: dict) -> int:
    """
    Counts how many links in one search come from trusted sites.

    Example:
        A search with one fcc.gov link and one blog gives you 1
    """
    total = 0
    for source in result["sources"]:
        if is_trusted(source["url"]):
            total += 1
    return total


def show_sources(result: dict) -> None:
    """
    Prints the links from one search, marking trusted sites and scam mentions.

    Input:  result, from research.run_search() or check_caller_number()
    Output: nothing, it just prints

    Example of what you see:
        * [trusted] [scam] Grandparent Scams Get More Sophisticated
          https://www.fcc.gov/...
    """
    if result["summary"]:
        print(f"      Tavily's summary: {result['summary'][:200]}")
    for source in result["sources"]:
        tags = ""
        if is_trusted(source["url"]):
            tags += "[trusted] "
        if source["mentions_scam"]:
            tags += "[scam] "
        print(f"      * {tags}{source['title']}")
        print(f"        {source['url']}")


def main() -> int:
    """
    Runs every search and prints the overall result.

    Input:  nothing
    Output: 0 if everything passed and 1 if anything failed

    Example:
        Running python scripts/test_tavily.py ends with "RESULT: PASS. Tavily is ready."
    """
    print("Day one check T4: Tavily web search\n")
    missing = find_missing_settings(get_settings(), ["TAVILY_API_KEY"])
    if not report(not missing, "Tavily key in .env"):
        print("\nAdd your Tavily key to .env, then run this again.")
        return 1

    all_passed = True
    scam_warnings = 0
    trusted_links = 0
    total_links = 0

    for name, phone in PHONE_NUMBERS.items():
        started = time.perf_counter()
        result = check_caller_number(phone)
        seconds = time.perf_counter() - started
        found = len(result["sources"]) > 0
        detail = f"{len(result['sources'])} links, {seconds:.1f}s"
        if not report(found, f"Number check: {name}", detail):
            all_passed = False
        show_sources(result)
        if result["reported_as_scam"]:
            scam_warnings += 1
        total_links += len(result["sources"])
        trusted_links += count_trusted(result)

    started = time.perf_counter()
    story = find_scam_warnings(SCAM_STORY)
    seconds = time.perf_counter() - started
    found = len(story["sources"]) > 0
    if not report(found, "Scam story search", f"{len(story['sources'])} links, {seconds:.1f}s"):
        all_passed = False
    show_sources(story)
    total_links += len(story["sources"])
    trusted_links += count_trusted(story)

    print("\nQuality note:")
    print(f"  {scam_warnings} out of {len(PHONE_NUMBERS)} number checks warned about scams.")
    print(f"  {trusted_links} out of {total_links} links came from trusted sites (.gov, AARP, BBB...).")

    if all_passed:
        print("\nRESULT: PASS. Tavily is ready.")
        return 0
    print("\nRESULT: FAIL. Check the lines above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
