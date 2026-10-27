"""Computes one feature row per customer from the raw tables in data/shop.db.

The first block of fields matches data/sample_customers.json, so the decision engine and
the preview page can use either file. The rest (browsing funnel, wishlist, brands, promotions,
reviews, returns, consent, Amazon-style audiences) come from the full-year event stream.
Column meanings: docs/DATA_DICTIONARY.md.
"""
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from .config import RULES
from .events import CAT as _CAT

CAT_PRICE_WINDOW_DAYS = _CAT["price_changes"]["window_days"]
from .generate import P, SHOP_DB


def _dt(s):
    return datetime.fromisoformat(s)


def _points(txs, ref):
    """FIFO loyalty lots: points expire points_expire_days after they were earned."""
    life = timedelta(days=P["points_expire_days"])
    lots = []  # [earned_at, points]
    for at, kind, pts in sorted(txs):
        lots = [l for l in lots if l[0] > at - life]
        if kind == "earn":
            lots.append([at, pts])
        else:
            need = -pts
            for lot in lots:
                used = min(need, lot[1])
                lot[1] -= used
                need -= used
            lots = [l for l in lots if l[1] > 0]
    lots = [l for l in lots if l[0] > ref - life]
    balance = sum(l[1] for l in lots)
    expiring = sum(l[1] for l in lots if l[0] <= ref - life + timedelta(days=30))
    return balance, expiring


def _tier(spend_12m):
    if spend_12m >= 100_000:
        return "Platinum"
    if spend_12m >= 40_000:
        return "Gold"
    if spend_12m >= 15_000:
        return "Silver"
    return "Bronze"


def compute(ref=None):
    ref = ref or datetime.now()
    conn = sqlite3.connect(SHOP_DB)
    conn.row_factory = sqlite3.Row

    def grouped(sql):
        out = defaultdict(list)
        for r in conn.execute(sql, (ref.isoformat(),)):
            out[r["customer_id"]].append(r)
        return out

    orders = grouped("SELECT * FROM orders WHERE created_at <= ? ORDER BY created_at")
    sessions = grouped("SELECT * FROM sessions WHERE started_at <= ?")
    carts = grouped("SELECT * FROM cart_events WHERE created_at <= ? ORDER BY created_at")
    loyalty = grouped("SELECT * FROM loyalty_tx WHERE created_at <= ?")
    events = grouped("SELECT * FROM events WHERE event_time <= ? ORDER BY event_time")
    items_by_order = defaultdict(list)
    for r in conn.execute("SELECT * FROM order_items"):
        items_by_order[r["order_id"]].append(r)
    products = {r["product_id"]: dict(r) for r in conn.execute("SELECT * FROM products")}
    bought_with = _bought_with(conn)
    brands = {pid: p["brand"] for pid, p in products.items()}

    rows = []
    for c in conn.execute("SELECT * FROM customers ORDER BY customer_id"):
        cid = c["customer_id"]
        o = orders[cid]
        dates = [_dt(r["created_at"]) for r in o]
        gaps = [(b - a).total_seconds() / 86400 for a, b in zip(dates, dates[1:])]
        sess = sessions[cid]

        if o:
            top_category = Counter(r["category"] for r in o).most_common(1)[0][0]
        elif sess:
            top_category = Counter(r["category"] for r in sess).most_common(1)[0][0]
        else:
            top_category = "Fashion"

        # Open abandoned cart = latest cart event is an abandon with no order after it.
        cart_hours = cart_value = cart_item = None
        if carts[cid]:
            last = carts[cid][-1]
            last_at = _dt(last["created_at"])
            if last["action"] == "abandon" and not any(d > last_at for d in dates):
                cart_hours = int((ref - last_at).total_seconds() // 3600)
                cart_value, cart_item = last["value"], last["product"]

        coupon_dates = [d for d, r in zip(dates, o) if r["used_coupon"]]
        points, expiring = _points([(_dt(r["created_at"]), r["kind"], r["points"]) for r in loyalty[cid]], ref)
        spend_12m = sum(r["total"] for d, r in zip(dates, o) if d > ref - timedelta(days=365))

        rows.append({
            "customer_id": cid,
            "name": c["name"],
            "persona": c["persona"],
            "opted_in": bool(c["opted_in"]),
            "city": c["city"],
            "tenure_days": (ref - _dt(c["signup_date"])).days,
            "orders_total": len(o),
            "recency_days": (ref - dates[-1]).days if dates else 0,
            "avg_gap_days": round(sum(gaps) / len(gaps), 1) if gaps else 0,
            "frequency_90d": sum(1 for d in dates if d > ref - timedelta(days=90)),
            "aov": round(sum(r["total"] for r in o) / len(o)) if o else 0,
            "coupon_rate": round(len(coupon_dates) / len(o), 2) if o else 0.0,
            "top_category": top_category,
            "cart_abandoned_hours_ago": cart_hours,
            "abandoned_cart_value": cart_value or 0,
            "abandoned_cart_item": cart_item,
            "browse_no_buy_14d": sum(1 for s in sess if not s["purchased"] and _dt(s["started_at"]) > ref - timedelta(days=14)),
            "points_balance": points,
            "points_expiring_30d": expiring,
            "tier": _tier(spend_12m),
            "days_since_discount_redeemed": (ref - coupon_dates[-1]).days if coupon_dates else None,
            **_profile(c),
            **_event_features(events[cid], o, items_by_order, brands, ref),
            **_focus_product(events[cid], o, items_by_order, products, top_category, ref),
            **_extra_features(events[cid], o, items_by_order, products, ref),
            **_bundle(events[cid], o, items_by_order, products, bought_with, ref),
            **_wishlist_alert(events[cid], o, items_by_order, products, ref),
        })
    conn.close()
    _add_audiences(rows)
    return rows


# ---- New parameters (full-year event stream) ------------------------------------------------

def _profile(c):
    keys = ["plus_member", "signup_channel", "preferred_device", "consent_telegram", "consent_email", "consent_sms", "consent_push",
            "consent_whatsapp"]
    out = {k: c[k] for k in keys}
    for k in keys:
        if k == "plus_member" or k.startswith("consent_"):
            out[k] = bool(out[k])
    return out


def _event_features(evs, orders, items_by_order, brands, ref):
    """Counts over Amazon-style lookback windows (7/30/90/365 days) from the event stream."""
    cut = {d: (ref - timedelta(days=d)).isoformat() for d in (7, 14, 30, 90, 365)}

    def count(name, days):
        return sum(1 for e in evs if e["event_name"] == name and e["event_time"] > cut[days])

    def sessions(days):
        return len({e["session_id"] for e in evs if e["session_id"] and e["event_time"] > cut[days]})

    def orders_in(days):
        return [r for r in orders if r["created_at"] > cut[days]]

    searches = [e for e in evs if e["event_name"] == "search"]
    impressions_30, clicks_30 = count("view_item_list", 30), count("select_item", 30)
    promo_views, promo_clicks = count("view_promotion", 90), count("select_promotion", 90)
    o90, o365 = orders_in(90), orders_in(365)

    bought = {i["product_id"] for r in orders for i in items_by_order.get(r["order_id"], [])}
    wishlisted = {e["product_id"] for e in evs if e["event_name"] == "add_to_wishlist"}
    followed = sorted({e["brand"] for e in evs if e["event_name"] == "follow_brand"})
    ratings = [e["rating"] for e in evs if e["event_name"] == "write_review" and e["event_time"] > cut[365]]
    returns = sum(1 for r in o365 if r["returned"])
    brand_counts = Counter(brands[i["product_id"]] for r in orders for i in items_by_order.get(r["order_id"], []))
    top_brand, top_n = brand_counts.most_common(1)[0] if brand_counts else (None, 0)

    return {
        "sessions_7d": sessions(7), "sessions_30d": sessions(30), "sessions_90d": sessions(90),
        "product_views_7d": count("view_item", 7), "product_views_30d": count("view_item", 30),
        "product_views_90d": count("view_item", 90),
        "searches_30d": sum(1 for e in searches if e["event_time"] > cut[30]),
        "last_search_term": searches[-1]["search_term"] if searches else None,
        "impressions_30d": impressions_30,
        "clicks_30d": clicks_30,
        "ctr_30d": round(clicks_30 / impressions_30, 3) if impressions_30 else 0.0,
        "cart_adds_30d": count("add_to_cart", 30), "cart_adds_90d": count("add_to_cart", 90),
        "cart_removes_30d": count("remove_from_cart", 30),
        "wishlist_adds_90d": count("add_to_wishlist", 90),
        "wishlist_open_items": len(wishlisted - bought),
        "promo_views_90d": promo_views, "promo_clicks_90d": promo_clicks,
        "promo_ctr_90d": round(promo_clicks / promo_views, 3) if promo_views else 0.0,
        "brands_followed": len(followed), "followed_brands": "|".join(followed) or None,
        "not_interested_90d": count("not_interested", 90),
        "orders_30d": len(orders_in(30)), "orders_90d": len(o90), "orders_365d": len(o365),
        "spend_365d": round(sum(r["total"] for r in o365)),
        "unit_session_pct_90d": round(len(o90) / sessions(90), 3) if sessions(90) else 0.0,
        "coupons_used_365d": sum(1 for r in o365 if r["used_coupon"]),
        "reviews_365d": len(ratings),
        "avg_rating_given": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "returns_365d": returns,
        "return_rate_365d": round(returns / len(o365), 2) if o365 else 0.0,
        "top_brand": top_brand,
        "top_brand_share": round(top_n / sum(brand_counts.values()), 2) if brand_counts else 0.0,
    }


def _focus_product(evs, orders, items_by_order, products, top_category, ref):
    """The one product this customer shows most interest in right now, for product coupons:
    open cart item > wishlisted and not bought > last viewed (30 days) > best-rated in their category."""
    bought = {i["product_id"] for r in orders for i in items_by_order.get(r["order_id"], [])}
    last_order = max((r["created_at"] for r in orders), default="")
    removed = {e["product_id"] for e in evs if e["event_name"] == "remove_from_cart"}
    cut30 = (ref - timedelta(days=30)).isoformat()

    sensitive = {t.lower() for t in RULES["message"]["sensitive_item_types"]}

    def usable(pid):  # R25 in stock, R16 not a sensitive product type
        p = products.get(pid)
        return p is not None and p["stock_units"] > 0 and p["item_type"].lower() not in sensitive

    def latest(name, cond):
        hits = [e for e in evs if e["event_name"] == name and e["product_id"] and cond(e) and usable(e["product_id"])]
        return hits[-1]["product_id"] if hits else None

    popular = [p for p in products.values() if p["category"] == top_category and usable(p["product_id"])]
    candidates = [
        ("in cart", latest("add_to_cart", lambda e: e["event_time"] > last_order and e["product_id"] not in removed)),
        ("wishlist", latest("add_to_wishlist", lambda e: e["product_id"] not in bought)),
        ("viewed", latest("view_item", lambda e: e["event_time"] > cut30)),
        ("popular in category", max(popular, key=lambda p: p["avg_rating"])["product_id"] if popular else None),
    ]
    found = next(((r, pid) for r, pid in candidates if pid), None)
    if found is None:
        return {"focus_product_id": None, "focus_product_reason": None}
    reason, pid = found
    p = products[pid]
    return {"focus_product_id": p["product_id"], "focus_product_name": p["name"], "focus_product_type": p["item_type"],
            "focus_product_price": p["price"], "focus_product_category": p["category"],
            "focus_product_reason": reason, "focus_product_in_stock": p["stock_units"] > 0,
            "focus_product_overstock": bool(p["overstock"])}


def _bought_with(conn):
    """item_type -> the item types most often bought in the same order (best first), from the
    store's own orders (same numbers as market_basket.csv)."""
    from .export import market_basket
    out = defaultdict(list)
    for r in market_basket(conn):
        if r["confidence"] >= RULES["bundle"]["min_confidence"]:
            out[r["item_type"]].append((r["bought_with"], r["confidence"]))
    return {k: sorted(v, key=lambda x: -x[1]) for k, v in out.items()}


def _usable(p):
    """R25 in stock, R16 not a sensitive product type."""
    sensitive = {t.lower() for t in RULES["message"]["sensitive_item_types"]}
    return p is not None and p["stock_units"] > 0 and p["item_type"].lower() not in sensitive


def _bundle(evs, orders, items_by_order, products, bought_with, ref):
    """Bought together: the customer's open cart item, a recent purchase or a wishlist item, and the
    product type other shoppers most often buy with it (in stock, not already bought)."""
    bought = {i["product_id"] for r in orders for i in items_by_order.get(r["order_id"], [])}
    bought_types = {products[pid]["item_type"] for pid in bought if pid in products}
    last_order = max((r["created_at"] for r in orders), default="")
    removed = {e["product_id"] for e in evs if e["event_name"] == "remove_from_cart"}
    recent = (ref - timedelta(days=RULES["bundle"]["recent_purchase_days"])).isoformat()
    anchors = [
        ("in cart", [e["product_id"] for e in evs if e["event_name"] == "add_to_cart"
                     and e["event_time"] > last_order and e["product_id"] not in removed]),
        ("just bought", [i["product_id"] for r in orders if r["created_at"] >= recent
                         for i in items_by_order.get(r["order_id"], [])]),
        ("wishlist", [e["product_id"] for e in evs if e["event_name"] == "add_to_wishlist" and e["product_id"] not in bought]),
    ]
    for reason, pids in anchors:
        for pid in reversed(pids):
            anchor = products.get(pid)
            if not anchor:
                continue
            for item_type, conf in bought_with.get(anchor["item_type"], []):
                if item_type in bought_types:
                    continue
                options = [p for p in products.values() if p["item_type"] == item_type and _usable(p)]
                if not options:
                    continue
                # An add-on should be easy to say yes to: the cheapest well-rated one.
                good = [x for x in options if x["avg_rating"] >= 4.0] or options
                p = min(good, key=lambda x: (x["price"], -x["avg_rating"]))
                return {"bundle_anchor_item": anchor["name"], "bundle_reason": reason, "bundle_item_id": p["product_id"],
                        "bundle_item_name": p["name"], "bundle_item_price": p["price"],
                        "bundle_item_category": p["category"], "bundle_confidence": conf}
    return {"bundle_item_id": None}


def _wishlist_alert(evs, orders, items_by_order, products, ref):
    """Wishlist watcher: a wishlisted, not-yet-bought product whose price really dropped, or that
    really came back in stock, in the last few days. Never invented: both come from the catalog."""
    bought = {i["product_id"] for r in orders for i in items_by_order.get(r["order_id"], [])}
    since = (ref - timedelta(days=CAT_PRICE_WINDOW_DAYS)).isoformat()
    wished = [e["product_id"] for e in evs if e["event_name"] == "add_to_wishlist" and e["product_id"] not in bought]
    for pid in reversed(list(dict.fromkeys(reversed(wished)))):
        p = products.get(pid)
        if not _usable(p):
            continue
        if p.get("price_dropped_at") and since <= p["price_dropped_at"] <= ref.isoformat():
            return {"wishlist_alert_item": p["name"], "wishlist_alert_kind": "price_drop",
                    "wishlist_alert_was_price": p["was_price"], "wishlist_alert_price": p["price"]}
        if p.get("restocked_at") and since <= p["restocked_at"] <= ref.isoformat():
            return {"wishlist_alert_item": p["name"], "wishlist_alert_kind": "back_in_stock",
                    "wishlist_alert_was_price": None, "wishlist_alert_price": p["price"]}
    return {"wishlist_alert_item": None}


def _extra_features(evs, orders, items_by_order, products, ref):
    """Inputs for the guards (R23-R25) and the free offers (R29)."""
    cut365 = (ref - timedelta(days=365)).isoformat()
    hours = Counter(int(e["event_time"][11:13]) for e in evs if e["event_name"] == "session_start")
    last3 = orders[-3:]

    # Open cart item stock (R25): the latest cart add after the last order, not removed.
    last_order = max((r["created_at"] for r in orders), default="")
    removed = {e["product_id"] for e in evs if e["event_name"] == "remove_from_cart"}
    cart = [e for e in evs if e["event_name"] == "add_to_cart" and e["event_time"] > last_order
            and e["product_id"] not in removed]
    cart_in_stock = products[cart[-1]["product_id"]]["stock_units"] > 0 if cart else None
    # R25: if the cart item is out of stock, a similar in-stock product (same type, best rated)
    alternative = None
    if cart and not cart_in_stock:
        item = products[cart[-1]["product_id"]]
        similar = [p for p in products.values() if p["item_type"] == item["item_type"]
                   and p["product_id"] != item["product_id"] and p["stock_units"] > 0]
        alternative = max(similar, key=lambda p: p["avg_rating"])["name"] if similar else None

    # Restock (R29): Grocery/Beauty bought 2+ times; due when the usual gap for that category has passed.
    replenish_due, replenish_item = False, None
    for cat in RULES["guards"]["replenish_categories"]:
        dates = [datetime.fromisoformat(r["created_at"]) for r in orders if r["category"] == cat]
        if len(dates) < 2:
            continue
        gap = (dates[-1] - dates[0]).days / (len(dates) - 1)
        since = (ref - dates[-1]).days
        if gap >= 3 and 0.9 * gap <= since <= 2 * gap:
            items = [i for r in orders if r["category"] == cat for i in items_by_order.get(r["order_id"], [])]
            replenish_due = True
            replenish_item = products[items[-1]["product_id"]]["item_type"] if items else cat.lower()
            break

    # Review request (R29): an order 5-30 days ago, not returned, not reviewed yet.
    reviewed = {e["transaction_id"] for e in evs if e["event_name"] == "write_review"}
    review_item = None
    for r in reversed(orders):
        age = (ref - datetime.fromisoformat(r["created_at"])).days
        if 5 <= age <= 30 and not r["returned"] and str(r["order_id"]) not in reviewed and items_by_order.get(r["order_id"]):
            review_item = products[items_by_order[r["order_id"]][0]["product_id"]]["item_type"]
            break

    return {
        "active_hour": hours.most_common(1)[0][0] if hours else None,
        "coupon_returns_365d": sum(1 for r in orders if r["created_at"] > cut365 and r["used_coupon"] and r["returned"]),
        "coupon_orders_last3": sum(1 for r in last3 if r["used_coupon"]),
        "cart_item_in_stock": cart_in_stock,
        "cart_alternative_name": alternative,
        "margin_365d": round(sum(r["margin"] for r in orders if r["created_at"] > cut365)),
        "replenish_due": replenish_due,
        "replenish_item": replenish_item,
        "review_due_item": review_item,
        "suspected_multi_account": False,  # needs device/address data the dataset doesn't have
    }


def _add_audiences(rows):
    """Audience flags following Amazon's published definitions (Brand Tailored Promotions,
    Sponsored Display, new-to-brand), applied at store level. See docs/amazon_research.md."""
    spends = sorted((r["spend_365d"] for r in rows if r["spend_365d"] > 0), reverse=True)
    pct = RULES["segment_thresholds"]["vip_top_spend_pct"]
    top10 = spends[max(0, len(spends) * pct // 100 - 1)] if spends else float("inf")
    for r in rows:
        flags = {
            "aud_brand_follower": r["brands_followed"] > 0,
            "aud_repeat_customer": r["orders_365d"] >= 2,                     # bought more than once in 12 months
            "aud_recent_customer": r["orders_30d"] > 0,
            "aud_high_spend": r["spend_365d"] > 0 and r["spend_365d"] >= top10,  # top 10% spend, 12 months
            "aud_potential_new_customer": r["orders_365d"] == 0 and (r["clicks_30d"] > 0 or r["cart_adds_90d"] > 0),
            "aud_cart_abandoner": r["cart_adds_90d"] > 0 and r["orders_90d"] == 0,  # cart add, no purchase in 3 months
            "aud_views_remarketing_30d": r["product_views_30d"] > 0 and r["orders_30d"] == 0,
            "aud_one_time_customer": r["orders_total"] == 1,
            "aud_lapsed": r["orders_total"] > 0 and r["recency_days"] > 90,
            "new_to_brand_12m": r["orders_365d"] == 0,
        }
        r.update(flags)
        r["amazon_audiences"] = "|".join(k[4:] for k, v in flags.items() if v and k.startswith("aud_")) or None
