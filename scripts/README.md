<!--
  This README explains the day one check scripts that live in this folder.
-->

# Day one checks

These are small scripts that each check that one outside service works **before** we build on top of it. Each one runs with a single command and prints **PASS** or **FAIL**.

Run them from the project folder, with the virtual environment turned on (`source .venv/bin/activate`).

| Script | What it checks | Status |
|---|---|---|
| `test_nemotron.py` | Nemotron catches a sample scam call, and how long it takes (our goal is under 3 seconds) | Ready: `python scripts/test_nemotron.py` |
| `test_tavily.py` | Tavily finds useful results for 3 scam phone numbers and 1 scam script | Ready: `python scripts/test_tavily.py` |
| `test_sms.py` | Twilio can send a text to our test phone | Coming soon |
| `test_languages.py` | Nemotron catches scam calls in Spanish | Ready: `python scripts/test_languages.py` |
| `test_twilio_call.py` | Our Twilio number can receive a phone call | Coming soon |
