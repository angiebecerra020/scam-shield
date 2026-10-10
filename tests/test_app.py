"""
test_app.py — Quick "smoke tests" for the web server (app/main.py).

How it fits in: these tests prove the server starts, the health check answers,
and the dashboard page loads. They don't call any outside service, so they
work even before you've added API keys. Run them with:  pytest
"""

from fastapi.testclient import TestClient

from app.main import app

# TestClient lets us "visit" our web pages in code, without starting a real server.
client = TestClient(app)


def test_health_check_says_ok():
    """
    The /health page should answer with status "ok".

    Example: GET /health -> {"status": "ok", "demo_mode": true}
    """
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_page_loads():
    """
    The home page should send back our HTML page with the app's name on it.

    Example: GET / -> an HTML page containing "Scam Shield"
    """
    response = client.get("/")

    assert response.status_code == 200
    assert "Scam Shield" in response.text


def test_dashboard_styles_load():
    """
    The stylesheet should be reachable, or the page would show up unstyled.

    Example: GET /static/styles.css -> the CSS file, which uses our gold color
    """
    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert "#C9A227" in response.text
