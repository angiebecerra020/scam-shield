<!--
  CONTRIBUTING.md — How we build Scam Shield: project context, code style,
  and team rules. Read this before writing code.
-->

# Contributing to Scam Shield

## Project context

Scam Shield catches scam phone calls while they happen and protects older adults.
It's our entry for the **Nebius x NVIDIA Global AI Hackathon** (Devpost).

- **Deadline:** Oct 30, 2026 (team target: **Oct 29**)
- **Judging** (equal weight): Technical Implementation, Design, Potential Impact, Quality of Idea
- **Team:** Angie (product, integration, testing) and Cass (builder)

### What we're building

1. The senior's calls forward to a Twilio number, which gives us a live transcript.
2. Tavily checks the caller's number and current scam news.
3. NVIDIA Nemotron (via Nebius Token Factory) scores scam risk 0–100 and explains why (gift cards, secrecy, urgency, fake grandchild, "SSN suspended").
4. "Is it really you?": if the caller claims to be family, text the real person "Are you calling Grandma? YES/NO". If NO, warn the senior.
5. The family gets a live text alert in THEIR language, with a "Join call" link.
6. Family web dashboard: live risk meter, reasons, Tavily source links, call history.
7. English and Spanish first.

### Demo rules

- **Simulated calls only.** Florida requires all parties to consent to recording. Never record or transcribe real people.
- **Always keep the backup demo working:** `DEMO_MODE=true` plays a scripted call as a "live" transcript, with no real phone call.

## Tech stack (keep it simple)

- **Backend:** Python 3.11+, FastAPI (`app/`)
- **AI:** NVIDIA Nemotron on Nebius Token Factory, called with the `openai` Python library and a custom `base_url`. The base URL and model ID live in `.env` (`NEBIUS_BASE_URL`, `NEMOTRON_MODEL`). Never hardcode them.
- **Search:** Tavily (`tavily-python`)
- **Phone + SMS:** Twilio (`twilio`)
- **Frontend:** plain HTML/CSS/JavaScript in `static/`, served by FastAPI. No React unless truly needed. Mobile-first. Colors: black `#1C1C1C` and gold `#C9A227`.
- **Tests:** pytest

## Code style rules

1. **Every file starts with a short header comment** saying what the file does and how it fits in the system.
2. **Every function has a plain-English docstring** covering what it does, its inputs, its outputs, and an example.
3. **Comment the "why", not just the "what."** Write comments a beginner can follow.
4. **Small, readable functions.** Clear names. No clever one-liners.
5. **Never hardcode secrets.** Settings come from `.env` through `app/config.py`. Commit `.env.example`, never `.env`.
6. **Keep README.md up to date.** Mark unfinished features "Coming soon".

## Git rules

- Write clear commit messages that say what changed ("Add Nemotron scam scorer", not "wip").
- Never commit `.env`, real call audio, or real phone numbers.
- When you add a new setting, add it to `.env.example` too (with a blank value and a comment).

## Platform notes (checked Oct 2026)

- **Twilio trial accounts:** can only send Twilio's pre-written SMS templates (no custom text), can only reach verified numbers (max 5), block `<Stream>` and `<Dial><Number>`, and expire after 30 days. Real family alerts need an upgraded account plus US sender registration (toll-free verification or A2P 10DLC).
- **Twilio real-time transcription** (`<Start><Transcription>`) works on trial accounts. It's the simplest route to a live transcript.
- **Nebius Token Factory:** base URL `https://api.tokenfactory.nebius.com/v1/`. `Llama-3_1-Nemotron-Ultra-253B-v1` and `Nemotron-3-Nano-Omni` were retired on Aug 31, 2026. Current Nemotron text models: `nvidia/Nemotron-3_5-Lightning` (fast) and `nvidia/nemotron-3-super-120b-a12b` (smarter, slower).

## Useful commands

```bash
# One-time setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Every day
source .venv/bin/activate
uvicorn app.main:app --reload   # then open http://localhost:8000
pytest                          # run the tests
```
