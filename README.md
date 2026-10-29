<!--
  README.md is the front page of the Scam Shield repo. It explains the problem,
  what Scam Shield does, how it works, and how to run it.
-->

# 🛡️ Scam Shield

[![Tests](https://github.com/angiebecerra020/scam-shield/actions/workflows/tests.yml/badge.svg)](https://github.com/angiebecerra020/scam-shield/actions/workflows/tests.yml)

**Catches scam phone calls while they're happening, and alerts the family in their own language.**

Scam Shield follows a senior's phone call through a live transcript, checks the caller against the web, and uses **NVIDIA Nemotron** on **Nebius Token Factory** to spot the warning signs of a scam: gift cards, secrecy, urgency, a "grandchild" in trouble. When the risk is high, the family gets an alert right away, in their own language, with a link to join the call.

**🌐 Try it: <https://scam-shield-ity3.onrender.com>**
- **[Watch a scam get caught](https://scam-shield-ity3.onrender.com/demo):** play a scripted scam call and watch Nemotron score it line by line. No phone or account needed.
- **[Call it yourself](https://scam-shield-ity3.onrender.com/try):** call our number from your own phone, play the scammer, and watch it catch you live.
- Family sign up, log in and the family dashboard are on the same site. It runs in demo mode, so no real texts go out and the family is made up.

> 🚧 **Work in progress** for the Nebius x NVIDIA Global AI Hackathon. Parts marked *Coming soon* are being built now.

## The problem

In 2025, Americans aged 60 and older reported **$7.7 billion** in fraud losses to the FBI, up about 60% from 2024, more than any other age group. ([FBI Internet Crime Complaint Center](https://www.ic3.gov/), [AARP summary](https://www.aarp.org/money/scams-fraud/fbi-ftc-report-2025-losses))

Phone scams work because they're **fast and emotional**:

> *"Grandma, it's me, Danny. I'm in trouble. Please don't tell Mom. Can you get $2,000 in gift cards?"*

Call blockers only stop numbers that are already known to be bad. Banks and family members usually find out **after** the money is gone. Scam Shield steps in **during the call**, while there's still time to stop it.

## What it does

| # | Feature | Status |
|---|---|---|
| 0 | **Senior's OK first.** When a family member signs someone up, we ask the senior on their own phone, by text (*"Reply YES or NO"*) or by phone call (*"Press 1 to allow, 2 to say no"*). The family picks which on the sign-up form; a landline can't get texts, so it always gets the call. Nothing is listened to until they say YES. | Done |
| 0b | **Works on cell phones and landlines.** The senior keeps their number. Calls forward to Scam Shield, which rings a calling app on their cell phone or an adapter on their home phone. See [Cell phone or landline?](#cell-phone-or-landline) | Done (needs a real-phone test) |
| 1 | **Live transcript.** The senior's calls forward to a Scam Shield number, which turns the call into text as it happens. | Working on our "Call it yourself" test line (Twilio live transcription). Forwarded calls coming soon |
| 2 | **Caller research.** Tavily checks whether the caller's number has been reported, and finds scam warnings that match the call. It looks at trusted sites first: the FTC, FBI, Social Security, Medicare, AARP and the BBB. | Done |
| 3 | **AI scam score.** NVIDIA Nemotron scores the risk from 0 to 100 and explains why: gift cards, secrecy, urgency, a fake grandchild, "your Social Security number is suspended". | Done |
| 4 | **"Is it really you?"** If the caller claims to be family, we text the real person: *"Are you calling Grandma? YES / NO."* If they say NO, we warn the senior. | Done in the demo player and the test line (on screen; real texts need US carrier sign-up) |
| 5 | **Family alert.** A text message in the family member's own language, with a "Join call" link and the top red flags. It goes out the first time the AI score hits 70. | Done (runs on live calls once the live transcript is ready) |
| 5b | **Join the call (3-way call).** Protected calls run through a conference room. Tapping "Join call" rings the family member's own phone and adds them to the call. Everyone hears a tone when they join. | Done |
| 6 | **Family dashboard.** Everyone you protect, their past calls (score, reasons, who the caller said they were, and Tavily links), a "Was this a scam?" answer for each call, and a button to pause protection. Each family only sees the people they signed up. | Call history and pause ready, live risk meter coming soon |
| 6b | **Report and block.** For a scam call, the dashboard writes up the details ready to paste into the FTC's report form ([reportfraud.ftc.gov](https://reportfraud.ftc.gov/)). The family also picks what happens if that number calls again: **warn us** (the call rings and the family is alerted the moment it starts) or **block it** (a busy signal, and it never rings). Each family has their own list. | Done |
| 7 | **Languages.** Text alerts in English, Spanish and Haitian Creole. Haitian Creole calls use the bigger Nemotron 3 Ultra so the alert is written in real Creole. Every screen has an **English / Español** switch, and the site remembers the choice (it starts in Spanish if the phone is set to Spanish). | Done. Haitian Creole is in the sign-up menus and texts. It's text only for now (our phone voices can't speak Creole), so a Creole-speaking senior needs a cell phone. The Creole texts are waiting on a check from a native speaker. |
| ★ | **Demo mode.** No real calls or texts go out: they're saved so you can see them. The demo player replays a scripted call as a live transcript. | Done, with 20 sample calls |
| ★ | **Call it yourself.** Get a code at `/try`, call our Scam Shield number from your own phone, and play the scammer. Twilio turns your words into text, Nemotron scores every sentence, Scam Shield says Grandma's warning out loud on the call, and Ana's alert can be emailed to you. The same number works as "Add Scam Shield to a call": add it as a 3-way call and type the code. | Done |

## How it works

```text
  Sign-up: family enters the senior's number and phone type
       |  we ask the SENIOR: a text (cell) or a phone call (landline)
       |  only a YES from the senior's own phone turns protection on
       v
  Anyone calls the senior's usual number
       |  their phone company forwards every call to
       v
  Twilio number, which rings the senior's calling app (cell) or adapter (landline)
       |  and turns the call into a live transcript
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
       - dashboard: call history with the score, reasons and source links
         (a live risk meter is coming soon)
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

**Scam detection** on 20 test calls we wrote, 10 scams and 10 normal calls in English and Spanish (run it yourself with `pytest tests/test_detector.py -s -k accuracy`, and see them all in [data/test_scripts](data/test_scripts/README.md)):

| Kind of call | Examples | Scores | Result |
|---|---|---|---|
| 10 scams | fake grandson in jail, fake IRS, fake Medicare, fake Microsoft support, fake bank "safe account", romance scam, fake electric company, fake sweepstakes, fake lawyer with cash pickup, fake Social Security | 85 to 92 | ✅ all caught |
| 7 normal calls | pharmacy, doctor's office, church friend, neighbor, delivery driver, cable company, granddaughter | 5 to 15 | ✅ all safe |
| 3 tricky normal calls | the real bank checking a charge, the real grandson asking for a ride, a daughter depositing money | 15 | ✅ all safe |

- **Accuracy:** 20 out of 20, about 1 second per check. These are calls we wrote ourselves, so the next step is testing with more people's scripts.
- **Other languages:** the same grandson scam gets caught in Spanish and in Haitian Creole (score 85 each).
- **Caller research:** for the real Social Security, IRS and Medicare numbers (scammers love to fake these on caller ID), Tavily warned about scam calls every time. Scam warnings now come from places like the FBI and AARP instead of random posts.
- **From score to alert:** playing the fake grandson call line by line, the score went from 30 to 85 and the family alert fired the moment "Danny" said he was arrested and needed bail. It fired only once, and Tavily pulled warnings from AARP, the FCC and the BBB.
- **Tests:** more than 120 automated tests run on GitHub for every change (that's the green badge at the top).

## Learning from the family's answers

Every call on the dashboard asks the family **"Was this a scam?"**: *Yes, it was a scam* or *No, false alarm*. We save the answer with the call, next to the score and the reasons Nemotron gave. That's the first step toward a Scam Shield that gets smarter on its own:

- **Find where we're wrong.** Calls the family calls a false alarm, but we scored 70 or more, show what scares the detector for no reason. Calls they call a scam, but we scored low, show what it missed. Both are listed by the reasons Nemotron gave, so we can see which red flags work and which don't.
- **Tune the alert line.** If families keep saying "false alarm" for calls in the 70s, the line where we alert (70 today) can move.
- **Teach Nemotron.** The best examples become new test calls in [data/test_scripts](data/test_scripts/README.md), and short examples in Nemotron's instructions, so each fix is checked by our accuracy test before it ships.

Today we save the answer, the score and the reasons, but **not what was said on the call**. Turning real calls into examples would need the family's clear OK first, and we'd remove names and numbers before keeping anything.

## Built with

| Tool | What we use it for |
|---|---|
| **NVIDIA Nemotron** | The brain. Nemotron 3.5 Lightning reads the transcript, scores the scam risk, explains why, and writes the family alert in their language. |
| **Nebius Token Factory** | Runs Nemotron for us through a fast, OpenAI compatible API with structured JSON output. |
| **Tavily** | Real-time web search: reports about the caller's number, and scam warnings from trusted sites. |
| **Twilio** | Phone number, forwarded calls and 3-way "Join call" calls, the senior's consent text or call, and the family alerts. Live call transcription and the "Is it really you?" texts are coming soon. |
| **FastAPI** (Python) | Our backend server, which also hosts the dashboard. |
| **Supabase** | Family accounts: sign up and log in with an email and password. |
| **Vercel** | Hosts the live site. |

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

Open <http://localhost:8000> in your browser. That's the landing page. The family dashboard is at <http://localhost:8000/dashboard>.

**Family logins (optional):** families sign up and log in with an email and password, kept by [Supabase](https://supabase.com/) (free). Make a Supabase project, then copy its URL and publishable key into `.env` as `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. In Supabase, under Authentication, then URL Configuration, set the Site URL to your app's address so the "confirm your email" link comes back to us. Leave both settings blank and login is off: the dashboard is open to anyone.

### 6. Run the tests

```bash
pytest
```

## Demo

**On the live site:** open <https://scam-shield-ity3.onrender.com>, tap **Log in** in the header (on a phone it's under **Menu**), and make an account. Then follow the steps below from "sign someone up". We host on Render because the live demo and the phone line need one always-on server that remembers each call (and a disk, so the database doesn't reset).

- **Try the consent check and "Join call" now (no phone needed):** with `DEMO_MODE=true`, open <http://localhost:8000/dashboard>, sign someone up (pick cell phone or landline), then use the dashed **Demo mode** buttons to pretend the senior said YES and a scam call started. The dashboard then shows the setup steps for that kind of phone. Open the "Join call" link to see the family's side. Texts and calls that would have gone out are listed at <http://localhost:8000/api/demo/outbox>. Back on the dashboard, **Your family** lists everyone you protect, with their past calls: tap a call to see its score, the reasons and the Tavily links. **Pause protection** turns listening off (calls still ring like normal) until you turn it back on.
- **Demo player** (`/demo`): pick one of our sample calls and watch it play line by line as if it were live: the risk score climbs, the family alert goes out, Danny gets "Is it really you?", and Grandma hears a spoken warning.
- **Call it yourself** (`/try`): get a code, call the number on the page, type the code, and play a scammer calling Grandma Rosa. You watch the transcript and the score on the page while you talk, Scam Shield says the warning out loud on the call, and if you type your email you get Ana's alert. Calls last up to 5 minutes, and we never save the audio or your phone number. To run it yourself, point your Twilio number's **A call comes in** webhook at `https://<your site>/twilio/line/incoming` (POST), and add `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` to `.env` for the emails.
- **Live demo:** a teammate calls the Scam Shield number and acts out a scam script. Another teammate plays the senior with the calling app open in a browser, so no forwarding or adapter is needed on stage.

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
│   ├── devices.py         # rings the senior's calling app (cell) or adapter (landline)
│   ├── storage.py         # SQLite database: sign-ups and calls
│   ├── phone_numbers.py   # cleans up phone numbers (+1XXXXXXXXXX)
│   ├── twilio_security.py # checks webhooks really came from Twilio
│   ├── auth.py            # family logins: checks Supabase login tokens
│   ├── family.py          # family dashboard: call history, call details, pause and resume
│   ├── verify.py          # "Is it really you?" check (coming soon)
│   ├── languages.py       # each person's language + translations
│   └── demo_mode.py       # loads the sample calls for the tests and the demo
├── static/                # landing page, login, family dashboard, "Join call" page, senior's calling app, the tabs on top of every page (nav.js, header.css), and every word in English and Spanish (strings.js)
├── data/test_scripts/     # 20 sample scam calls and normal calls (English and Spanish)
├── scripts/               # day one checks for Nemotron, Tavily and languages
├── tests/                 # automated tests (pytest)
├── .github/workflows/     # runs the tests on GitHub for every change
├── .env.example           # template for your settings (no real keys)
└── requirements.txt       # Python libraries we use
```

## Cell phone or landline?

Seniors keep the phone number they already have, whether it's a cell phone or a landline. Every call to it forwards to the Scam Shield number. Scam Shield can't ring the senior back on that same number, because the call would just forward to us again in a loop. So Scam Shield rings a **private device** that only it can reach:

| | Cell phone | Landline (home phone) |
|---|---|---|
| **How we ask for their OK** | A text: reply YES or NO | A phone call: press 1 or 2 (landlines can't get texts) |
| **What rings** | Our calling app (`/phone/<link>`) on their phone | Their own home phone, plugged into a small adapter |
| **Extra hardware** | None | A phone adapter (ATA), about $40. Homes without internet need one that uses cell data, about $100 |
| **Their outgoing calls** | Unchanged | Go through Scam Shield and still show their own number |
| **Turning it off** | Dial `##21#` (Verizon: `*73`), or text STOP | Plug the phone back into the wall jack and dial `*73` |

**Order matters for both:** ask for their OK *before* turning on forwarding. Once forwarding is on, our consent text still arrives, but our consent call to a landline would forward back to us instead of ringing them.

### Setting up a cell phone

1. Sign up on the dashboard and choose **Cell phone**. Under **How should we ask them?**, pick a text (the senior replies YES) or a phone call (the senior presses **1**).
2. On the senior's phone, open the calling-app link the dashboard shows, tap **Turn on calls**, allow the microphone, and add the page to the home screen. Keep it open, since calls only ring while the page is running.
3. Turn on call forwarding to the Scam Shield number. On most phones, dial `**21*` + the number + `#`. On Verizon, dial `*72` + the number.

If the app isn't open (or the phone has no internet), the caller hears "the person you are calling is not available."

### Setting up a landline

If the senior has a landline rather than a cell phone, there are a few extra steps, and the order matters:

1. Sign up on the dashboard and choose **Landline (home phone)**. We **call** the landline, and the senior presses **1** to say yes.
2. **Verify their number in Twilio** so their outgoing calls can show it (Twilio Console → Phone Numbers → Verified Caller IDs). Twilio calls the landline with a code. Do this before step 4, while calls still reach the home phone normally.
3. **Set up the adapter.** Plug it into the internet router and sign it in to our SIP domain with the username the dashboard shows. The password is the one you set for that username in Twilio (see the Twilio setup below).
4. **Turn on forwarding.** With the phone still plugged into the wall jack, pick it up and dial `*72` then the Scam Shield number. Wait for the tone and hang up.
5. **Move the phone.** Unplug the home phone from the wall and plug it into the adapter. It rings and dials just like before.

> ⚠️ **911 on a landline adapter:** once the phone is on the adapter, 911 calls go through Scam Shield's Twilio number, not the wall jack. **Register the senior's home address as the emergency address on the Twilio number** (Twilio Console → Phone Numbers → Emergency Calling) before anyone relies on it. Without that, emergency services can't find them. Until this is done for a home, don't move a real senior's phone onto the adapter.

## Setting up Twilio for real calls

Point your Twilio number's webhooks at your public URL (`PUBLIC_BASE_URL`, e.g. an ngrok address):

- **A message comes in** → `POST {PUBLIC_BASE_URL}/twilio/sms` (seniors' YES/NO replies)
- **A call comes in** → `POST {PUBLIC_BASE_URL}/twilio/voice`

For cell phones (the calling app), create an **API key** (Console → Account → API keys & tokens) and put it in `.env` as `TWILIO_API_KEY_SID` and `TWILIO_API_KEY_SECRET`.

For landlines (the adapter):

1. Create a **SIP domain** (Console → Voice → Manage → SIP domains), e.g. `scamshield.sip.twilio.com`, and put it in `.env` as `TWILIO_SIP_DOMAIN`.
2. Turn on **SIP registration** for the domain, and add a credential list with one username + password per senior (the username is the one the dashboard shows).
3. Set the domain's **A call comes in** webhook → `POST {PUBLIC_BASE_URL}/twilio/adapter-call` (the senior's outgoing calls).

With `DEMO_MODE=false`, every webhook must carry Twilio's signature, so nobody can fake a senior's YES.

## What's next

- Live transcription on forwarded calls, so protection is always on without the senior adding Scam Shield to the call
- Real text alerts once our US carrier sign-up is approved (email for now)
- More languages: Vietnamese and Chinese
- Trusted contact setup the family can do in two minutes from their phone
- A phone app (App Store and Google Play), so a blocked number is blocked on the phone itself too, including texts. Today our block works on calls that come through Scam Shield, and the dashboard shows the steps to block a number in the phone's settings.

## Team

- **Angie**: product, integration, testing
- **Cass**: builder

## License

MIT. See [LICENSE](LICENSE).
