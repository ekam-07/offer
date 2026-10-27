"""Simulates how customers respond to offers, to compare offer policies offline.

Each customer's true behaviour comes from their hidden persona (config/response_model.yaml),
which no policy can see. Every policy is run against the same random draws ("common random
numbers"), so for each simulated week we know exactly who bought because of the offer and
who would have bought anyway.
"""
import os
from datetime import datetime

import numpy as np
import yaml

from . import offer_log
from .config import CATALOG, CONFIG_DIR, DATA_DIR, OFFERS, RULES
from .decide import decide_batch
from .rules import category_margin, is_bundle, is_product_coupon, is_scoped, min_basket, perk_points, safe_categories
from .segments import prepare

with open(CONFIG_DIR / "response_model.yaml", encoding="utf-8") as f:
    RM = yaml.safe_load(f)
# Overrides measured by calibrate.py from the Hillstrom email test (delete the file to revert).
if (CONFIG_DIR / "response_model_calibrated.yaml").exists():
    with open(CONFIG_DIR / "response_model_calibrated.yaml", encoding="utf-8") as f:
        for persona, values in ((yaml.safe_load(f) or {}).get("personas") or {}).items():
            RM["personas"][persona].update(values)

CASH_TYPES = {"percent", "flat", "shipping", "points", "choice"}


# ---- Policies: customer_id -> (offer_id, value) ---------------------------------------

def policy_no_offers(customers, now):
    return {c["customer_id"]: ("NONE", 0) for c in customers}


def policy_blanket(customers, now, pct=10):
    """The naive baseline: same % discount to everyone who agreed to messages, no other rules."""
    return {c["customer_id"]: ("PERCENT_OFF", pct) if c["opted_in"] else ("NONE", 0) for c in customers}


def _policy_engine(customers, now, use_agent):
    """Our decision engine, logging to a throwaway DB so the real offer log is untouched."""
    real_db = offer_log.DB_PATH
    offer_log.DB_PATH = DATA_DIR / "sim_offers.db"
    # This snapshot stands for a whole day of decisions made at one moment, so it gets the whole
    # day's budget; hourly pacing (R13) is tested for real in the 30-day simulation.
    pacing = RULES["budget"].get("pacing")
    RULES["budget"]["pacing"] = "none"
    try:
        offer_log.reset()
        rows = decide_batch(customers, now=now, use_agent=use_agent, skip_holdout=True, explore=False)
    finally:
        offer_log.DB_PATH = real_db
        RULES["budget"]["pacing"] = pacing
    decisions = {r["customer_id"]: (r.get("offer_id") or "NONE", r.get("value") or 0) for r in rows}
    agent_stats = {
        "decided_by_agent": sum(r["decided_by"] == "AGENT" for r in rows),
        "agent_failed": sum(r.get("agent_status") in ("FAILED", "REJECTED") for r in rows),
        "flagged": sum(r.get("flagged", 0) for r in rows),
    }
    return decisions, agent_stats


def policy_rules(customers, now):
    return _policy_engine(customers, now, use_agent=False)[0]


def policy_ai(customers, now):
    return _policy_engine(customers, now, use_agent=True)


def agent_available():
    from .agent import configured
    return configured()


# ---- Response model ---------------------------------------------------------------------

def _aov(c):
    return c["aov"] or RM["default_aov_inr"]


def uplift(c, offer_id, value):
    """Share of would-be non-buyers this offer converts, for this customer's true persona."""
    if offer_id == "NONE":
        return 0.0
    p = RM["personas"][c["persona_key"]]
    offer = OFFERS[offer_id]
    t, half = offer["type"], RM["discount_half_effect_pct"]

    def discount_effect(pct):
        return p["discount_sensitivity"] * pct / (pct + half)

    if is_bundle(offer_id):  # acts on the bought-together item, not on the main order (see bundle_uplift)
        return 0.0
    if t == "choice":  # they pick the perk they really value more
        return max(uplift(c, "FREE_SHIPPING", 0), uplift(c, "BONUS_POINTS", perk_points()))
    if is_product_coupon(offer):
        return discount_effect(value * RM["product_coupon_breadth"].get(c.get("focus_product_reason"), 0.5))
    if t == "percent":
        pct = value * (RM["category_deal_breadth"] if offer_id == "CATEGORY_DEAL" else 1)
        if is_scoped(offer) and c["top_category"] not in safe_categories(c, offer_id, value):
            pct *= RM["scoped_offer_breadth"]
        return discount_effect(pct)
    if t == "flat":
        if offer.get("goal_multiple"):  # only those who actually reach the target count (and get the reward)
            target = max(_aov(c), min_basket(c, offer_id) or 0)
            return RM["goal_completion"] * discount_effect(value / target * 100)
        return discount_effect(value / _aov(c) * 100)
    if t == "shipping":
        return discount_effect(min(10, CATALOG["shipping_cost_inr"] / _aov(c) * 100))
    if t == "points":
        return p["points_affinity"] * discount_effect(value * CATALOG["point_value_inr"] / _aov(c) * 100)
    if offer_id == "CART_REMINDER":
        return p["cart_reminder"] if c.get("cart_abandoned_hours_ago") is not None else 0.01
    if offer_id == "CART_ALTERNATIVE":  # a similar product converts less than the item they chose
        return 0.6 * p["cart_reminder"] if c.get("cart_alternative_name") else 0.0
    if offer_id == "POINTS_REMINDER":
        has_points = c["points_expiring_30d"] >= RM["min_points_for_reminder"]
        return p["points_reminder"] * p["points_affinity"] * (2 if has_points else 0.3)
    if offer_id == "EARLY_ACCESS":
        return p["early_access"]
    if offer_id in RM["free_offer_effect"]:
        effect = RM["free_offer_effect"][offer_id]
        if offer_id == "REPLENISH_REMINDER":
            return effect if c.get("replenish_due") else 0.0
        if offer_id == "WISHLIST_ALERT":
            return effect if c.get("wishlist_alert_item") else 0.0
        return effect * (p["points_affinity"] if offer_id == "POINTS_UPDATE" else 1)
    return 0.0


def bundle_uplift(c, offer_id, value):
    """Extra chance the customer adds the bought-together item, for their true persona."""
    if not is_bundle(offer_id) or not c.get("bundle_item_id"):
        return 0.0
    p = RM["personas"][c["persona_key"]]
    pct = value / (c.get("bundle_item_price") or _aov(c)) * 100
    return RM["bundle_attach_effect"] + p["discount_sensitivity"] * pct / (pct + RM["discount_half_effect_pct"])


def _persona_key(persona):
    # Sample customers have personas like "at_risk_opted_out"; map them to a response persona.
    for key in sorted(RM["personas"], key=len, reverse=True):
        if persona.startswith(key):
            return key
    return "loyal" if persona == "points_rich" else "deal_seeker"


def incremental_margin_rate(c, offer_id, value):
    """Margin on a purchase made because of the offer. A category-limited offer is spent in
    one of its eligible categories, even if the customer usually browses elsewhere."""
    offer = OFFERS[offer_id]
    if is_scoped(offer) and c["top_category"] not in safe_categories(c, offer_id, value):
        cats = safe_categories(c, offer_id, value)
        return sum(category_margin(x) for x in cats) / len(cats) / 100 if cats else 0.0
    if is_product_coupon(offer) and c.get("focus_product_category"):
        return category_margin(c["focus_product_category"]) / 100
    return c["margin_rate"]


def offer_cost(offer_id, value, order_value, c=None):
    """What the business pays when a buyer uses the offer (0 if the order is too small)."""
    if offer_id == "NONE":
        return 0.0
    offer = OFFERS[offer_id]
    if is_product_coupon(offer):
        return (c or {}).get("focus_product_price", 0) * value / 100  # they buy the couponed product
    if offer["type"] not in CASH_TYPES or order_value < ((min_basket(c, offer_id) if c else None) or offer.get("min_order", 0)):
        return 0.0
    if offer["type"] == "percent":
        return order_value * value / 100
    if offer["type"] == "flat":
        return float(value)
    if offer["type"] in ("shipping", "choice"):
        return float(CATALOG["shipping_cost_inr"])
    return value * CATALOG["point_value_inr"]


# ---- Simulation -------------------------------------------------------------------------

def prepare_population(customers, seed):
    rng = np.random.default_rng(seed)
    pop = []
    for c in customers:
        c = prepare(c)
        c["persona_key"] = _persona_key(c["persona"])
        p = RM["personas"][c["persona_key"]]
        c["p_base"] = float(min(0.95, p["base_buy"] * rng.lognormal(0, RM["customer_noise"])))
        c["margin_rate"] = category_margin(c["top_category"]) / 100
        pop.append(c)
    return pop


def simulate(pop, decisions, runs, seed):
    """Monte Carlo over `runs` simulated weeks. Same seed -> same draws for every policy."""
    rng = np.random.default_rng(seed)
    n = len(pop)
    u_buy = rng.random((runs, n))
    u_optout = rng.random((runs, n))
    noise = rng.lognormal(0, RM["order_value_noise"], (runs, n))

    p_base = np.array([c["p_base"] for c in pop])
    aov = np.array([_aov(c) for c in pop])
    margin_rate = np.array([c["margin_rate"] for c in pop])
    offers = [decisions[c["customer_id"]] for c in pop]
    messaged = np.array([o[0] != "NONE" for o in offers])
    p_offer = np.array([pb + (1 - pb) * uplift(c, *o) for pb, c, o in zip(p_base, pop, offers)])
    optout_p = np.array([RM["personas"][c["persona_key"]]["optout_per_message"] for c in pop]) * messaged

    order_value = aov * noise
    buys_base = u_buy < p_base
    buys = u_buy < p_offer
    # Customers who buy *because of* an offer top their basket up to its minimum order,
    # so they actually get (and cost) the discount. Would-be buyers keep their usual basket.
    min_order = np.array([(min_basket(c, o[0]) or 0) if OFFERS[o[0]]["type"] in CASH_TYPES else 0
                          for c, o in zip(pop, offers)])
    order_value = np.where(buys & ~buys_base, np.maximum(order_value, min_order), order_value)
    cost = np.zeros((runs, n))
    for j, (offer_id, value) in enumerate(offers):
        if offer_id != "NONE":
            cost[:, j] = [offer_cost(offer_id, value, v, pop[j]) for v in order_value[:, j]]
    cost = cost * buys

    extra = buys & ~buys_base
    margin_extra = np.array([incremental_margin_rate(c, *o) for c, o in zip(pop, offers)])

    # Bought together: the offer works on a second item. Without it they add the item at the store's
    # "bought with" rate when they buy; with it, a share of the rest add it too.
    b_price = np.array([c.get("bundle_item_price") or 0 for c in pop])
    b_margin = np.array([category_margin(c.get("bundle_item_category")) / 100 for c in pop])
    b_base = p_base * np.array([c.get("bundle_confidence") or 0 for c in pop])
    b_lift = np.array([bundle_uplift(c, *o) for c, o in zip(pop, offers)])
    b_value = np.array([o[1] if o[0] == "BUNDLE_DEAL" else 0 for o in offers], dtype=float)
    if b_lift.any():
        u_b = np.random.default_rng(seed + 7).random((runs, n))
        b_buys = u_b < b_base + (1 - b_base) * b_lift
        b_wasted = u_b < b_base  # would have added it anyway, still gets the ₹ off
        b_extra = b_buys & ~b_wasted
    else:
        b_buys = b_extra = b_wasted = np.zeros((runs, n), dtype=bool)
    b_gain = b_extra * b_price * b_margin - b_buys * b_value
    revenue = (order_value * buys).sum(1)
    base_net = (order_value * margin_rate * buys_base).sum(1)
    gross = base_net + (order_value * margin_extra * extra).sum(1) + b_gain.sum(1)
    net = gross - cost.sum(1)
    incremental = extra.sum(1) + b_extra.sum(1)

    per_customer = {
        "incremental": (extra | b_extra).mean(0),
        "cost": (cost + b_buys * b_value).mean(0),
        "net_gain": (order_value * margin_extra * extra - cost + b_gain).mean(0),
    }
    return {
        "messaged": int(messaged.sum()),
        "purchases": float(buys.sum(1).mean()),
        "incremental_purchases": float(incremental.mean()),
        "incremental_sd": float(incremental.std()),
        "redemptions": float((cost > 0).sum(1).mean()),
        "discount_cost": float(cost.sum(1).mean() + (b_buys * b_value).sum(1).mean()),
        "wasted_cost": float((cost * buys_base).sum(1).mean() + (b_wasted * b_value).sum(1).mean()),
        "revenue": float(revenue.mean()),
        "net_margin": float(net.mean()),
        "incremental_net_margin": float((net - base_net).mean()),
        "incremental_net_margin_sd": float((net - base_net).std()),
        "optouts": float((u_optout < optout_p).sum(1).mean()),
        "per_customer": per_customer,
    }


def holdout_experiment(pop, decisions, holdout_ids, seed):
    """One simulated week measured the way it would be in real life: treated vs control group.
    Returns (estimated uplift in purchase rate, 95% CI half-width, true uplift for the treated)."""
    rng = np.random.default_rng(seed + 1)
    treated, control, true_gain = [], [], []
    for c in pop:
        offer = decisions[c["customer_id"]]
        u = rng.random()
        if c["customer_id"] in holdout_ids:
            control.append(u < c["p_base"])
        else:
            p_off = c["p_base"] + (1 - c["p_base"]) * uplift(c, *offer)
            treated.append(u < p_off)
            true_gain.append(p_off - c["p_base"])
    t, k = np.array(treated, float), np.array(control, float)
    est = t.mean() - k.mean()
    half_width = 1.96 * np.sqrt(t.var() / len(t) + k.var() / max(len(k), 1))
    return float(est), float(half_width), float(np.mean(true_gain)), len(t), len(k)


def default_now():
    return datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)
