"""
storage.py — Saves sign-ups and phone calls in a small database file (SQLite).

How it fits in: Scam Shield has to remember two things between requests:
  - enrollments: who signed up to protect whom, and whether the senior said
    YES to having their calls watched (see consent.py)
  - calls: each call we're watching, the conference "room" it lives in, the
    secret link the family uses to join it (see calls.py), and how risky it
    got, so the family dashboard can show past calls (see family.py)
  - scam_numbers: numbers a family reported as scams, and whether to warn
    them or block the call if that number calls again (see calls.py)

SQLite comes with Python, so there's nothing extra to install. The file's
location comes from DATABASE_PATH in .env (see config.py).
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings

# The tables we need. "IF NOT EXISTS" means running this again is harmless.
SCHEMA = """
CREATE TABLE IF NOT EXISTS enrollments (
    id            TEXT PRIMARY KEY,  -- random, hard to guess (it's in URLs)
    senior_name   TEXT NOT NULL,
    senior_phone  TEXT NOT NULL,     -- E.164, e.g. +13055550100
    family_name   TEXT NOT NULL,
    family_phone  TEXT NOT NULL,
    phone_type    TEXT NOT NULL,     -- "cell" or "landline"
    ask_by        TEXT,              -- "text" or "call": how we asked for their YES
    device_id     TEXT NOT NULL,     -- name of the senior's app or adapter at Twilio
    device_key    TEXT NOT NULL,     -- secret part of the calling-app link
    senior_language TEXT NOT NULL,   -- "en" or "es"
    family_language TEXT NOT NULL,
    status        TEXT NOT NULL,     -- pending / active / paused / declined / expired / revoked
    created_at    TEXT NOT NULL,
    answered_at   TEXT,              -- when the senior replied YES or NO
    owner_id      TEXT               -- the family's login (Supabase user ID), NULL when login is off
);

CREATE TABLE IF NOT EXISTS calls (
    id              TEXT PRIMARY KEY,
    call_sid        TEXT,            -- Twilio's ID for the scammer's call leg
    enrollment_id   TEXT NOT NULL,
    caller_number   TEXT,
    conference_name TEXT NOT NULL,   -- the "room" all the phones join
    join_token      TEXT NOT NULL UNIQUE,  -- secret part of the "Join call" link
    status          TEXT NOT NULL,   -- live / ended
    family_called_at TEXT,           -- last time we rang the family into it
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    risk_score      INTEGER,         -- the highest score the call got, 0 to 100
    verdict         TEXT,            -- safe / suspicious / likely_scam, at that highest score
    reasons         TEXT,            -- the detector's reasons at that moment, as a JSON list
    claimed_identity TEXT,           -- who the caller said they were, like "grandson Danny"
    sources         TEXT,            -- the Tavily links we found, as a JSON list
    alerted_at      TEXT,            -- when we sent the family alert (NULL if we didn't)
    family_answer   TEXT,            -- the family's "Was this a scam?" answer: scam / not_scam
    family_answered_at TEXT,         -- when they answered (NULL if they haven't)
    scam_list       TEXT             -- "warn" or "block" if the caller was on the family's scam list
);

CREATE TABLE IF NOT EXISTS scam_numbers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id      TEXT,              -- the family who reported it (NULL when login is off)
    phone         TEXT NOT NULL,     -- the scammer's number, E.164
    action        TEXT NOT NULL,     -- "warn" or "block" when it calls again
    from_call_id  TEXT,              -- the call they reported it from
    created_at    TEXT NOT NULL
);
"""

# Columns we added after the first version of the tables. CREATE TABLE IF NOT
# EXISTS skips tables that are already there, so a database made before these
# columns existed wouldn't get them. add_missing_columns() adds them.
NEWER_COLUMNS = {
    "enrollments": {"owner_id": "TEXT", "ask_by": "TEXT"},
    "calls": {
        "risk_score": "INTEGER",
        "verdict": "TEXT",
        "reasons": "TEXT",
        "claimed_identity": "TEXT",
        "sources": "TEXT",
        "alerted_at": "TEXT",
        "family_answer": "TEXT",
        "family_answered_at": "TEXT",
        "scam_list": "TEXT",
    },
}


def now_text() -> str:
    """
    The current time as text, in UTC, so every saved time uses the same clock.

    Example:
        now_text()  ->  "2026-10-13T18:04:05+00:00"
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(text: str) -> datetime:
    """
    Turn a time saved by now_text() back into a datetime we can compare.

    Example:
        parse_time("2026-10-13T18:04:05+00:00")  ->  datetime(2026, 10, 13, 18, 4, 5, ...)
    """
    return datetime.fromisoformat(text)


def add_missing_columns(db) -> None:
    """
    Add the columns in NEWER_COLUMNS to an older database that doesn't have them yet.

    New columns start out empty (NULL) on the rows that are already there,
    which is what we want: an old call just has no score saved.

    Input:  db, an open connection
    Output: nothing

    Example:
        A database from last week has no risk_score column. After this, it does.
    """
    for table, columns in NEWER_COLUMNS.items():
        have = set()
        for row in db.execute(f"PRAGMA table_info({table})").fetchall():
            have.add(row["name"])
        for name, kind in columns.items():
            if name not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


@contextmanager
def connect():
    """
    Open the database file, creating it and its tables the first time.

    Use it in a "with" block. When the block finishes, changes are saved and
    the file is closed; if something goes wrong, the changes are thrown away.

    Input:  nothing (the file path comes from DATABASE_PATH)
    Output: an open connection. Rows come back dictionary-like, so we can
            write row["status"] instead of row[6].

    Example:
        with connect() as db:
            db.execute("SELECT COUNT(*) FROM enrollments")
    """
    path = Path(get_settings().database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        db.executescript(SCHEMA)
        add_missing_columns(db)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------


def save_enrollment(enrollment: dict) -> None:
    """
    Save a new enrollment.

    Input:  enrollment — a dict with every column of the enrollments table
                         (owner_id can be left out, it means nobody's login owns it;
                         ask_by can be left out, see consent.how_we_asked())
    Output: nothing

    Example:
        save_enrollment({"id": "abc", "senior_name": "Rosa", ..., "status": "pending"})
    """
    # Code written before logins (like the demo) doesn't set owner_id or
    # ask_by, so we fill in "no owner" and "not saved" for them.
    row = {"owner_id": None, "ask_by": None, **enrollment}
    with connect() as db:
        db.execute(
            """
            INSERT INTO enrollments (id, senior_name, senior_phone, family_name,
                family_phone, phone_type, ask_by, device_id, device_key,
                senior_language, family_language, status, created_at, answered_at,
                owner_id)
            VALUES (:id, :senior_name, :senior_phone, :family_name,
                :family_phone, :phone_type, :ask_by, :device_id, :device_key,
                :senior_language, :family_language, :status, :created_at, :answered_at,
                :owner_id)
            """,
            row,
        )


def get_enrollment(enrollment_id: str) -> dict | None:
    """
    Find one enrollment by its ID.

    Input:  enrollment_id — the random ID we gave it
    Output: the enrollment as a dict, or None if there isn't one

    Example:
        get_enrollment("abc")  ->  {"id": "abc", "status": "active", ...}
    """
    with connect() as db:
        row = db.execute(
            "SELECT * FROM enrollments WHERE id = ?", (enrollment_id,)
        ).fetchone()
    return dict(row) if row else None


def find_enrollment_by_device(column: str, value: str) -> dict | None:
    """
    Find the enrollment that owns a calling app or phone adapter.

    Input:  column — "device_id" (the name Twilio knows the device by) or
                     "device_key" (the secret in the calling-app link)
            value  — what to look for
    Output: the enrollment as a dict, or None

    Example:
        find_enrollment_by_device("device_id", "senior-1a2b3c4d")  ->  {"senior_name": "Rosa", ...}
    """
    # The column name can't be a "?" placeholder, so we only allow these two.
    if column not in ("device_id", "device_key"):
        raise ValueError(f"Can't look up enrollments by {column}")
    with connect() as db:
        row = db.execute(
            f"SELECT * FROM enrollments WHERE {column} = ?", (value,)
        ).fetchone()
    return dict(row) if row else None


def find_enrollments_for_senior(senior_phone: str) -> list[dict]:
    """
    List every enrollment for one senior's phone, newest first.

    Input:  senior_phone — E.164 number, e.g. "+13055550100"
    Output: a list of enrollment dicts (empty if nobody signed them up)

    Example:
        find_enrollments_for_senior("+13055550100")  ->  [{"status": "pending", ...}]
    """
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM enrollments WHERE senior_phone = ? ORDER BY created_at DESC",
            (senior_phone,),
        ).fetchall()
    return [dict(row) for row in rows]


def find_active_enrollments() -> list[dict]:
    """
    List every enrollment where the senior said YES, newest first.

    Example:
        find_active_enrollments()  ->  [{"senior_name": "Rosa", "status": "active", ...}]
    """
    return find_enrollments_with_status(("active",))


def find_enrollments_with_status(statuses: tuple[str, ...]) -> list[dict]:
    """
    List every enrollment with one of these statuses, newest first.

    Input:  statuses, like ("active", "paused")
    Output: a list of enrollment dicts

    Example:
        find_enrollments_with_status(("active", "paused")) gives you every
        senior who said YES, even if their family paused protection
    """
    # One "?" for each status, like "?, ?" for two of them.
    marks = ", ".join("?" for _ in statuses)
    with connect() as db:
        rows = db.execute(
            f"SELECT * FROM enrollments WHERE status IN ({marks}) ORDER BY created_at DESC",
            statuses,
        ).fetchall()
    return [dict(row) for row in rows]


def find_enrollments_for_owner(owner_id: str) -> list[dict]:
    """
    List every senior one family login signed up, newest first.

    Input:  owner_id, the family's Supabase user ID
    Output: a list of enrollment dicts (empty if they haven't signed anyone up)

    Example:
        find_enrollments_for_owner("user-ana") gives you [{"senior_name": "Rosa", ...}]
    """
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM enrollments WHERE owner_id = ? ORDER BY created_at DESC",
            (owner_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def find_all_enrollments() -> list[dict]:
    """
    List every enrollment, newest first. Only used when login is off, since
    then the dashboard is open to anyone anyway.

    Example:
        find_all_enrollments() gives you [{"senior_name": "Rosa", ...}, ...]
    """
    with connect() as db:
        rows = db.execute("SELECT * FROM enrollments ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def set_enrollment_status(enrollment_id: str, status: str, answered: bool) -> None:
    """
    Change an enrollment's status, e.g. from "pending" to "active".

    Input:  enrollment_id — which enrollment
            status        — the new status
            answered      — True when this change is the senior's own reply,
                            so we record when they answered
    Output: nothing

    Example:
        set_enrollment_status("abc", "active", answered=True)
    """
    with connect() as db:
        if answered:
            db.execute(
                "UPDATE enrollments SET status = ?, answered_at = ? WHERE id = ?",
                (status, now_text(), enrollment_id),
            )
        else:
            db.execute(
                "UPDATE enrollments SET status = ? WHERE id = ?",
                (status, enrollment_id),
            )


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


def save_call(call: dict) -> None:
    """
    Save a call we've started watching.

    Input:  call — a dict with the columns of the calls table (except ended_at)
    Output: nothing

    Example:
        save_call({"id": "c1", "conference_name": "scam-shield-c1", ..., "status": "live"})
    """
    with connect() as db:
        db.execute(
            """
            INSERT INTO calls (id, call_sid, enrollment_id, caller_number,
                conference_name, join_token, status, started_at)
            VALUES (:id, :call_sid, :enrollment_id, :caller_number,
                :conference_name, :join_token, :status, :started_at)
            """,
            call,
        )


def get_call(call_id: str) -> dict | None:
    """
    Find one call by our ID for it.

    Example:
        get_call("c1")  ->  {"id": "c1", "status": "live", ...}
    """
    with connect() as db:
        row = db.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    return dict(row) if row else None


def get_call_by_join_token(join_token: str) -> dict | None:
    """
    Find a call from the secret token in a "Join call" link.

    Example:
        get_call_by_join_token("Xy7...")  ->  {"id": "c1", "status": "live", ...}
    """
    with connect() as db:
        row = db.execute(
            "SELECT * FROM calls WHERE join_token = ?", (join_token,)
        ).fetchone()
    return dict(row) if row else None


def get_call_by_conference_name(conference_name: str) -> dict | None:
    """
    Find a call from its conference room name (Twilio tells us this name).

    Example:
        get_call_by_conference_name("scam-shield-c1")  ->  {"id": "c1", ...}
    """
    with connect() as db:
        row = db.execute(
            "SELECT * FROM calls WHERE conference_name = ?", (conference_name,)
        ).fetchone()
    return dict(row) if row else None


def mark_call_ended(call_id: str) -> None:
    """
    Mark a call as over. Its "Join call" link stops working after this.

    Example:
        mark_call_ended("c1")
    """
    with connect() as db:
        db.execute(
            "UPDATE calls SET status = 'ended', ended_at = ? WHERE id = ?",
            (now_text(), call_id),
        )


def mark_family_called(call_id: str) -> None:
    """
    Remember when we rang the family member into this call, so tapping the
    link over and over doesn't ring their phone over and over.

    Example:
        mark_family_called("c1")
    """
    with connect() as db:
        db.execute(
            "UPDATE calls SET family_called_at = ? WHERE id = ?",
            (now_text(), call_id),
        )


def find_calls_for_enrollment(enrollment_id: str, limit: int = 50) -> list[dict]:
    """
    List one senior's calls, newest first, for the family dashboard.

    Input:  enrollment_id, which senior
            limit, the most calls to give back
    Output: a list of call dicts

    Example:
        find_calls_for_enrollment("abc") gives you [{"id": "c2", "risk_score": 92, ...}, ...]
    """
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM calls WHERE enrollment_id = ? ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (enrollment_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def save_call_score(call_id: str, detector_result: dict) -> None:
    """
    Save how risky a call looks, but only if it's the riskiest it's been.

    The detector checks the call over and over as it goes. The family wants to
    know how bad it GOT, so a later, calmer moment doesn't replace a high score.

    Input:  call_id, which call
            detector_result, what detector.score_call() gave back
    Output: nothing. If the detector couldn't score the call, we save nothing.

    Example:
        save_call_score("c1", {"risk_score": 92, ...}) and then
        save_call_score("c1", {"risk_score": 60, ...}) keeps 92
    """
    score = detector_result.get("risk_score")
    if score is None:
        return
    with connect() as db:
        db.execute(
            """
            UPDATE calls SET risk_score = ?, verdict = ?, reasons = ?, claimed_identity = ?
            WHERE id = ? AND (risk_score IS NULL OR risk_score <= ?)
            """,
            (
                score,
                detector_result.get("verdict"),
                json.dumps(detector_result.get("reasons") or []),
                detector_result.get("claimed_identity"),
                call_id,
                score,
            ),
        )


def save_call_sources(call_id: str, sources: list[dict]) -> None:
    """
    Save the Tavily links we found for a call.

    Input:  call_id, which call
            sources, like [{"title": "FTC: grandparent scams", "url": "https://..."}]
    Output: nothing

    Example:
        save_call_sources("c1", [{"title": "FTC warning", "url": "https://consumer.ftc.gov/..."}])
    """
    with connect() as db:
        db.execute(
            "UPDATE calls SET sources = ? WHERE id = ?",
            (json.dumps(sources), call_id),
        )


def mark_call_alerted(call_id: str) -> None:
    """
    Remember when we sent the family alert for this call, so the dashboard
    can show which calls the family was told about.

    Example:
        mark_call_alerted("c1")
    """
    with connect() as db:
        db.execute(
            "UPDATE calls SET alerted_at = ? WHERE id = ? AND alerted_at IS NULL",
            (now_text(), call_id),
        )


def save_family_answer(call_id: str, answer: str) -> None:
    """
    Save the family's answer to "Was this a scam?" for a call. A new answer
    replaces the old one, so the family can change their mind.

    Input:  call_id, which call
            answer, "scam" or "not_scam" (family.py checks it first)
    Output: nothing

    Example:
        save_family_answer("c1", "not_scam")
    """
    with connect() as db:
        db.execute(
            "UPDATE calls SET family_answer = ?, family_answered_at = ? WHERE id = ?",
            (answer, now_text(), call_id),
        )


def mark_call_scam_list(call_id: str, action: str) -> None:
    """
    Remember that this call came from a number on the family's scam list, and
    what we did about it.

    Input:  call_id, which call
            action, "warn" (we alerted the family) or "block" (we blocked it)
    Output: nothing

    Example:
        mark_call_scam_list("c1", "block")
    """
    with connect() as db:
        db.execute("UPDATE calls SET scam_list = ? WHERE id = ?", (action, call_id))


# Scam numbers: each family's own list


def find_scam_number(owner_id: str | None, phone: str) -> dict | None:
    """
    Look up a number on one family's scam list.

    Input:  owner_id, the family's login (None when login is off)
            phone, the number, E.164
    Output: {"phone", "action", ...}, or None if it isn't on their list

    Example:
        find_scam_number("user-ana", "+13055550142") gives you {"action": "block", ...}
    """
    with connect() as db:
        # "IS" instead of "=" so None (login off) matches None.
        row = db.execute(
            "SELECT * FROM scam_numbers WHERE owner_id IS ? AND phone = ?",
            (owner_id, phone),
        ).fetchone()
    return dict(row) if row else None


def save_scam_number(owner_id: str | None, phone: str, action: str, from_call_id: str) -> None:
    """
    Put a number on one family's scam list, or change what we do about it.

    Input:  owner_id, the family's login (None when login is off)
            phone, the number, E.164
            action, "warn" or "block"
            from_call_id, the call they reported it from
    Output: nothing

    Example:
        save_scam_number("user-ana", "+13055550142", "block", "c1")
    """
    with connect() as db:
        # One row per number per family: replace the old one if it's there.
        db.execute(
            "DELETE FROM scam_numbers WHERE owner_id IS ? AND phone = ?",
            (owner_id, phone),
        )
        db.execute(
            """
            INSERT INTO scam_numbers (owner_id, phone, action, from_call_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (owner_id, phone, action, from_call_id, now_text()),
        )


def remove_scam_number(owner_id: str | None, phone: str) -> None:
    """
    Take a number off one family's scam list (they reported it by mistake).

    Example:
        remove_scam_number("user-ana", "+13055550142")
    """
    with connect() as db:
        db.execute(
            "DELETE FROM scam_numbers WHERE owner_id IS ? AND phone = ?",
            (owner_id, phone),
        )
