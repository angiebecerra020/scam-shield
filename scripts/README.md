<!--
  README for scripts/ — explains the day-1 check scripts that live here.
-->

# Day-1 checks

Small scripts that each check one outside service works **before** we build on it. Each one runs with a single command and prints **PASS** or **FAIL**.

**Coming soon (Step 2, tracker T3–T7):**

| Script | What it checks |
|---|---|
| `test_nemotron.py` | Nemotron scores a sample scam call, and how long it takes (goal: under 3 seconds) |
| `test_tavily.py` | Tavily finds useful results for 3 scam phone numbers + 1 scam script |
| `test_sms.py` | Twilio can send a text to our test phone |
| `test_languages.py` | Nemotron handles Spanish and Haitian Creole scam calls |
| `test_twilio_call.py` | Our Twilio number can receive a phone call |
