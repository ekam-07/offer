"""Generate synthetic customers, compute their features, and check persona vs segment.

    python generate_data.py                   # 200 customers, activity up to today 14:00
    python generate_data.py -n 1000 --seed 7 --ref "2026-10-22 14:00"

Writes data/shop.db (raw tables), data/customers.json (features, used by the preview page)
and CSV files in data/dataset/ (see docs/DATA_DICTIONARY.md).
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime

from src.config import DATA_DIR, RULES
from src.export import export
from src.features import compute
from src.generate import SHOP_DB, generate
from src.segments import prepare

sys.stdout.reconfigure(encoding="utf-8")

# Which segment we expect each persona to land in (used only for this check).
EXPECTED = {
    "loyal": {"LOYAL"}, "deal_seeker": {"DEAL_SEEKER"}, "at_risk": {"AT_RISK"}, "dormant": {"DORMANT"},
    "new": {"NEW"}, "cart_abandoner": {"CART_ABANDONER"}, "window_shopper": {"BROWSER"}, "vip": {"VIP"},
}


def raw_summary():
    conn = sqlite3.connect(SHOP_DB)
    print("Raw tables:", ", ".join(
        f"{t} {conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}"
        for t in ["customers", "orders", "sessions", "cart_events", "loyalty_tx"]))
    print("\nPersona       customers  orders/cust  avg order  coupon use")
    for persona, n, orders, aov, coupon in conn.execute("""
        SELECT c.persona, COUNT(DISTINCT c.customer_id), COUNT(o.order_id) * 1.0 / COUNT(DISTINCT c.customer_id),
               AVG(o.total), AVG(o.used_coupon)
        FROM customers c LEFT JOIN orders o ON o.customer_id = c.customer_id
        GROUP BY c.persona ORDER BY 2 DESC"""):
        print(f"{persona:15} {n:7}  {orders:11.1f}  ₹{aov or 0:8,.0f}  {(coupon or 0) * 100:8.0f}%")
    conn.close()


def event_summary():
    conn = sqlite3.connect(SHOP_DB)
    rows = conn.execute("SELECT event_name, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC").fetchall()
    n_sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM events").fetchone()[0]
    conn.close()
    print(f"\nEvent stream (last 365 days): {sum(n for _, n in rows):,} events in {n_sessions:,} sessions")
    print("  " + ", ".join(f"{name} {n:,}" for name, n in rows))


def crosstab(customers):
    table = defaultdict(Counter)
    for c in customers:
        table[c["persona"]][prepare(c)["segment"]] += 1
    segs = RULES["segment_order"]
    short = {s: s[:8] for s in segs}
    print("\nPersona x segment (rows: hidden persona, columns: segment the rules assigned)")
    print(f"{'':15}" + "".join(f"{short[s]:>9}" for s in segs) + "   match")
    total_match = 0
    for persona in sorted(table):
        row = table[persona]
        match = sum(row[s] for s in EXPECTED.get(persona, ()))
        total_match += match
        print(f"{persona:15}" + "".join(f"{row[s] or '.':>9}" for s in segs) + f"   {match / sum(row.values()):5.0%}")
    print(f"\nOverall match: {total_match / len(customers):.0%} "
          "(not 100% on purpose: real customers overlap, e.g. a loyal customer with an abandoned cart)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ref", help='reference "now" for the data, e.g. "2026-10-22 14:00" (default: today 14:00)')
    args = ap.parse_args()
    ref = datetime.fromisoformat(args.ref) if args.ref else datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)

    generate(n=args.n, seed=args.seed, ref=ref)
    customers = compute(ref)
    out = DATA_DIR / "customers.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(customers, f, indent=1, ensure_ascii=False)

    counts = export(customers)

    print(f"Generated {len(customers)} customers as of {ref:%Y-%m-%d %H:%M} -> {SHOP_DB.name}, {out.name}\n")
    raw_summary()
    event_summary()
    crosstab(customers)
    print(f"\nCSV export in data/dataset/ (columns explained in docs/DATA_DICTIONARY.md):")
    for name, n in counts.items():
        print(f"  {name:24} {n:>9,} rows")


if __name__ == "__main__":
    main()
