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


@pytest.mark.parametrize("path", ["/", "/login", "/dashboard", "/setup/some-id", "/profile", "/demo", "/try", "/qa", "/privacy", "/terms"])
def test_main_pages_have_the_header(path):
    """Home, login, the dashboard, the demos, the Q&A and the fine print all get the same tabs on top."""
    page = client.get(path).text

    assert 'id="site-header"' in page
    assert "/static/nav.js" in page


@pytest.mark.parametrize("path", ["/join/some-token", "/phone/some-key"])
def test_one_job_pages_skip_the_header(path):
    """The "Join call" page and the senior's calling app stay without the header."""
    page = client.get(path).text

    assert "/static/nav.js" not in page


def test_nav_script_has_the_links():
    """nav.js has the Home, Live demo, Test it, Q&A and Dashboard tabs."""
    script = client.get("/static/nav.js").text

    assert '{ href: "/", text: "nav.home" }' in script
    assert '"/demo"' in script
    assert '"/try"' in script
    assert '"/qa"' in script
    assert '"/dashboard"' in script


@pytest.mark.parametrize(
    "path, page_script",
    [
        ("/dashboard", "/static/app.js"),
        ("/setup/some-id", "/static/setup.js"),
        ("/profile", "/static/profile.js"),
        ("/login", "/static/login.js"),
        ("/join/some-token", "/static/join.js"),
        ("/phone/some-key", "/static/phone.js"),
    ],
)
def test_pages_load_the_loading_and_error_helpers_first(path, page_script):
    """Every page that waits on the server loads busy.js before its own script."""
    page = client.get(path).text

    assert "/static/busy.js" in page
    assert page.index("/static/busy.js") < page.index(page_script)
