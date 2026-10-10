"""
app — the Scam Shield Python package.

How it fits in: this folder holds all the backend code. Having this file here
tells Python "app is a package", so other code can write `from app.config import get_settings`.

What each file does:
  main.py        the web server (FastAPI) and its routes
  config.py      loads settings and API keys from .env
  detector.py    asks NVIDIA Nemotron to score scam risk
  research.py    looks up the caller's number and scam news with Tavily
  alerts.py      sends text messages with Twilio
  verify.py      the "Is it really you?" family check
  languages.py   each person's language + translations
  demo_mode.py   plays scripted calls as if they were live
"""
