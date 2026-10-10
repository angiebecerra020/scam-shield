"""
demo_mode.py — Plays a scripted phone call as if it were happening live.

How it fits in: this is our BACKUP DEMO. It reads a call script from
data/test_scripts/ and sends it into the app one line at a time, with
realistic pauses, exactly as if a real call were being transcribed. The
detector, alerts and dashboard can't tell the difference.

Why we need it:
  - Florida law says everyone on a call must agree before it's recorded, so we
    never use real calls. Scripted calls are always safe to show.
  - If the phone line, Wi-Fi or Twilio fails during judging, the demo still works.

Turned on with DEMO_MODE=true in .env.

Coming soon (a later step).
"""
