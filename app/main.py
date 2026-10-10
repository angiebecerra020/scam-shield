"""
main.py — The Scam Shield web server (built with FastAPI).

How it fits in: this is the program you start with
    uvicorn app.main:app --reload
It sends the family dashboard (the files in static/) to the browser, and it
will hold all of our web routes: Twilio call webhooks, demo mode, and live
dashboard updates.

Right now (Step 1) it has two routes:
    GET /        -> the dashboard page (a placeholder for now)
    GET /health  -> a quick "is the server alive?" check
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings

# static/ sits next to app/ in the project folder.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="Scam Shield",
    description="Catches scam phone calls while they happen and alerts the family.",
)

# Serve the CSS and JavaScript files at /static/... so index.html can load them.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def show_dashboard() -> FileResponse:
    """
    Send the family dashboard page to the browser.

    Input:  nothing (someone opens http://localhost:8000/ in a browser)
    Output: the static/index.html page.

    Example:
        Open http://localhost:8000 -> you see the Scam Shield page.
    """
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health_check() -> dict:
    """
    Report that the server is running, and whether demo mode is on.

    We use this to check the server quickly, and later hosting services
    can call it to make sure the app is still up. It never shows secrets.

    Input:  nothing
    Output: a small dictionary, e.g. {"status": "ok", "demo_mode": True}

    Example:
        curl http://localhost:8000/health
        -> {"status":"ok","demo_mode":true}
    """
    settings = get_settings()
    return {"status": "ok", "demo_mode": settings.demo_mode}
