"""
test_screen_languages.py

Tests for showing the screens in English or Spanish (static/strings.js and
static/i18n.js).

How it fits in: the browser does the translating, so here we check the word
lists themselves: every key is in BOTH languages with the same blanks, every
key a page or script uses really exists, and every page loads the word list
before its own scripts. Run them with: pytest tests/test_screen_languages.py
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

STATIC = Path(__file__).resolve().parent.parent / "static"
STRINGS_JS = (STATIC / "strings.js").read_text()

# Every page, and the script that runs it.
PAGES = {
    "/": "/static/nav.js",
    "/login": "/static/login.js",
    "/dashboard": "/static/app.js",
    "/setup/some-id": "/static/setup.js",
    "/profile": "/static/profile.js",
    "/join/some-token": "/static/join.js",
    "/phone/some-key": "/static/phone.js",
}


def words_for(language: str) -> dict[str, str]:
    """
    Reads one language's words out of strings.js.

    Example:
        words_for("es")["nav.home"] gives you "Inicio"
    """
    # The "es" list starts at "  es: {", and the server messages after it.
    english, rest = STRINGS_JS.split("\n  es: {", 1)
    spanish = rest.split("const SERVER_MESSAGES_ES", 1)[0]
    block = english if language == "en" else spanish
    # Each entry looks like "key": "words" (sometimes with the words on the next line).
    pairs = re.findall(r'"([a-z]+\.[A-Za-z0-9]+)":\s*"((?:[^"\\]|\\.)*)"', block)
    return dict(pairs)


def blanks(words: str) -> set[str]:
    """The {blanks} in some words. Example: blanks("Hi {name}") gives you {"name"}"""
    return set(re.findall(r"\{(\w+)\}", words))


def test_every_key_is_in_english_and_spanish():
    """Adding words in one language and forgetting the other fails here."""
    assert set(words_for("en")) == set(words_for("es"))


def test_spanish_has_the_same_blanks_as_english():
    """If English says {name}, the Spanish must too, or the name goes missing."""
    english = words_for("en")
    spanish = words_for("es")
    for key, words in english.items():
        assert blanks(spanish[key]) == blanks(words), key


def test_every_key_the_pages_use_exists():
    """Every data-text="..." in the HTML and every t("...") in our scripts has words."""
    known = set(words_for("en"))
    used = set()
    for page in STATIC.glob("*.html"):
        used |= set(re.findall(r'data-text(?:-aria-label)?="([^"]+)"', page.read_text()))
    for script in STATIC.glob("*.js"):
        used |= set(re.findall(r'\bt\("([a-z]+\.[A-Za-z0-9]+)"', script.read_text()))
        # Keys kept in lists, like { text: "nav.demo" } or label: "report.choiceNone"
        used |= set(re.findall(r'(?:text|label|means|title|hint|button): "([a-z]+\.[A-Za-z0-9]+)"', script.read_text()))
        # Keys handed to helpers, like setText(status, "demo.waiting") or showEmpty("reasons", "demo.nothingWorrying")
        used |= set(re.findall(r'(?:setText|showEmpty)\([^,()]+, "([a-z]+\.[A-Za-z0-9]+)"', script.read_text()))
        used |= set(re.findall(r'setCallStatus\("([a-z]+\.[A-Za-z0-9]+)"', script.read_text()))
        # Keys picked with ?:, like t(playing ? "demo.pause" : "demo.play"), and kept in
        # tables, like likely_scam: "demo.verdictScam"
        used |= set(re.findall(r'[?:] "((?:demo|try|flow)\.[A-Za-z0-9]+)"', script.read_text()))
    missing = used - known
    assert missing == set()


@pytest.mark.parametrize("path, page_script", PAGES.items())
def test_every_page_loads_the_words_first(path, page_script):
    """Each page loads strings.js, then i18n.js, then its own script."""
    page = client.get(path).text

    assert page.index("/static/strings.js") < page.index("/static/i18n.js") < page.index(page_script)


@pytest.mark.parametrize("page", ["about.html", "try.html", "demo.html"])
def test_language_blocks_come_in_pairs(page):
    """Longer text with links in it has an English block and a Spanish block
    (data-lang). Every English block has a Spanish one, and the Spanish ones
    start hidden, so nobody sees both before i18n.js runs."""
    html = (STATIC / page).read_text()
    english = re.findall(r'<[^>]*data-lang="en"[^>]*>', html)
    spanish = re.findall(r'<[^>]*data-lang="es"[^>]*>', html)

    assert len(english) > 0
    assert len(english) == len(spanish)
    for tag in spanish:
        assert "hidden" in tag


@pytest.mark.parametrize("page", ["about.html", "try.html", "demo.html"])
def test_tab_pages_follow_the_language_switch(page):
    """About us, Test it and Live demo load the words and the language switch,
    so they change to Spanish with the rest of the site."""
    html = (STATIC / page).read_text()

    assert "/static/strings.js" in html
    assert "/static/i18n.js" in html
    assert html.count("data-text=") >= 20
