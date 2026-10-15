"""
app/__init__.py

This folder holds all the backend code for Scam Shield. This file tells
Python that "app" is a package, so other code can do things like
`from app.config import get_settings`.

What each file does:
  main.py        the web server (FastAPI) and its routes
  config.py      loads our settings and API keys from .env
  detector.py    asks NVIDIA Nemotron how risky a call is
  research.py    looks up the caller's number and scam news with Tavily
  alerts.py      sends text messages with Twilio
  verify.py      the "Is it really you?" family check
  languages.py   each person's language and our translations
  demo_mode.py   plays scripted calls like they're live
"""
