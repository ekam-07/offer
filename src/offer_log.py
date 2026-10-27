"""SQLite log of every offer decision: what was chosen, why, and by whom."""
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .config import DATA_DIR

DB_PATH = Path(os.getenv("OFFERS_DB") or DATA_DIR / "offers.db")  # OFFERS_DB: e.g. a separate demo log

# status: READY (decided, waiting for delivery), SENT, DRY_RUN (would have been sent; dry-run mode),
#         BLOCKED_AT_SEND (consent / kill switch at send time), SEND_FAILED (channel error;
#         flagged, doesn't count as given, can be retried), NO_OFFER,
#         HOLDOUT (control group), NOT_ELIGIBLE, DEFERRED (quiet hours)
# decided_by: AGENT | RULES | EXPLORE (random allowed offer, R27) | SYSTEM (no offer chosen)
# agent_status: OK | OK_AFTER_RETRY | FAILED | REJECTED | SKIPPED | NOT_NEEDED (every offer blocked)
#               | OUTDATED (AI choice no longer fit the budget after other decisions)
# Offers that count as "given" for frequency, active-offer and budget rules:
GIVEN = ("READY", "SENT", "DRY_RUN")
SCHEMA = """
CREATE TABLE IF NOT EXISTS offer_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    customer_id     TEXT NOT NULL,
    segment         TEXT,
    status          TEXT NOT NULL,
    offer_id        TEXT,
    offer_type      TEXT,
    value           REAL,
    est_cost_inr    REAL DEFAULT 0,
    valid_until     TEXT,
    message         TEXT,
    reason          TEXT,
    decided_by      TEXT NOT NULL,
    agent_status    TEXT,
    agent_failure   TEXT,
    violations      TEXT,
    flagged         INTEGER DEFAULT 0,
    model           TEXT,
    latency_ms      INTEGER,
    request_id      TEXT
)
"""

# Columns added after the first version (migrated automatically on older databases).
ADDED_COLUMNS = {
    "rules_version": "TEXT",      # hash of rules.yaml + offers.yaml, for reproducibility
    "review_reasons": "TEXT",     # why a human should look (JSON list); flagged = 1 when set
    "explored": "INTEGER",        # 1 = random allowed offer for learning (R27)
    "propensity": "REAL",         # chance this offer was chosen (for unbiased learning later)
    "uplift_group": "TEXT",
    "send_at": "TEXT",            # planned send time inside 08:00-22:00 (customer's active hour)
    "sent_at": "TEXT",
    "channel": "TEXT",
    "ep_inr": "REAL",             # R30 expected profit of the chosen offer (engine estimate)
    "expected_cost_inr": "REAL",  # cost x chance it is redeemed, for budget planning
    "coupon_code": "TEXT",        # single-use code issued at send time (coupons.py)
}

COLUMNS = [
    "created_at", "customer_id", "segment", "status", "offer_id", "offer_type", "value",
    "est_cost_inr", "valid_until", "message", "reason", "decided_by", "agent_status",
    "agent_failure", "violations", "flagged", "model", "latency_ms", "request_id",
] + list(ADDED_COLUMNS)


class BudgetExceeded(Exception):
    """Another decision spent the remaining budget between the check and the write."""


def connect():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    have = {r["name"] for r in conn.execute("PRAGMA table_info(offer_log)")}
    for col, kind in ADDED_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE offer_log ADD COLUMN {col} {kind}")
    return conn


def write(row, budget_limit=None):
    """Insert one decision. With budget_limit, the budget check and the insert happen in one
    BEGIN IMMEDIATE transaction, so two processes can't both spend the last rupees (R13)."""
    row = dict(row)
    for key in ("violations", "review_reasons"):
        if isinstance(row.get(key), list):
            row[key] = json.dumps(row[key]) if row[key] else None
    conn = connect()
    conn.isolation_level = None  # manual transaction control
    try:
        conn.execute("BEGIN IMMEDIATE")
        if budget_limit is not None and row.get("status") == "READY" and row.get("est_cost_inr"):
            day = row["created_at"][:10]
            (spent,) = conn.execute(
                f"SELECT COALESCE(SUM(est_cost_inr), 0) FROM offer_log WHERE status IN {GIVEN} "
                "AND substr(created_at, 1, 10) = ?", (day,)).fetchone()
            if spent + row["est_cost_inr"] > budget_limit:
                conn.execute("ROLLBACK")
                raise BudgetExceeded(f"₹{spent:.0f} already committed of ₹{budget_limit:.0f}")
        cur = conn.execute(
            f"INSERT INTO offer_log ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
            [row.get(c) for c in COLUMNS],
        )
        conn.execute("COMMIT")
        return cur.lastrowid
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def update(row_id, **fields):
    with connect() as conn:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE offer_log SET {sets} WHERE id = ?", [*fields.values(), row_id])


def customer_history(customer_id, since, until):
    """Offers actually decided for delivery (READY/SENT) between two datetimes, newest first.
    `until` matters when replaying a simulated time: offers dated later must not count."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM offer_log WHERE customer_id = ? AND status IN ('READY', 'SENT', 'DRY_RUN') "
            "AND created_at >= ? AND created_at <= ? ORDER BY created_at DESC",
            (customer_id, since.isoformat(), until.isoformat()),
        ).fetchall()
    return [dict(r) for r in rows]


def spent_on(day):
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    with connect() as conn:
        (total,) = conn.execute(
            "SELECT COALESCE(SUM(est_cost_inr), 0) FROM offer_log "
            "WHERE status IN ('READY', 'SENT', 'DRY_RUN') AND created_at >= ? AND created_at < ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
    return float(total)


def all_rows(flagged_only=False, limit=100):
    sql = "SELECT * FROM offer_log"
    if flagged_only:
        sql += " WHERE flagged = 1"
    sql += " ORDER BY id DESC LIMIT ?"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, (limit,)).fetchall()]


def latest_per_customer():
    """customer_id -> most recent decision row."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM offer_log WHERE id IN (SELECT MAX(id) FROM offer_log GROUP BY customer_id)"
        ).fetchall()
    return {r["customer_id"]: dict(r) for r in rows}


def active_offers(now):
    """customer_id -> newest offer that is still valid at `now` (sent before it, not expired)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM offer_log WHERE status IN ('READY', 'SENT', 'DRY_RUN') AND offer_id != 'NONE' "
            "AND created_at <= ? AND valid_until > ? ORDER BY id",
            (now.isoformat(), now.isoformat()),
        ).fetchall()
    return {r["customer_id"]: dict(r) for r in rows}


def live_offers(now, holds_live):
    """customer_id -> newest offer still valid at `now` whose validity the customer was told
    (holds_live(offer_id) decides which offers count). Used by the daily check and the list."""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM offer_log WHERE status IN {GIVEN} AND offer_id != 'NONE' "
            "AND created_at <= ? AND valid_until > ? ORDER BY id",
            (now.isoformat(), now.isoformat()),
        ).fetchall()
    return {r["customer_id"]: dict(r) for r in rows if holds_live(r["offer_id"])}


def customer_rows(customer_id, limit=20):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM offer_log WHERE customer_id = ? ORDER BY id DESC LIMIT ?", (customer_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def reset():
    with connect() as conn:
        conn.execute("DELETE FROM offer_log")
