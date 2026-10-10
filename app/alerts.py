"""
alerts.py — Sends text messages (SMS) with Twilio.

How it fits in: other parts of the app call this file whenever someone needs a
text message:
  - the family alert: "Grandma may be on a scam call right now" + a "Join call"
    link, written in the family member's own language (see languages.py)
  - the "Is it really you?" check: "Are you calling Grandma? Reply YES or NO"
    (the logic lives in verify.py; this file just sends the text)

Note: a Twilio TRIAL account can only send Twilio's pre-written template
messages, not our own text. Real alerts need an upgraded Twilio account.

Coming soon (Step 2 tests first, then this module in a later step).
"""
