"""
languages.py — Keeps track of which language each person speaks, and holds our
translations.

How it fits in: a senior might speak Spanish while their daughter reads texts in
English. This file remembers each person's language, so:
  - family alerts (alerts.py) go out in the reader's language
  - the dashboard shows labels in the viewer's language
  - the detector (detector.py) knows what language the call is in

We start with English and Spanish. Haitian Creole is next (it's widely spoken
in Florida), and we test it in Step 2.

Coming soon (a later step).
"""
