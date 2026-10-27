"""30-day forward simulation (22 Oct -> 21 Nov 2026, with Diwali on 8 Nov).

    python simulate_30d.py                 # rules-only arm vs control (no API calls)
    python simulate_30d.py --ai            # AI arm vs rules arm vs control (~1,500+ API calls)
    python simulate_30d.py --days 10

Every day each customer is decided once (at their usual active hour), offers go through the
delivery layer in dry-run mode (consent re-checked at send time), simulated customers buy,
redeem, opt out or press "not interested", and their features update. At the end the whole
month's log is checked: no rule may ever have been broken. Writes data/sim30_report.md.
"""
import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime

from src import coupons, offer_log
from src.config import DATA_DIR, default_customers_file
from src.sim30 import run

sys.stdout.reconfigure(encoding="utf-8")


def _mean_se(values):
    n = len(values)
    if n < 2:
        return (values[0] if values else 0.0), float("nan")
    m = sum(values) / n
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return m, math.sqrt(var / n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--start", default="2026-10-22")
    ap.add_argument("--ai", action="store_true", help="add an AI arm (one API call per AI decision)")
    ap.add_argument("--customers", default=str(default_customers_file()))
    args = ap.parse_args()

    with open(args.customers, encoding="utf-8") as f:
        customers = json.load(f)
    lines = []

    def log(s=""):
        print(s)
        lines.append(s)

    log(f"# 30-day simulation from {args.start} ({args.days} days{', with AI arm' if args.ai else ''})\n")
    result = run(customers, datetime.fromisoformat(args.start), days=args.days, ai=args.ai, log=log)
    (fails, n_given) = result["checks"]

    log(f"\n## Rule checks over the whole period ({n_given} offers given)\n")
    for name, problems in fails.items():
        log(f"- {'PASS' if not problems else 'FAIL'}  {name}" + (f": {len(problems)} cases, e.g. {problems[:3]}" if problems else ""))

    misuse = coupons.misuse_report()
    by_reason = Counter(m["reason"] for m in misuse)
    with sqlite3.connect(offer_log.DB_PATH) as c2:
        issued, redeemed = c2.execute("SELECT COUNT(*), SUM(status = 'redeemed') FROM coupon_codes").fetchone()
    log(f"\n## Coupon codes\n\n- {issued} single-use codes issued, {redeemed or 0} redeemed by their owner.")
    log(f"- {len(misuse)} attempts refused and logged: {dict(by_reason)} (e.g. classmates sharing codes).")

    # Arm comparison, per customer
    conn = sqlite3.connect(offer_log.DB_PATH)
    conn.row_factory = sqlite3.Row
    given = Counter(r["customer_id"] for r in conn.execute(
        f"SELECT customer_id FROM offer_log WHERE status IN {offer_log.GIVEN}"))
    by_decider = Counter(r["decided_by"] for r in conn.execute(
        f"SELECT decided_by FROM offer_log WHERE status IN {offer_log.GIVEN}"))
    conn.close()
    arms = defaultdict(list)
    for cid, arm in result["arms"].items():
        arms[arm].append(cid)
    stats = result["stats"]
    control_margin = [stats[c]["margin"] for c in arms["CONTROL"]]
    control_buys = [stats[c]["purchases"] for c in arms["CONTROL"]]
    cm, cse = _mean_se(control_margin)
    cb, _ = _mean_se(control_buys)

    log("\n## Arms (per customer over the period)\n")
    log("| Arm | Customers | Offers given | Purchases | Net margin | Discount cost | Redemptions | Opt-outs | Extra purchases vs control | Extra margin vs control |")
    log("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for arm in ("CONTROL", "RULES", "AI"):
        ids = arms.get(arm)
        if not ids:
            continue
        m, se = _mean_se([stats[c]["margin"] for c in ids])
        b, _ = _mean_se([stats[c]["purchases"] for c in ids])
        cost = sum(stats[c]["discount_cost"] for c in ids) / len(ids)
        red = sum(stats[c]["redemptions"] for c in ids)
        offers = sum(given[c] for c in ids)
        opt = sum(1 for c in ids if c in result["optouts"])
        extra_b = "-" if arm == "CONTROL" else f"{b - cb:+.2f}"
        extra_m = "-" if arm == "CONTROL" else f"₹{m - cm:+,.0f} ± {math.sqrt(se ** 2 + cse ** 2):,.0f}"
        log(f"| {arm} | {len(ids)} | {offers} | {b:.2f} | ₹{m:,.0f} | ₹{cost:,.0f} | {red} | {opt} | {extra_b} | {extra_m} |")
    log(f"\nOffers given by: {dict(by_decider)} (EXPLORE = random allowed offer for learning, R27).")
    log(f"\nControl group: {len(arms['CONTROL'])} customers. Differences smaller than about twice the ± value are "
        "within noise; with a classmate-sized pool (~20 people, ~3 controls) a test like this cannot prove anything.")
    log("\nNote: customers' true responses come from the simulator's assumptions (config/response_model.yaml), "
        "and the arms contain different customers, so segment mix also differs between arms.")

    out = DATA_DIR / "sim30_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
