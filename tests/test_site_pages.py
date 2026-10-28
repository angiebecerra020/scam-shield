"""
test_site_pages.py

Tests for the launch checklist pieces in app/site_pages.py: privacy, terms,
the friendly 404 page, the tab icon, robots.txt, the sitemap and the safety
headers. Plus a check that every page has its icon and link preview tags.

How it fits in: these are quick checks with no AI, no internet and no phones.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

STATIC = Path(__file__).resolve().parent.parent / "static"

# What a browser sends when someone types an address in.
BROWSER = {"Accept": "text/html,application/xhtml+xml"}


@pytest.mark.parametrize("path,words", [("/privacy", "No audio"), ("/terms", "Not for emergencies")])
def test_privacy_and_terms_pages_load(path, words):
    """The privacy and terms pages open and say the important part."""
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
    for path in ("/", "/api/demo/calls"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "max-age" in headers["strict-transport-security"]


@pytest.mark.parametrize(
    "page",
    ["landing.html", "login.html", "index.html", "join.html", "phone.html", "demo.html", "try.html",
     "privacy.html", "terms.html", "404.html"],
)
def test_every_page_has_an_icon_and_a_description(page):
    """Every page has the tab icon and a description for search engines."""
    html = (STATIC / page).read_text()

    assert 'rel="icon"' in html
    assert 'name="description"' in html


@pytest.mark.parametrize("page", ["landing.html", "demo.html", "try.html", "login.html"])
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
