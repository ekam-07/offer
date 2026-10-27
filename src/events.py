"""Full-year browsing event stream with GA4-style event names (see docs/DATA_DICTIONARY.md).

Builds the product catalog and store promotions, then simulates every browsing session a
customer had in the last 365 days: search or category browsing, impressions, clicks, product
views, wishlist, brand follows, "not interested", cart adds/removes, checkout and purchase,
plus later reviews and refunds. Purchase sessions line up with the orders generated in
generate.py, so orders and events always agree.
"""
import random
from datetime import date, timedelta

import yaml

from .config import CONFIG_DIR

with open(CONFIG_DIR / "catalog.yaml", encoding="utf-8") as f:
    CAT = yaml.safe_load(f)

DEVICES = ["mobile_app", "mobile_web", "desktop"]
EVENT_COLUMNS = ["customer_id", "session_id", "event_time", "event_name", "product_id", "brand", "category",
                 "price", "quantity", "value", "search_term", "item_list_name", "position", "promotion_id",
                 "coupon", "transaction_id", "rating", "device"]


# ---- Catalog and promotions -------------------------------------------------------------

def build_products(seed, ref):
    rng = random.Random(f"{seed}-catalog")
    products, n = [], 0
    for category, items in CAT["items"].items():
        for item_type, l2, base in items:
            for brand in rng.sample(CAT["brands"][category], CAT["brands_per_item"]):
                n += 1
                price = base * rng.uniform(*CAT["brand_price_factor"])
                products.append({
                    "product_id": f"P{n:04d}",
                    "name": f"{brand} {item_type}",
                    "item_type": item_type,
                    "brand": brand,
                    "category": category,
                    "category_l2": l2,
                    "price": float(max(99, round(price / 10) * 10 - 1)),  # ends in 9, like store prices
                    "avg_rating": round(rng.uniform(*CAT["rating_range"]), 1),
                    "launch_date": (ref - timedelta(days=rng.randint(30, 720))).date().isoformat(),
                })
    # Stock uses its own random stream so prices and ratings above stay unchanged.
    srng = random.Random(f"{seed}-stock")
    st = CAT["stock"]
    for p in products:
        r = srng.random()
        units = 0 if r < st["out_of_stock_share"] else (
            srng.randint(*st["overstock_units"]) if r < st["out_of_stock_share"] + st["overstock_share"]
            else srng.randint(*st["normal_units"]))
        p["stock_units"] = units
        p["overstock"] = int(units >= st["overstock_units"][0])
    # Recent price drops and restocks, also on their own stream.
    prng = random.Random(f"{seed}-price")
    pc = CAT["price_changes"]
    for p in products:
        r, when = prng.random(), ref - timedelta(days=prng.uniform(0, pc["window_days"]))
        p["was_price"] = p["price_dropped_at"] = p["restocked_at"] = None
        if p["stock_units"] == 0:
            continue
        if r < pc["drop_share"]:
            drop = prng.randint(*pc["drop_pct"]) / 100
            p["was_price"] = float(round(p["price"] / (1 - drop) / 10) * 10 - 1)
            p["price_dropped_at"] = when.isoformat(timespec="seconds")
        elif r < pc["drop_share"] + pc["restock_share"]:
            p["restocked_at"] = when.isoformat(timespec="seconds")
    return products


def festival_multiplier(day):
    """Browsing boost in the run-up to a festival (catalog.yaml festivals), e.g. Diwali."""
    for f in CAT["festivals"]:
        days_before = (date.fromisoformat(f["date"]) - day.date()).days
        if 0 <= days_before <= f["boost_days_before"]:
            return f["browsing_boost"]
    return 1.0


def build_promotions(seed, ref):
    rng = random.Random(f"{seed}-promotions")
    cfg = CAT["promotions"]
    promos, t, n = [], ref - timedelta(days=365), 0
    # The store plans campaigns ahead: the calendar runs 60 days past `ref` (used by R22 and
    # the 30-day simulation). Past campaigns are generated first, so they don't change.
    while t < ref + timedelta(days=cfg["plan_ahead_days"]):
        n += 1
        kind, value, scope = rng.choice(cfg["types"])
        category = rng.choice(list(CAT["items"])) if scope == "category" else None
        end = t + timedelta(days=rng.randint(*cfg["duration_days"]))
        label = {"PERCENT_OFF": f"{value}% off", "FLAT_OFF": f"Rs {value} off", "FREE_SHIPPING": "Free shipping",
                 "CATEGORY_DEAL": f"{value}% off"}[kind]
        promos.append({
            "promotion_id": f"PR{n:03d}",
            "promotion_name": f"{label} {category or 'sitewide'}",
            "offer_type": kind,
            "value": value,
            "category": category,
            "starts_at": t.isoformat(timespec="seconds"),
            "ends_at": end.isoformat(timespec="seconds"),
            "coupon_code": f"{kind.split('_')[0][:4]}{value}{(category or 'ALL')[:3].upper()}{n}",
        })
        t += timedelta(days=cfg["every_days"])
    return promos


# ---- Session simulation -----------------------------------------------------------------

class CustomerEvents:
    """Generates one customer's events. `b` holds behaviour rates (defaults + persona overrides)."""

    def __init__(self, cid, b, products_by_cat, promotions, ref, rng):
        self.cid, self.b, self.pbc, self.promos, self.ref, self.rng = cid, b, products_by_cat, promotions, ref, rng
        self.events, self.order_items, self.returned, self.coupons = [], [], set(), {}
        self.followed, self.n_sessions = set(), 0
        self.device = rng.choice(DEVICES)

    def _emit(self, t, sid, device, name, product=None, **kw):
        row = dict.fromkeys(EVENT_COLUMNS)
        row.update(customer_id=self.cid, session_id=sid, event_time=t.isoformat(timespec="seconds"),
                   event_name=name, device=device, **kw)
        if product:
            row.update(product_id=product["product_id"], brand=product["brand"], category=product["category"],
                       price=product["price"])
        self.events.append(row)

    def _active_promo(self, t):
        live = [p for p in self.promos if p["starts_at"] <= t.isoformat() < p["ends_at"]]
        return live[0] if live else None

    def session(self, t, category, order=None, forced_cart=None):
        """One visit. order = (order_id, created_at, total, used_coupon) for a purchase session."""
        rng, b = self.rng, self.b
        self.n_sessions += 1
        sid = f"{self.cid}-S{self.n_sessions:04d}"
        device = self.device if rng.random() < 0.7 else rng.choice(DEVICES)
        clock = [t]

        def tick():
            clock[0] += timedelta(seconds=rng.randint(8, 90))
            return clock[0]

        self._emit(clock[0], sid, device, "session_start")

        promo = self._active_promo(clock[0])
        if promo and rng.random() < b["promo_view_rate"]:
            self._emit(tick(), sid, device, "view_promotion", promotion_id=promo["promotion_id"])
            if rng.random() < b["promo_click_rate"]:
                self._emit(tick(), sid, device, "select_promotion", promotion_id=promo["promotion_id"])

        pool = self.pbc[category]
        if rng.random() < b["search_rate"]:
            item_type = rng.choice(pool)["item_type"].lower()
            term = f"{category.lower()} offers" if rng.random() < b["promo_click_rate"] else item_type
            self._emit(tick(), sid, device, "search", search_term=term)
            list_name, shown = "search_results", rng.sample(pool, min(8, len(pool)))
            matching = [p for p in pool if p["item_type"].lower() == term]
            shown = matching + [p for p in shown if p not in matching]
            shown = shown[:8]
        else:
            list_name, shown = "category_page", rng.sample(pool, min(6, len(pool)))
        for pos, p in enumerate(shown, 1):
            self._emit(clock[0], sid, device, "view_item_list", p, item_list_name=list_name, position=pos)

        viewed = []
        for pos, p in enumerate(shown, 1):
            if rng.random() < b["click_rate"] / (1 + 0.35 * (pos - 1)):
                self._emit(tick(), sid, device, "select_item", p, item_list_name=list_name, position=pos)
                self._emit(tick(), sid, device, "view_item", p)
                viewed.append(p)

        if rng.random() < b["not_interested_rate"]:
            self._emit(tick(), sid, device, "not_interested", rng.choice(shown))
        for p in viewed:
            if rng.random() < b["wishlist_rate"]:
                self._emit(tick(), sid, device, "add_to_wishlist", p, value=p["price"])
        if viewed and rng.random() < b["follow_rate"]:
            brand_item = rng.choice(viewed)
            if brand_item["brand"] not in self.followed:
                self.followed.add(brand_item["brand"])
                self._emit(tick(), sid, device, "follow_brand", brand_item)

        if order is not None:
            self._purchase(sid, device, tick, category, viewed, order)
        elif forced_cart is not None:
            self._emit(tick(), sid, device, "view_item", forced_cart)
            self._emit(tick(), sid, device, "add_to_cart", forced_cart, quantity=1, value=forced_cart["price"])
        elif rng.random() < b["abandon_rate"]:
            item = viewed[0] if viewed else rng.choice(shown)
            if not viewed:
                self._emit(tick(), sid, device, "view_item", item)
            self._emit(tick(), sid, device, "add_to_cart", item, quantity=1, value=item["price"])
            if rng.random() < 0.15:
                self._emit(tick(), sid, device, "remove_from_cart", item, quantity=1, value=item["price"])

    def _purchase(self, sid, device, tick, category, viewed, order):
        rng = self.rng
        order_id, created_at, total, used_coupon = order
        pool = self.pbc[category]
        k = rng.choice([1, 1, 1, 2, 2, 3])
        items = (viewed + [p for p in rng.sample(pool, len(pool)) if p not in viewed])[:k]
        weight = sum(p["price"] for p in items)
        lines = [(p, round(total * p["price"] / weight, 2)) for p in items]  # split the order total by list price
        for p, line_total in lines:
            if p not in viewed:
                self._emit(tick(), sid, device, "view_item", p)
            self._emit(tick(), sid, device, "add_to_cart", p, quantity=1, value=line_total)
            self.order_items.append((order_id, p["product_id"], 1, p["price"], line_total))
        self._emit(tick(), sid, device, "view_cart", value=total)
        coupon, promo_id = None, None
        if used_coupon:
            promo = self._active_promo(created_at)
            coupon, promo_id = (promo["coupon_code"], promo["promotion_id"]) if promo else ("APP10", None)
            self.coupons[order_id] = (coupon, promo_id)
        self._emit(tick(), sid, device, "begin_checkout", value=total, coupon=coupon)
        self._emit(created_at, sid, device, "purchase", value=total, coupon=coupon, promotion_id=promo_id,
                   transaction_id=str(order_id), quantity=len(lines))

        if rng.random() < self.b["review_rate"]:
            at = created_at + timedelta(days=rng.uniform(3, 20))
            if at < self.ref:
                p = lines[0][0]
                rating = max(1, min(5, round(rng.gauss(p["avg_rating"], 0.9))))
                self._emit(at, None, device, "write_review", p, rating=rating, transaction_id=str(order_id))
        return_p = CAT_RETURN_RATE.get(category, 0.03) * self.b["return_rate_mult"]
        if rng.random() < return_p:
            at = created_at + timedelta(days=rng.uniform(5, 20))
            if at < self.ref:
                self.returned.add(order_id)
                self._emit(at, None, device, "refund", lines[0][0], value=total, transaction_id=str(order_id))


CAT_RETURN_RATE = {}  # set by generate.py from personas.yaml (return_rate_by_category)


# ---- Compatibility: the older sessions / cart_events tables ---------------------------------

def legacy_tables(events, product_names):
    """Derive the original `sessions` and `cart_events` rows from the event stream,
    so the existing features keep working."""
    by_session = {}
    for e in events:
        if e["session_id"]:
            by_session.setdefault(e["session_id"], []).append(e)
    sessions, carts = [], []
    for sid, evs in by_session.items():
        cats = [e["category"] for e in evs if e["category"]]
        purchased = any(e["event_name"] == "purchase" for e in evs)
        first = evs[0]
        sessions.append((first["customer_id"], first["event_time"],
                         sum(e["event_name"] in ("view_item", "view_item_list") for e in evs),
                         max(set(cats), key=cats.count) if cats else None, first["device"], int(purchased)))
        adds = [e for e in evs if e["event_name"] == "add_to_cart"]
        removed = {e["product_id"] for e in evs if e["event_name"] == "remove_from_cart"}
        if purchased and adds:
            a = adds[0]
            carts.append((a["customer_id"], a["event_time"], "checkout", product_names[a["product_id"]], a["category"], a["value"]))
        elif adds and adds[-1]["product_id"] not in removed:
            a = adds[-1]
            carts.append((a["customer_id"], a["event_time"], "abandon", product_names[a["product_id"]], a["category"], a["value"]))
    return sessions, carts
