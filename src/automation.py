"""Automatic decisions: nobody has to press "Decide".

Two things start a decision:
- Events from the store (or the Telegram bot), sent to POST /api/events or queued with add_event():
    signup               a new customer -> decide right away (e.g. a welcome offer)
    cart_abandoned       an item left in the cart -> decide after cart_wait_minutes (cart reminder)
    order_placed         an order -> update the customer; a "bought together" check bundle_after_days later
    wishlist_price_drop  a wishlisted item got cheaper -> decide right away (wishlist alert)
    back_in_stock        a wishlisted item is available again -> decide right away
    reply                a message from the customer (stop / start / 1 / 2 / complaint)
- A daily check of every customer at automation.daily_hour (slow changes: at risk, gone quiet,
  points expiring), skipping anyone decided in the last daily_skip_hours.

tick() does one round: due events, the daily check if it's time, then sending READY offers whose
send time has come (dry run unless delivery.mode is live). run_forever() repeats it.
Every decision still goes through the same AI + rules + checks as a manual one.
"""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from . import delivery, offer_log
from .agent import configured
from .config import DATA_DIR, RULES, default_customers_file
from .decide import decide, decide_batch
from .generate import SHOP_DB
from .rules import holds_live_offer

CFG = RULES["automation"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS automation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, customer_id TEXT, payload TEXT,
    created_at TEXT, due_at TEXT, done_at TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS live_customers (customer_id TEXT PRIMARY KEY, data TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS automation_state (key TEXT PRIMARY KEY, value TEXT);
"""
KINDS = ("signup", "cart_abandoned", "order_placed", "wishlist_price_drop", "back_in_stock", "reply", "bundle_check")
_lock = threading.Lock()


def _conn():
    conn = offer_log.connect()  # same database as the offer log
    conn.executescript(SCHEMA)
    return conn


# ---- Customers: the generated file plus everything events have changed ------------------

def _base_customers():
    with open(default_customers_file(), encoding="utf-8") as f:
        return {c["customer_id"]: c for c in json.load(f)}


def all_customers():
    """Customer features: data/customers.json, overlaid with customers created or updated by events."""
    out = _base_customers()
    with _conn() as conn:
        for r in conn.execute("SELECT customer_id, data FROM live_customers"):
            out[r["customer_id"]] = json.loads(r["data"])
    return out


def live_version():
    """Changes whenever an event updates a customer (lets the page refresh its cache)."""
    with _conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n, MAX(updated_at) AS t FROM live_customers").fetchone()
    return f"{row['n']}:{row['t']}"


def _save_customer(c, now):
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO live_customers VALUES (?, ?, ?)",
                     (c["customer_id"], json.dumps(c, ensure_ascii=False), now.isoformat(timespec="seconds")))


def _product(product_id):
    if not product_id or not SHOP_DB.exists():
        return None
    conn = sqlite3.connect(SHOP_DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _new_customer(payload, now):
    """A brand-new account: every activity count at zero, profile and consent from the sign-up."""
    template = next(iter(_base_customers().values()))
    c = {}
    for k, v in template.items():
        c[k] = False if isinstance(v, bool) else 0 if isinstance(v, (int, float)) else None
    c.update(customer_id=payload["customer_id"], name=payload.get("name") or "there", persona="unknown",
             opted_in=bool(payload.get("opted_in", True)), city=payload.get("city"),
             top_category=payload.get("interest") or "Fashion", tier="Bronze", new_to_brand_12m=True,
             signup_channel=payload.get("signup_channel"), preferred_device=payload.get("device"))
    for ch in ("telegram", "email", "sms", "push", "whatsapp"):
        c[f"consent_{ch}"] = bool(payload.get(f"consent_{ch}", ch in (payload.get("channels") or ["telegram"])))
    _set_focus_popular(c)
    return c


def _set_focus_popular(c):
    """Product-coupon target for someone with no history: the best-rated in-stock item in their category."""
    if not SHOP_DB.exists():
        return
    conn = sqlite3.connect(SHOP_DB)
    conn.row_factory = sqlite3.Row
    try:
        p = conn.execute("SELECT * FROM products WHERE category = ? AND stock_units > 0 ORDER BY avg_rating DESC LIMIT 1",
                         (c["top_category"],)).fetchone()
    finally:
        conn.close()
    if p:
        c.update(focus_product_id=p["product_id"], focus_product_name=p["name"], focus_product_type=p["item_type"],
                 focus_product_price=p["price"], focus_product_category=p["category"],
                 focus_product_reason="popular in category", focus_product_in_stock=True,
                 focus_product_overstock=bool(p["overstock"]))


def _bundle_for(product):
    """The item other shoppers most often buy with this product (same logic as features.py)."""
    from .features import _bought_with, _usable
    conn = sqlite3.connect(SHOP_DB)
    conn.row_factory = sqlite3.Row
    try:
        pairs = _bought_with(conn).get(product["item_type"], [])
        products = [dict(r) for r in conn.execute("SELECT * FROM products")]
    finally:
        conn.close()
    for item_type, conf in pairs:
        options = [p for p in products if p["item_type"] == item_type and _usable(p)]
        if options:
            good = [x for x in options if x["avg_rating"] >= 4.0] or options
            p = min(good, key=lambda x: (x["price"], -x["avg_rating"]))
            return {"bundle_anchor_item": product["name"], "bundle_reason": "just bought", "bundle_item_id": p["product_id"],
                    "bundle_item_name": p["name"], "bundle_item_price": p["price"],
                    "bundle_item_category": p["category"], "bundle_confidence": conf}
    return {"bundle_item_id": None}


# ---- Events -----------------------------------------------------------------------------

def add_event(kind, customer_id, payload=None, now=None, delay_minutes=None):
    """Queue an event. Most are handled at the next tick; an abandoned cart waits cart_wait_minutes
    (unless delay_minutes says otherwise) so a customer who is still shopping isn't nudged."""
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r}; expected one of {', '.join(KINDS)}")
    now = now or datetime.now()
    if delay_minutes is None:
        delay_minutes = CFG["cart_wait_minutes"] if kind == "cart_abandoned" else 0
    due = now + timedelta(minutes=delay_minutes)
    with _conn() as conn:
        cur = conn.execute("INSERT INTO automation_events (kind, customer_id, payload, created_at, due_at) "
                           "VALUES (?, ?, ?, ?, ?)",
                           (kind, customer_id, json.dumps(payload or {}, ensure_ascii=False),
                            now.isoformat(timespec="seconds"), due.isoformat(timespec="seconds")))
        return cur.lastrowid


def _decide(c, now, use_agent):
    row = decide(c, now=now, use_agent=use_agent and configured())
    return f"decided: {row.get('offer_id') or row['status']} by {row['decided_by']}"


def handle(event, now, use_agent=None):
    """Apply one event to the customer and decide if it calls for it. Returns a short result."""
    use_agent = CFG["use_agent"] if use_agent is None else use_agent
    kind, cid, p = event["kind"], event["customer_id"], json.loads(event["payload"] or "{}")
    customers = all_customers()
    c = customers.get(cid)
    if kind == "signup":
        if c is not None:
            return "skipped: customer already exists"
        c = _new_customer(dict(p, customer_id=cid), now)
        _save_customer(c, now)
        return _decide(c, now, use_agent)
    if c is None:
        return "skipped: unknown customer"
    c = dict(c)
    if kind == "reply":
        return f"reply: {delivery.handle_reply(cid, p.get('text', ''), now=now)}"
    if kind == "cart_abandoned":
        if (c.get("_last_order_at") or "") >= event["created_at"]:
            return "skipped: they ordered after leaving the cart"
        prod = _product(p.get("product_id")) or {}
        hours = max(1, round((now - datetime.fromisoformat(event["created_at"])).total_seconds() / 3600))
        c.update(cart_abandoned_hours_ago=hours, abandoned_cart_value=float(p.get("value") or prod.get("price") or 0),
                 abandoned_cart_item=p.get("item") or prod.get("name"),
                 cart_item_in_stock=(prod.get("stock_units", 1) > 0) if prod else True)
        if prod:
            c.update(focus_product_id=prod["product_id"], focus_product_name=prod["name"], focus_product_type=prod["item_type"],
                     focus_product_price=prod["price"], focus_product_category=prod["category"],
                     focus_product_reason="in cart", focus_product_in_stock=prod["stock_units"] > 0)
        _save_customer(c, now)
        return _decide(c, now, use_agent)
    if kind == "order_placed":
        total, n = float(p.get("total") or 0), c.get("orders_total") or 0
        if n and c.get("recency_days") is not None:
            c["avg_gap_days"] = round(((c.get("avg_gap_days") or 0) * max(n - 1, 0) + c["recency_days"]) / n, 1)
        c.update(orders_total=n + 1, recency_days=0, aov=round(((c.get("aov") or 0) * n + total) / (n + 1)),
                 orders_30d=(c.get("orders_30d") or 0) + 1, orders_90d=(c.get("orders_90d") or 0) + 1,
                 frequency_90d=(c.get("frequency_90d") or 0) + 1, orders_365d=(c.get("orders_365d") or 0) + 1,
                 spend_365d=(c.get("spend_365d") or 0) + total, cart_abandoned_hours_ago=None,
                 abandoned_cart_value=0, abandoned_cart_item=None, _last_order_at=now.isoformat(timespec="seconds"))
        if p.get("category"):
            c["top_category"] = p["category"] if n == 0 else c["top_category"]
        _save_customer(c, now)
        if p.get("product_id"):
            add_event("bundle_check", cid, {"product_id": p["product_id"]}, now=now,
                      delay_minutes=CFG["bundle_after_days"] * 24 * 60)
        return "updated: order recorded" + (f"; bought-together check in {CFG['bundle_after_days']} days" if p.get("product_id") else "")
    if kind == "bundle_check":
        prod = _product(p.get("product_id"))
        if not prod:
            return "skipped: unknown product"
        c.update(_bundle_for(prod))
        _save_customer(c, now)
        return _decide(c, now, use_agent) if c.get("bundle_item_id") else "skipped: nothing is usually bought with it"
    if kind in ("wishlist_price_drop", "back_in_stock"):
        prod = _product(p.get("product_id")) or {}
        name = p.get("item") or prod.get("name")
        if not name:
            return "skipped: unknown product"
        if kind == "wishlist_price_drop":
            was, new = float(p.get("was_price") or prod.get("was_price") or 0), float(p.get("price") or prod.get("price") or 0)
            if not was or new >= was:
                return "skipped: the price didn't really drop"
            c.update(wishlist_alert_item=name, wishlist_alert_kind="price_drop", wishlist_alert_was_price=was,
                     wishlist_alert_price=new)
        else:
            c.update(wishlist_alert_item=name, wishlist_alert_kind="back_in_stock", wishlist_alert_was_price=None,
                     wishlist_alert_price=float(p.get("price") or prod.get("price") or 0))
        _save_customer(c, now)
        return _decide(c, now, use_agent)
    return f"skipped: no handler for {kind}"


def process_due_events(now=None, use_agent=None):
    now = now or datetime.now()
    with _conn() as conn:
        due = conn.execute("SELECT * FROM automation_events WHERE done_at IS NULL AND due_at <= ? ORDER BY due_at, id",
                           (now.isoformat(timespec="seconds"),)).fetchall()
    done = []
    for e in due:
        try:
            result = handle(dict(e), now, use_agent)
        except Exception as ex:  # one bad event must never stop the others
            result = f"error: {type(ex).__name__}: {ex}"
        with _conn() as conn:
            conn.execute("UPDATE automation_events SET done_at = ?, result = ? WHERE id = ?",
                         (now.isoformat(timespec="seconds"), result, e["id"]))
        done.append((e["id"], e["kind"], e["customer_id"], result))
    return done


# ---- Daily check and sending --------------------------------------------------------------

def _state(key, value=None):
    with _conn() as conn:
        if value is None:
            row = conn.execute("SELECT value FROM automation_state WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None
        conn.execute("INSERT OR REPLACE INTO automation_state VALUES (?, ?)", (key, value))
    return value


def daily_due(now):
    today = now.date().isoformat()
    if _state("last_daily_run") == today or now.hour < CFG["daily_hour"]:
        return False
    return CFG["daily_catch_up"] or now.hour == CFG["daily_hour"]


def daily_run(now=None, use_agent=None, force=False):
    """Decide for every customer not decided in the last daily_skip_hours."""
    now = now or datetime.now()
    if not force and not daily_due(now):
        return None
    use_agent = CFG["use_agent"] if use_agent is None else use_agent
    _state("last_daily_run", now.date().isoformat())  # first, so two ticks can't both start it
    recent_cut = (now - timedelta(hours=CFG["daily_skip_hours"])).isoformat(timespec="seconds")
    latest = offer_log.latest_per_customer()
    live = offer_log.live_offers(now, holds_live_offer) if RULES["frequency"].get("one_live_offer") else {}
    everyone = all_customers()
    todo = [c for cid, c in everyone.items()
            if cid not in live and not (latest.get(cid) and latest[cid]["created_at"] >= recent_cut)]
    rows = decide_batch(todo, now=now, use_agent=use_agent and configured())
    held = sum(1 for cid in everyone if cid in live)
    summary = (f"{now:%Y-%m-%d %H:%M}: {len(rows)} customers checked, {sum(r['status'] == 'READY' for r in rows)} offers ready, "
               f"{held} skipped (still have a live offer)")
    _state("last_daily_summary", summary)
    return summary


def send_due(now=None, ignore_send_time=None):
    """Send (or dry-run) READY offers whose send time has come. Stale ones are never sent.
    ignore_send_time (default: on in Telegram test mode) sends them now instead of at each
    customer's usual active hour; quiet hours still apply."""
    now = now or datetime.now()
    if ignore_send_time is None:
        ignore_send_time = os.getenv("TELEGRAM_TEST_MODE", "1") != "0" and bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    oldest = (now - timedelta(hours=CFG["send_max_age_hours"])).isoformat(timespec="seconds")
    latest_send = "9999" if ignore_send_time else now.isoformat(timespec="minutes")
    with offer_log.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM offer_log WHERE status = 'READY' AND created_at >= ? AND created_at <= ? "
            "AND (send_at IS NULL OR send_at <= ?)",
            (oldest, now.isoformat(timespec="seconds"), latest_send))]
    if not rows:
        return {}
    customers = all_customers()
    out = {}
    for r in rows:
        c = customers.get(r["customer_id"])
        if c is not None:
            out[r["id"]] = delivery.deliver(r, c, now=now)
    return out


def tick(now=None, use_agent=None):
    """One round of automation. Safe to call from several places: only one round runs at a time."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        now = now or datetime.now()
        events = process_due_events(now, use_agent)
        daily = daily_run(now, use_agent)
        sent = send_due(now)
        _state("last_tick", datetime.now().isoformat(timespec="seconds"))  # heartbeat: real time, even for test events
        return {"events": events, "daily": daily, "sent": sent}
    finally:
        _lock.release()


def status(now=None):
    now = now or datetime.now()
    with _conn() as conn:
        waiting = conn.execute("SELECT COUNT(*) FROM automation_events WHERE done_at IS NULL").fetchone()[0]
        today = conn.execute("SELECT COUNT(*) FROM automation_events WHERE done_at >= ?",
                             (now.date().isoformat(),)).fetchone()[0]
        recent = [dict(r) for r in conn.execute(
            "SELECT id, kind, customer_id, created_at, due_at, done_at, result FROM automation_events "
            "ORDER BY id DESC LIMIT 8")]
    nxt = now.replace(hour=CFG["daily_hour"], minute=0, second=0, microsecond=0)
    if _state("last_daily_run") == now.date().isoformat() or now >= nxt + timedelta(hours=1):
        nxt += timedelta(days=1)
    return {"last_tick": _state("last_tick"), "last_daily": _state("last_daily_summary"), "next_daily": nxt.isoformat(timespec="minutes"),
            "waiting": waiting, "handled_today": today, "recent": recent, "use_agent": CFG["use_agent"] and configured(),
            "delivery_mode": delivery.mode()}


def run_forever(stop=None, tick_seconds=None):
    """Background loop used by run_automation.py and the preview server."""
    every = tick_seconds or CFG["tick_seconds"]
    while not (stop and stop.is_set()):
        try:
            tick()
        except Exception as ex:  # keep the loop alive; the next tick tries again
            _state("last_error", f"{datetime.now():%Y-%m-%d %H:%M:%S} {type(ex).__name__}: {ex}")
        if stop:
            stop.wait(every)
        else:
            time.sleep(every)


def reset():
    """Clear queued events, event-created customers and the automation state (tests / fresh start)."""
    with _conn() as conn:
        conn.execute("DELETE FROM automation_events")
        conn.execute("DELETE FROM live_customers")
        conn.execute("DELETE FROM automation_state")
