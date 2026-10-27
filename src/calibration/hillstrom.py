"""Measures how much a promotional email moves different kinds of customers, from the Hillstrom
MineThatData experiment (64,000 past buyers randomly sent a men's email, a women's email or nothing;
purchases tracked for 2 weeks).

Expected file: Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv
with columns recency, history, newbie, segment, conversion.

What it can and can't tell us:
- It is a randomised test, so treated - control is the true effect of the message (uplift).
- It is a 2008 US email with no stated discount, not an INR coupon, so only the SHAPE carries
  over (which customers react more than others), not the size of the effect.
- It has no coupon-use, cart or browsing data, so deal seekers, cart abandoners and window
  shoppers can't be matched and keep their hand-set values.
"""
import numpy as np
import pandas as pd

# Persona -> the Hillstrom customers that look like it (recency = months since last purchase,
# newbie = first purchase in the last 12 months, history = spend in the last year).
CELLS = {
    "loyal": lambda d: (d.recency <= 3) & (d.newbie == 0),
    "vip": lambda d: (d.recency <= 3) & (d.newbie == 0) & (d.history >= d.history.quantile(0.75)),
    "at_risk": lambda d: d.recency.between(4, 8) & (d.newbie == 0),
    "dormant": lambda d: (d.recency >= 9) & (d.newbie == 0),
    "new": lambda d: (d.recency <= 3) & (d.newbie == 1),
}
NOT_MATCHED = ["deal_seeker", "cart_abandoner", "window_shopper"]
CONFIDENCE = 0.90
BOOTSTRAP_RUNS = 1000


def _lift(conv, treated, mask):
    """Extra share of would-be non-buyers converted by the email (same unit as discount_sensitivity)."""
    c = conv[mask & ~treated].mean()
    t = conv[mask & treated].mean()
    return (t - c) / (1 - c)


def measure(path, seed=0):
    d = pd.read_csv(path)
    conv = d["conversion"].to_numpy()
    treated = (d["segment"] != "No E-Mail").to_numpy()
    masks = {p: f(d).to_numpy() for p, f in CELLS.items()}

    everyone = np.ones(len(d), dtype=bool)

    def stats(idx):
        # Ratios are to the lift over all 64,000 customers: a far steadier yardstick than any cell.
        overall = _lift(conv[idx], treated[idx], everyone)
        lifts = {p: _lift(conv[idx], treated[idx], m[idx]) for p, m in masks.items()}
        return lifts, {p: v / overall for p, v in lifts.items()}

    lifts, ratios = stats(np.arange(len(d)))
    rng = np.random.default_rng(seed)
    boot = {p: [] for p in masks}
    for _ in range(BOOTSTRAP_RUNS):
        _, r = stats(rng.integers(0, len(d), len(d)))
        for p in masks:
            boot[p].append(r[p])
    tail = (1 - CONFIDENCE) / 2 * 100

    cells = {}
    for p, m in masks.items():
        cells[p] = {
            "customers": int(m.sum()),
            "buy_rate_no_email": round(float(conv[m & ~treated].mean()), 4),
            "buy_rate_email": round(float(conv[m & treated].mean()), 4),
            "uplift": round(float(lifts[p]), 4),
            "ratio_to_all": round(float(ratios[p]), 2),
            "ratio_range": [round(float(np.percentile(boot[p], tail)), 2),
                            round(float(np.percentile(boot[p], 100 - tail)), 2)],
        }
    c, t = conv[~treated].mean(), conv[treated].mean()
    return {
        "source": str(path),
        "customers": int(len(d)),
        "window_days": 14,
        "buy_rate_no_email": round(float(c), 4),
        "buy_rate_email": round(float(t), 4),
        "relative_lift": round(float(t / c - 1), 2),
        "confidence": CONFIDENCE,
        "cells": cells,
    }


def build_overrides(measured, rm):
    """Move a persona's discount_sensitivity only when Hillstrom clearly disagrees with it.

    Hillstrom gives each persona's reaction as a ratio to the average customer's. The hand-set
    values are put on the same scale (their average over the matched personas is pinned to
    Hillstrom's average over the same personas). If a hand-set ratio falls outside Hillstrom's
    90% range, it moves to the nearest edge of that range (the smallest change the data asks
    for); otherwise it stays. The overall level is kept, because an email is not a discount.
    """
    hs = measured["cells"]
    hand = {p: rm["personas"][p]["discount_sensitivity"] for p in hs}
    unit = np.mean(list(hand.values())) / np.mean([c["ratio_to_all"] for c in hs.values()])
    overrides, rows = {}, []
    for p, cell in hs.items():
        old_ratio = hand[p] / unit
        lo, hi = cell["ratio_range"]
        new_ratio = min(max(old_ratio, max(lo, 0.0)), hi)
        new = round(float(new_ratio * unit), 3)
        changed = abs(new - hand[p]) >= 0.005
        if changed:
            overrides.setdefault("personas", {})[p] = {"discount_sensitivity": new}
        rows.append((p, hand[p], round(float(old_ratio), 2), cell["ratio_to_all"], (lo, hi), new if changed else hand[p]))
    notes = [
        f"Hillstrom: {measured['customers']:,} past buyers; an email lifted 2-week buying from "
        f"{measured['buy_rate_no_email']:.2%} to {measured['buy_rate_email']:.2%} (+{measured['relative_lift']:.0%})",
        "Only the shape is used (who reacts more); the size of a discount's effect stays hand-set",
        f"Not matched (no coupon, cart or browsing data in Hillstrom): {', '.join(NOT_MATCHED)}",
    ]
    return overrides, notes, rows
