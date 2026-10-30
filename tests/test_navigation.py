"""
test_navigation.py

Tests for the header at the top of the pages (static/nav.js), and the
loading and error helpers (static/busy.js).

How it fits in: nav.js builds the header in the browser, so here we just
check that the right pages have the spot for it and load nav.js, and that
the "Join call" page and the senior's calling app don't (they each do one
job in a hurry, so they stay without it). Run them with: pytest tests/test_navigation.py
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("path", ["/", "/login", "/dashboard", "/setup/some-id", "/profile", "/demo", "/try", "/watch", "/qa", "/privacy", "/terms"])
def test_main_pages_have_the_header(path):
    """Home, login, the dashboard, the demos, the Q&A and the fine print all get the same tabs on top."""
    page = client.get(path).text

    assert 'id="site-header"' in page
    assert "/static/nav.js" in page


def test_the_join_call_page_skips_the_header():
    """The "Join call" page stays without the header."""
    page = client.get("/join/some-token").text

    assert "/static/nav.js" not in page


def test_nav_script_has_the_links():
    """nav.js has the tabs in order: Home, About us, Dashboard, Q&A, Test it,
    Live demo. Call Log and Account (the profile page) are added only once
    someone is logged in, after the Log in check."""
    script = client.get("/static/nav.js").text
    tabs = ['"/"', '"/about"', '"/dashboard"', '"/qa"', '"/try"', '"/demo"']

    positions = [script.index(f"href: {tab}") for tab in tabs]
    assert positions == sorted(positions)
    # The logged in tabs come after the public ones, inside the login check.
    assert script.index('href: "/calls"') > script.index("session === null")
    assert script.index('href: "/profile"') > script.index("session === null")
    assert '"/how-to"' not in script


def test_dashboard_links_to_profile_and_setup():
    """The dashboard has the Profile link and the How to set up button."""
    html = client.get("/dashboard").text

    assert 'href="/profile"' in html
    assert 'href="/how-to"' in html


@pytest.mark.parametrize(
    "path, page_script",
    [
        ("/dashboard", "/static/app.js"),
        ("/setup/some-id", "/static/setup.js"),
        ("/profile", "/static/profile.js"),
        ("/login", "/static/login.js"),
        ("/join/some-token", "/static/join.js"),
    ],
)
def test_pages_load_the_loading_and_error_helpers_first(path, page_script):
    """Every page that waits on the server loads busy.js before its own script."""
    page = client.get(path).text

    assert "/static/busy.js" in page
    assert page.index("/static/busy.js") < page.index(page_script)


def test_the_call_log_page_loads_its_script_and_stays_out_of_search():
    """/calls is the logged in Call Log: private, so it's marked noindex."""
    html = client.get("/calls").text

    assert "/static/calls.js" in html
    assert 'name="robots" content="noindex"' in html


def test_the_account_page_can_change_the_password():
    html = client.get("/profile").text

    assert 'id="password-form"' in html
    assert "/static/account.js" in html
