"""
research.py — Looks things up on the web with Tavily while a call is happening.

How it fits in: when a call comes in, we ask Tavily two questions and pass the
answers to the detector (detector.py) and the family dashboard:
  1. "Has anyone reported this caller's phone number as a scam?"
  2. "Is there current news about a scam that matches what the caller is saying?"
     (for example, "grandparent scam gift cards")
We keep the source links so the family can see WHY we're worried.

Coming soon (Step 2 tests first, then this module in a later step).
"""
