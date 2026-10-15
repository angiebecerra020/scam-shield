"""
storage.py — Saves sign-ups and phone calls in a small database file (SQLite).

How it fits in: Scam Shield has to remember two things between requests:
  - enrollments: who signed up to protect whom, and whether the senior said
    YES to having their calls watched (see consent.py)
  - calls: each call we're watching, the conference "room" it lives in, and
    the secret link the family uses to join it (see calls.py)

SQLite comes with Python, so there's nothing extra to install. The file's
location comes from DATABASE_PATH in .env (see config.py).
"""

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
    device_id     TEXT NOT NULL,     -- name of the senior's app or adapter at Twilio
    device_key    TEXT NOT NULL,     -- secret part of the calling-app link
    senior_language TEXT NOT NULL,   -- "en" or "es"
    family_language TEXT NOT NULL,
    status        TEXT NOT NULL,     -- pending / active / declined / expired / revoked
    created_at    TEXT NOT NULL,
    answered_at   TEXT               -- when the senior replied YES or NO
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
    ended_at        TEXT
);
"""


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
    Output: nothing

    Example:
        save_enrollment({"id": "abc", "senior_name": "Rosa", ..., "status": "pending"})
    """
    with connect() as db:
        db.execute(
            """
            INSERT INTO enrollments (id, senior_name, senior_phone, family_name,
                family_phone, phone_type, device_id, device_key,
                senior_language, family_language, status, created_at, answered_at)
            VALUES (:id, :senior_name, :senior_phone, :family_name,
                :family_phone, :phone_type, :device_id, :device_key,
                :senior_language, :family_language, :status, :created_at, :answered_at)
            """,
            enrollment,
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
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM enrollments WHERE status = 'active' ORDER BY created_at DESC"
        ).fetchall()
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
