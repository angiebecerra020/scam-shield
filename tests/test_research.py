"""
test_research.py

Tests for the Tavily web research (app/research.py).

How it fits in: these use a FAKE Tavily, so they don't use up our search
credits and they work without internet. They check our own code, like
cleaning up results, spotting scam warnings, and never crashing.
"""

from app import research

FCC_RESULT = {
    "title": "Grandparent Scams Get More Sophisticated",
    "url": "https://www.fcc.gov/consumers/scam-alert/grandparent-scams",
    "content": "Scammers pretend to be a grandchild in trouble and ask for gift cards.",
}

BAKERY_RESULT = {
    "title": "Sunshine Bakery",
    "url": "https://example.com/bakery",
    "content": "Fresh bread every morning.",
}


class FakeTavily:
    """
    A pretend Tavily client that answers with whatever we pick.

    It remembers every search, so tests can check what we asked for.

    Example:
        fake = FakeTavily({"results": [FCC_RESULT]})
        research.run_search("grandparent scam", client=fake)
    """

    def __init__(self, response):
        # The response is either a dict to send back, or an error to raise.
        self.response = response
        self.searches = []

    def search(self, **request):
        """Acts like TavilyClient.search() and gives back our pick."""
        self.searches.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_phone_numbers_are_written_like_websites_write_them():
    """The +1 and the parentheses go away, and we get 800-772-1213."""
    assert research.format_phone_number("+18007721213") == "800-772-1213"
    assert research.format_phone_number("(800) 772-1213") == "800-772-1213"
    assert research.format_phone_number("12345") == "12345"


def test_caller_check_spots_scam_warnings():
    """If a result talks about scams, the number counts as reported."""
    fake = FakeTavily({"answer": "Scammers often fake this number.", "results": [FCC_RESULT]})

    result = research.check_caller_number("+18007721213", client=fake)

    assert result["reported_as_scam"] is True
    assert result["summary"] == "Scammers often fake this number."
    assert result["sources"][0]["url"].startswith("https://www.fcc.gov")
    assert '"800-772-1213"' in fake.searches[0]["query"]


def test_caller_check_with_no_scam_mentions_is_not_reported():
    """A result about a bakery shouldn't make the number look like a scam."""
    fake = FakeTavily({"results": [BAKERY_RESULT]})

    result = research.check_caller_number("+13055550110", client=fake)

    assert result["reported_as_scam"] is False


def test_we_keep_at_most_three_short_sources():
    """Lots of results get trimmed to 3, and long snippets get shortened."""
    long_result = dict(FCC_RESULT, content="scam " * 200)
    fake = FakeTavily({"results": [long_result] * 6})

    result = research.run_search("grandparent scam", client=fake)

    assert len(result["sources"]) == 3
    assert len(result["sources"][0]["snippet"]) <= research.MAX_SNIPPET_LENGTH + 3


def test_tavily_problem_never_crashes():
    """If Tavily is down, we get an empty list and a note, not a crash."""
    fake = FakeTavily(ConnectionError("no internet"))

    result = research.run_search("grandparent scam", client=fake)

    assert result["sources"] == []
    assert "ConnectionError" in result["note"]


def test_missing_key_gives_a_clear_note(monkeypatch):
    """No Tavily key in .env? We say so instead of crashing."""
    monkeypatch.setenv("TAVILY_API_KEY", "")

    result = research.run_search("grandparent scam")

    assert result["sources"] == []
    assert result["note"] == "Missing in .env: TAVILY_API_KEY"


def test_safe_calls_skip_the_scam_news_search():
    """We don't spend credits looking for scam news when the call looks safe."""
    fake = FakeTavily({"results": [BAKERY_RESULT]})

    result = research.research_call("+13055550110", {"verdict": "safe"}, client=fake)

    assert len(fake.searches) == 1
    assert result["news"]["sources"] == []


def test_risky_calls_search_for_matching_scam_news():
    """For a risky call we search using who they claim to be and the top red flag."""
    fake = FakeTavily({"results": [FCC_RESULT]})
    detector_result = {
        "verdict": "likely_scam",
        "claimed_identity": "grandson Danny",
        "reasons": ["Asks for gift cards", "Says to keep it a secret"],
    }

    result = research.research_call("+13055550142", detector_result, client=fake)

    assert len(fake.searches) == 2
    assert "grandson Danny" in fake.searches[1]["query"]
    assert "Asks for gift cards" in fake.searches[1]["query"]
    # The scam warning search looks at trusted sites (FTC, AARP...) first.
    assert "consumer.ftc.gov" in fake.searches[1]["include_domains"]
    assert result["news"]["sources"][0]["mentions_scam"] is True


def test_scam_warnings_fall_back_to_the_whole_web():
    """If the trusted sites have nothing, we search everywhere so we still show something."""

    class TrustedSitesEmpty(FakeTavily):
        """Gives back nothing for trusted sites, and a result for the whole web."""

        def search(self, **request):
            self.searches.append(request)
            if "include_domains" in request:
                return {"results": []}
            return {"results": [FCC_RESULT]}

    fake = TrustedSitesEmpty(None)

    result = research.find_scam_warnings("brand new scam nobody wrote about yet", client=fake)

    assert len(fake.searches) == 2
    assert "include_domains" not in fake.searches[1]
    assert len(result["sources"]) == 1


def test_shorten_never_cuts_a_word_in_half():
    """Shortened text ends on a full word plus three dots."""
    assert research.shorten("Scammers often fake this number", 20) == "Scammers often fake..."
    assert research.shorten("Short text", 50) == "Short text"
