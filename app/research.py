"""
research.py

This looks stuff up on the web with Tavily while a call is happening.

How it fits in: when a call comes in, we ask Tavily two questions:
  1. Has anyone reported this caller's phone number as a scam?
  2. Is there a warning or news story about a scam that sounds like this call?
     (like "grandparent scam gift cards")
The answers go on the family dashboard with their links, so the family can
see WHY we're worried and read it for themselves.

Each search gives back something like this:

    {
        "query": "what we searched for",
        "summary": "Tavily's short answer, or None",
        "sources": [{"title": "...", "url": "...", "snippet": "...", "mentions_scam": True}],
        "note": None,
    }

If Tavily is down or the key is missing, we never crash the call. You just
get an empty list of sources and a note that says what happened.
"""

import re

from tavily import TavilyClient

from app.config import find_missing_settings, get_settings

# How many links we keep for each question. Three fits nicely on a phone screen.
MAX_SOURCES = 3

# If Tavily takes longer than this many seconds, we stop waiting so the call keeps going.
SEARCH_TIMEOUT_SECONDS = 10

# We cut snippets down to this many characters so they're quick to read.
MAX_SNIPPET_LENGTH = 220

# Sites we trust for scam warnings: the FTC, FCC, FBI, Social Security,
# Medicare, AARP and the BBB. We search these first, so families see real
# warnings instead of random social media posts.
TRUSTED_DOMAINS = [
    "consumer.ftc.gov",
    "ftc.gov",
    "fcc.gov",
    "fbi.gov",
    "ic3.gov",
    "ssa.gov",
    "medicare.gov",
    "aarp.org",
    "bbb.org",
]

# If a result has any of these words, it's talking about scams or spam calls.
# We include Spanish words too, since some of our families read Spanish sites.
SCAM_WORDS = ("scam", "fraud", "spam", "spoof", "robocall", "estafa", "fraude")


def shorten(text: str, limit: int) -> str:
    """
    Cuts text down to a limit without chopping a word in half.

    Input:  text, any text
            limit, the most characters we want
    Output: the text as is if it's short enough, or cut at the last full
            word with "..." on the end

    Example:
        shorten("Scammers often fake this number", 20) gives you "Scammers often fake..."
    """
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "..."


def format_phone_number(phone: str) -> str:
    """
    Writes a US phone number the way most websites write it, so searches find it.

    Input:  phone, like "+18007721213" or "(800) 772-1213"
    Output: "800-772-1213". Numbers that aren't 10 US digits come back as they were.

    Examples:
        format_phone_number("+18007721213") gives you "800-772-1213"
        format_phone_number("12345") gives you "12345"
    """
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return (phone or "").strip()
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def mentions_scam(text: str) -> bool:
    """
    Checks if some text talks about scams, fraud or spam calls.

    Input:  text, like a search result's title and snippet
    Output: True or False

    Example:
        mentions_scam("Scammers spoof the SSA number") gives you True
    """
    lowered = (text or "").lower()
    for word in SCAM_WORDS:
        if word in lowered:
            return True
    return False


def clean_sources(results: list) -> list[dict]:
    """
    Keeps just the parts of Tavily's results that the dashboard needs.

    Input:  results, the "results" list Tavily sends back
    Output: up to 3 sources, each with a title, url, short snippet, and
            whether it mentions a scam

    Example:
        clean_sources([{"title": "FCC scam alert", "url": "https://fcc.gov/...", "content": "..."}])
        gives you [{"title": "FCC scam alert", "url": "https://fcc.gov/...",
                    "snippet": "...", "mentions_scam": True}]
    """
    sources = []
    for result in results or []:
        title = shorten(result.get("title", ""), 120)
        snippet = shorten(result.get("content", ""), MAX_SNIPPET_LENGTH)
        url = result.get("url", "")
        if not url:
            continue
        sources.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "mentions_scam": mentions_scam(title + " " + snippet),
            }
        )
    return sources[:MAX_SOURCES]


def empty_research(query: str, why: str) -> dict:
    """
    The answer we give when we couldn't (or didn't need to) search.

    Input:  query, what we would have searched for ("" if nothing)
            why, a short note about what happened
    Output: a search result with no sources and the note filled in

    Example:
        empty_research("", "No internet") gives you
        {"query": "", "summary": None, "sources": [], "note": "No internet"}
    """
    return {"query": query, "summary": None, "sources": [], "note": why}


def make_client() -> TavilyClient:
    """
    Creates the Tavily client using the key in .env.

    Input:  nothing (it reads TAVILY_API_KEY from .env)
    Output: a TavilyClient that's ready to search

    Example:
        client = make_client()
    """
    return TavilyClient(api_key=get_settings().tavily_api_key)


def run_search(query: str, client=None, only_sites: list[str] | None = None) -> dict:
    """
    Runs one Tavily search and gives back a clean result.

    Input:  query, what to search for
            client, leave this empty in the app (the tests pass a fake one)
            only_sites, a list of websites to search (leave empty to search everywhere)
    Output: a search result (check out the top of this file)

    Example:
        run_search("grandparent scam gift cards", only_sites=TRUSTED_DOMAINS)
        gives you up to 3 sources from places like the FTC or AARP
    """
    if client is None:
        missing = find_missing_settings(get_settings(), ["TAVILY_API_KEY"])
        if missing:
            return empty_research(query, "Missing in .env: TAVILY_API_KEY")
        client = make_client()

    search_settings = {
        "query": query,
        "max_results": MAX_SOURCES,
        # Tavily also writes a one or two sentence answer we can show the family.
        "include_answer": True,
        "timeout": SEARCH_TIMEOUT_SECONDS,
    }
    if only_sites:
        search_settings["include_domains"] = only_sites

    try:
        response = client.search(**search_settings)
    except Exception as error:
        # We catch every error on purpose. A search problem should never
        # crash the app while someone's on the phone.
        print(f"[research] Tavily search failed: {type(error).__name__}: {error}")
        return empty_research(query, f"Couldn't reach Tavily ({type(error).__name__}).")

    return {
        "query": query,
        "summary": response.get("answer") or None,
        "sources": clean_sources(response.get("results", [])),
        "note": None,
    }


def check_caller_number(phone: str, client=None) -> dict:
    """
    Asks Tavily if anyone has reported this phone number as a scam.

    Input:  phone, the caller's number, like "+18007721213"
            client, leave this empty in the app (the tests pass a fake one)
    Output: a search result, plus "reported_as_scam", which is True if any
            source talks about scams

    Example:
        check_caller_number("+18007721213") gives you sources that say
        scammers often fake this Social Security number, and reported_as_scam True
    """
    number = format_phone_number(phone)
    if not number:
        result = empty_research("", "We don't know the caller's number.")
    else:
        result = run_search(f'"{number}" phone number scam reports', client)

    result["reported_as_scam"] = False
    for source in result["sources"]:
        if source["mentions_scam"]:
            result["reported_as_scam"] = True
    return result


def scam_news_query(claimed_identity: str | None, reasons: list[str]) -> str:
    """
    Builds the search for scam warnings that match this call.

    Input:  claimed_identity, who the caller says they are (or None)
            reasons, the red flags the detector found
    Output: a short search, like "phone scam caller claims to be grandson
            Danny Requests money via gift cards"

    Example:
        scam_news_query("IRS agent", ["Threatens arrest"]) gives you
        "phone scam caller claims to be IRS agent Threatens arrest"
    """
    parts = ["phone scam"]
    if claimed_identity:
        parts.append(f"caller claims to be {claimed_identity}")
    if reasons:
        parts.append(reasons[0])
    return shorten(" ".join(parts), 250)


def find_scam_warnings(query: str, client=None) -> dict:
    """
    Looks for scam warnings on trusted sites first, then the whole web if needed.

    Families trust a warning from the FTC or AARP way more than a random post,
    and judges notice that too. If the trusted sites don't have anything, we
    search everywhere so we still have something to show.

    Input:  query, what to search for, like "grandparent scam gift cards"
            client, leave this empty in the app (the tests pass a fake one)
    Output: a search result (check out the top of this file)

    Example:
        find_scam_warnings("grandparent scam gift cards") gives you warnings
        from places like consumer.ftc.gov and aarp.org
    """
    trusted = run_search(query, client, only_sites=TRUSTED_DOMAINS)
    if trusted["sources"]:
        return trusted
    return run_search(query, client)


def research_call(phone: str, detector_result: dict, client=None) -> dict:
    """
    Does all the web research for one call: the caller's number and matching
    scam warnings.

    We only look for scam warnings when the detector thinks the call is
    suspicious or worse. If the call looks safe, that search would just use
    up our credits.

    Input:  phone, the caller's number
            detector_result, what detector.score_call() gave back
            client, leave this empty in the app (the tests pass a fake one)
    Output: {"caller": <search result>, "news": <search result>}

    Example:
        research_call("+13055550142", {"verdict": "likely_scam",
                      "claimed_identity": "grandson Danny", "reasons": ["Wants gift cards"]})
        gives you a caller check plus warnings from places like the FCC and AARP
    """
    caller = check_caller_number(phone, client)

    if detector_result.get("verdict") in ("suspicious", "likely_scam"):
        query = scam_news_query(
            detector_result.get("claimed_identity"), detector_result.get("reasons", [])
        )
        news = find_scam_warnings(query, client)
    else:
        news = empty_research("", "The call looks safe so far, so we didn't search for scam news.")

    return {"caller": caller, "news": news}
