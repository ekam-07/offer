"""Business rules / guardrails. Every offer is checked here before it can be sent.

validate() returns a list of human-readable violations like
"R4: 20% exceeds the AT_RISK limit of 15%". An empty list means the offer is allowed.
"""
import hashlib
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import List, Optional

from . import consent, offer_log
from .config import CATALOG, DATA_DIR, OFFERS, RULES
from .segments import has_open_cart

DISCOUNT_TYPES = {"percent", "flat", "bundle"}
ACTIVE_TYPES = {"percent", "flat", "shipping", "points", "bundle", "choice"}  # count as an "active offer" (R8)
SHIPPING_LIKE = ("shipping", "choice")  # PERK_CHOICE costs the same as free delivery (the other perk is equal)
TIERS = RULES["coupon_tiers"]


def _check_tier_order():
    """R19: on the same product a frequent buyer must always get a smaller coupon, less often,
    than an occasional, irregular or first-order customer. Existing-customer tiers must increase
    in that order; FIRST_ORDER must beat FREQUENT but may stay below IRREGULAR (new accounts are
    easy to fake). Refuse to run with tiers that break this."""
    def worse(a, b):  # a gives at least as much as b, or more often
        return (a["max_percent"] >= b["max_percent"] or a["max_coupon_inr"] > b["max_coupon_inr"]
                or a["coupon_every_days"] < b["coupon_every_days"])
    existing = [t for t in TIERS if not t.get("first_order")]
    pairs = list(zip(existing, existing[1:])) + [(existing[0], t) for t in TIERS if t.get("first_order")]
    for a, b in pairs:
        if worse(a, b):
            raise ValueError(f"R19: coupon tier {a['name']} must give less, less often, than {b['name']} "
                             f"(got {a['max_percent']}%/₹{a['max_coupon_inr']} every {a['coupon_every_days']}d vs "
                             f"{b['max_percent']}%/₹{b['max_coupon_inr']} every {b['coupon_every_days']}d)")


def _check_ladders():
    """R2: NONE must be the last offer in every segment, or the fallback could never reach what follows it."""
    for seg, s in RULES["segments"].items():
        if "NONE" in s["allowed"] and s["allowed"][-1] != "NONE":
            raise ValueError(f"R2: in segment {seg}, NONE must be the last allowed offer "
                             f"(offers after it can never be reached): {s['allowed']}")


_check_tier_order()
_check_ladders()
HISTORY_DAYS = max(t["coupon_every_days"] for t in TIERS) + 5  # enough history for R20


@dataclass
class Context:
    """State the rules need besides the customer: time, recent offers, budget used,
    feedback preferences and live store promotions."""
    now: datetime
    history: List[dict] = field(default_factory=list)  # this customer's given offers, newest first
    spent_today: float = 0.0
    prefs: dict = field(default_factory=lambda: {"fewer_offers": False, "suppressed": set()})
    store_promotions: List[dict] = field(default_factory=list)

    @classmethod
    def load(cls, customer_id, now=None):
        now = now or datetime.now()
        return cls(
            now=now,
            history=offer_log.customer_history(customer_id, now - timedelta(days=HISTORY_DAYS), now),
            spent_today=offer_log.spent_on(now),
            prefs=consent.active_prefs(customer_id, now),
            store_promotions=live_store_promotions(now),
        )

    def since(self, days):
        cut = (self.now - timedelta(days=days)).isoformat()
        return [h for h in self.history if h["created_at"] >= cut]


@lru_cache(maxsize=64)
def _promotions_at(hour_key):
    from .generate import SHOP_DB as shop
    if not shop.exists():
        return ()
    conn = sqlite3.connect(shop)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM promotions WHERE starts_at <= ? AND ends_at > ?", (hour_key, hour_key)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return tuple(dict(r) for r in rows)


def live_store_promotions(now):
    """Store-wide campaigns running at `now` (data/shop.db promotions), for R22 no-stacking."""
    return list(_promotions_at(now.replace(minute=0, second=0, microsecond=0).isoformat()))


def coupon_tier(c):
    """FIRST_ORDER if the customer has never ordered (segment NEW or NEVER_BOUGHT), else the
    first tier whose buy-chance threshold they reach."""
    if not c.get("orders_total"):
        return next(t for t in TIERS if t.get("first_order"))
    return next(t for t in TIERS if not t.get("first_order") and c.get("p_buy_7d", 0) >= t["min_p_buy_7d"])


# ---- Eligibility checks done before any offer is chosen --------------------------

def in_holdout(customer_id):
    """R18: stable random control group (same customer always lands in the same group)."""
    key = f"{RULES.get('holdout_salt', '')}:{customer_id}"
    bucket = int(hashlib.md5(key.encode()).hexdigest(), 16) % 100
    return bucket < RULES["holdout_pct"]


def in_quiet_hours(now):
    """R11"""
    start, end = RULES["frequency"]["quiet_hours"]
    return now.hour >= start or now.hour < end


def budget_allowance(now):
    """R13 pacing: how much of the daily budget may be committed by `now`. Linear over the
    sending window (quiet_hours end -> start), counting the current hour as available."""
    daily = RULES["budget"]["daily_inr"]
    if RULES["budget"].get("pacing") != "linear":
        return daily
    start, end = RULES["frequency"]["quiet_hours"]  # e.g. [22, 8]: send from 08:00 to 22:00
    window = start - end
    # Night decisions (allowed; only sending is blocked) get the first hour's slice.
    hours_open = min(window, max(1, now.hour - end + 1))
    return round(daily * hours_open / window, 2)


# ---- Value helpers -----------------------------------------------------------------

def category_margin(category):
    margins = RULES["category_margin_pct"]
    return margins.get(category, margins["default"])


def is_scoped(offer):
    """Offers that only apply to categories with enough margin (e.g. WELCOME)."""
    return offer.get("scope") == "margin_safe_categories"


def eligible_categories(value):
    """Categories where a value% discount still leaves the margin floor (R5)."""
    floor = RULES["margin_floor_pct"]
    return [cat for cat, m in RULES["category_margin_pct"].items() if cat != "default" and m - floor >= value]


def all_categories():
    return [k for k in RULES["category_margin_pct"] if k != "default"]


def safe_categories(c, offer_id, value):
    """R5 whatever the customer buys: categories where this offer still leaves the margin floor.
    A % off must fit each category's margin; a flat ₹ off or free delivery must fit it on the
    smallest basket the offer allows (an order of min_order in that category)."""
    offer = OFFERS[offer_id]
    if offer["type"] == "percent":
        return eligible_categories(value)
    basket = min_basket(c, offer_id)
    if not basket:
        return []
    cost = CATALOG["shipping_cost_inr"] if offer["type"] in SHIPPING_LIKE else value
    floor = RULES["margin_floor_pct"]
    return [cat for cat in all_categories() if (category_margin(cat) - floor) * basket / 100 >= cost]


def scope_categories(c, offer_id, value):
    """Categories a scoped offer is limited to, or None when it is safe everywhere (no limit to state)."""
    if not is_scoped(OFFERS[offer_id]):
        return None
    cats = safe_categories(c, offer_id, value)
    return None if len(cats) == len(all_categories()) else cats


def perk_points():
    """PERK_CHOICE's points option: worth exactly the delivery cost, so both perks cost the same."""
    return int(CATALOG["shipping_cost_inr"] / CATALOG["point_value_inr"])


def holds_live_offer(offer_id):
    """An offer whose validity the customer was told ("valid for 5 days"): while it lasts, it's theirs."""
    offer = OFFERS.get(offer_id or "NONE", {})
    return offer_id not in (None, "NONE") and bool(offer.get("valid_days")) and offer.get("state_validity", True)


def live_offer(history, now):
    """The newest still-valid offer this customer was told about, or None (R8)."""
    now_iso = now.isoformat()
    return next((h for h in history if holds_live_offer(h["offer_id"]) and (h["valid_until"] or "") > now_iso), None)


def is_bundle(offer_id):
    return offer_id in ("BUNDLE_SUGGEST", "BUNDLE_DEAL")


def is_product_coupon(offer):
    """Offers that apply only to the customer's focus product (PRODUCT_COUPON)."""
    return offer.get("scope") == "focus_product"


def _margin_room(c, offer):
    margins = [m for k, m in RULES["category_margin_pct"].items() if k != "default"]
    if is_scoped(offer) and offer["type"] == "percent":  # % off: limited to the categories that can afford it
        best = max(margins)
    elif is_product_coupon(offer):
        best = category_margin(c.get("focus_product_category") or c["top_category"])
    else:
        best = category_margin(c["top_category"])
    return best - RULES["margin_floor_pct"]


def base_aov(c):
    """Average order used for R6 and cost estimates; platform default when there is no history."""
    return c.get("aov") or RULES["default_aov_inr"]


def seg_limits(c):
    """R4 caps: the stricter of the customer's segment and base segment (so a VIP with an
    open cart keeps VIP's limits). Returns the caps plus a label for messages."""
    seg = c["segment"]
    base = c.get("base_segment") or seg
    a, b = RULES["segments"][seg], RULES["segments"][base]
    out = {}
    for key in ("max_percent", "max_flat_inr", "max_offer_cost_inr", "product_coupon_max_percent"):
        vals = [s[key] for s in (a, b) if s.get(key) is not None]
        out[key] = min(vals) if vals else None
    out["label"] = seg if base == seg else f"{seg}/{base}"
    return out


def _flat_ceiling(c, lim, offer_id="FLAT_OFF"):
    """Largest flat ₹ off allowed by R4/R6 (before the minimum basket is raised for R5)."""
    offer = OFFERS[offer_id]
    cap = min(offer["value_range"][1], lim["max_flat_inr"], base_aov(c) * RULES["max_flat_share_of_aov"],
              lim["max_offer_cost_inr"] if lim["max_offer_cost_inr"] is not None else float("inf"))
    return int(cap // 10 * 10)


def min_basket(c, offer_id):
    """Minimum basket (₹) for this offer and customer, or None if it would be unreasonably large.
    R5 for flat ₹ off and free shipping: the basket rises until the cost is within the
    category's allowed discount %; blocked if that exceeds max_min_basket_multiple x average order."""
    offer = OFFERS[offer_id]
    if is_product_coupon(offer):
        return coupon_tier(c).get("min_order_inr") or 0
    base = offer.get("min_order") or 0
    if offer.get("goal_multiple"):  # SPEND_GOAL: a target above their usual order, rounded up to ₹50
        base = max(base, int(-(-offer["goal_multiple"] * base_aov(c) // 50) * 50))
    if offer["type"] not in ("flat",) + SHIPPING_LIKE:
        return base
    room = _margin_room(c, offer)
    cost = CATALOG["shipping_cost_inr"] if offer["type"] in SHIPPING_LIKE else _flat_ceiling(c, seg_limits(c), offer_id)
    if room <= 0 or cost <= 0:
        return None if room <= 0 else base
    needed = -(-cost * 100 // room)  # ceil(cost / room%)
    basket = int(max(base, -(-needed // 10) * 10))  # round up to ₹10
    if basket > RULES["max_min_basket_multiple"] * base_aov(c):
        return None
    return basket


def _caps(c, offer_id):
    """Every cap on this offer's value for this customer: list of (limit, reason)."""
    offer = OFFERS[offer_id]
    lim = seg_limits(c)
    label = lim["label"]
    room = _margin_room(c, offer)
    floor = RULES["margin_floor_pct"]
    cost_cap = lim["max_offer_cost_inr"]
    caps = []
    if is_product_coupon(offer):
        tier = coupon_tier(c)
        price = c.get("focus_product_price") or 0
        caps = [(tier["max_percent"], f"R19: {tier['name']} coupon tier allows at most {tier['max_percent']}%"),
                (room, f"R5: {c.get('focus_product_category')} margin allows at most {room}% off "
                       f"(keeps the {floor}% floor)"),
                (int(tier["max_coupon_inr"] / price * 100) if price else 0,
                 f"R19: the {tier['name']} tier's ₹{tier['max_coupon_inr']} cap is under the minimum % on a ₹{price:.0f} product")]
        if lim["product_coupon_max_percent"] is not None:
            caps.append((lim["product_coupon_max_percent"],
                         f"R4: segment {label} allows coupons up to {lim['product_coupon_max_percent']}%"))
        if cost_cap is not None and price:
            caps.append((int(cost_cap / price * 100), f"R4: segment {label} allows offers costing up to ₹{cost_cap}"))
    elif offer["unit"] == "percent":
        caps = [(lim["max_percent"], f"R4: segment {label} allows at most {lim['max_percent']}% off"),
                (room, f"R5: {c['top_category']} margin allows at most {room}% off (keeps the {floor}% floor)")]
        if cost_cap is not None:
            caps.append((int(cost_cap / base_aov(c) * 100), f"R4: segment {label} allows offers costing up to ₹{cost_cap}"))
    elif offer["type"] == "bundle":
        price = c.get("bundle_item_price") or 0
        item_room = int(price * (category_margin(c.get("bundle_item_category")) - floor) / 100)
        caps = [(lim["max_flat_inr"], f"R4: segment {label} allows at most ₹{lim['max_flat_inr']} off"),
                (item_room, f"R5: ₹ off the {c.get('bundle_item_name')} must keep its {floor}% margin floor "
                            f"(at most ₹{item_room})")]
        if cost_cap is not None:
            caps.append((cost_cap, f"R4: segment {label} allows offers costing up to ₹{cost_cap}"))
    elif offer["unit"] == "inr":
        aov_cap = base_aov(c) * RULES["max_flat_share_of_aov"]
        caps = [(lim["max_flat_inr"], f"R4: segment {label} allows at most ₹{lim['max_flat_inr']} off"),
                (aov_cap, f"R6: 15% of the average order (₹{base_aov(c):.0f}) is only ₹{aov_cap:.0f}")]
        if cost_cap is not None:
            caps.append((cost_cap, f"R4: segment {label} allows offers costing up to ₹{cost_cap}"))
    elif offer["unit"] == "points" and cost_cap is not None:
        caps = [(int(cost_cap / CATALOG["point_value_inr"]),
                 f"R4: segment {label} allows offers costing up to ₹{cost_cap} ({int(cost_cap / CATALOG['point_value_inr'])} points)")]
    return caps


def value_bounds(c, offer_id, with_reason=False):
    """(min, max) value this customer may get for this offer after all caps, or None if impossible.
    with_reason=True returns (bounds, reason) where reason names the cap that made it impossible."""
    offer = OFFERS[offer_id]
    if offer["unit"] == "none":
        reason = None
        if offer["type"] in SHIPPING_LIKE:
            lim = seg_limits(c)
            if lim["max_offer_cost_inr"] is not None and CATALOG["shipping_cost_inr"] > lim["max_offer_cost_inr"]:
                reason = f"R4: segment {lim['label']} allows offers costing up to ₹{lim['max_offer_cost_inr']}"
            elif min_basket(c, offer_id) is None:
                reason = (f"R5: keeping the margin floor on free shipping in {c['top_category']} needs a basket over "
                          f"{RULES['max_min_basket_multiple']}x the customer's average order")
        bounds = None if reason else (0, 0)
        return (bounds, reason) if with_reason else bounds
    lo, hi = offer["value_range"]
    reason = None
    if is_bundle(offer_id) and not c.get("bundle_item_id"):
        reason = "R29: no bought-together item for this customer"
    if offer["type"] == "flat" and min_basket(c, offer_id) is None:
        reason = (f"R5: keeping the margin floor on a flat discount in {c['top_category']} needs a basket over "
                  f"{RULES['max_min_basket_multiple']}x the customer's average order")
    if is_product_coupon(offer):
        if not c.get("focus_product_id"):
            reason = "R19: no focus product (nothing in cart, wishlist or recently viewed)"
        elif c.get("uplift_group") == "sure_thing" and not RULES["coupons_for_sure_things"]:
            reason = "R19: coupons for customers who buy anyway are switched off (coupons_for_sure_things)"
    if reason is None:
        caps = _caps(c, offer_id)
        for limit, why in caps:
            if limit < lo:
                reason = f"{why}, below this offer's minimum of {lo}{'%' if offer['unit'] == 'percent' else ''}"
                break
        hi = min([hi] + [limit for limit, _ in caps])
        hi = int(hi // 10 * 10) if offer["unit"] == "inr" else int(hi)
        if hi < lo and reason is None:
            reason = f"caps leave no value between {lo} and {offer['value_range'][1]}"
    bounds = None if reason else (lo, hi)
    return (bounds, reason) if with_reason else bounds


def est_cost(c, offer_id, value):
    offer = OFFERS[offer_id]
    t = offer["type"]
    if is_product_coupon(offer):
        return round((c.get("focus_product_price") or 0) * value / 100, 2)
    if t == "percent":
        return round(base_aov(c) * value / 100, 2)
    if t == "flat":
        return float(value)
    if t in SHIPPING_LIKE:
        return float(CATALOG["shipping_cost_inr"])
    if t == "points":
        return round(value * CATALOG["point_value_inr"], 2)
    if t == "bundle":
        return float(value)
    return 0.0


# ---- Message checks ---------------------------------------------------------------

def _value_stated(message, unit, value):
    v = int(value)
    patterns = {
        "percent": rf"\b{v}\s*%",
        "inr": rf"(₹|rs\.?|inr)\s*{v}\b",
        "points": rf"\b{v}\b",
    }
    return re.search(patterns[unit], message, re.IGNORECASE) is not None


# "days" in English, Hinglish ("din") and Hindi ("दिन"), for the expiry and invented-terms checks
DAY_WORDS = r"(?:days?\b|din\b|दिन)"

BROAD_PHRASES = ["everything", "all products", "anything", "sitewide", "site-wide", "entire order", "whole order"]


def allowed_terms(c, offer, value):
    """The only day counts, rupee amounts and percentages a message may state for this offer.
    Shared by the checker and the AI prompt so both use the same facts."""
    days = set(offer.get("extra_allowed_days", []))
    if offer.get("valid_days") and offer.get("state_validity", True):
        days.add(offer["valid_days"])
    rupees = set()
    offer_id = next((k for k, v in OFFERS.items() if v is offer), None)
    basket = min_basket(c, offer_id) if offer_id else offer.get("min_order")
    if basket:
        rupees.add(basket)
    if offer["unit"] == "inr":
        rupees.add(int(value))
    if c.get("abandoned_cart_value"):
        rupees.add(int(c["abandoned_cart_value"]))
    if is_product_coupon(offer) and c.get("focus_product_price"):
        rupees.add(int(c["focus_product_price"]))
    if is_bundle(offer_id) and c.get("bundle_item_price"):
        rupees.add(int(c["bundle_item_price"]))
    if offer_id == "WISHLIST_ALERT":
        rupees |= {int(c[k]) for k in ("wishlist_alert_was_price", "wishlist_alert_price") if c.get(k)}
    percents = {int(value)} if offer["unit"] == "percent" else set()
    return {"days": sorted(days), "rupees": sorted(rupees), "percents": sorted(percents)}


def _check_terms(c, offer, value, low):
    """R15: no invented terms. Every number of days, ₹ amount and % must come from the catalog."""
    t = allowed_terms(c, offer, value)
    out = []
    for d in {int(x) for x in re.findall(rf"(\d+)[\s-]*{DAY_WORDS}", low)}:
        if d not in t["days"]:
            out.append(f"R15: message mentions {d} days, not a term of this offer"
                       + (f" (allowed: {', '.join(map(str, t['days']))} days)" if t["days"] else " (it has no customer-facing validity)"))
    if "week" in low and 7 not in t["days"]:
        out.append("R15: message mentions a week, not a term of this offer")
    for r in _rupee_amounts(low):
        if r not in t["rupees"]:
            out.append(f"R15: message mentions ₹{r}, not a term of this offer")
    for p in {int(x) for x in re.findall(r"(\d+)\s*%", low)}:
        if p not in t["percents"]:
            out.append(f"R15: message mentions {p}%, not the value of this offer")
    for phrase in RULES["message"]["unsupported_claims"]:
        if phrase in low:
            out.append(f"R15: message promises '{phrase}', which the offer catalog does not offer")
    return out


def _check_scope_text(low, eligible):
    """R15 for category-limited offers: name where it applies, never imply it applies everywhere."""
    named = [cat for cat in all_categories() if re.search(rf"\b{cat.lower()}\b", low)]
    out = []
    if not any(cat in eligible for cat in named):
        out.append(f"R15: category-limited offer must name where it applies ({', '.join(eligible)})")
    for cat in named:
        if cat not in eligible:
            out.append(f"R15: message mentions {cat}, where this offer does not apply")
    for phrase in BROAD_PHRASES:
        if phrase in low:
            out.append(f"R15: message says '{phrase}' but the offer only applies to {', '.join(eligible)}")
    return out


def _check_product_text(c, low):
    """R15 for product coupons: name the product, never imply the coupon covers more."""
    out = []
    names = [n.lower() for n in (c.get("focus_product_name"), c.get("focus_product_type")) if n]
    if not any(n in low for n in names):
        out.append(f"R15: product coupon must name the product it applies to ({c.get('focus_product_name')})")
    for phrase in BROAD_PHRASES:
        if phrase in low:
            out.append(f"R15: message says '{phrase}' but the coupon only applies to {c.get('focus_product_name')}")
    return out


def _check_new_offer_text(c, offer_id, low):
    """R15 for the bought-together, wishlist and perk messages: name the real item, never invent news."""
    out = []
    if is_bundle(offer_id) and c.get("bundle_item_name") and c["bundle_item_name"].lower() not in low:
        out.append(f"R15: a bought-together message must name the item ({c['bundle_item_name']})")
    if offer_id == "BUNDLE_DEAL":
        for phrase in BROAD_PHRASES:
            if phrase in low:
                out.append(f"R15: message says '{phrase}' but the ₹ off is only on {c.get('bundle_item_name')}")
    if offer_id == "WISHLIST_ALERT":
        item = c.get("wishlist_alert_item")
        if item and item.lower() not in low:
            out.append(f"R15: a wishlist alert must name the item ({item})")
        if c.get("wishlist_alert_kind") == "price_drop" and "price" not in low:
            out.append("R15: this wishlist alert is about a price drop and must say so")
        if c.get("wishlist_alert_kind") == "back_in_stock" and "back in stock" not in low:
            out.append("R15: this wishlist alert is about a restock and must say 'back in stock'")
        if c.get("wishlist_alert_kind") != "price_drop" and re.search(r"price (drop|cut)|cheaper|price.*(₹|rs)", low):
            out.append("R15: message claims a price drop that didn't happen")
    if offer_id == "PERK_CHOICE":
        if "delivery" not in low and "shipping" not in low:
            out.append("R15: pick-your-perk must offer free delivery as one choice")
        if "points" not in low or str(perk_points()) not in low:
            out.append(f"R15: pick-your-perk must offer {perk_points()} bonus points as the other choice")
    return out


def _rupee_amounts(low):
    return {int(x.replace(",", "")) for x in re.findall(r"(?:₹|\brs\.?|\binr)\s*([\d,]+)", low)}


def clean_text(s, max_len=40):
    """Sanitise customer-supplied text (names, search terms) before it reaches the AI or a
    template: letters, digits, spaces and a little punctuation only, length-capped."""
    if not s:
        return s
    s = re.sub(r"[^\w\s'.,&-]", " ", str(s), flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()[:max_len]


def first_name(c):
    return (clean_text(c.get("name"), 30) or "there").split()[0]


def _known_strings(c):
    """Customer/product text that may contain digits (e.g. 'Rice 5kg', 'SPF 50'), removed
    before the every-number check."""
    keys = ["focus_product_name", "focus_product_type", "abandoned_cart_item", "replenish_item", "review_due_item",
            "bundle_item_name", "bundle_anchor_item", "wishlist_alert_item"]
    return [str(c[k]).lower() for k in keys if c.get(k)] + [first_name(c).lower()]


def _check_numbers(c, offer, value, low):
    """R15: every number in the text must be a term of this offer or a fact about the customer."""
    t = allowed_terms(c, offer, value)
    allowed = set(t["days"]) | set(t["rupees"]) | set(t["percents"])
    if offer["type"] in ("points", "reminder") or offer.get("unit") == "points":
        allowed |= {int(value or 0), int(c.get("points_balance") or 0), int(c.get("points_expiring_30d") or 0)}
    if offer["type"] == "choice":  # "reply 1 ... or 2 ... N bonus points"
        allowed |= {1, 2, perk_points()}
    text = low
    for s in sorted(_known_strings(c), key=len, reverse=True):
        text = text.replace(s, " ")
    found = {int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", text) if x.replace(",", "").isdigit()}
    return [f"R15: the number {n} is not a term of this offer" for n in sorted(found - allowed)]


def _check_offer_type(offer_id, offer, low):
    """R15: the text must describe the chosen offer, not a different one."""
    out = []
    words = RULES["message"]["offer_keywords"].get(offer_id)
    if words and not any(w in low for w in words):
        out.append(f"R15: a {offer_id} message must mention {' / '.join(words)}")
    if offer["type"] not in DISCOUNT_TYPES and offer["type"] != "shipping":
        if re.search(r"\d+\s*%|\bdiscount\b|\bcoupon\b|(₹|rs\.?)\s*\d[\d,]*\s*off", low):
            out.append(f"R15: {offer_id} is not a discount, but the message talks about one")
    return out


def check_message(c, offer, value, message, offer_id=None):
    m = RULES["message"]
    out = []
    if not message or not message.strip():
        return ["R15: message is empty"]
    if len(message) > m["max_chars"]:
        out.append(f"R15: message is {len(message)} chars, limit is {m['max_chars']}")
    if "{" in message or "}" in message:
        out.append("R15: message contains an unfilled template placeholder")
    if m["must_state_value"] and offer["unit"] != "none" and not _value_stated(message, offer["unit"], value):
        out.append(f"R15: message does not state the real offer value ({int(value)} {offer['unit']})")
    days = offer.get("valid_days")
    if days and offer.get("state_validity", True):
        said = re.search(rf"\b{days}[\s-]*{DAY_WORDS}", message, re.IGNORECASE) or (days == 7 and "week" in message.lower())
        if not said:
            out.append(f"R15: message must state the expiry honestly (valid for {days} days)")
    low = message.lower()
    out += _check_terms(c, offer, value, low)
    out += _check_numbers(c, offer, value, low)
    if offer_id:
        out += _check_offer_type(offer_id, offer, low)
    for pattern in m["forbidden_patterns"]:
        if re.search(pattern, message, re.IGNORECASE):
            out.append("R15: message contains a link, email, phone number or HTML")
            break
    for item in m["sensitive_item_types"]:
        if item.lower() in low:
            out.append(f"R16: message names a sensitive product type ({item})")
    if is_scoped(offer):
        limited = scope_categories(c, offer_id or next(k for k, v in OFFERS.items() if v is offer), value)
        if limited is not None:
            out += _check_scope_text(low, limited)
    if is_product_coupon(offer):
        out += _check_product_text(c, low)
    out += _check_new_offer_text(c, offer_id, low)
    basket = min_basket(c, offer_id) if offer_id else None
    if basket and basket not in _rupee_amounts(low):
        out.append(f"R15: this offer needs a ₹{basket} minimum basket, and the message must say so")
    for phrase in m["banned_phrases"]:
        if phrase in low:
            out.append(f"R15: message uses banned pressure phrase '{phrase}'")
    for term in m["sensitive_terms"]:
        if re.search(rf"\b{re.escape(term)}\b", low):
            out.append(f"R16: message mentions sensitive attribute '{term}'")
    return out


# ---- Main validator ---------------------------------------------------------------

def validate(c, proposal, ctx, check_text=True):
    """Check one proposed offer {offer_id, value, message} against every rule."""
    offer_id = proposal.get("offer_id")
    if offer_id not in OFFERS:
        return [f"R17: offer_id '{offer_id}' is not in the offer catalog"]
    if not c.get("opted_in", False):
        return ["R1: customer has not opted in to offers"]
    if offer_id == "NONE":
        return []

    offer = OFFERS[offer_id]
    seg_name = c["segment"]
    seg = RULES["segments"][seg_name]
    lim = seg_limits(c)  # R4: stricter of segment and base segment
    freq = RULES["frequency"]
    value = proposal.get("value") or 0
    cost = est_cost(c, offer_id, value)
    out = []

    # R2 / R3: allowed for the segment, value within catalog range
    if offer_id not in seg["allowed"]:
        out.append(f"R2: {offer_id} is not allowed for segment {seg_name}")
    if offer["unit"] != "none":
        lo, hi = offer["value_range"]
        if not lo <= value <= hi:
            out.append(f"R3: value {value} is outside the catalog range {lo}-{hi} for {offer_id}")

    # R4-R6: value limits
    margin_room = _margin_room(c, offer)
    if offer_id == "WELCOME" and c.get("orders_total", 0) > 0:
        out.append("R21: WELCOME is for a customer's first order only")
    if is_product_coupon(offer):
        tier = coupon_tier(c)
        if not c.get("focus_product_id"):
            out.append("R19: product coupon needs a focus product (cart, wishlist or recently viewed)")
        if c.get("uplift_group") == "sure_thing" and not RULES["coupons_for_sure_things"]:
            out.append("R19: coupons for customers who buy anyway are switched off (coupons_for_sure_things)")
        seg_cap = lim["product_coupon_max_percent"]
        if seg_cap is not None and value > seg_cap:
            out.append(f"R4: segment {lim['label']} allows coupons up to {seg_cap}%")
        # R19: the tier, not the segment, caps product coupons
        if value > tier["max_percent"]:
            out.append(f"R19: {value}% exceeds the {tier['name']} coupon tier limit of {tier['max_percent']}% "
                       "(more regular buyers get smaller coupons)")
        coupon_inr = (c.get("focus_product_price") or 0) * value / 100
        if coupon_inr > tier["max_coupon_inr"]:
            out.append(f"R19: {value}% of ₹{c.get('focus_product_price'):.0f} is ₹{coupon_inr:.0f}, above the "
                       f"{tier['name']} tier cap of ₹{tier['max_coupon_inr']}")
        if value > margin_room:
            out.append(f"R5: {value}% off {c.get('focus_product_category')} leaves less than "
                       f"{RULES['margin_floor_pct']}% margin")
        # R20: coupon interval per tier
        last_discount = next((h for h in ctx.history if h["offer_type"] in DISCOUNT_TYPES), None)
        if last_discount:
            days = (ctx.now - datetime.fromisoformat(last_discount["created_at"])).total_seconds() / 86400
            if days < tier["coupon_every_days"]:
                out.append(f"R20: last discount was {days:.0f} days ago; {tier['name']} customers get a coupon "
                           f"at most every {tier['coupon_every_days']} days")
    elif offer["unit"] == "percent":
        if value > lim["max_percent"]:
            out.append(f"R4: {value}% exceeds the {lim['label']} limit of {lim['max_percent']}%")
        if is_scoped(offer):
            # Margin is protected by limiting the offer to categories that can afford it.
            if not eligible_categories(value):
                out.append(f"R5: no category has enough margin for {value}% off")
        elif value > margin_room:
            out.append(f"R5: {value}% off {c['top_category']} leaves less than {RULES['margin_floor_pct']}% margin")
    if offer["type"] == "bundle":
        if value > lim["max_flat_inr"]:
            out.append(f"R4: ₹{value} exceeds the {lim['label']} limit of ₹{lim['max_flat_inr']}")
        price = c.get("bundle_item_price") or 0
        room = price * (category_margin(c.get("bundle_item_category")) - RULES["margin_floor_pct"]) / 100
        if value > room:
            out.append(f"R5: ₹{value} off the {c.get('bundle_item_name')} leaves less than {RULES['margin_floor_pct']}% margin")
    elif offer["unit"] == "inr":
        if value > lim["max_flat_inr"]:
            out.append(f"R4: ₹{value} exceeds the {lim['label']} limit of ₹{lim['max_flat_inr']}")
        aov_cap = base_aov(c) * RULES["max_flat_share_of_aov"]
        if value > aov_cap:
            out.append(f"R6: ₹{value} is more than {int(RULES['max_flat_share_of_aov'] * 100)}% of the customer's average order (₹{int(base_aov(c))})")

    # R5 for flat ₹ off and free shipping: the minimum basket keeps the margin floor
    if offer["type"] in ("flat",) + SHIPPING_LIKE and min_basket(c, offer_id) is None:
        out.append(f"R5: keeping the {RULES['margin_floor_pct']}% margin floor in {c['top_category']} needs a basket over "
                   f"{RULES['max_min_basket_multiple']}x the customer's average order")
    elif is_scoped(offer) and offer["type"] in ("flat",) + SHIPPING_LIKE and not safe_categories(c, offer_id, value):
        out.append(f"R5: no category keeps the {RULES['margin_floor_pct']}% margin floor with this offer")
    # R4: cost cap for every paid offer, whatever its type (free shipping, points, coupons...)
    if lim["max_offer_cost_inr"] is not None and cost > lim["max_offer_cost_inr"]:
        out.append(f"R4: offer costs ₹{cost:.0f}, above the {lim['label']} cap of ₹{lim['max_offer_cost_inr']}")

    # R8: one live offer at a time: nothing new (paid or free) while they hold an offer they were told is valid
    now_iso = ctx.now.isoformat()
    live = live_offer(ctx.history, ctx.now) if RULES["frequency"].get("one_live_offer") else None
    if live:
        out.append(f"R8: customer already has a live offer ({live['offer_id']}) valid until {live['valid_until'][:16]}; "
                   "no new offer until it ends")
    # ...and one active paid offer at a time, never the same offer again while it is still valid
    if offer["type"] in ACTIVE_TYPES:
        for h in ctx.history:
            if h["offer_type"] in ACTIVE_TYPES and (h["valid_until"] or "") > now_iso:
                out.append(f"R8: customer already has an active offer ({h['offer_id']}) until {h['valid_until'][:16]}")
                break
    for h in ctx.history:
        if h["offer_id"] == offer_id and (h["valid_until"] or "") > now_iso:
            out.append(f"R8: {offer_id} was already sent and is valid until {h['valid_until'][:16]}; don't repeat it")
            break

    out += _frequency(offer_id, cost, ctx)

    # R10: cooldown after redeeming a discount
    redeemed = c.get("days_since_discount_redeemed")
    if offer["type"] in DISCOUNT_TYPES and redeemed is not None and redeemed < freq["discount_cooldown_days"]:
        out.append(f"R10: customer redeemed a discount {redeemed} days ago, cooldown is {freq['discount_cooldown_days']} days")

    # R12: anyone with an open cart gets a plain reminder first (whatever their segment)
    if has_open_cart(c) and offer["type"] not in {"reminder", "none", "access"}:
        wait = timedelta(hours=freq["escalation_wait_hours"])
        reminded = any(
            h["offer_id"] in ("CART_REMINDER", "CART_ALTERNATIVE") and ctx.now - datetime.fromisoformat(h["created_at"]) >= wait
            for h in ctx.history
        )
        if not reminded:
            out.append(f"R12: cart abandoner must get CART_REMINDER at least {freq['escalation_wait_hours']}h before a paid offer")

    # R12 escalation: the reminder didn't lead to a purchase (the cart is still open), so the next cart
    # message is a discount, not another reminder. If no discount pays (R30), they get nothing.
    stage = cart_escalation(c, ctx)
    if stage and offer_id not in RULES["frequency"]["cart_discount_offers"]:
        out.append(f"R12: a cart reminder {stage['days']:.0f} day(s) ago didn't lead to a purchase; the next step is a cart "
                   f"discount ({', '.join(RULES['frequency']['cart_discount_offers'])}), not {offer_id}")

    out += _guards(c, offer_id, offer, value, ctx)

    # R30: paid offers must be expected to make money (the goodwill coupon is the exception)
    if cost > 0 and not goodwill_coupon(c, offer_id):
        ep = expected_profit(c, offer_id, value)
        if ep["ep_inr"] <= 0:
            out.append(f"R30: expected profit ₹{ep['ep_inr']:.0f} is not positive (buy chance {ep['p_without']:.0%} -> "
                       f"{ep['p_with']:.0%}, margin ₹{ep['margin_inr']}, cost ₹{ep['cost_inr']:.0f})")

    # R31: per-customer spend cap over the window
    if cost > 0:
        window = ctx.since(RULES["spend_cap"]["window_days"])
        spent = sum(h.get("est_cost_inr") or 0 for h in window)
        cap = spend_cap(c)
        if spent + cost > cap:
            out.append(f"R31: ₹{spent:.0f} already given in {RULES['spend_cap']['window_days']} days + ₹{cost:.0f} "
                       f"is over this customer's cap of ₹{cap:.0f} ({RULES['spend_cap']['pct_of_margin_12m']}% of 12-month margin)")

    # R13: daily budget, paced over the day
    allowance = budget_allowance(ctx.now)
    if ctx.spent_today + cost > allowance:
        out.append(f"R13: cost ₹{cost:.0f} would exceed the budget released by {ctx.now:%H}:59 "
                   f"(₹{ctx.spent_today:.0f} of ₹{allowance:.0f} used; daily ₹{RULES['budget']['daily_inr']})")

    if check_text:
        out += check_message(c, offer, value, proposal.get("message", ""), offer_id)
    return out


def cart_escalation(c, ctx):
    """R12 escalation: the cart is still open, a reminder went out at least escalation_wait_hours ago
    (and within cart_escalation_days), and no cart discount has been given since. Returns
    {"days": days since the reminder} or None."""
    f = RULES["frequency"]
    if not f.get("cart_escalation") or not has_open_cart(c):
        return None
    wait, window = timedelta(hours=f["escalation_wait_hours"]), timedelta(days=f["cart_escalation_days"])
    reminder = next((h for h in ctx.history if h["offer_id"] in ("CART_REMINDER", "CART_ALTERNATIVE")
                     and wait <= ctx.now - datetime.fromisoformat(h["created_at"]) <= window), None)
    if not reminder:
        return None
    if any(h["offer_id"] in f["cart_discount_offers"] and h["created_at"] >= reminder["created_at"] for h in ctx.history):
        return None  # already escalated once: the normal rules take it from here
    return {"days": (ctx.now - datetime.fromisoformat(reminder["created_at"])).total_seconds() / 86400}


def goodwill_coupon(c, offer_id):
    """The one documented exception to R30: a small coupon for a customer who would buy anyway,
    kept as a business choice (coupons_for_sure_things)."""
    return (offer_id == "PRODUCT_COUPON" and c.get("uplift_group") == "sure_thing"
            and RULES["coupons_for_sure_things"])


def estimated_lift(c, offer_id, value):
    """The engine's own estimate of how much an offer raises the chance of buying in 7 days
    (rules.yaml expected_profit). Uses only observable signals, never the hidden persona."""
    p = RULES["expected_profit"]
    offer = OFFERS[offer_id]
    if offer_id in p["free_lift"]:
        lift = p["free_lift"][offer_id]
        conditions = {
            "CART_REMINDER": has_open_cart(c),
            "CART_ALTERNATIVE": bool(c.get("cart_alternative_name")),
            "REPLENISH_REMINDER": bool(c.get("replenish_due")),
            "POINTS_REMINDER": (c.get("points_expiring_30d") or 0) >= RULES["segment_thresholds"]["points_expiring_min"],
            "BUNDLE_SUGGEST": bool(c.get("bundle_item_id")),
            "WISHLIST_ALERT": bool(c.get("wishlist_alert_item")),
        }
        return lift if conditions.get(offer_id, True) else 0.0
    if offer["type"] in ("none", "reminder", "access"):
        return 0.0
    if offer["type"] == "choice":  # they pick whichever perk they value more
        best = max(estimated_lift(c, "FREE_SHIPPING", 0), estimated_lift(c, "BONUS_POINTS", perk_points()))
        return min(1.0, best * (1 + p["choice_bonus"]))
    price_signal = max(c.get("coupon_rate") or 0, 2 * (c.get("promo_ctr_90d") or 0))
    sensitivity = min(p["max_sensitivity"], p["base_sensitivity"] + p["price_signal_weight"] * price_signal
                      + p["churn_weight"] * (c.get("churn_risk") or 0))
    aov = base_aov(c)
    if offer["type"] == "bundle":  # ₹ off the bought-together item, on top of the suggestion itself
        price = c.get("bundle_item_price") or aov
        pct = value / price * 100
        return p["free_lift"]["BUNDLE_SUGGEST"] + sensitivity * pct / (pct + p["half_effect_pct"])
    if is_product_coupon(offer):
        pct = value * p["intent_factor"].get(c.get("focus_product_reason"), 0.5)
    elif offer["type"] == "percent":
        pct = value * (0.7 if offer_id == "CATEGORY_DEAL" else 1.0)
        if is_scoped(offer) and c.get("top_category") not in safe_categories(c, offer_id, value):
            pct *= p["scoped_breadth"]  # limited to categories the customer isn't browsing
    elif offer["type"] == "flat":
        # A spend goal's reward is measured against the target they must reach, not their usual order.
        pct = value / (max(aov, min_basket(c, offer_id) or 0) if offer.get("goal_multiple") else aov) * 100
    elif offer["type"] == "shipping":
        pct = min(10.0, CATALOG["shipping_cost_inr"] / aov * 100)
    else:  # points: worth less to customers than cash
        pct = value * CATALOG["point_value_inr"] / aov * 100 * 0.5
    lift = sensitivity * pct / (pct + p["half_effect_pct"])
    return lift * p["goal_completion"] if offer.get("goal_multiple") else lift


def expected_profit(c, offer_id, value):
    """R30: EP = (P_with - P_without) x margin - P_with x cost."""
    offer = OFFERS[offer_id]
    p0 = c.get("p_buy_7d", 0.05)
    if is_bundle(offer_id):
        # The extra sale is the bought-together ITEM: they'd add it anyway at the "bought with" rate.
        p0 = p0 * (c.get("bundle_confidence") or 0)
        p1 = p0 + (1 - p0) * estimated_lift(c, offer_id, value)
        margin = (c.get("bundle_item_price") or 0) * category_margin(c.get("bundle_item_category")) / 100
        cost = est_cost(c, offer_id, value)
        return {"p_without": round(p0, 3), "p_with": round(p1, 3), "margin_inr": round(margin),
                "cost_inr": round(cost, 2), "expected_cost_inr": round(p1 * cost, 2),
                "ep_inr": round((p1 - p0) * margin - p1 * cost, 2)}
    p1 = p0 + (1 - p0) * estimated_lift(c, offer_id, value)
    category = c.get("focus_product_category") if is_product_coupon(offer) else c.get("top_category")
    margin_pct = category_margin(category)
    if is_scoped(offer) and category not in safe_categories(c, offer_id, value):
        # A category-limited offer is spent in one of its eligible categories.
        cats = safe_categories(c, offer_id, value)
        margin_pct = sum(category_margin(x) for x in cats) / len(cats) if cats else 0  # usable nowhere (R5 rejects it)
    margin = base_aov(c) * margin_pct / 100
    cost = est_cost(c, offer_id, value)
    # Customers who buy BECAUSE of an offer with a minimum order fill their basket up to it
    # (expected_profit.count_basket_topup), so the extra order is bigger and, for a % off, costs more.
    extra_margin, extra_cost = margin, cost
    if (RULES["expected_profit"].get("count_basket_topup") and offer["type"] in ("flat", "percent") + SHIPPING_LIKE
            and not is_product_coupon(offer)):
        basket = max(base_aov(c), min_basket(c, offer_id) or 0)
        extra_margin = basket * margin_pct / 100
        extra_cost = basket * value / 100 if offer["type"] == "percent" else cost
    ep = (p1 - p0) * (extra_margin - extra_cost) - p0 * cost
    return {"p_without": round(p0, 3), "p_with": round(p1, 3), "margin_inr": round(extra_margin),
            "cost_inr": round(cost, 2), "expected_cost_inr": round(p1 * cost, 2),
            "ep_inr": round(ep, 2)}


def spend_cap(c):
    """R31: the most this customer may receive in offers over the window."""
    s = RULES["spend_cap"]
    margin = c.get("margin_365d")
    if margin is None:  # data without the field: estimate from recent orders x average order x margin %
        margin = (c.get("frequency_90d") or 0) * 4 * base_aov(c) * category_margin(c.get("top_category")) / 100
    return max(s["min_inr"], margin * s["pct_of_margin_12m"] / 100)


def _frequency(offer_id, cost, ctx):
    """R9: separate caps for paid offers and for all messages; cart reminders skip the gaps
    (they only matter inside the cart window) but count towards the weekly limits."""
    f = RULES["frequency"]
    out = []
    exempt = offer_id in f["gap_exempt_offers"]

    def check(history, min_hours, per_week, what):
        if history and not exempt:
            hours = (ctx.now - datetime.fromisoformat(history[0]["created_at"])).total_seconds() / 3600
            if hours < min_hours:
                out.append(f"R9: last {what} was {hours:.1f}h ago, minimum gap is {min_hours}h"
                           + (" (customer asked for fewer offers)" if what == "paid offer" and ctx.prefs.get("fewer_offers") else ""))
        week = [h for h in history if h["created_at"] >= (ctx.now - timedelta(days=7)).isoformat()]
        if len(week) >= per_week:
            out.append(f"R9: {len(week)} {what}s in the last 7 days, limit is {per_week}")

    check(ctx.history, f["message_min_hours_between"], f["message_max_per_7_days"], "message")
    if cost > 0:
        paid_gap = f["paid_min_hours_between"]
        if ctx.prefs.get("fewer_offers"):
            paid_gap = max(paid_gap, RULES["feedback"]["fewer_offers_min_hours"])
        paid = [h for h in ctx.history if (h.get("est_cost_inr") or 0) > 0]
        check(paid, paid_gap, f["paid_max_per_7_days"], "paid offer")
    return out


def _guards(c, offer_id, offer, value, ctx):
    """R22-R26, R28, R29: stacking, abuse, discount training, stock, uplift group, feedback,
    and conditions for the free offers."""
    g = RULES["guards"]
    out = []
    cash_discount = offer["type"] in DISCOUNT_TYPES
    costs_money = est_cost(c, offer_id, value) > 0

    # R22: never stack a coupon on a store promotion that already covers this purchase
    if cash_discount:
        category = (c.get("focus_product_category") if is_product_coupon(offer)
                    else c.get("bundle_item_category") if is_bundle(offer_id) else c.get("top_category"))
        for p in ctx.store_promotions:
            if p["offer_type"] != "FREE_SHIPPING" and p["category"] in (None, category):
                out.append(f"R22: store promotion {p['promotion_id']} ({p['promotion_name']}) is live for "
                           f"{p['category'] or 'everything'}; discounts don't stack (one discount per order)")
                break

    # R23: abuse guard
    if costs_money:
        if c.get("orders_365d", 0) >= g["abuse_min_orders"] and c.get("return_rate_365d", 0) >= g["abuse_max_return_rate"]:
            out.append(f"R23: return rate {c['return_rate_365d']:.0%} in 12 months is above "
                       f"{g['abuse_max_return_rate']:.0%}; no paid offers")
        if c.get("coupon_returns_365d", 0) >= g["abuse_max_coupon_returns"]:
            out.append(f"R23: {c['coupon_returns_365d']} coupon orders returned in 12 months; no paid offers")
        if c.get("suspected_multi_account"):
            out.append("R23: suspected duplicate account; no paid offers")

    # R24: don't train customers to wait for discounts
    n = g["discount_training_last_orders"]
    if cash_discount and c.get("orders_total", 0) >= n and c.get(f"coupon_orders_last{n}", 0) >= n:
        out.append(f"R24: the last {n} orders all used a coupon; no discount now, so they don't learn to wait for one")

    # R25: stock
    if is_product_coupon(offer) and c.get("focus_product_in_stock") is False:
        out.append(f"R25: {c.get('focus_product_name')} is out of stock; never promote it")
    if offer_id == "CART_REMINDER" and c.get("cart_item_in_stock") is False:
        out.append(f"R25: the cart item {c.get('abandoned_cart_item')} is out of stock; suggest an alternative instead")

    # R26: uplift group
    group = c.get("uplift_group")
    if group == "sleeping_dog":
        out.append("R26: offers backfire for this customer (sleeping dog); no offers")
    elif group == "lost_cause" and costs_money:
        out.append("R26: lost cause (long gone, not browsing); free offers only")

    # R28: "not interested" in this offer type recently
    if offer_id in ctx.prefs.get("suppressed", ()):
        out.append(f"R28: customer said 'not interested' to {offer_id} recently")

    # R29: free offers only when their condition holds
    if offer_id == "CART_ALTERNATIVE" and not (c.get("cart_item_in_stock") is False and c.get("cart_alternative_name")):
        out.append("R29: CART_ALTERNATIVE is only for an out-of-stock cart item with a similar product in stock")
    if offer_id == "REPLENISH_REMINDER" and not c.get("replenish_due"):
        out.append("R29: no restock is due (needs a usual reorder cycle in Grocery or Beauty)")
    if offer_id == "REVIEW_REQUEST" and not c.get("review_due_item"):
        out.append("R29: no recent purchase waiting for a review")
    if offer_id == "POINTS_UPDATE" and c.get("points_balance", 0) < g["points_update_min_balance"]:
        out.append(f"R29: points balance below {g['points_update_min_balance']}")
    if is_bundle(offer_id) and not c.get("bundle_item_id"):
        out.append("R29: no bought-together item for this customer")
    if offer_id == "WISHLIST_ALERT" and not c.get("wishlist_alert_item"):
        out.append("R29: no wishlist item has really dropped in price or come back in stock")
    if offer_id == "PERK_CHOICE" and ctx.prefs.get("perk"):
        out.append(f"R29: they already picked {ctx.prefs['perk']} as their perk; send that directly instead of asking again")
    return out


def feasible_offers(c, ctx):
    """Offers this customer may receive right now, with the value range still open.

    Returns (feasible, blocked): feasible is a list of option dicts the agent may pick
    from; blocked maps offer_id -> the violations that ruled it out.
    """
    feasible, blocked = [], {}
    for offer_id in RULES["segments"][c["segment"]]["allowed"]:
        offer = OFFERS[offer_id]
        bounds, why = value_bounds(c, offer_id, with_reason=True)
        if bounds is None:
            blocked[offer_id] = [why]
            continue
        lo, hi = bounds
        # The value with the best expected profit (R30) among a few candidates in the range.
        candidates = sorted({lo, hi, (lo + hi) // 2} if offer["unit"] != "none" else {0})
        if offer["unit"] == "inr":
            candidates = sorted({v // 10 * 10 for v in candidates if v // 10 * 10 >= lo} or {lo})
        best = max(candidates, key=lambda v: expected_profit(c, offer_id, v)["ep_inr"])
        problems = validate(c, {"offer_id": offer_id, "value": best}, ctx, check_text=False)
        if problems:
            blocked[offer_id] = problems
            continue
        ep = expected_profit(c, offer_id, best)
        option = {
            "offer_id": offer_id,
            "type": offer["type"],
            "unit": offer["unit"],
            "min_value": lo,
            "max_value": hi,
            "min_order_inr": min_basket(c, offer_id) or None,
            "valid_days": offer.get("valid_days"),
            "est_cost_inr_at_max": est_cost(c, offer_id, hi),
            "best_value": best,
            "expected_profit_at_best": ep,
            "goodwill_exception": goodwill_coupon(c, offer_id),
            "description": offer["description"],
        }
        limited = scope_categories(c, offer_id, hi)
        if limited is not None:
            option["applies_only_to_categories"] = limited
        if is_product_coupon(offer):
            option["applies_only_to_product"] = {"name": c["focus_product_name"], "price_inr": c["focus_product_price"],
                                                 "why": c.get("focus_product_reason")}
            option["coupon_tier"] = coupon_tier(c)["name"]
        feasible.append(option)
    return feasible, blocked


def valid_until(offer_id, now) -> Optional[str]:
    days = OFFERS[offer_id].get("valid_days")
    return (now + timedelta(days=days)).isoformat() if days else None
