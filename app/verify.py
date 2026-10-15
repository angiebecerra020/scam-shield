"""
verify.py

This is the "Is it really you?" check.

How it fits in: if the detector (detector.py) sees that the caller says
they're family ("Grandma, it's me, Danny!"), this file:
  1. looks up the REAL Danny's phone number in the family's contact list
  2. texts him through alerts.py: "Are you calling Grandma right now? YES or NO"
  3. waits for his answer
  4. if he says NO, or the call is really risky and he doesn't answer in time,
     we warn the senior right away

This one check stops the most common scam on older adults, the "grandparent
scam", because the scammer can't fake the real grandkid's answer.

Coming soon.
"""
