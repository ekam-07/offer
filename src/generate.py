"""Generates synthetic customers and their raw activity into data/shop.db.

Tables: customers, orders, order_items, products, promotions, events (full-year GA4-style
stream), loyalty_tx, plus sessions and cart_events (derived from events, kept for older code).
Behaviour comes from hidden personas in config/personas.yaml. Features are computed
from these raw tables afterwards (src/features.py), like a real platform would.
"""
import itertools
import os
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from . import events as events_mod
from .config import CONFIG_DIR, DATA_DIR, RULES
from .events import EVENT_COLUMNS, CustomerEvents, build_products, build_promotions, festival_multiplier, legacy_tables

SHOP_DB = Path(os.getenv("SHOP_DB") or DATA_DIR / "shop.db")  # SHOP_DB: e.g. the slim copy used on Vercel

CALIBRATED = CONFIG_DIR / "personas_calibrated.yaml"


def _merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


with open(CONFIG_DIR / "personas.yaml", encoding="utf-8") as f:
    P = yaml.safe_load(f)
# Values measured from real datasets (python calibrate.py) override the hand-set ones.
if CALIBRATED.exists():
    with open(CALIBRATED, encoding="utf-8") as f:
        _merge(P, yaml.safe_load(f) or {})

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Arjun", "Sai", "Reyansh", "Krishna", "Ishaan", "Rohan", "Kabir",
    "Ananya", "Diya", "Priya", "Saanvi", "Aadhya", "Kavya", "Meera", "Isha", "Neha", "Sneha",
    "Harpreet", "Gurleen", "Simran", "Manpreet", "Jaspreet", "Rahul", "Vikram", "Pooja", "Riya", "Tanvi",
    "Farhan", "Zoya", "Imran", "Ayesha", "Joseph", "Maria", "Karthik", "Lakshmi", "Deepak", "Nisha",
]
LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Singh", "Kaur", "Patel", "Shah", "Iyer", "Nair", "Reddy",
    "Rao", "Mehta", "Joshi", "Kumar", "Das", "Bose", "Khan", "Fernandes", "Pillai", "Gill",
]
CITIES = ["Ludhiana", "Delhi", "Mumbai", "Bengaluru", "Chennai", "Hyderabad", "Pune", "Kolkata", "Jaipur", "Chandigarh"]
DEVICES = ["mobile_app", "mobile_web", "desktop"]

SCHEMA = """
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS cart_events;
DROP TABLE IF EXISTS loyalty_tx;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS promotions;
DROP TABLE IF EXISTS events;
CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, city TEXT, signup_date TEXT,
    opted_in INTEGER, persona TEXT, points_mult REAL, plus_member INTEGER, signup_channel TEXT,
    preferred_device TEXT, consent_telegram INTEGER, consent_email INTEGER, consent_sms INTEGER, consent_push INTEGER, consent_whatsapp INTEGER);
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id TEXT, created_at TEXT,
    category TEXT, total REAL, margin REAL, used_coupon INTEGER, discount REAL,
    coupon_code TEXT, promotion_id TEXT, returned INTEGER);
CREATE TABLE order_items (order_id INTEGER, product_id TEXT, quantity INTEGER, list_price REAL, line_total REAL);
CREATE TABLE sessions (customer_id TEXT, started_at TEXT, pages INTEGER, category TEXT, device TEXT, purchased INTEGER);
CREATE TABLE cart_events (customer_id TEXT, created_at TEXT, action TEXT, product TEXT, category TEXT, value REAL);
CREATE TABLE loyalty_tx (customer_id TEXT, created_at TEXT, kind TEXT, points INTEGER);
CREATE TABLE products (product_id TEXT PRIMARY KEY, name TEXT, item_type TEXT, brand TEXT, category TEXT,
    category_l2 TEXT, price REAL, avg_rating REAL, launch_date TEXT, stock_units INTEGER, overstock INTEGER,
    was_price REAL, price_dropped_at TEXT, restocked_at TEXT);
CREATE TABLE promotions (promotion_id TEXT PRIMARY KEY, promotion_name TEXT, offer_type TEXT, value REAL,
    category TEXT, starts_at TEXT, ends_at TEXT, coupon_code TEXT);
CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT, session_id TEXT, event_time TEXT,
    event_name TEXT, product_id TEXT, brand TEXT, category TEXT, price REAL, quantity INTEGER, value REAL,
    search_term TEXT, item_list_name TEXT, position INTEGER, promotion_id TEXT, coupon TEXT,
    transaction_id TEXT, rating INTEGER, device TEXT);
CREATE INDEX events_customer ON events (customer_id, event_time);
"""
EVENT_DAYS = 365        # browsing events are simulated for the last year (orders cover the whole tenure)
SIGNUP_CHANNELS = ["organic", "search_ad", "social", "referral", "marketplace"]


def _u(r, rng):
    """Sample uniformly from [a, b], or return a scalar as-is."""
    return rng.uniform(*r) if isinstance(r, list) else r


def _category(rng, favourite):
    if rng.random() < 0.6:
        return favourite
    cats = P["categories"]
    return rng.choices(list(cats), weights=[c["weight"] for c in cats.values()])[0]


def _order_value(rng, aov, category):
    # Lognormal noise around the customer's typical spend, scaled by category price level.
    return round(max(149, aov * P["categories"][category]["price_mult"] * rng.lognormvariate(0, 0.35)), 0)


def _behaviour(p):
    b = dict(P["behaviour_defaults"])
    b.update({k: v for k, v in p.items() if k in b})
    b["abandon_rate"] = p["abandon_rate"]
    return b


def simulate_customer(cid, persona, rng, ref, seed=42, catalog=None, next_order_id=None):
    p = P["personas"][persona]
    tenure = int(_u(p["tenure_days"], rng))
    signup = ref - timedelta(days=tenure, hours=rng.randint(0, 23))
    gap = _u(p["order_gap_days"], rng)
    aov = _u(p["aov_inr"], rng)
    coupon = _u(p["coupon_rate"], rng)
    favourite = rng.choices(list(P["categories"]), weights=[c["weight"] for c in P["categories"].values()])[0]
    points_mult = p.get("points_mult", 1)

    if "stop_days" in p:
        active_end = ref - timedelta(days=_u(p["stop_days"], rng))
    elif "stop_gap_mult" in p:
        active_end = ref - timedelta(days=min(85, gap * _u(p["stop_gap_mult"], rng)))
    else:
        active_end = ref - timedelta(hours=rng.randint(6, 48))

    customer = {
        "customer_id": cid,
        "name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
        "city": rng.choice(CITIES),
        "signup_date": signup.isoformat(timespec="seconds"),
        "opted_in": int(rng.random() < p["opt_in"]),
        "persona": persona,
        "points_mult": points_mult,
    }

    # Orders: roughly regular gaps (+-50%) while the customer is active.
    orders, loyalty = [], []
    t = signup + timedelta(days=rng.uniform(0.2, 1.0) * gap)
    if persona == "new":
        t = signup + timedelta(hours=rng.uniform(2, max(3, tenure * 24 - 2)))
    balance = 0
    while t < active_end and len(orders) < p.get("max_orders", 10_000):
        if persona == "new" and rng.random() < 0.5:
            break  # half of new customers haven't ordered yet
        cat = _category(rng, favourite)
        total = _order_value(rng, aov, cat)
        used = rng.random() < coupon
        discount = round(total * rng.uniform(0.05, 0.15), 0) if used else 0.0
        margin = round(total * RULES["category_margin_pct"].get(cat, 20) / 100 - discount, 2)
        orders.append((cid, t.isoformat(timespec="seconds"), cat, total, margin, int(used), discount))
        earned = int(total * P["points_per_inr"] * points_mult)
        loyalty.append((cid, t.isoformat(timespec="seconds"), "earn", earned))
        balance += earned
        if balance > 200 and rng.random() < P["redeem_chance"]:
            loyalty.append((cid, t.isoformat(timespec="seconds"), "redeem", -(balance // 2)))
            balance -= balance // 2
        t += timedelta(days=gap * rng.uniform(0.5, 1.5))

    _replay_legacy_draws(p, signup, ref, favourite, aov, {o[1][:10] for o in orders}, rng)

    # Everything below uses its own random stream, so names, orders and segments are
    # identical to datasets generated before the event stream existed.
    erng = random.Random(f"{seed}-{cid}-events")
    customer.update(
        plus_member=int(erng.random() < _behaviour(p)["plus_member"]),
        signup_channel=erng.choice(SIGNUP_CHANNELS),
        **{f"consent_{ch}": int(customer["opted_in"] and erng.random() < pr) for ch, pr in P["consent"].items()},
    )
    order_ids = [next(next_order_id) for _ in orders]
    events, order_items, returned, coupons = _simulate_events(cid, p, orders, order_ids, signup, active_end,
                                                              favourite, catalog, ref, erng)
    customer["preferred_device"] = events.device
    # Real data has gaps: a few customers with no city or signup channel recorded.
    if erng.random() < P["missing_field_share"]:
        customer["city"] = None
    if erng.random() < P["missing_field_share"]:
        customer["signup_channel"] = None
    full_orders = [o + (coupons.get(oid, (None, None))[0], coupons.get(oid, (None, None))[1], int(oid in returned))
                   for o, oid in zip(orders, order_ids)]
    sessions, carts = legacy_tables(events.events, catalog["names"])
    return customer, list(zip(order_ids, full_orders)), sessions, carts, loyalty, events.events, order_items


def _replay_legacy_draws(p, signup, ref, favourite, aov, order_days, rng):
    """The first generator simulated 30 days of sessions with the shared random stream.
    The event stream replaced that, but repeating the same draws (results discarded) keeps
    every later customer identical, so earlier evaluations and tuning stay reproducible."""
    rate_per_day = _u(p["sessions_per_week"], rng) / 7
    day = max(signup, ref - timedelta(days=30))
    while day < ref:
        n = sum(1 for _ in range(4) if rng.random() < rate_per_day / 4)
        for _ in range(n):
            at = day + timedelta(hours=rng.uniform(8, 23))
            if at >= ref:
                continue
            cat = _category(rng, favourite)
            rng.randint(1, 15), rng.choice(DEVICES), rng.choice(P["products"][cat])
            _order_value(rng, aov, cat)
            if at.date().isoformat() not in order_days:
                rng.random()
        day += timedelta(days=1)
    if rng.random() < p["recent_abandon"]:
        rng.uniform(1, 40)
        cat = _category(rng, favourite)
        rng.choice(P["products"][cat]), _order_value(rng, aov * 1.3, cat), rng.randint(3, 15), rng.choice(DEVICES)


def _simulate_events(cid, p, orders, order_ids, signup, active_end, favourite, catalog, ref, rng):
    """Full-year session simulation (see src/events.py). Purchase sessions match the orders."""
    b = _behaviour(p)
    ev = CustomerEvents(cid, b, catalog["by_category"], catalog["promotions"], ref, rng)
    start = max(signup, ref - timedelta(days=EVENT_DAYS))
    spw = _u(p["sessions_per_week"], rng)
    spw_active = _u(p.get("sessions_per_week_active", spw), rng)
    by_day = {}
    for oid, o in zip(order_ids, orders):
        at = datetime.fromisoformat(o[1])
        if at >= start:
            by_day.setdefault(at.date(), []).append((oid, at, o[3], bool(o[5]), o[2]))

    day = datetime(start.year, start.month, start.day)
    while day < ref:
        rate = (spw_active if day < active_end else spw) / 7 * festival_multiplier(day)
        n = sum(1 for _ in range(4) if rng.random() < rate / 4)
        for oid, at, total, used, cat in by_day.get(day.date(), []):
            ev.session(at - timedelta(minutes=rng.uniform(4, 25)), cat, order=(oid, at, total, used))
        for _ in range(n):
            at = day + timedelta(hours=rng.uniform(8, 23))
            if start <= at < ref:
                ev.session(at, _category(rng, favourite))
        day += timedelta(days=1)

    if rng.random() < p["recent_abandon"]:
        at = ref - timedelta(hours=rng.uniform(1, 40))
        cat = _category(rng, favourite)
        pricey = sorted(catalog["by_category"][cat], key=lambda x: -x["price"])[:5]
        ev.session(at, cat, forced_cart=rng.choice(pricey))

    ev.events.sort(key=lambda e: e["event_time"])
    return ev, ev.order_items, ev.returned, ev.coupons


def generate(n=200, seed=42, ref=None):
    """Create n customers with activity up to ref (datetime). Overwrites data/shop.db."""
    ref = ref or datetime.now()
    rng = random.Random(seed)
    personas = list(P["personas"])
    weights = [P["personas"][k]["weight"] for k in personas]

    products = build_products(seed, ref)
    promotions = build_promotions(seed, ref)
    by_category = {}
    for prod in products:
        by_category.setdefault(prod["category"], []).append(prod)
    catalog = {"by_category": by_category, "promotions": promotions,
               "names": {prod["product_id"]: prod["name"] for prod in products}}
    events_mod.CAT_RETURN_RATE.update(P["return_rate_by_category"])
    order_counter = itertools.count(1)

    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(SHOP_DB)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO products VALUES (:product_id, :name, :item_type, :brand, :category, :category_l2, "
                     ":price, :avg_rating, :launch_date, :stock_units, :overstock, :was_price, :price_dropped_at, "
                     ":restocked_at)", products)
    conn.executemany("INSERT INTO promotions VALUES (:promotion_id, :promotion_name, :offer_type, :value, :category, "
                     ":starts_at, :ends_at, :coupon_code)", promotions)
    for i in range(1, n + 1):
        persona = rng.choices(personas, weights=weights)[0]
        c, orders, sessions, carts, loyalty, events, items = simulate_customer(
            f"U{i:04d}", persona, rng, ref, seed=seed, catalog=catalog, next_order_id=order_counter)
        conn.execute("INSERT INTO customers VALUES (:customer_id, :name, :city, :signup_date, :opted_in, :persona, "
                     ":points_mult, :plus_member, :signup_channel, :preferred_device, :consent_telegram, :consent_email, :consent_sms, "
                     ":consent_push, :consent_whatsapp)", c)
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         [(oid,) + o for oid, o in orders])
        conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", items)
        conn.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)", sessions)
        conn.executemany("INSERT INTO cart_events VALUES (?, ?, ?, ?, ?, ?)", carts)
        conn.executemany("INSERT INTO loyalty_tx VALUES (?, ?, ?, ?)", loyalty)
        conn.executemany(f"INSERT INTO events ({', '.join(EVENT_COLUMNS)}) VALUES ({', '.join('?' * len(EVENT_COLUMNS))})",
                         [[e[k] for k in EVENT_COLUMNS] for e in events])
    conn.commit()
    conn.close()
