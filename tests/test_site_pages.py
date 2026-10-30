"""
test_site_pages.py

Tests for the launch checklist pieces in app/site_pages.py: privacy, terms,
the friendly 404 page, the tab icon, robots.txt, the sitemap and the safety
headers. Plus a check that every page has its icon and link preview tags.

How it fits in: these are quick checks with no AI, no internet and no phones.
"""

import json
import re
from html import unescape
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

STATIC = Path(__file__).resolve().parent.parent / "static"

# What a browser sends when someone types an address in.
BROWSER = {"Accept": "text/html,application/xhtml+xml"}


@pytest.mark.parametrize("path,words", [("/privacy", "No audio"), ("/terms", "Not for emergencies"), ("/qa", "Does my loved one have to agree?")])
def test_privacy_and_terms_pages_load(path, words):
    """The privacy, terms and Q&A pages open and say the important part."""
    response = client.get(path)

    assert response.status_code == 200
    assert words in response.text


def test_browsers_get_a_friendly_404_page():
    """A wrong address in a browser shows our page, with ways back."""
    response = client.get("/this-page-does-not-exist", headers=BROWSER)

    assert response.status_code == 404
    assert "We couldn't find that page" in response.text
    assert 'href="/demo"' in response.text


def test_our_code_still_gets_json_404s():
    """Our pages and Twilio still get the plain JSON error, never a web page."""
    api = client.get("/api/nothing-here", headers=BROWSER)
    no_browser = client.get("/this-page-does-not-exist")

    assert api.status_code == 404
    assert api.json() == {"detail": "Not Found"}
    assert no_browser.json() == {"detail": "Not Found"}


def test_tab_icon():
    """Browsers find the icon at /favicon.ico."""
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_robots_keeps_private_pages_out_of_search():
    """robots.txt points to the sitemap and keeps family pages out of search engines."""
    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert "Disallow: /dashboard" in response.text
    assert "Disallow: /join/" in response.text
    assert "Sitemap: http://testserver/sitemap.xml" in response.text


def test_sitemap_lists_the_public_pages():
    """The sitemap lists the home page, the demo and the test line, but not the dashboard."""
    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert "<loc>http://testserver/try</loc>" in response.text
    assert "/dashboard" not in response.text


def test_every_answer_has_the_safety_headers():
    """Pages and data both come with the safety headers."""
    for path in ("/", "/api/demo/calls", "/static/app.js"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "max-age" in headers["strict-transport-security"]
        assert headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    "page",
    ["landing.html", "login.html", "index.html", "join.html", "phone.html", "demo.html", "try.html",
     "qa.html", "privacy.html", "terms.html", "404.html",
     "seniors.html", "family-alerts.html", "phones.html", "watch.html"],
)
def test_every_page_has_an_icon_and_a_description(page):
    """Every page has the tab icon and a description for search engines."""
    html = (STATIC / page).read_text()

    assert 'rel="icon"' in html
    assert 'name="description"' in html


# The public pages: (path, file). These are the ones search engines should list.
PUBLIC = [
    ("/", "landing.html"),
    ("/demo", "demo.html"),
    ("/try", "try.html"),
    ("/watch", "watch.html"),
    ("/qa", "qa.html"),
    ("/scam-call-protection-for-seniors", "seniors.html"),
    ("/family-scam-alerts", "family-alerts.html"),
    ("/landline-and-cell-phone-scam-protection", "phones.html"),
    ("/login", "login.html"),
    ("/privacy", "privacy.html"),
    ("/terms", "terms.html"),
]

# The service pages and the words each one has to say.
SERVICE_PAGES = [
    ("/scam-call-protection-for-seniors", "Scam call protection for seniors"),
    ("/family-scam-alerts", "Receive a call the moment your loved one is targeted by a scam"),
    ("/landline-and-cell-phone-scam-protection", "Scam call protection for a landline or a cell phone"),
]


@pytest.mark.parametrize("path,words", SERVICE_PAGES)
def test_service_pages_load(path, words):
    """The three service pages open, are in the sitemap, and link to the Q&A."""
    response = client.get(path)

    assert response.status_code == 200
    assert words in response.text
    assert 'href="/qa"' in response.text
    assert f"<loc>http://testserver{path}</loc>" in client.get("/sitemap.xml").text


@pytest.mark.parametrize("path,page", PUBLIC)
def test_public_pages_have_a_canonical_link(path, page):
    """Each public page tells search engines its one true address, on the live site."""
    html = (STATIC / page).read_text()

    assert f'<link rel="canonical" href="https://scam-shield-86hy.onrender.com{path}">' in html
    assert "ity3" not in html


@pytest.mark.parametrize("path,page", [entry for entry in PUBLIC if entry[0] != "/login"])
def test_public_pages_link_to_the_service_pages(path, page):
    """The footer links every public page to the service pages and the Q&A.
    (Not the login page: it has no footer, just the form.)"""
    html = (STATIC / page).read_text()

    for link in ("/scam-call-protection-for-seniors", "/family-scam-alerts",
                 "/landline-and-cell-phone-scam-protection", "/qa"):
        assert f'href="{link}"' in html


@pytest.mark.parametrize("page", ["qa.html", "seniors.html", "family-alerts.html", "phones.html"])
def test_faq_schema_matches_the_page(page):
    """The FAQ schema is real JSON, and every question in it is also on the page,
    word for word (search engines don't like schema the page doesn't show)."""
    html = (STATIC / page).read_text()
    found = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    schema = json.loads(found.group(1))
    shown = unescape(html)

    assert schema["@type"] == "FAQPage"
    assert len(schema["mainEntity"]) >= 3
    for question in schema["mainEntity"]:
        assert question["name"] in shown
        assert question["acceptedAnswer"]["text"] in shown


def test_video_page_waits_for_the_video():
    """/watch opens and is in the sitemap. Until the YouTube ID is filled in,
    it shows "coming soon" and a way to the live demo, and the home page links to it."""
    response = client.get("/watch")

    assert response.status_code == 200
    assert 'data-video-id=""' in response.text
    assert "Our video is coming soon" in response.text
    assert 'href="/demo"' in response.text
    assert 'href="/login?mode=signup"' in response.text
    assert "<loc>http://testserver/watch</loc>" in client.get("/sitemap.xml").text
    assert 'href="/watch"' in (STATIC / "landing.html").read_text()


def test_video_uses_youtube_privacy_mode():
    """The video comes from youtube-nocookie.com, so YouTube doesn't track
    visitors before they press play (our privacy page promises no tracking)."""
    script = (STATIC / "watch.js").read_text()

    assert "https://www.youtube-nocookie.com/embed/" in script
    assert "www.youtube.com/embed" not in script


@pytest.mark.parametrize("page", ["landing.html", "demo.html", "try.html", "login.html", "watch.html"])
def test_public_pages_have_link_previews(page):
    """Shared links show our preview image on Devpost and social media."""
    html = (STATIC / page).read_text()

    assert 'property="og:image"' in html
    assert 'name="twitter:card"' in html


@pytest.mark.parametrize("page", ["index.html", "join.html", "phone.html"])
def test_private_pages_stay_out_of_search(page):
    """The dashboard, "Join call" and the calling app tell search engines to skip them."""
    html = (STATIC / page).read_text()

    assert '<meta name="robots" content="noindex">' in html


def test_home_page_leads_with_the_demo():
    """The first buttons on the home page go to the demo and the test line,
    and Cass's sign up and log in links are still there."""
    html = (STATIC / "landing.html").read_text()

    assert html.index('href="/demo"') < html.index('href="/login?mode=signup"')
    assert 'href="/try"' in html
    assert 'href="/login"' in html


@pytest.mark.parametrize("photo", ["/static/team/angie.jpg", "/static/team/cassandra.jpg"])
def test_team_photos_are_on_the_about_page(photo):
    """"Who we are" on the About us page shows Angie's and Cassandra's photos,
    and each one describes the photo for screen readers."""
    html = (STATIC / "about.html").read_text()
    image = client.get(photo)

    assert f'src="{photo}" alt="' in html
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
