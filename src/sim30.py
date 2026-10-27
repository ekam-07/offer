"""30-day forward simulation: decide -> deliver (dry run) -> customers respond -> data updates,
every day, then check that no rule was ever broken and compare the arms.

Arms: CONTROL = the R18 holdout (never gets offers); the rest are RULES (rule-based engine),
or split 50/50 into AI and RULES with ai=True (one API call per AI decision).
Customers' true behaviour comes from their hidden persona (config/response_model.yaml);
the engine only sees their features, which are updated each day from what happened.
"""
import hashlib
import random
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import consent, coupons, delivery, offer_log
from .config import DATA_DIR, OFFERS, RULES
from .decide import decide
from .events import CAT
from .rules import ACTIVE_TYPES, DISCOUNT_TYPES, budget_allowance, coupon_tier, in_holdout, spend_cap
from .segments import prepare
from .simulate import RM, incremental_margin_rate, offer_cost, prepare_population, uplift

ROUNDS = (10, 14, 19)  # decision rounds; each customer is decided once a day, in the round nearest their active hour


def _arm(cid, ai):
    if in_holdout(cid):
        return "CONTROL"
    if not ai:
        return "RULES"
    return "AI" if int(hashlib.md5(f"arm:{cid}".encode()).hexdigest(), 16) % 2 == 0 else "RULES"


def _round_for(c):
    hour = c.get("active_hour")
    return min(ROUNDS, key=lambda r: abs(r - hour)) if hour is not None else ROUNDS[0]


def _purchase_boost(day):
    for f in CAT["festivals"]:
        days_before = (date.fromisoformat(f["date"]) - day.date()).days
        if 0 <= days_before <= f["boost_days_before"]:
            return f["purchase_boost"]
    return 1.0


def run(customers, start, days=30, ai=False, seed=11, log=print):
    offer_log.DB_PATH = DATA_DIR / "sim30_offers.db"
    offer_log.reset()
    consent.reset_all()
    coupons.reset_all()
    rng = random.Random(seed)
    pop = {c["customer_id"]: c for c in prepare_population(customers, seed)}
    state = {cid: dict(c) for cid, c in pop.items()}  # features that evolve day by day
    arms = {cid: _arm(cid, ai) for cid in state}
    redemptions, optouts, tiers_at = defaultdict(list), {}, {}
    daily = []
    stats = defaultdict(lambda: defaultdict(float))

    for d in range(days):
        day = start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=d)
        given_today = []
        for hour in ROUNDS:
            now = day + timedelta(hours=hour)
            for cid, c in state.items():
                if _round_for(c) != hour:
                    continue
                prepared = prepare(c)
                row = decide(c, now=now, use_agent=(arms[cid] == "AI"))
                if row.get("status") == "READY":
                    tiers_at[row["id"]] = coupon_tier(prepared)["name"]
                    status = delivery.deliver(row, c, channel="whatsapp", now=now)
                    if status in offer_log.GIVEN:
                        given_today.append(row)
                        _react_to_offer(cid, row, now, rng, optouts, pop[cid])
        _simulate_purchases(state, pop, day, rng, redemptions, stats)
        _simulate_code_sharing(state, day, rng)
        _age_one_day(state)
        spent = sum(r["est_cost_inr"] for r in given_today)
        daily.append((day, len(given_today), spent))
        log(f"{day:%a %d %b}: {len(given_today):3} offers given, ₹{spent:,.0f} committed"
            + (f"  (festival boost x{_purchase_boost(day)})" if _purchase_boost(day) > 1 else ""))
    checks = check_invariants(redemptions, optouts, tiers_at, start, days,
                              {cid: spend_cap(prepare(c)) for cid, c in state.items()})
    return {"checks": checks, "stats": stats, "arms": arms, "daily": daily, "optouts": optouts}


def _react_to_offer(cid, row, now, rng, optouts, truth):
    """Simulated reactions to a delivered offer: /stop (persona opt-out rate) or feedback buttons."""
    r = rng.random()
    optout = RM["personas"][truth["persona_key"]]["optout_per_message"]
    if r < optout:
        consent.opt_out(cid, source="sim:/stop", now=now)
        optouts[cid] = now
    elif r < optout + 0.04:
        consent.record_feedback(cid, "not_interested", row["offer_id"], now=now)
    elif r < optout + 0.05:
        consent.record_feedback(cid, "fewer_offers", now=now)


def _active_offer(cid, day):
    """The cash/points offer currently held by the customer (valid at the end of `day`)."""
    end = (day + timedelta(days=1)).isoformat()
    with offer_log.connect() as conn:
        r = conn.execute(f"SELECT * FROM offer_log WHERE customer_id = ? AND status IN {offer_log.GIVEN} "
                         "AND created_at < ? AND (valid_until IS NULL OR valid_until > ?) ORDER BY id DESC LIMIT 1",
                         (cid, end, day.isoformat())).fetchone()
    return dict(r) if r else None


def _simulate_purchases(state, pop, day, rng, redemptions, stats):
    boost = _purchase_boost(day)
    for cid, c in state.items():
        truth = pop[cid]
        offer = _active_offer(cid, day)
        p_week = min(0.95, truth["p_base"] * boost)
        lift = uplift(dict(truth, **c), offer["offer_id"], offer["value"]) if offer else 0.0
        p_week_offer = p_week + (1 - p_week) * lift
        p_day = 1 - (1 - p_week_offer) ** (1 / 7)
        s = stats[cid]
        if rng.random() >= p_day:
            continue
        aov = c["aov"] or RM["default_aov_inr"]
        value = aov * rng.lognormvariate(0, RM["order_value_noise"])
        cost = 0.0
        if offer and OFFERS[offer["offer_id"]]["type"] in ACTIVE_TYPES:
            cost = offer_cost(offer["offer_id"], offer["value"], value, dict(truth, **c))
        margin = value * incremental_margin_rate(dict(truth, **c), offer["offer_id"], offer["value"]) if offer \
            else value * truth["margin_rate"]
        s["purchases"] += 1
        s["revenue"] += value
        s["margin"] += margin - cost
        s["discount_cost"] += cost
        if cost > 0:
            code = coupons.code_for(offer["id"])
            ok, _ = coupons.redeem(code, cid, now=day + timedelta(hours=20)) if code else (False, "no code")
            if not ok:
                cost = 0.0  # the checkout refuses an invalid code: full price
        used_discount = cost > 0 and OFFERS[offer["offer_id"]]["type"] in DISCOUNT_TYPES
        if cost > 0:
            s["redemptions"] += 1
            offer_log.update(offer["id"], valid_until=(day + timedelta(hours=20)).isoformat())  # used up
        if used_discount:
            redemptions[cid].append(day + timedelta(hours=20))
        _record_order(c, value, used_coupon=used_discount)


def _simulate_code_sharing(state, day, rng):
    """Classmates share codes in group chats: now and then someone tries another customer's code.
    The coupon system must refuse every one of these (logged in coupon_misuse)."""
    if rng.random() >= 0.3:
        return
    with offer_log.connect() as conn:
        rows = conn.execute("SELECT code, customer_id FROM coupon_codes WHERE status = 'issued'").fetchall()
    if rows:
        code, owner = rng.choice(rows)
        other = rng.choice([cid for cid in state if cid != owner])
        coupons.redeem(code, other, now=day + timedelta(hours=21))


def _record_order(c, value, used_coupon):
    n = c["orders_total"]
    if n:
        c["avg_gap_days"] = round((c["avg_gap_days"] * max(n - 1, 0) + c["recency_days"]) / n, 1) if n > 1 else c["recency_days"]
    c["coupon_rate"] = round((c["coupon_rate"] * n + (1 if used_coupon else 0)) / (n + 1), 2)
    c["orders_total"] = n + 1
    c["aov"] = round(((c["aov"] or 0) * n + value) / (n + 1))
    c["recency_days"] = 0
    c["frequency_90d"] = c.get("frequency_90d", 0) + 1
    c["orders_30d"] = c.get("orders_30d", 0) + 1
    c["orders_90d"] = c.get("orders_90d", 0) + 1
    c["orders_365d"] = c.get("orders_365d", 0) + 1
    c["spend_365d"] = c.get("spend_365d", 0) + round(value)
    c["cart_abandoned_hours_ago"] = None
    c["abandoned_cart_value"] = 0
    if used_coupon:
        c["days_since_discount_redeemed"] = 0
    last3 = c.setdefault("_last3", [])
    last3.append(used_coupon)
    c["coupon_orders_last3"] = sum(last3[-3:]) if len(last3) >= 3 else c.get("coupon_orders_last3", 0)


def _age_one_day(state):
    for c in state.values():
        c["tenure_days"] += 1
        if c["orders_total"]:
            c["recency_days"] += 1
        if c.get("cart_abandoned_hours_ago") is not None:
            c["cart_abandoned_hours_ago"] += 24
        if c.get("days_since_discount_redeemed") is not None:
            c["days_since_discount_redeemed"] += 1


# ---- Invariants ------------------------------------------------------------------------------

def check_invariants(redemptions, optouts, tiers_at, start, days, spend_caps=None):
    """Re-read the whole month's log and confirm no rule was ever broken."""
    spend_caps = spend_caps or {}
    with offer_log.connect() as conn:
        given = [dict(r) for r in conn.execute(
            f"SELECT * FROM offer_log WHERE status IN {offer_log.GIVEN} ORDER BY created_at, id")]
    by_cust = defaultdict(list)
    for r in given:
        by_cust[r["customer_id"]].append(r)
    freq = RULES["frequency"]
    fails = defaultdict(list)
    tiers = {t["name"]: t for t in RULES["coupon_tiers"]}

    for cid, rows in by_cust.items():
        times = [datetime.fromisoformat(r["created_at"]) for r in rows]
        paid_times = []
        for i, (r, t) in enumerate(zip(rows, times)):
            exempt = r["offer_id"] in freq["gap_exempt_offers"]
            paid = (r["est_cost_inr"] or 0) > 0
            if i and not exempt and (t - times[i - 1]).total_seconds() / 3600 < freq["message_min_hours_between"]:
                fails["R9 message gap"].append(f"{cid} {t}")
            if paid and paid_times and not exempt and (t - paid_times[-1]).total_seconds() / 3600 < freq["paid_min_hours_between"]:
                fails["R9 paid gap"].append(f"{cid} {t}")
            if sum(1 for x in times[:i + 1] if t - x < timedelta(days=7)) > freq["message_max_per_7_days"]:
                fails["R9 messages per 7 days"].append(f"{cid} {t}")
            if paid:
                paid_times.append(t)
                if sum(1 for x in paid_times if t - x < timedelta(days=7)) > freq["paid_max_per_7_days"]:
                    fails["R9 paid per 7 days"].append(f"{cid} {t}")
                window = [pr for pr, pt in zip(rows[:i + 1], times[:i + 1])
                          if t - pt < timedelta(days=RULES["spend_cap"]["window_days"])]
                if sum(pr["est_cost_inr"] or 0 for pr in window) > spend_caps.get(cid, float("inf")) + 0.01:
                    fails["R31 per-customer spend"].append(f"{cid} {t}")
            if r["offer_type"] in DISCOUNT_TYPES:
                # whole days, like the rule (days_since_discount_redeemed)
                if any(t > x and (t.date() - x.date()).days < freq["discount_cooldown_days"] for x in redemptions[cid]):
                    fails["R10 cooldown"].append(f"{cid} {t}")
            if r["offer_id"] == "PRODUCT_COUPON":
                every = tiers[tiers_at.get(r["id"], "IRREGULAR")]["coupon_every_days"]
                prev = [x for x, pr in zip(times[:i], rows[:i]) if pr["offer_type"] in DISCOUNT_TYPES]
                if prev and (t - prev[-1]).total_seconds() / 86400 < every:
                    fails["R20 coupon interval"].append(f"{cid} {t}")
            if any(pr["offer_id"] == r["offer_id"] and (pr["valid_until"] or "") > r["created_at"] for pr in rows[:i]):
                fails["R8 same offer repeated"].append(f"{cid} {t}")
            if r["offer_type"] in ACTIVE_TYPES:
                for pr, pt in zip(rows[:i], times[:i]):
                    if pr["offer_type"] in ACTIVE_TYPES and (pr["valid_until"] or "") > r["created_at"]:
                        fails["R8 one active offer"].append(f"{cid} {t}")
            if cid in optouts and t > optouts[cid]:  # the offer that triggered /stop is not a breach
                fails["R1 offer after /stop"].append(f"{cid} {t}")

    by_day = defaultdict(float)
    by_round = defaultdict(float)
    for r in given:
        t = datetime.fromisoformat(r["created_at"])
        by_day[t.date()] += r["est_cost_inr"] or 0
        for hour in ROUNDS:
            if t.hour <= hour:
                by_round[(t.date(), hour)] += r["est_cost_inr"] or 0
    for d, spent in by_day.items():
        if spent > RULES["budget"]["daily_inr"] + 0.01:
            fails["R13 daily budget"].append(f"{d} ₹{spent:.0f}")
    for (d, hour), spent in by_round.items():
        allowance = budget_allowance(datetime(d.year, d.month, d.day, hour))
        if spent > allowance + 0.01:
            fails["R13 pacing"].append(f"{d} {hour}:00 ₹{spent:.0f} > ₹{allowance:.0f}")

    names = ["R1 offer after /stop", "R8 one active offer", "R8 same offer repeated", "R9 message gap", "R9 paid gap",
             "R9 messages per 7 days", "R9 paid per 7 days", "R10 cooldown", "R20 coupon interval", "R31 per-customer spend",
             "R13 daily budget", "R13 pacing"]
    return {n: fails.get(n, []) for n in names}, len(given)
