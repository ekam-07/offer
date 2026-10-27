"""Unique, single-use coupon codes tied to one customer (stored in data/offers.db).

Every paid offer gets its own code when it is delivered (delivery.py appends it to the
message). redeem() accepts a code only for the customer it was issued to, once, before it
expires; every refused attempt is logged in coupon_misuse, so codes shared in a group chat
are caught, not honoured.
"""
import secrets
from datetime import datetime

from . import offer_log
from .config import RULES

SCHEMA = """
CREATE TABLE IF NOT EXISTS coupon_codes (
    code TEXT PRIMARY KEY, customer_id TEXT NOT NULL, offer_log_id INTEGER, offer_id TEXT,
    value REAL, valid_until TEXT, status TEXT NOT NULL, issued_at TEXT NOT NULL, redeemed_at TEXT);
CREATE TABLE IF NOT EXISTS coupon_misuse (
    code TEXT, attempted_by TEXT, owner TEXT, reason TEXT, at TEXT NOT NULL);
"""
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I, easy to read out


def _conn():
    conn = offer_log.connect()
    conn.executescript(SCHEMA)
    return conn


def issue(row, now=None):
    """Create the code for one paid decision (row from the offer log). Returns the code."""
    now = now or datetime.now()
    cfg = RULES["coupon_codes"]
    code = cfg["prefix"] + "-" + "".join(secrets.choice(ALPHABET) for _ in range(cfg["length"]))
    with _conn() as conn:
        conn.execute("INSERT INTO coupon_codes VALUES (?, ?, ?, ?, ?, ?, 'issued', ?, NULL)",
                     (code, row["customer_id"], row["id"], row["offer_id"], row.get("value"), row.get("valid_until"),
                      now.isoformat(timespec="seconds")))
    offer_log.update(row["id"], coupon_code=code)
    return code


def redeem(code, customer_id, now=None):
    """Try to use a code at checkout. Returns (ok, reason). Refusals are logged as misuse."""
    now = now or datetime.now()
    with _conn() as conn:
        r = conn.execute("SELECT * FROM coupon_codes WHERE code = ?", (code,)).fetchone()
        reason = None
        if r is None:
            reason = "unknown code"
        elif r["customer_id"] != customer_id:
            reason = "code belongs to another customer"
        elif r["status"] == "redeemed":
            reason = "code already used"
        elif r["valid_until"] and r["valid_until"] < now.isoformat():
            reason = "code expired"
        if reason:
            conn.execute("INSERT INTO coupon_misuse VALUES (?, ?, ?, ?, ?)",
                         (code, customer_id, r["customer_id"] if r else None, reason, now.isoformat(timespec="seconds")))
            return False, reason
        conn.execute("UPDATE coupon_codes SET status = 'redeemed', redeemed_at = ? WHERE code = ?",
                     (now.isoformat(timespec="seconds"), code))
    return True, "ok"


def code_for(offer_log_id):
    with _conn() as conn:
        r = conn.execute("SELECT code FROM coupon_codes WHERE offer_log_id = ?", (offer_log_id,)).fetchone()
    return r["code"] if r else None


def misuse_report():
    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM coupon_misuse ORDER BY at")]


def reset_all():
    with _conn() as conn:
        conn.execute("DELETE FROM coupon_codes")
        conn.execute("DELETE FROM coupon_misuse")
