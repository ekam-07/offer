"""Exports the generated dataset as CSV files in data/dataset/ (column guide: docs/DATA_DICTIONARY.md)."""
import csv
import sqlite3
from collections import Counter
from itertools import combinations

from .config import DATA_DIR
from .generate import SHOP_DB
from .segments import prepare

OUT_DIR = DATA_DIR / "dataset"
RAW_TABLES = ["customers", "products", "promotions", "orders", "order_items", "events", "loyalty_tx"]


def _write(path, rows, columns=None):
    rows = list(rows)
    columns = columns or (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def market_basket(conn, min_orders=3):
    """Product types bought in the same order, like Amazon's Market Basket report:
    support = share of orders with both, confidence = P(B | A), lift = confidence / P(B)."""
    baskets = {}
    for order_id, item_type in conn.execute(
            "SELECT oi.order_id, p.item_type FROM order_items oi JOIN products p USING (product_id)"):
        baskets.setdefault(order_id, set()).add(item_type)
    n = len(baskets)
    single, pairs = Counter(), Counter()
    for items in baskets.values():
        single.update(items)
        pairs.update(combinations(sorted(items), 2))
    rows = []
    for (a, b), both in pairs.items():
        if both < min_orders:
            continue
        for x, y in ((a, b), (b, a)):
            conf = both / single[x]
            rows.append({"item_type": x, "bought_with": y, "orders_together": both,
                         "support": round(both / n, 4), "confidence": round(conf, 3),
                         "lift": round(conf / (single[y] / n), 2)})
    return sorted(rows, key=lambda r: (-r["lift"], -r["orders_together"]))


def export(customers):
    """customers: feature rows from features.compute(). Returns {file: row count}."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}
    conn = sqlite3.connect(SHOP_DB)
    conn.row_factory = sqlite3.Row
    for table in RAW_TABLES:
        cur = conn.execute(f"SELECT * FROM {table}")
        columns = [d[0] for d in cur.description]
        counts[f"{table}.csv"] = _write(OUT_DIR / f"{table}.csv", (dict(r) for r in cur), columns)
    counts["market_basket.csv"] = _write(
        OUT_DIR / "market_basket.csv", market_basket(conn),
        ["item_type", "bought_with", "orders_together", "support", "confidence", "lift"])
    conn.close()
    # One row per customer with every feature plus the engine's derived scores and segment.
    counts["customer_features.csv"] = _write(OUT_DIR / "customer_features.csv", (prepare(c) for c in customers))
    return counts
