<!--
  README.md is the front page of the Scam Shield repo. It explains the problem,
  what Scam Shield does, how it works, and how to run it.
-->

# 🛡️ Scam Shield

[![Tests](https://github.com/angiebecerra020/scam-shield/actions/workflows/tests.yml/badge.svg)](https://github.com/angiebecerra020/scam-shield/actions/workflows/tests.yml)

**Catches scam phone calls while they're happening, and alerts the family in their own language.**

Scam Shield follows a senior's phone call through a live transcript, checks the caller against the web, and uses **NVIDIA Nemotron** on **Nebius Token Factory** to spot the warning signs of a scam: gift cards, secrecy, urgency, a "grandchild" in trouble. When the risk is high, the family gets an alert right away, in their own language, with a link to join the call.

> 🚧 **Work in progress** for the Nebius x NVIDIA Global AI Hackathon. Parts marked *Coming soon* are being built now.

## The problem

In 2025, Americans aged 60 and older reported **$7.7 billion** in fraud losses to the FBI, up about 60% from 2024, more than any other age group. ([FBI Internet Crime Complaint Center](https://www.ic3.gov/), [AARP summary](https://www.aarp.org/money/scams-fraud/fbi-ftc-report-2025-losses))

Phone scams work because they're **fast and emotional**:

> *"Grandma, it's me, Danny. I'm in trouble. Please don't tell Mom. Can you get $2,000 in gift cards?"*

Call blockers only stop numbers that are already known to be bad. Banks and family members usually find out **after** the money is gone. Scam Shield steps in **during the call**, while there's still time to stop it.

## What it does

| # | Feature | Status |
|---|---|---|
| 0 | **Senior's OK first.** When a family member signs someone up, we text the senior: *"Ana wants to protect your calls. Reply YES or NO."* Nothing is listened to until a YES comes from the senior's own phone. STOP turns it off any time. | Done |
| 1 | **Live transcript.** The senior's calls forward to a Scam Shield number, which turns the call into text as it happens. | Coming soon |
| 2 | **Caller research.** Tavily checks whether the caller's number has been reported, and finds scam warnings that match the call. It looks at trusted sites first: the FTC, FBI, Social Security, Medicare, AARP and the BBB. | Done |
| 3 | **AI scam score.** NVIDIA Nemotron scores the risk from 0 to 100 and explains why: gift cards, secrecy, urgency, a fake grandchild, "your Social Security number is suspended". | Done |
| 4 | **"Is it really you?"** If the caller claims to be family, we text the real person: *"Are you calling Grandma? YES / NO."* If they say NO, we warn the senior. | Coming soon |
| 5 | **Family alert.** A live text message in the family member's own language, with a "Join call" link. | Text + link done; triggered by the AI score soon |
| 5b | **Join the call (3-way call).** Protected calls run through a conference room. Tapping "Join call" rings the family member's own phone and adds them to the call. Everyone hears a tone when they join. | Done |
| 6 | **Family dashboard.** A live risk meter, the reasons, source links, and call history. | Coming soon |
| 7 | **Languages.** English, Spanish and Haitian Creole. Haitian Creole calls use the bigger Nemotron 3 Ultra so the alert is written in real Creole. | Done |
| ★ | **Demo mode.** Replays a scripted call as a live transcript, with no real phone call needed. | Sample calls ready, player coming soon |

## How it works

```text
  Sign-up: family enters the senior's number
       |  we text the SENIOR: "Reply YES or NO"
       |  only a YES from the senior's own phone turns protection on
       v
  Senior's phone
       |  calls forward to
       v
  Twilio number, which turns the call into a live transcript
       |
       +  Tavily: has this number been reported? Any scam warnings that match the call?
       |
       +  NVIDIA Nemotron (on Nebius Token Factory):
       |     a risk score from 0 to 100, the reasons, and who the caller claims to be
       |
       +  "Is it really you?": caller says he's grandson Danny?
       |     we text the REAL Danny: "Are you calling Grandma? YES / NO"
       |     if he says NO, we warn Grandma right away
       v
  Family
       - text alert in THEIR language + "Join call" link
         (tap it -> we ring the family's phone into the call: a 3-way call)
       - live dashboard: risk meter, reasons, source links, call history
```

## How we use NVIDIA Nemotron and Nebius Token Factory

Nemotron is the brain of Scam Shield. All of this lives in [`app/detector.py`](app/detector.py).

- **The model.** We use **Nemotron 3.5 Lightning** (`nvidia/Nemotron-3_5-Lightning`) on Nebius Token Factory. Token Factory works just like the OpenAI API, so we call it with the regular `openai` Python library and point it at `https://api.tokenfactory.nebius.com/v1/`.
- **What we send.** The call so far, plus instructions that list the red flags the FBI and FTC warn about (gift cards, secrecy, rushing, threats of arrest, a grandchild in trouble, "your Social Security number is suspended") and what a normal call looks like, so real family doesn't get flagged.
- **What we get back.** Token Factory's structured output makes Nemotron answer in an exact JSON shape: a risk score from 0 to 100, a verdict, the reasons, who the caller claims to be, and a short alert for the family written in the family's language.
- **Fast enough for a live call.** We switch off Nemotron's step by step "thinking" mode for live checks. Each check takes about 1 second (our goal was under 3).
- **Safe by design.** We set the verdict from the score so they never disagree, safe calls never send an alert, and if anything goes wrong we say "couldn't check" instead of guessing "safe". The transcript is treated as evidence, never as instructions, so a scammer who says "ignore your rules" just looks more like a scammer.
- **The right Nemotron for each job.** Lightning handles the fast live checks. For Haitian Creole calls we switch to **Nemotron 3 Ultra**, which writes the reasons and the family alert in real Creole (score 95, about 2 seconds). Picking the model is one setting in `.env` (`NEMOTRON_SMART_MODEL`).
- **From score to alert.** [`app/call_monitor.py`](app/call_monitor.py) checks the call every time a new line comes in. The first time the score hits 70, the family gets the alert with the "Join call" link plus a short text with the top red flags. It only alerts once per call, and only for seniors who said YES.

**Where Token Factory sped us up:** one API key gave us the whole Nemotron family (Lightning, Super and Ultra), so trying a bigger model is a one line change in `.env`. Because it's OpenAI compatible, we didn't need a special library. And structured output meant we got clean data back on the first try instead of digging through paragraphs.

## Results so far

**Scam detection** on our sample calls (run it yourself with `pytest tests/test_detector.py -s -k accuracy`):

| Call | Language | What happens | Score | Verdict |
|---|---|---|---|---|
| Real granddaughter Sofía | Spanish | Calls about Sunday lunch, asks for nothing | 10 | ✅ safe |
| Pharmacy | English | Refill is ready, nothing to pay over the phone | 5 | ✅ safe |
| Fake grandson "Danny" | English | In jail, wants gift cards, "don't tell Mom" | 92 | ✅ likely scam |
| Fake Social Security officer | Spanish | "Your number was suspended," wants Bitcoin | 85 | ✅ likely scam |

- **Accuracy:** 4 out of 4, about 1 second per check.
- **Other languages:** the same grandson scam gets caught in Spanish and in Haitian Creole (score 85 each).
- **Caller research:** for the real Social Security, IRS and Medicare numbers (scammers love to fake these on caller ID), Tavily warned about scam calls every time. Scam warnings now come from places like the FBI and AARP instead of random posts.
- **From score to alert:** playing the fake grandson call line by line, the score went from 30 to 85 and the family alert fired the moment "Danny" said he was arrested and needed bail. It fired only once, and Tavily pulled warnings from AARP, the FCC and the BBB.
- **Tests:** 67 automated tests run on GitHub for every change (that's the green badge at the top).

## Built with

| Tool | What we use it for |
|---|---|
| **NVIDIA Nemotron** | The brain. Nemotron 3.5 Lightning reads the transcript, scores the scam risk, explains why, and writes the family alert in their language. |
| **Nebius Token Factory** | Runs Nemotron for us through a fast, OpenAI compatible API with structured JSON output. |
| **Tavily** | Real-time web search: reports about the caller's number, and scam warnings from trusted sites. |
| **Twilio** | Phone number, live call transcription, text alerts, and the family "Is it really you?" texts. |
| **FastAPI** (Python) | Our backend server, which also hosts the dashboard. |

## Getting started

### 1. What you need

- Python 3.11 or newer
- API keys from:
  - [Nebius Token Factory](https://tokenfactory.nebius.com/) (for Nemotron)
  - [Tavily](https://app.tavily.com/)
  - [Twilio](https://www.twilio.com/) (only for real phone calls; a trial account can't send custom text messages, so real alerts need an upgraded account)

### 2. Install

```bash
git clone https://github.com/angiebecerra020/scam-shield.git
cd scam-shield
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Add your keys

```bash
cp .env.example .env
```

Then open `.env` and paste your keys after each `=`. The `.env` file is never uploaded to GitHub.

### 4. Check that everything works

Each of these prints PASS or FAIL:

```bash
python scripts/test_nemotron.py     # Nemotron answers fast and catches a scam
python scripts/test_tavily.py       # Tavily checks phone numbers and finds scam warnings
python scripts/test_languages.py    # scams get caught in Spanish and Haitian Creole
```

### 5. Run it

```bash
uvicorn app.main:app --reload
```

Open <http://localhost:8000> in your browser.

### 6. Run the tests

```bash
pytest
```

## Demo

*Coming soon.*

- **Try the consent check and "Join call" now (no phone needed):** with `DEMO_MODE=true`, open <http://localhost:8000>, sign someone up, then use the dashed **Demo mode** buttons to pretend the senior texted YES and a scam call started. Open the "Join call" link to see the family's side. Texts and calls that would have gone out are listed at <http://localhost:8000/api/demo/outbox>.
- **Backup demo (no phone needed):** with `DEMO_MODE=true`, Scam Shield plays a scripted scam call as if it were live, so you can watch the risk score climb and the family alert go out.
- **Live demo:** a teammate calls the Scam Shield number and acts out a scam script.

**Privacy and consent:** our demos use **simulated calls only**, with scripts and teammates. Florida, where we're based, requires everyone on a call to agree before it's recorded, so we never record or transcribe real people without their consent.

## Project structure

```text
scam-shield/
├── app/                   # Python backend
│   ├── main.py            # web server and routes
│   ├── config.py          # loads settings and API keys from .env
│   ├── detector.py        # Nemotron scam scoring
│   ├── call_monitor.py    # checks live calls and sends the family alert at 70 or more
│   ├── research.py        # Tavily caller checks and scam warnings
│   ├── alerts.py          # Twilio text messages
│   ├── consent.py         # senior's YES/NO before we ever listen
│   ├── calls.py           # conference rooms + "Join call" 3-way calls
│   ├── storage.py         # SQLite database: sign-ups and calls
│   ├── phone_numbers.py   # cleans up phone numbers (+1XXXXXXXXXX)
│   ├── twilio_security.py # checks webhooks really came from Twilio
│   ├── verify.py          # "Is it really you?" check
│   ├── languages.py       # each person's language + translations
│   └── demo_mode.py       # loads the sample calls and plays them like they're live
├── static/                # family dashboard (HTML, CSS, JavaScript)
├── data/test_scripts/     # sample scam calls and normal calls (English and Spanish)
├── scripts/               # day one checks for Nemotron, Tavily and languages
├── tests/                 # automated tests (pytest)
├── .github/workflows/     # runs the tests on GitHub for every change
├── .env.example           # template for your settings (no real keys)
└── requirements.txt       # Python libraries we use
```

## Setting up Twilio for real calls

Point your Twilio number's webhooks at your public URL (`PUBLIC_BASE_URL`, e.g. an ngrok address):

- **A message comes in** → `POST {PUBLIC_BASE_URL}/twilio/sms` (seniors' YES/NO replies)
- **A call comes in** → `POST {PUBLIC_BASE_URL}/twilio/voice`

With `DEMO_MODE=false`, every webhook must carry Twilio's signature, so nobody can fake a senior's YES.

## What's next

- The demo player: Grandma's phone, the live transcript, and the risk meter climbing line by line
- More languages: Vietnamese and Chinese
- A spoken warning to the senior during the call
- Trusted contact setup the family can do in two minutes from their phone

## Team

- **Angie**: product, integration, testing
- **Cass**: builder

## License

MIT. See [LICENSE](LICENSE).
