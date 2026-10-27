"""Builds the small databases the hosted (Vercel) copy of the dashboard starts from.

    python tools/make_vercel_data.py      # -> data/demo/shop_lite.db, data/demo/offers_seed.db

shop_lite.db is data/shop.db without the clickstream tables (products, orders, promotions and
the rest stay, so bundles, product coupons and R22 no-stacking still work). offers_seed.db is
the offer log from the last evaluate.py run (data/sim_offers.db), so the page opens with decisions.
"""
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.config import DATA_DIR  # noqa: E402

DROP = ("events", "sessions")


def main():
    out = DATA_DIR / "demo"
    out.mkdir(exist_ok=True)
    lite = out / "shop_lite.db"
    lite.unlink(missing_ok=True)
    src = sqlite3.connect(DATA_DIR / "shop.db")
    dst = sqlite3.connect(lite)
    src.backup(dst)
    src.close()
    for t in DROP:
        dst.execute(f"DROP TABLE IF EXISTS {t}")
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    shutil.copyfile(DATA_DIR / "sim_offers.db", out / "offers_seed.db")
    for f in (lite, out / "offers_seed.db"):
        print(f"{f.relative_to(ROOT)}: {f.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
