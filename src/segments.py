"""Derived features (churn risk, would-buy-anyway) and segment assignment."""
from .config import RULES


def _clamp(x):
    return round(max(0.0, min(1.0, x)), 2)


def derive_features(c):
    """Add derived scores to a customer dict. Returns a new dict."""
    c = dict(c)
    has_history = c["orders_total"] > 0
    gap_ratio = c["recency_days"] / max(c["avg_gap_days"], 1) if has_history else 0.0
    c["gap_ratio"] = round(gap_ratio, 2)

    # Higher when the customer is late compared with their own habit and buying less.
    c["churn_risk"] = _clamp(
        0.5 * min(gap_ratio / 3, 1)
        + 0.3 * min(c["recency_days"] / 120, 1)
        + 0.2 * (1 if c["frequency_90d"] == 0 else 0)
    ) if has_history else 0.0

    # Higher when the customer buys often, recently, and without coupons:
    # a discount for them is mostly lost margin.
    c["would_buy_anyway"] = _clamp(
        0.4 * min(c["frequency_90d"] / 6, 1)
        + 0.3 * (1 - c["coupon_rate"])
        + 0.3 * (1 if gap_ratio <= 1 else 0)
    ) if c["orders_total"] >= 3 else 0.0

    c["p_buy_7d"] = p_buy_7d(c)
    c["uplift_group"] = uplift_group(c)
    return c


def uplift_group(c):
    """Rule-of-thumb uplift quadrant (rules.yaml uplift_groups):
    sleeping_dog  offers make things worse (keeps hiding products) -> no offers (R26)
    lost_cause    long gone and not even browsing -> only free offers (R26)
    sure_thing    buys anyway and rarely uses coupons -> discounts are mostly wasted
    persuadable   everyone else: where offers can change behaviour"""
    u = RULES["uplift_groups"]
    # Bad reactions to OUR OFFERS (fewer offers, not interested, /stop), counted by the caller
    # from the feedback log; hiding products is dislike of a product, not of offers.
    if c.get("negative_offer_reactions_90d", 0) >= u["sleeping_dog_min_negative_reactions_90d"]:
        return "sleeping_dog"
    if (c["orders_total"] > 0 and c["recency_days"] >= u["lost_cause_min_recency_days"]
            and c.get("sessions_90d", 1) == 0):
        return "lost_cause"
    if c["p_buy_7d"] >= u["sure_thing_min_p_buy_7d"] and c["coupon_rate"] < u["sure_thing_max_coupon_rate"]:
        return "sure_thing"
    return "persuadable"


def p_buy_7d(c):
    """Estimated probability the customer buys in the next 7 days WITHOUT any offer.

    Unlike would_buy_anyway (a 0-1 score), this is meant to be read as a probability:
    - purchase rate: blend of the last 90 days and their long-run habit (1 / usual gap),
      with the habit part decayed the more overdue they are (gap_ratio above 1);
    - only the share of orders bought without a coupon counts as "organic" buying;
    - Poisson assumption: P(at least one order in 7 days) = 1 - exp(-7 x rate).
    """
    import math
    if c["orders_total"] == 0:
        return 0.05  # no history yet: assume a low base rate
    recent = c["frequency_90d"] / 90
    habit = 1 / c["avg_gap_days"] if c["avg_gap_days"] else recent
    habit *= math.exp(-max(0.0, c["gap_ratio"] - 1))
    organic_rate = (0.5 * recent + 0.5 * habit) * (1 - c["coupon_rate"])
    return round(min(0.9, max(0.01, 1 - math.exp(-7 * organic_rate))), 2)


def has_open_cart(c):
    """Open cart in the abandonment window. R12 (reminder first) applies to anyone with one."""
    hours = c.get("cart_abandoned_hours_ago")
    return hours is not None and hours <= RULES["segment_thresholds"]["cart_abandon_window_hours"]


def assign_segment(c, include_cart=True):
    """Return the first segment whose condition matches, in rules.yaml segment_order.
    include_cart=False gives the BASE segment (who the customer is, ignoring the open cart)."""
    t = RULES["segment_thresholds"]
    checks = {
        "CART_ABANDONER": include_cart and has_open_cart(c),
        # NEW and the NEW coupon tier both mean "never ordered" (first-order offers only).
        "NEW": c["orders_total"] == 0 and c["tenure_days"] <= t["new_max_tenure_days"],
        "NEVER_BOUGHT": c["orders_total"] == 0,
        # Relative to the customer's own rhythm: someone who buys twice a year isn't dormant at 100 days.
        "DORMANT": c["orders_total"] > 0
        and c["recency_days"] >= max(t["dormant_min_recency_days"], t["dormant_gap_multiple"] * c["avg_gap_days"]),
        "AT_RISK": c["orders_total"] >= 3
        and (c["gap_ratio"] >= t["at_risk_min_gap_ratio"] or c["churn_risk"] >= t["at_risk_min_churn_risk"]),
        "POINTS_EXPIRING": c["points_expiring_30d"] >= t["points_expiring_min"],
        "DEAL_SEEKER": c["orders_total"] >= t["deal_seeker_min_orders"]
        and c["coupon_rate"] >= t["deal_seeker_min_coupon_rate"],
        # Top 10% by 12-month spend (computed across customers in features.py); the fixed
        # threshold is only a fallback for data without that flag (e.g. the hand-made samples).
        "VIP": bool(c["aud_high_spend"]) if "aud_high_spend" in c else c["aov"] >= t["vip_min_aov"],
        "LOYAL": c["would_buy_anyway"] >= t["loyal_min_would_buy_anyway"],
        "BROWSER": c["browse_no_buy_14d"] >= t["browser_min_sessions_no_buy"],
        "REGULAR": True,
    }
    for seg in RULES["segment_order"]:
        if checks[seg]:
            return seg
    return "REGULAR"


def prepare(customer):
    c = derive_features(customer)
    c["segment"] = assign_segment(c)
    c["base_segment"] = assign_segment(c, include_cart=False)
    return c
