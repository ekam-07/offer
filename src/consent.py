"""Consent, preferences and data erasure (stored next to the offer log in data/offers.db).

- /stop  -> opt_out(customer)            takes effect immediately, for decisions AND sending (R1)
- /start -> opt_in(customer)             explicit opt-in overrides the profile flag
- channel-level: opt_out(customer, "whatsapp")
- feedback buttons -> record_feedback(): "fewer_offers" slows the customer down,
  "not_interested" suppresses that offer type for a while (R28), "stop" opts out
- erase(customer): deletes their offer history and preferences (India's DPDP Act gives a
  right to withdraw consent and to erasure); a minimal "erased" opt-out record is kept so
  we never contact them again by mistake.
"""
from datetime import datetime, timedelta

from . import offer_log
from .config import RULES

SCHEMA = """
CREATE TABLE IF NOT EXISTS consent (
    customer_id TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL,
    source TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (customer_id, channel));
CREATE TABLE IF NOT EXISTS prefs (
    customer_id TEXT NOT NULL, key TEXT NOT NULL, until TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY (customer_id, key));
CREATE TABLE IF NOT EXISTS feedback (
    customer_id TEXT NOT NULL, kind TEXT NOT NULL, offer_id TEXT, at TEXT NOT NULL);
"""
NEGATIVE = ("not_interested", "fewer_offers", "stop")
CHANNELS = ("telegram", "email", "sms", "push", "whatsapp")  # telegram is real; the others are simulated


def _conn():
    conn = offer_log.connect()
    conn.executescript(SCHEMA)
    return conn


def _set(customer_id, channel, status, source, now=None):
    now = (now or datetime.now()).isoformat(timespec="seconds")
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO consent VALUES (?, ?, ?, ?, ?)", (customer_id, channel, status, source, now))


def opt_out(customer_id, channel="all", source="/stop", now=None):
    _set(customer_id, channel, "opt_out", source, now)
    if channel == "all" and source != "erased":  # a /stop is also a bad reaction to our offers (R26)
        with _conn() as conn:
            conn.execute("INSERT INTO feedback VALUES (?, 'stop', NULL, ?)",
                         (customer_id, (now or datetime.now()).isoformat()))


def opt_in(customer_id, channel="all", source="/start", now=None):
    _set(customer_id, channel, "opt_in", source, now)


def _status(customer_id, channel):
    with _conn() as conn:
        row = conn.execute("SELECT status FROM consent WHERE customer_id = ? AND channel = ?",
                           (customer_id, channel)).fetchone()
    return row["status"] if row else None


def allows_offers(c):
    """R1 at decision time: the profile opt-in, overridden by any later /stop or /start."""
    override = _status(c["customer_id"], "all")
    if override is not None:
        return override == "opt_in"
    return bool(c.get("opted_in"))


def allows_channel(c, channel):
    """R1 at SEND time: overall consent plus consent for this specific channel."""
    if not allows_offers(c):
        return False
    override = _status(c["customer_id"], channel)
    if override is not None:
        return override == "opt_in"
    return bool(c.get(f"consent_{channel}", c.get("opted_in")))


def record_feedback(customer_id, kind, offer_id=None, now=None):
    """Feedback buttons: redeemed | not_interested | fewer_offers | stop."""
    now = now or datetime.now()
    fb = RULES["feedback"]
    if kind == "stop":
        opt_out(customer_id, source="feedback:stop", now=now)  # also logs the reaction
        return
    with _conn() as conn:
        conn.execute("INSERT INTO feedback VALUES (?, ?, ?, ?)", (customer_id, kind, offer_id, now.isoformat()))
    with _conn() as conn:
        if kind == "fewer_offers":
            until = now + timedelta(days=fb["fewer_offers_days"])
            conn.execute("INSERT OR REPLACE INTO prefs VALUES (?, 'fewer_offers', ?, ?)",
                         (customer_id, until.isoformat(), now.isoformat()))
        elif kind == "not_interested" and offer_id:
            until = now + timedelta(days=fb["not_interested_suppress_days"])
            conn.execute("INSERT OR REPLACE INTO prefs VALUES (?, ?, ?, ?)",
                         (customer_id, f"suppress:{offer_id}", until.isoformat(), now.isoformat()))


def active_prefs(customer_id, now):
    """{'fewer_offers': bool, 'suppressed': {offer_id, ...}} still in force at `now`."""
    with _conn() as conn:
        rows = conn.execute("SELECT key FROM prefs WHERE customer_id = ? AND until > ?",
                            (customer_id, now.isoformat())).fetchall()
    keys = [r["key"] for r in rows]
    perks = [k.split(":", 1)[1] for k in keys if k.startswith("perk:")]
    return {"fewer_offers": "fewer_offers" in keys,
            "suppressed": {k.split(":", 1)[1] for k in keys if k.startswith("suppress:")},
            "perk": perks[0] if perks else None}


def record_perk(customer_id, offer_id, now=None, days=365):
    """Pick your perk: remember which perk the customer chose (FREE_SHIPPING or BONUS_POINTS)."""
    now = now or datetime.now()
    with _conn() as conn:
        conn.execute("DELETE FROM prefs WHERE customer_id = ? AND key LIKE 'perk:%'", (customer_id,))
        conn.execute("INSERT INTO prefs VALUES (?, ?, ?, ?)",
                     (customer_id, f"perk:{offer_id}", (now + timedelta(days=days)).isoformat(), now.isoformat()))
        conn.execute("INSERT INTO feedback VALUES (?, ?, ?, ?)", (customer_id, "picked_perk", offer_id, now.isoformat()))


def negative_reactions(customer_id, now, days=90):
    """Bad reactions to our offers in the last `days` (feedback buttons and /stop): the
    sleeping-dog signal (R26)."""
    since = (now - timedelta(days=days)).isoformat()
    with _conn() as conn:
        (n,) = conn.execute(f"SELECT COUNT(*) FROM feedback WHERE customer_id = ? AND kind IN {NEGATIVE} "
                            "AND at >= ? AND at <= ?", (customer_id, since, now.isoformat())).fetchone()
    return n


def reset_all():
    """Clear all consent overrides, preferences and feedback (simulations and tests only)."""
    with _conn() as conn:
        conn.execute("DELETE FROM consent")
        conn.execute("DELETE FROM prefs")
        conn.execute("DELETE FROM feedback")


def erase(customer_id, now=None):
    """Right to erasure: delete the customer's offer history and preferences."""
    with _conn() as conn:
        conn.execute("DELETE FROM offer_log WHERE customer_id = ?", (customer_id,))
        conn.execute("DELETE FROM prefs WHERE customer_id = ?", (customer_id,))
        conn.execute("DELETE FROM feedback WHERE customer_id = ?", (customer_id,))
        conn.execute("DELETE FROM consent WHERE customer_id = ?", (customer_id,))
    opt_out(customer_id, source="erased", now=now)
