<!--
  README for data/test_scripts/ — explains what goes in this folder.
-->

# Test call scripts

Scripted phone calls, written by our team. We use them to:

- **Test the scam detector.** `tests/test_detector.py` runs every script and prints an accuracy table.
- **Run the backup demo.** `app/demo_mode.py` plays a script as if it were a live call.

They're fiction: no real calls and no real people. Phone numbers use 555-01XX, which is reserved for fiction.

## The scripts so far

| File | Language | Expected | What happens |
|---|---|---|---|
| `scam_grandparent_en.json` | English | scam | "Danny" is in jail and needs gift cards, and says don't tell Mom |
| `scam_ssn_es.json` | Spanish | scam | Fake Social Security officer: "your number was suspended," wants Bitcoin |
| `normal_pharmacy_en.json` | English | normal | Pharmacy says a refill is ready, and asks for nothing over the phone |
| `normal_granddaughter_es.json` | Spanish | normal | Real granddaughter Sofía calls about Sunday lunch (tests that real family isn't flagged) |

## How to write a new script

Make a `.json` file in this folder. Name it `scam_...` or `normal_...` plus the language, like `scam_tech_support_en.json`:

```json
{
  "id": "scam_tech_support_en",
  "title": "Short description of the call",
  "language": "en",
  "expected": "scam",
  "caller_number": "+13055550150",
  "lines": [
    {"speaker": "caller", "text": "What the caller says."},
    {"speaker": "senior", "text": "What the senior answers."}
  ]
}
```

- `language`: `"en"` or `"es"`
- `expected`: `"scam"` or `"normal"`. This is what the detector SHOULD say.
- `speaker`: `"caller"` or `"senior"`

The detector's tests pick up new files automatically. If a file has a mistake, the error message names the file and the line.

**Coming soon:** Cass writes the full set of 20, including tricky ones: real family asking for a small favor, a real bank fraud-alert call, and so on.
