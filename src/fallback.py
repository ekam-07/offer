"""Rule-based offer picker. Used when the AI agent is off, fails, or breaks the rules.

It tries every allowed offer, keeps those that pass validation, and picks the one with the
highest expected profit (R30), so it can never send an offer that breaks a rule.
"""
from .config import OFFERS, RULES
from .rules import (expected_profit, first_name, goodwill_coupon, is_scoped, perk_points, scope_categories,
                    min_basket, validate)



def segment_reason(c):
    s = c["segment"]
    if s == "NEVER_BOUGHT":
        return f"has never ordered ({c['tenure_days']} days since signup)"
    if s == "NEW":
        return f"new customer ({c['tenure_days']} days, {c['orders_total']} orders)"
    if s == "CART_ABANDONER":
        return f"left ₹{c.get('abandoned_cart_value', 0):.0f} in cart {c['cart_abandoned_hours_ago']}h ago"
    if s == "DORMANT":
        return f"no order for {c['recency_days']} days"
    if s == "AT_RISK":
        return (f"last order {c['recency_days']} days ago vs usual gap of {c['avg_gap_days']} days "
                f"({c['gap_ratio']}x), churn risk {c['churn_risk']}")
    if s == "POINTS_EXPIRING":
        return f"{c['points_expiring_30d']} points expire within 30 days"
    if s == "DEAL_SEEKER":
        return f"uses coupons on {int(c['coupon_rate'] * 100)}% of orders"
    if s == "VIP":
        return f"high-value customer (avg order ₹{c['aov']:.0f})"
    if s == "LOYAL":
        return f"buys regularly without coupons (would-buy-anyway {c['would_buy_anyway']})"
    if s == "BROWSER":
        return f"{c['browse_no_buy_14d']} sessions without buying in 14 days"
    return "regular customer"


def pick_value(c, option):
    if option["unit"] == "none":
        return 0
    lo, hi = option["min_value"], option["max_value"]
    if option["offer_id"] == "PRODUCT_COUPON":
        return hi  # the coupon tier already sets the size (R19)
    strategy = RULES["segments"][c["segment"]].get("value_strategy", "min")
    if strategy == "max":
        return hi
    if strategy == "churn":
        # Scale with churn risk: the more likely they are to leave, the bigger the offer.
        step = 10 if option["unit"] == "inr" else 5
        value = lo + (hi - lo) * c["churn_risk"]
        return max(lo, min(hi, int(round(value / step) * step)))
    if option["unit"] == "points" and c["segment"] == "POINTS_EXPIRING":
        return min(option["max_value"], 200)
    return option["min_value"]


def _category_list(c, offer_id, value):
    cats = scope_categories(c, offer_id, value)
    if not cats:
        return ""
    if c["top_category"] in cats:  # lead with what they already like
        cats = [c["top_category"]] + [x for x in cats if x != c["top_category"]]
    return cats[0] if len(cats) == 1 else ", ".join(cats[:-1]) + " or " + cats[-1]


def _wishlist_news(c):
    if c.get("wishlist_alert_kind") == "price_drop":
        return f"its price dropped from ₹{int(c['wishlist_alert_was_price'])} to ₹{int(c['wishlist_alert_price'])}"
    return "it's back in stock"


def render(c, offer_id, value):
    offer = OFFERS[offer_id]
    return offer["template"].format(
        categories=_category_list(c, offer_id, value),
        only_on=f" (only on {_category_list(c, offer_id, value)})" if scope_categories(c, offer_id, value) else "",
        product=c.get("focus_product_name") or "item",
        coupon_min_order=(f", on orders above ₹{min_basket(c, offer_id)}"
                          if offer_id == "PRODUCT_COUPON" and min_basket(c, offer_id) else ""),
        # Only say why if it's the customer's own activity, so the message never claims more than the data.
        product_why={"in cart": " in your cart", "wishlist": " in your wishlist",
                     "viewed": " you looked at recently"}.get(c.get("focus_product_reason"), ""),
        name=first_name(c),  # sanitised: customer data is never trusted in a message
        value=int(value),
        replenish_item=c.get("replenish_item") or "usual items",
        review_item=c.get("review_due_item") or "recent order",
        points_balance=int(c.get("points_balance") or 0),
        category=c["top_category"],
        cart_item=c.get("abandoned_cart_item") or "item",
        points=c["points_expiring_30d"] or c["points_balance"],
        min_order=min_basket(c, offer_id) or offer.get("min_order", ""),  # R5: margin-safe basket
        cart_alternative=c.get("cart_alternative_name") or "similar item",
        bundle_anchor=c.get("bundle_anchor_item") or "last item",
        bundle_item=c.get("bundle_item_name") or "item",
        bundle_price=int(c.get("bundle_item_price") or 0),
        wishlist_item=c.get("wishlist_alert_item") or "item",
        wishlist_news=_wishlist_news(c),
        perk_points=perk_points(),
        valid_days=offer.get("valid_days", ""),
    )


def choose(c, feasible, blocked, ctx):
    """Return a proposal {offer_id, value, message, reason}. Always returns something (NONE at worst).

    Picks the allowed offer with the highest EXPECTED PROFIT (R30): paid offers only pass the
    rules when EP > 0, free nudges count as EP >= 0, so a free nudge wins whenever no paid offer
    pays. Ties go to the cheaper offer, then to the segment list's order. The one exception is
    the goodwill coupon for customers who buy anyway (coupons_for_sure_things): given when due."""
    why = segment_reason(c)
    ladder = RULES["segments"][c["segment"]]["allowed"]
    skipped, candidates = [], []
    for option in feasible:
        offer_id = option["offer_id"]
        if offer_id == "NONE":
            continue
        proposal = None
        for value in dict.fromkeys([pick_value(c, option), option.get("best_value", option["min_value"])]):
            attempt = {"offer_id": offer_id, "value": value, "message": render(c, offer_id, value)}
            problems = validate(c, attempt, ctx)
            if not problems:
                proposal = attempt
                break
        if proposal is None:
            skipped.append(f"{offer_id} ({problems[0]})")
            continue
        ep = expected_profit(c, offer_id, proposal["value"])
        candidates.append((option, proposal, ep))

    goodwill = [x for x in candidates if goodwill_coupon(c, x[0]["offer_id"])]
    if goodwill:
        option, proposal, ep = goodwill[0]
        proposal["reason"] = (f"{c['segment']}: {why}; goodwill coupon of {int(proposal['value'])}% for a customer who "
                              f"buys anyway (coupons_for_sure_things, exception to R30; EP ₹{ep['ep_inr']:.0f})")
        return proposal
    if candidates:
        option, proposal, ep = max(candidates, key=lambda x: (x[2]["ep_inr"], -x[2]["cost_inr"],
                                                              -ladder.index(x[0]["offer_id"])))
        reason = f"{c['segment']}: {why}; picked {option['offer_id']}"
        if proposal["value"]:
            reason += f" at {int(proposal['value'])} {option['unit']}"
        reason += (f" - highest expected profit (EP ₹{ep['ep_inr']:.0f}: buy chance {ep['p_without']:.0%} -> "
                   f"{ep['p_with']:.0%}, cost ₹{ep['cost_inr']:.0f})")
        if blocked:
            reason += f"; ruled out: {', '.join(sorted(blocked))}"
        proposal["reason"] = reason
        return proposal
    # Group offers by the rule that blocked them so the log stays readable.
    by_rule = {}
    for oid, problems in sorted(blocked.items()):
        by_rule.setdefault(problems[0], []).append(oid)
    details = [f"{rule} [{', '.join(oids)}]" for rule, oids in by_rule.items()] + skipped
    return {"offer_id": "NONE", "value": 0, "message": "",
            "reason": f"{c['segment']}: {why}; no offer sent, every option was blocked" + (": " + "; ".join(details) if details else "")}
