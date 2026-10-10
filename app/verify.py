"""
verify.py — The "Is it really you?" check.

How it fits in: if the detector (detector.py) finds that the caller claims to be
a family member ("Grandma, it's me, Danny!"), this file:
  1. looks up the REAL Danny's phone number in the family's contact list
  2. texts him (through alerts.py): "Are you calling Grandma right now? YES / NO"
  3. listens for his reply
  4. if he says NO, or the call is very risky and he doesn't answer in time,
     we warn the senior right away

This one check stops the most common scam on older adults, the
"grandparent scam", because the scammer can't fake the real grandchild's reply.

Coming soon (a later step, tracker Phase 3).
"""
