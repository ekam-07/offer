"""Turns measured dataset statistics into persona overrides (config/personas_calibrated.yaml).

Real datasets give population numbers (e.g. "median gap between orders is 9 days").
Personas are slices of that population, so each persona maps to a part of the measured
distribution (loyal = the fast end of order gaps, window shoppers = the heavy browsers...).
That mapping is a design assumption and lives in the tables below.
"""
from datetime import date

import yaml

# Persona position in the measured distributions (percentile keys from behaviour.py).
SESSIONS_BAND = {
    "loyal": ("p50", "p90"), "deal_seeker": ("p50", "p90"), "at_risk": ("p10", "p25"),
    "new": ("p25", "p75"), "cart_abandoner": ("p50", "p90"), "window_shopper": ("p75", "p90"), "vip": ("p25", "p75"),
}
GAP_BAND = {
    "loyal": ("p10", "p50"), "deal_seeker": ("p25", "p75"), "at_risk": ("p10", "p50"),
    "dormant": ("p50", "p90"), "cart_abandoner": ("p50", "p90"), "vip": ("p25", "p75"),
}
# Multiplier on the measured "non-buying session leaves a cart" rate.
ABANDON_MULT = {
    "loyal": 0.5, "deal_seeker": 1.2, "at_risk": 1.0, "dormant": 1.0, "new": 1.5,
    "cart_abandoner": 5.0, "window_shopper": 1.0, "vip": 0.5,
}
# Order value as a multiple of a typical basket (median product price x items per order).
ITEMS_PER_ORDER = 1.4
AOV_LEVEL = {
    "loyal": (1.0, 2.0), "deal_seeker": (0.6, 1.2), "at_risk": (0.8, 2.0), "dormant": (0.7, 1.6),
    "new": (0.4, 1.2), "cart_abandoner": (1.2, 2.8), "window_shopper": (0.4, 1.0), "vip": (4.0, 9.0),
}
MIN_GAP_DAYS = 3
# Order gaps need a long window: a 4-month file only "sees" people who buy again quickly, so
# it measures gaps far too short (RetailRocket: median 6 days from 544 repeat buyers).
MIN_DAYS_FOR_GAPS = 365
MIN_REPEAT_BUYERS = 1000
# A catalogue's category mix is what the store LISTS, not what customers buy (Flipkart's sample
# is 68% fashion with 6 grocery items), so it never sets category popularity. Category price
# levels are only taken from categories with enough products to measure.
MIN_PRODUCTS_FOR_PRICE = 200


def build_overrides(measured, base_personas):
    """Return (overrides dict, list of notes for the user)."""
    overrides, notes = {}, []
    fk = measured.get("flipkart")
    bh = measured.get("behaviour")

    if fk:
        cats = base_personas["categories"]
        found = {c: v for c, v in fk["categories"].items()
                 if c in cats and v["products"] >= MIN_PRODUCTS_FOR_PRICE}
        skipped = [c for c in cats if c not in found]
        overrides["categories"] = {
            c: {"price_mult": round(min(3.0, max(0.3, v["median_price_inr"] / fk["overall_median_price_inr"])), 2)}
            for c, v in found.items()
        }
        notes.append("Category popularity kept hand-set: a catalogue's mix is what the store lists, not what people buy")
        if skipped:
            notes.append(f"Price level kept hand-set for {', '.join(skipped)} "
                         f"(fewer than {MIN_PRODUCTS_FOR_PRICE} products in the file)")
        basket = fk["overall_median_price_inr"] * ITEMS_PER_ORDER
        overrides["personas"] = {
            p: {"aov_inr": [round(lo * basket, -1), round(hi * basket, -1)]} for p, (lo, hi) in AOV_LEVEL.items()
        }
        notes.append(f"Flipkart: {fk['products_used']} products, median price ₹{fk['overall_median_price_inr']:.0f} "
                     f"-> typical basket ₹{basket:.0f}")

    if bh:
        personas = overrides.setdefault("personas", {})
        base_abandon = bh["abandon_rate_per_non_buying_session"]
        if base_abandon is not None:
            for p, mult in ABANDON_MULT.items():
                personas.setdefault(p, {})["abandon_rate"] = round(min(0.95, base_abandon * mult), 3)
        spw = bh["sessions_per_week_returning_users"]
        if spw:
            for p, (lo, hi) in SESSIONS_BAND.items():
                personas.setdefault(p, {})["sessions_per_week"] = [max(0.1, spw[lo]), max(0.2, spw[hi])]
        gaps = bh["order_gap_days_repeat_buyers"]
        if gaps and bh["days_covered"] >= MIN_DAYS_FOR_GAPS and bh["repeat_buyers_with_gap"] >= MIN_REPEAT_BUYERS:
            for p, (lo, hi) in GAP_BAND.items():
                personas.setdefault(p, {})["order_gap_days"] = [max(MIN_GAP_DAYS, gaps[lo]), max(MIN_GAP_DAYS + 1, gaps[hi])]
        else:
            notes.append(f"Order gaps NOT calibrated: the file covers {bh['days_covered']:.0f} days with "
                         f"{bh['repeat_buyers_with_gap']} repeat buyers (need {MIN_DAYS_FOR_GAPS}+ days and "
                         f"{MIN_REPEAT_BUYERS}+ repeat buyers; short windows only see fast repeat buyers)")
        notes.append(f"Behaviour ({bh['format']}): {bh['users']} users, {bh['sessions']} sessions over {bh['days_covered']} days; "
                     f"cart abandonment {bh['cart_abandonment_rate']:.0%}, session purchase rate {bh['session_purchase_rate']:.1%}")
        if spw and spw["p90"] < 1.5:
            notes.append(f"Real users browse less than the BROWSER threshold assumes (p90 = {spw['p90']} sessions/week); "
                         "consider lowering browser_min_sessions_no_buy in rules.yaml")
    return overrides, notes


def write(overrides, path, sources, base_file="personas.yaml"):
    header = (f"# Generated by calibrate.py on {date.today()} - do not edit by hand.\n"
              f"# Overrides config/{base_file}. Sources: {', '.join(sources)}\n"
              "# Delete this file to go back to the hand-set values.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(overrides, f, sort_keys=False, allow_unicode=True)
