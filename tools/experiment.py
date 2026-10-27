"""Try changes to the business rules and measure the profit they bring in the simulator.

    python tools/experiment.py                       # every idea, rules engine only (free, fast)
    python tools/experiment.py --only baseline,caps  # a few ideas
    python tools/experiment.py --ai --only baseline  # the live policy: AI first, rules if the AI fails

Each idea is a set of rules.yaml overrides applied in memory (the file is never changed). Every
idea faces the same customers and random draws, on several decision days, so differences come
from the idea and not from luck. "train" days are for choosing ideas, "check" days for confirming
the winner wasn't a fluke of those days.
"""
import argparse
import copy
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src import agent, rules  # noqa: E402
from src.config import RULES, default_customers_file  # noqa: E402
from src.simulate import policy_ai, policy_rules, prepare_population, simulate  # noqa: E402

TRAIN_DAYS = ["2026-10-02 14:00", "2026-10-09 14:00", "2026-10-16 14:00"]
CHECK_DAYS = ["2026-10-23 14:00", "2026-10-30 14:00"]
RUNS, SEED = 1000, 7

# name -> {dotted rules.yaml path: new value}
TOPUP = {"expected_profit.count_basket_topup": True}
IDEAS = {
    "baseline": {},
    # 1. The engine's profit estimate ignores that "₹100 off on ₹999+" makes new buyers fill their basket.
    "ep_basket_topup": TOPUP,
    # 2. R6: a flat ₹ off may be at most 15% of the average order; calibrated orders are smaller.
    "flat_share_20": {"max_flat_share_of_aov": 0.20},
    "flat_share_25": {"max_flat_share_of_aov": 0.25},
    "topup+flat_share_20": {**TOPUP, "max_flat_share_of_aov": 0.20},
    "topup+flat_share_25": {**TOPUP, "max_flat_share_of_aov": 0.25},
    # 3. Let NEW / REGULAR / BROWSER customers get a flat ₹ off (minimum order ₹999 keeps it safe).
    "new_flat_off": {"segments.NEW.allowed": ["WELCOME", "FLAT_OFF", "PRODUCT_COUPON", "FREE_SHIPPING", "NONE"]},
    "regular_flat_off": {"segments.REGULAR.allowed": ["REPLENISH_REMINDER", "POINTS_UPDATE", "REVIEW_REQUEST", "BONUS_POINTS",
                                                      "FREE_SHIPPING", "FLAT_OFF", "PRODUCT_COUPON", "NONE"]},
    "browser_flat_off": {"segments.BROWSER.allowed": ["CATEGORY_DEAL", "FLAT_OFF", "PRODUCT_COUPON", "FREE_SHIPPING", "NONE"]},
    # 4. Bigger caps where the blanket discount beat us.
    "deal_seeker_caps_150": {"segments.DEAL_SEEKER.max_flat_inr": 150, "segments.DEAL_SEEKER.max_offer_cost_inr": 150},
    "dormant_cap_200": {"segments.DORMANT.max_flat_inr": 200, "segments.DORMANT.max_offer_cost_inr": 200},
    # 5. The engine's guess of how much discounts move people (fitted from experiment data in real life).
    "sensitivity_up": {"expected_profit.base_sensitivity": 0.15, "expected_profit.price_signal_weight": 0.9},
    "sensitivity_down": {"expected_profit.base_sensitivity": 0.05, "expected_profit.price_signal_weight": 0.4},
    "half_effect_5": {"expected_profit.half_effect_pct": 5},
    "half_effect_10": {"expected_profit.half_effect_pct": 10},
    # 6. Early access for VIP / loyal is worth more than the engine thinks?
    "early_access_lift_06": {"expected_profit.free_lift.EARLY_ACCESS": 0.06},
    # 7. Information only (your decision keeps goodwill coupons on): what they cost.
    "no_goodwill_coupons": {"coupons_for_sure_things": False},
    # 8. Bigger daily budget / looser per-customer cap.
    "spend_cap_15pct": {"spend_cap.pct_of_margin_12m": 15},
}


def _walk(path):
    node, keys = RULES, path.split(".")
    for k in keys[:-1]:
        node = node[int(k)] if isinstance(node, list) else node[k]
    last = int(keys[-1]) if isinstance(node, list) else keys[-1]
    return node, last


def apply(overrides):
    """Set the overrides in place (other modules hold references into RULES) and return an undo list."""
    undo = []
    for path, value in overrides.items():
        node, key = _walk(path)
        undo.append((node, key, copy.deepcopy(node[key]) if (isinstance(node, dict) and key in node) or isinstance(node, list) else KeyError))
        node[key] = copy.deepcopy(value)
    rules._check_tier_order()
    rules._check_ladders()
    agent.SYSTEM_PROMPT = agent.build_system_prompt()
    return undo


def restore(undo):
    for node, key, old in reversed(undo):
        if old is KeyError:
            del node[key]
        else:
            node[key] = old
    agent.SYSTEM_PROMPT = agent.build_system_prompt()


def evaluate(customers, days, use_ai):
    totals, segs, extra = [], defaultdict(list), {}
    for day in days:
        now = datetime.fromisoformat(day)
        pop = prepare_population(copy.deepcopy(customers), SEED)
        decisions = policy_ai(customers, now)[0] if use_ai else policy_rules(copy.deepcopy(customers), now)
        r = simulate(pop, decisions, RUNS, SEED)
        totals.append(r["incremental_net_margin"])
        extra[day] = (r["incremental_purchases"], r["discount_cost"])
        for i, c in enumerate(pop):
            segs[c["segment"]].append(r["per_customer"]["net_gain"][i])
    return {
        "mean": sum(totals) / len(totals),
        "per_day": totals,
        "extra_purchases": sum(v[0] for v in extra.values()) / len(extra),
        "cost": sum(v[1] for v in extra.values()) / len(extra),
        "segments": {s: sum(v) / len(v) * 1 for s, v in segs.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated idea names")
    ap.add_argument("--ai", action="store_true", help="AI first, rules fallback (one API call per customer per day)")
    ap.add_argument("--check", action="store_true", help="use the check days instead of the train days")
    ap.add_argument("--days", help="comma-separated decision times, overrides train/check")
    ap.add_argument("--json", type=Path, help="also save the results here")
    args = ap.parse_args()

    with open(default_customers_file(), encoding="utf-8") as f:
        customers = json.load(f)
    days = args.days.split(",") if args.days else (CHECK_DAYS if args.check else TRAIN_DAYS)
    names = args.only.split(",") if args.only else list(IDEAS)
    print(f"{'AI first, rules fallback' if args.ai else 'Rules engine'} | days: {', '.join(d[:10] for d in days)}")
    print(f"{'idea':28} {'extra margin/wk':>15} {'vs baseline':>11} {'extra buys':>10} {'disc. cost':>10}  per day")

    results, base = {}, None
    for name in names:
        undo = apply(IDEAS[name])
        try:
            r = evaluate(customers, days, args.ai)
        finally:
            restore(undo)
        results[name] = r
        base = r["mean"] if name == "baseline" else base
        diff = f"{r['mean'] - base:+,.0f}" if base is not None else "-"
        print(f"{name:28} {r['mean']:+15,.0f} {diff:>11} {r['extra_purchases']:10.1f} {r['cost']:10,.0f}  "
              + " ".join(f"{x:+,.0f}" for x in r["per_day"]), flush=True)
    if args.json:
        args.json.write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
