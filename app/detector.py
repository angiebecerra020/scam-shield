"""
detector.py — The "brain" of Scam Shield: asks NVIDIA Nemotron how likely a
call is to be a scam, and why.

How it fits in: the live call pipeline (and demo mode) send the call transcript
here. We send it to Nemotron on Nebius Token Factory and get back:
  - a risk score from 0 (safe) to 100 (almost certainly a scam)
  - a verdict, e.g. "likely scam"
  - the reasons: gift cards, secrecy ("don't tell Mom"), urgency, a "grandchild"
    in trouble, "your Social Security number is suspended", and so on
  - who the caller claims to be, e.g. "grandson Danny" (used by verify.py)
  - a short alert message for the family (sent by alerts.py)

Coming soon (Step 3, tracker T9–T10):
  score_call(transcript, language) -> {
      "risk_score": 0-100,
      "verdict": "...",
      "reasons": ["..."],
      "claimed_identity": "grandson Danny" or None,
      "family_alert_message": "...",
  }
"""
