"""
site_pages.py

The little things every real website needs: the Q&A, privacy and terms pages, a
friendly "page not found", the icon in the browser tab, robots.txt and a
sitemap for search engines, and a few safety headers on every answer.

How it fits in: main.py adds this file's router and calls add_site_extras(app)
once at startup. Nothing here changes how calls, alerts or logins work.
"""

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import PROJECT_ROOT, get_settings

router = APIRouter()

STATIC = PROJECT_ROOT / "static"

# The pages search engines can list. The dashboard, "Join call" links and the
# senior's calling app stay out, since they're private to each family.
PUBLIC_PAGES = [
    "/",
    "/demo",
    "/try",
    "/qa",
    "/scam-call-protection-for-seniors",
    "/family-scam-alerts",
    "/landline-and-cell-phone-scam-protection",
    "/login",
    "/privacy",
    "/terms",
]

# Paths where the answer is data for our own pages or for Twilio, never a
# web page. A wrong address there keeps getting the plain JSON error.
DATA_PATHS = ("/api/", "/twilio/", "/static/")

# Safety headers we add to every answer:
#   Strict-Transport-Security: browsers always use https with us from now on
#   X-Content-Type-Options: browsers don't guess what a file is
#   Referrer-Policy: other sites only see our domain, never the full link
#     (our "Join call" links have secrets in them)
#   X-Frame-Options: nobody can put our pages inside their own site to trick people
#   Cache-Control: browsers check with us for a newer copy every time, so
#     after a deploy nobody gets the new page with an old app.js (it would
#     look for buttons that aren't there anymore and leave the page empty)
SAFETY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-cache",
}


def wants_a_web_page(request: Request) -> bool:
    """
    Checks if a person in a browser asked for this, instead of our own code.

    Input:  request, the incoming web request
    Output: True for a browser asking for a page, False for data paths

    Example:
        A browser opening /prices gives you True
        Our page asking /api/line/abc gives you False
    """
    if request.url.path.startswith(DATA_PATHS):
        return False
    return "text/html" in request.headers.get("accept", "")


async def not_found(request: Request, problem: StarletteHTTPException) -> Response:
    """
    Shows our friendly "page not found" page to people, and keeps the usual
    JSON error for our own code and for Twilio.

    Example:
        Opening /prices in a browser gives you the 404 page with a way back home
    """
    if problem.status_code == 404 and wants_a_web_page(request):
        return FileResponse(STATIC / "404.html", status_code=404)
    return JSONResponse({"detail": problem.detail}, status_code=problem.status_code, headers=problem.headers)


def add_site_extras(app: FastAPI) -> None:
    """
    Turns on the friendly 404 page and the safety headers for the whole app.
    main.py calls this once.

    Example:
        add_site_extras(app) and every answer now has the safety headers
    """
    app.add_exception_handler(StarletteHTTPException, not_found)

    @app.middleware("http")
    async def add_safety_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SAFETY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


@router.get("/qa")
def show_qa_page() -> FileResponse:
    """
    Sends the Q&A page: the questions families ask us most.

    Example:
        Open http://localhost:8000/qa
    """
    return FileResponse(STATIC / "qa.html")


@router.get("/scam-call-protection-for-seniors")
def show_seniors_page() -> FileResponse:
    """
    Sends the service page for seniors: the scam tricks we listen for, and
    how the senior stays in charge.

    Example:
        Open http://localhost:8000/scam-call-protection-for-seniors
    """
    return FileResponse(STATIC / "seniors.html")


@router.get("/family-scam-alerts")
def show_family_alerts_page() -> FileResponse:
    """
    Sends the service page for the family alert: the call (and email) the
    family gets when a call looks like a scam.

    Example:
        Open http://localhost:8000/family-scam-alerts
    """
    return FileResponse(STATIC / "family-alerts.html")


@router.get("/landline-and-cell-phone-scam-protection")
def show_phones_page() -> FileResponse:
    """
    Sends the service page for phones: how Scam Shield works on a cell phone
    and on a home landline.

    Example:
        Open http://localhost:8000/landline-and-cell-phone-scam-protection
    """
    return FileResponse(STATIC / "phones.html")


@router.get("/privacy")
def show_privacy_page() -> FileResponse:
    """
    Sends the privacy policy: what we keep, what we never keep, and why.

    Example:
        Open http://localhost:8000/privacy
    """
    return FileResponse(STATIC / "privacy.html")


@router.get("/terms")
def show_terms_page() -> FileResponse:
    """
    Sends the terms of use.

    Example:
        Open http://localhost:8000/terms
    """
    return FileResponse(STATIC / "terms.html")


@router.get("/favicon.ico")
def show_tab_icon() -> FileResponse:
    """
    Sends the little icon browsers show in the tab. Browsers ask for
    /favicon.ico on their own, even when the page names another icon.

    Example:
        GET /favicon.ico gives you the gold shield
    """
    return FileResponse(STATIC / "icons" / "favicon-32.png", media_type="image/png")


@router.get("/robots.txt")
def show_robots() -> PlainTextResponse:
    """
    Tells search engines what they can look at, and where the sitemap is.

    Example:
        GET /robots.txt gives you "User-agent: * ... Sitemap: https://.../sitemap.xml"
    """
    base = get_settings().public_base_url.rstrip("/")
    lines = [
        "User-agent: *",
        "Disallow: /api/",
        "Disallow: /twilio/",
        "Disallow: /dashboard",
        "Disallow: /join/",
        "Disallow: /phone/",
        f"Sitemap: {base}/sitemap.xml",
    ]
    return PlainTextResponse("\n".join(lines) + "\n")


@router.get("/sitemap.xml")
def show_sitemap() -> Response:
    """
    Lists our public pages for search engines.

    Example:
        GET /sitemap.xml gives you <urlset> with /, /demo, /try and the rest
    """
    base = get_settings().public_base_url.rstrip("/")
    entries = []
    for page in PUBLIC_PAGES:
        entries.append(f"  <url><loc>{base}{page}</loc></url>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")
