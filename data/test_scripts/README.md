<!--
  This README explains what goes in the data/test_scripts folder.
-->

# Test call scripts

Scripted phone calls, written by our team. We use them to:

- **Test the scam detector.** `tests/test_detector.py` runs every script and prints an accuracy table.
- **Run the backup demo.** `app/demo_mode.py` plays a script as if it were a live call.

They're fiction: no real calls and no real people. Phone numbers use 555-01XX, which is reserved for fiction.

## The 20 calls

We have 10 scams and 10 normal calls, in English and Spanish. Three of the normal calls are **tricky** on purpose: they sound scary (a bank, a grandson, money) but they're real, so they check that we don't freak out over every call.

**Scams**

| File | Language | What happens |
|---|---|---|
| `scam_grandparent_en.json` | English | "Danny" is in jail and needs gift cards, and says don't tell Mom |
| `scam_ssn_es.json` | Spanish | Fake Social Security officer: "your number was suspended," wants Bitcoin |
| `scam_tech_support_en.json` | English | Fake Microsoft support: a virus, a remote access app, and a gift card fee |
| `scam_medicare_es.json` | Spanish | Fake Medicare: a "new chip card," wants Medicare, Social Security and bank numbers |
| `scam_irs_en.json` | English | Fake IRS: back taxes, police coming in two hours, gift cards |
| `scam_bank_safe_account_en.json` | English | Fake bank fraud team: "read me the code," move money to a "safe account" |
| `scam_romance_en.json` | English | Online sweetheart stuck at customs, wants Bitcoin, "don't tell your kids" |
| `scam_utility_es.json` | Spanish | Fake electric company: power cut in 30 minutes unless she pays with a prepaid card |
| `scam_sweepstakes_en.json` | English | "You won $2.5 million," just wire the fees first |
| `scam_lawyer_cash_pickup_es.json` | Spanish | Fake lawyer: grandson in jail, a courier picks up the cash at her door |

**Normal calls**

| File | Language | What happens |
|---|---|---|
| `normal_pharmacy_en.json` | English | Pharmacy says a refill is ready, and asks for nothing over the phone |
| `normal_granddaughter_es.json` | Spanish | Real granddaughter Sofía calls about Sunday lunch |
| `normal_doctor_reminder_es.json` | Spanish | The doctor's office reminds her about an appointment |
| `normal_bank_real_alert_en.json` | English | **Tricky:** the real bank checks a charge and asks for nothing |
| `normal_grandson_ride_en.json` | English | **Tricky:** the real grandson asks for a ride, and gas money comes up |
| `normal_church_es.json` | Spanish | A church friend asks her to bring food on Sunday |
| `normal_delivery_en.json` | English | The delivery driver left her package with a neighbor |
| `normal_neighbor_es.json` | Spanish | The neighbor asks if she needs anything from the store |
| `normal_cable_appointment_en.json` | English | The cable company confirms a repair visit |
| `normal_daughter_deposit_es.json` | Spanish | **Tricky:** her daughter deposits money for her medicine |

**Latest result:** 20 out of 20 right, about 1 second per call. Scams scored 85 to 92 and normal calls scored 5 to 15.

## How to write a new script

Make a `.json` file in this folder. Name it `scam_...` or `normal_...` plus the language, like `scam_fake_charity_en.json`:

```json
{
  "id": "scam_fake_charity_en",
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

Have an idea for a new scam or a tricky normal call? Add it here and run `pytest tests/test_detector.py -s -k accuracy` to see how the detector does.
