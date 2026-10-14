<!--
  README.md — The front page of the Scam Shield repo.
  Explains the problem, what Scam Shield does, how it works, and how to run it.
-->

# 🛡️ Scam Shield

**Catches scam phone calls while they're happening, and alerts the family in their own language.**

Scam Shield follows a senior's phone call through a live transcript, checks the caller against the web, and uses **NVIDIA Nemotron** on **Nebius Token Factory** to spot the warning signs of a scam: gift cards, secrecy, urgency, a "grandchild" in trouble. When the risk is high, the family gets a text right away, in English or Spanish, with a link to join the call.

> 🚧 **Work in progress** for the Nebius x NVIDIA Global AI Hackathon. Parts marked *Coming soon* are being built now.

---

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
| 2 | **Caller research.** Tavily checks whether the caller's number has been reported, and finds current scam news that matches the call. | Coming soon |
| 3 | **AI scam score.** NVIDIA Nemotron scores the risk from 0 to 100 and explains why: gift cards, secrecy, urgency, a fake grandchild, "your Social Security number is suspended". | Coming soon |
| 4 | **"Is it really you?"** If the caller claims to be family, we text the real person: *"Are you calling Grandma? YES / NO."* If they say NO, we warn the senior. | Coming soon |
| 5 | **Family alert.** A live text message in the family member's own language, with a "Join call" link. | Text + link done; triggered by the AI score soon |
| 5b | **Join the call (3-way call).** Protected calls run through a conference room. Tapping "Join call" rings the family member's own phone and adds them to the call. Everyone hears a tone when they join. | Done |
| 6 | **Family dashboard.** A live risk meter, the reasons, source links, and call history. | Coming soon |
| 7 | **Bilingual.** English and Spanish first. | Coming soon |
| ★ | **Demo mode.** Replays a scripted call as a live transcript, with no real phone call needed. | Coming soon |

## How it works

```text
  Sign-up: family enters the senior's number
       |  we text the SENIOR: "Reply YES or NO"
       |  only a YES from the senior's own phone turns protection on
       v
  Senior's phone
       |  calls forward to
       v
  Twilio number ----> live transcript (what the caller says, line by line)
       |
       |---> Tavily: has this number been reported? any matching scam news today?
       |
       |---> NVIDIA Nemotron (on Nebius Token Factory):
       |        risk score 0-100 + reasons + who the caller claims to be
       |
       |---> "Is it really you?": caller says he's grandson Danny?
       |        text the REAL Danny: "Are you calling Grandma? YES / NO"
       |        NO  ->  warn Grandma right away
       v
  Family
       - text alert in THEIR language + "Join call" link
         (tap it -> we ring the family's phone into the call: a 3-way call)
       - live dashboard: risk meter, reasons, source links, call history
```

## Built with

| Tool | What we use it for |
|---|---|
| **NVIDIA Nemotron** | The brain. Reads the transcript, scores the scam risk, explains why, and writes the family alert in their language. |
| **Nebius Token Factory** | Runs Nemotron for us through a fast, OpenAI-compatible API. |
| **Tavily** | Real-time web search: reports about the caller's number and current scam news. |
| **Twilio** | Phone number, live call transcription, text alerts, and the family "Is it really you?" texts. |
| **FastAPI** (Python) | Our backend server, which also hosts the dashboard. |

## Getting started

### 1. What you need

- Python 3.11 or newer
- API keys from:
  - [Nebius Token Factory](https://tokenfactory.nebius.com/) (for Nemotron)
  - [Tavily](https://app.tavily.com/)
  - [Twilio](https://www.twilio.com/) (a trial account can't send custom text messages; real alerts need an upgraded account)

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

### 4. Run it

```bash
uvicorn app.main:app --reload
```

Open <http://localhost:8000> in your browser.

### 5. Run the tests

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
│   ├── main.py            # web server + routes
│   ├── config.py          # loads settings and API keys from .env
│   ├── detector.py        # Nemotron scam scoring
│   ├── research.py        # Tavily number + scam news lookups
│   ├── alerts.py          # Twilio text messages
│   ├── consent.py         # senior's YES/NO before we ever listen
│   ├── calls.py           # conference rooms + "Join call" 3-way calls
│   ├── storage.py         # SQLite database: sign-ups and calls
│   ├── phone_numbers.py   # cleans up phone numbers (+1XXXXXXXXXX)
│   ├── twilio_security.py # checks webhooks really came from Twilio
│   ├── verify.py          # "Is it really you?" check
│   ├── languages.py       # each person's language + translations
│   └── demo_mode.py       # plays scripted calls as if live
├── static/                # family dashboard (HTML, CSS, JavaScript)
├── data/test_scripts/     # scripted scam + normal calls (English/Spanish)
├── scripts/               # day-1 checks for each outside service
├── tests/                 # automated tests (pytest)
├── .env.example           # template for your settings (no real keys)
└── requirements.txt       # Python libraries we use
```

## Setting up Twilio for real calls

Point your Twilio number's webhooks at your public URL (`PUBLIC_BASE_URL`, e.g. an ngrok address):

- **A message comes in** → `POST {PUBLIC_BASE_URL}/twilio/sms` (seniors' YES/NO replies)
- **A call comes in** → `POST {PUBLIC_BASE_URL}/twilio/voice`

With `DEMO_MODE=false`, every webhook must carry Twilio's signature, so nobody can fake a senior's YES.

## What's next

- More languages: Haitian Creole, then Vietnamese and Chinese
- A spoken warning to the senior during the call
- Trusted-contact setup the family can do in two minutes from their phone

## Team

- **Angie**: product, integration, testing
- **Cass**: builder

## License

MIT. See [LICENSE](LICENSE).
