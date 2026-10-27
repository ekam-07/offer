"""Explains a decision in plain words for the preview page, so anyone can follow it.

The AI's own reason stays in the log (and under "details" on the page). This builds a short,
fixed-shape explanation from the facts instead: who the customer is, how likely they are to buy
anyway, what we send, whether it pays, and the one rule that mattered most.
"""
from .config import OFFERS, RULES
from .rules import (all_categories, base_aov, category_margin, eligible_categories, est_cost, expected_profit,
                    min_basket, perk_points, safe_categories, scope_categories)
from .segments import has_open_cart


def _inr(x):
    return f"₹{x:,.0f}"


def _ago(hours):
    if hours is None:
        return "a while ago"
    if hours < 24:
        return "1 hour ago" if round(hours) == 1 else f"{hours:.0f} hours ago"
    days = round(hours / 24)
    return "yesterday" if days == 1 else f"{days} days ago"


def who(c):
    text = _who(c)
    if c.get("segment") != "CART_ABANDONER" and has_open_cart(c):
        item = c.get("abandoned_cart_item") or "something"
        text += f" They left {item} in the cart {_ago(c['cart_abandoned_hours_ago'])}."
    return text


def _who(c):
    s = c.get("segment")
    cat = (c.get("top_category") or "").lower()
    if s == "CART_ABANDONER":
        item = c.get("abandoned_cart_item") or (f"a {cat} item" if cat else "something")
        return f"Left {item} ({_inr(c.get('abandoned_cart_value') or 0)}) in the cart {_ago(c.get('cart_abandoned_hours_ago'))}."
    if s == "NEW":
        return "A new shopper who hasn't bought anything yet."
    if s == "NEVER_BOUGHT":
        return f"Joined {c.get('tenure_days', 0)} days ago but has never bought anything."
    if s == "DORMANT":
        return f"Used to shop here, but hasn't bought anything for {c.get('recency_days')} days."
    if s == "AT_RISK":
        return (f"Usually buys every {c.get('avg_gap_days', 0):.0f} days, but it has been {c.get('recency_days')} days. "
                "We might lose them.")
    if s == "POINTS_EXPIRING":
        return f"Has {c.get('points_expiring_30d')} reward points that will expire soon."
    if s == "DEAL_SEEKER":
        return f"Loves deals: used a coupon on {round((c.get('coupon_rate') or 0) * 100)} out of 100 orders."
    if s == "VIP":
        return f"One of our best customers: spends about {_inr(c.get('aov') or 0)} per order."
    if s == "LOYAL":
        return f"A regular: buys about every {c.get('avg_gap_days', 0):.0f} days, usually without coupons."
    if s == "BROWSER":
        return "Looks around a lot but rarely buys."
    return "Shops here now and then."


def chance(c):
    p = c.get("p_buy_7d") or 0
    n = max(1, round(p * 100)) if p > 0 else 0
    group = c.get("uplift_group")
    tail = {
        "sure_thing": "They'll probably buy anyway, so a big discount would be wasted.",
        "persuadable": "A small push could make the difference.",
        "lost_cause": "Hard to win back, so we don't spend money here.",
        "sleeping_dog": "Messages seem to annoy them.",
    }.get(group, "")
    return n, f"About {n} in 100 chance they buy this week on their own. {tail}".strip()


def what(c, row):
    oid, v = row.get("offer_id") or "NONE", row.get("value") or 0
    basket = min_basket(c, oid) if oid in OFFERS and oid != "NONE" else None
    over = f" on orders of {_inr(basket)} or more" if basket else ""
    only = scope_categories(c, oid, v) if oid in OFFERS and oid != "NONE" else None
    if only and oid != "CATEGORY_DEAL":
        over += f" (only on {_join(only)})"
    product = c.get("focus_product_name") or "a product they looked at"
    return {
        "NONE": "Nothing this time.",
        "CART_REMINDER": "A friendly reminder that their cart is waiting. No discount.",
        "CART_ALTERNATIVE": f"Their cart item is sold out, so we suggest a similar one: {c.get('cart_alternative_name') or 'an alternative'}.",
        "POINTS_REMINDER": "A reminder to use their points before they expire.",
        "POINTS_UPDATE": f"A note that they have {c.get('points_balance', 0)} points to spend.",
        "REPLENISH_REMINDER": f"A reminder that they may be running out of {c.get('replenish_item') or 'something they buy often'}.",
        "REVIEW_REQUEST": f"A request to review {c.get('review_due_item') or 'their last order'}.",
        "EARLY_ACCESS": "Early entry to the next sale, before everyone else.",
        "BONUS_POINTS": f"{v:.0f} bonus reward points on their next order.",
        "FREE_SHIPPING": f"Free delivery{over}.",
        "FLAT_OFF": f"{_inr(v)} off{over}.",
        "PERCENT_OFF": f"{v:.0f}% off{over}.",
        "CATEGORY_DEAL": f"{v:.0f}% off {', '.join(eligible_categories(v)[:3]) or 'some categories'}{over}.",
        "PRODUCT_COUPON": f"{v:.0f}% off {product}{over}.",
        "WELCOME": f"A welcome {v:.0f}% off their first order{over}.",
        "BUNDLE_SUGGEST": (f"A tip: people who buy the {c.get('bundle_anchor_item')} often add the "
                           f"{c.get('bundle_item_name')} ({_inr(c.get('bundle_item_price') or 0)}). No discount."),
        "BUNDLE_DEAL": f"{_inr(v)} off the {c.get('bundle_item_name')}, which goes well with their {c.get('bundle_anchor_item')}.",
        "WISHLIST_ALERT": (f"News about the {c.get('wishlist_alert_item')} on their wishlist: "
                           + (f"its price dropped from {_inr(c.get('wishlist_alert_was_price') or 0)} to "
                              f"{_inr(c.get('wishlist_alert_price') or 0)}." if c.get("wishlist_alert_kind") == "price_drop"
                              else "it's back in stock.")),
        "SPEND_GOAL": f"A goal: spend {_inr(basket or 0)} in 7 days (one order or several) and get {_inr(v)} off{over[over.find(' (only'):] if ' (only' in over else ''}.",
        "PERK_CHOICE": f"They choose: free delivery{over}, or {perk_points()} bonus points. Both cost us the same.",
    }.get(oid, OFFERS.get(oid, {}).get("description", oid))


def worth(c, row):
    oid, v = row.get("offer_id") or "NONE", row.get("value") or 0
    if row.get("decided_by") == "SYSTEM":
        return "neutral", "No money spent."
    if oid == "NONE" or oid not in OFFERS:
        return "neutral", "No offer would earn more than it costs here, so we keep the money."
    cost = row.get("est_cost_inr") or 0
    ep = row.get("ep_inr")
    if ep is None:
        ep = expected_profit(c, oid, v)["ep_inr"]
    pays = f"Costs us about {_inr(cost)}, only if they use it." if cost else "Costs us nothing."
    if ep > 0.5:
        return "good", f"{pays} On average we expect to earn {_inr(ep)} more than if we sent nothing."
    if cost and c.get("uplift_group") == "sure_thing":
        return "neutral", f"{pays} A small thank-you for a good customer (our choice, even though they'd buy anyway)."
    if not cost:
        return "good", "Costs us nothing, so any extra sale is pure gain."
    return "neutral", f"{pays} A small cost for a possible extra sale."


def money_rule(c, row):
    """Shows the sum behind R5 for the worst case: the lowest-profit category the offer works on,
    at the smallest order it allows, minus what the offer costs."""
    oid, v = row["offer_id"], row.get("value") or 0
    basket = min_basket(c, oid) or base_aov(c)
    cats = safe_categories(c, oid, v) or [c.get("top_category") or "default"]
    cat = min(cats, key=category_margin)
    m = category_margin(cat)
    before = basket * m / 100
    cost = basket * v / 100 if OFFERS[oid]["type"] == "percent" else (row.get("est_cost_inr") or est_cost(c, oid, v))
    left = before - cost
    excluded = [x for x in all_categories() if x not in cats]
    text = (f"Money rule: even on a {_inr(basket)} {cat.lower()} order (the lowest-profit category it works on) "
            f"the shop earns about {_inr(before)} ({m:.0f} in 100). The offer costs {_inr(cost)}, so {_inr(left)} is left: "
            f"never less than {RULES['margin_floor_pct']} in 100 of the order.")
    if excluded:
        text += f" It doesn't work on {_join(excluded)}, where it would lose money."
    return text


def _join(items):
    items = [i.lower() for i in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def _escalated(c, row):
    """Was this decision the step after an unanswered cart reminder (R12 escalation)?"""
    from datetime import datetime, timedelta
    from .rules import Context, cart_escalation
    if not row.get("created_at"):
        return None
    before = datetime.fromisoformat(row["created_at"]) - timedelta(seconds=1)  # the state just before this decision
    return cart_escalation(c, Context.load(c["customer_id"], now=before))


def rule(c, row):
    status, oid, by = row.get("status"), row.get("offer_id"), row.get("decided_by")
    if oid in RULES["frequency"].get("cart_discount_offers", []) and _escalated(c, row):
        return ("Cart rule: the reminder didn't lead to a purchase, so the next step is a small discount on the cart. "
                "It still has to earn more than it costs.")
    if status == "NO_OFFER" and "R12: a cart reminder" in (row.get("reason") or ""):
        return ("Cart rule: the reminder didn't lead to a purchase, but no discount would earn more than it costs, "
                "so we send nothing rather than lose money.")
    if status == "HOLDOUT":
        return "This shopper is in the test group that gets no offers. Comparing with them shows if offers really work."
    if status == "NOT_ELIGIBLE":
        return "They didn't agree to get offers (or asked us to stop), so we never message them."
    if status == "NO_OFFER" and "R8: customer already has a live offer" in (row.get("reason") or ""):
        import re
        m = re.search(r"live offer \((\w+)\) valid until (\S+)", row["reason"])
        what_ = (m.group(1).replace("_", " ").lower(), m.group(2)[:10]) if m else ("an offer", "it ends")
        return f"One-offer rule: they already have a live offer ({what_[0]}) until {what_[1]}, so nothing new is sent until it ends."
    if status == "NO_OFFER" and (row.get("reason") or "").startswith("R26"):
        return "They reacted badly to offers before, so we leave them alone."
    if by == "EXPLORE":
        return "Picked at random (5 times in 100) so we can learn which offers work best."
    if oid in ("CART_REMINDER", "CART_ALTERNATIVE"):
        return "Cart rule: a friendly reminder always comes before any discount."
    if row.get("send_at") and row.get("created_at") and row["send_at"][11:13] == "08" and row["created_at"][11:13] in ("22", "23", "00", "01", "02", "03", "04", "05", "06", "07"):
        return "It's night time, so the message waits until 8 am."
    if oid == "BUNDLE_SUGGEST":
        return (f"Bought-together rule: {round((c.get('bundle_confidence') or 0) * 100)} in 100 shoppers who bought the "
                f"{c.get('bundle_anchor_item')} also bought the {c.get('bundle_item_name')}. Suggesting it costs nothing.")
    if oid == "BUNDLE_DEAL":
        m = category_margin(c.get("bundle_item_category"))
        return (f"Money rule: the {c.get('bundle_item_name')} earns about {_inr((c.get('bundle_item_price') or 0) * m / 100)} "
                f"({m:.0f} in 100), so {_inr(row.get('value') or 0)} off still leaves at least {RULES['margin_floor_pct']} in 100.")
    if oid == "WISHLIST_ALERT":
        return "Honesty rule: we only send this when the price really dropped or the item really came back in stock."
    if oid == "SPEND_GOAL":
        return money_rule(c, row) + " The goal is set above their usual order, so reaching it means a bigger basket."
    if oid == "PERK_CHOICE":
        return ("Choice rule: both perks cost the shop the same, so letting them pick costs nothing extra, "
                "and their pick tells us what they like for next time.")
    if oid == "PRODUCT_COUPON":
        return "Coupon rule: people who buy often get smaller coupons than people who rarely buy."
    if oid in ("FLAT_OFF", "PERCENT_OFF", "FREE_SHIPPING"):
        return money_rule(c, row)
    if oid in ("CATEGORY_DEAL", "WELCOME"):
        return (f"Money rule: only in categories where the shop still keeps at least {RULES['margin_floor_pct']} in 100 "
                "as profit after the discount.")
    if oid == "NONE":
        return "Profit rule: we only pay for offers that earn more than they cost."
    return "Free messages are tried first: they cost nothing."


def explain(c, row):
    """Plain-words explanation of one logged decision for the preview card."""
    if not row:
        return None
    n, chance_text = chance(c)
    tone, worth_text = worth(c, row)
    by = row.get("decided_by")
    return {
        "who": who(c),
        "chance_pct": n,
        "chance": chance_text,
        "what": what(c, row),
        "worth_tone": tone,
        "worth": worth_text,
        "rule": rule(c, row),
        "goal_target": min_basket(c, "SPEND_GOAL") if row.get("offer_id") == "SPEND_GOAL" else None,
        "perk": c.get("perk"),
        "decider": {"AGENT": "🤖 Chosen by the AI, then checked against every rule",
                    "RULES": "📘 Chosen by the rules (the backup when the AI isn't used or fails)",
                    "EXPLORE": "🎲 Chosen at random to learn, within the rules",
                    "SYSTEM": "⚙️ Decided before any offer was considered"}.get(by, by),
    }
