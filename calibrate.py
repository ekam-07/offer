"""Calibrate the personas from real datasets placed in data/raw/.

    python calibrate.py                         # auto-find files in data/raw/
    python calibrate.py --flipkart data/raw/flipkart_com-ecommerce_sample.csv --behaviour data/raw/events.csv
    python calibrate.py --sample 0.05           # use 5% of users (for multi-GB REES46 files)

Writes config/calibration.json (what was measured) and config/personas_calibrated.yaml
(persona overrides). Then run: python generate_data.py
If the Hillstrom email test is in data/raw/, also writes config/response_model_calibrated.yaml
(how strongly each persona reacts to offers; used by evaluate.py).
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

from src.calibration import apply, behaviour, flipkart, hillstrom
from src.config import CONFIG_DIR, DATA_DIR

sys.stdout.reconfigure(encoding="utf-8")
RAW = DATA_DIR / "raw"


def find_files():
    """Pick up the Flipkart catalog, one clickstream file and the Hillstrom test from data/raw/ by their columns."""
    fk = bh = hs = None
    for path in sorted(RAW.glob("*.csv*")) if RAW.exists() else []:
        try:
            cols = set(pd.read_csv(path, nrows=0).columns)
        except Exception:
            continue
        if {"product_category_tree", "retail_price"} <= cols:
            fk = fk or path
        elif {"visitorid", "event"} <= cols or {"user_id", "event_type"} <= cols:
            bh = bh or path
        elif {"recency", "newbie", "segment", "conversion"} <= cols:
            hs = hs or path
    return fk, bh, hs


def show_changes(base, overrides):
    print("\nPersona changes (hand-set -> calibrated):")
    for persona, values in overrides.get("personas", {}).items():
        for key, new in values.items():
            old = base["personas"].get(persona, {}).get(key)
            print(f"  {persona:15} {key:18} {old!s:>16} -> {new}")
    if "categories" in overrides:
        print("\nCategory price level (popularity stays hand-set):")
        for cat, v in overrides["categories"].items():
            print(f"  {cat:12} {base['categories'][cat]['price_mult']:.2f} -> {v['price_mult']:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flipkart", type=Path)
    ap.add_argument("--behaviour", type=Path)
    ap.add_argument("--hillstrom", type=Path)
    ap.add_argument("--sample", type=float, help="share of users to read from the clickstream (default: auto by file size)")
    ap.add_argument("--out-dir", type=Path, default=CONFIG_DIR)
    ap.add_argument("--reuse", action="store_true",
                    help="rebuild the persona settings from config/calibration.json without re-reading the files")
    args = ap.parse_args()

    found_fk, found_bh, found_hs = find_files()
    fk_path, bh_path = args.flipkart or found_fk, args.behaviour or found_bh
    hs_path = args.hillstrom or found_hs
    if args.reuse:
        with open(CONFIG_DIR / "calibration.json", encoding="utf-8") as f:
            measured = json.load(f)
        fk_path = bh_path = None
        print("Reusing the measurements in config/calibration.json")
    elif not fk_path and not bh_path and not hs_path:
        print(f"No datasets found in {RAW}. See the download steps in PLAN.md (Step 1a).")
        return 1
    else:
        measured = {}
    if fk_path:
        print(f"Reading Flipkart catalog: {fk_path}")
        measured["flipkart"] = flipkart.measure(fk_path)
    if bh_path:
        size_mb = bh_path.stat().st_size / 1e6
        sample = args.sample or (1.0 if size_mb < 500 else 0.05)
        print(f"Reading clickstream: {bh_path} ({size_mb:,.0f} MB, sampling {sample:.0%} of users)")
        measured["behaviour"] = behaviour.measure(bh_path, sample=sample)

    if hs_path:
        print(f"Reading Hillstrom email test: {hs_path}")
        measured["hillstrom"] = hillstrom.measure(hs_path)

    with open(CONFIG_DIR / "personas.yaml", encoding="utf-8") as f:
        base = yaml.safe_load(f)
    overrides, notes = apply.build_overrides(measured, base)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with open(args.out_dir / "calibration.json", "w", encoding="utf-8") as f:
        json.dump(measured, f, indent=2, ensure_ascii=False)
    sources = [str(p.name) for p in (fk_path, bh_path) if p] or [
        m.get("source", "?").split("\\")[-1] for k, m in measured.items() if k != "hillstrom"]
    apply.write(overrides, args.out_dir / "personas_calibrated.yaml", sources)
    if "hillstrom" in measured:
        with open(CONFIG_DIR / "response_model.yaml", encoding="utf-8") as f:
            rm = yaml.safe_load(f)
        rm_overrides, hs_notes, hs_rows = hillstrom.build_overrides(measured["hillstrom"], rm)
        apply.write(rm_overrides, args.out_dir / "response_model_calibrated.yaml",
                    [Path(measured["hillstrom"]["source"]).name], base_file="response_model.yaml")
        notes += hs_notes

    print()
    for n in notes:
        print("- " + n)
    show_changes(base, overrides)
    if "hillstrom" in measured:
        print("\nOffer reaction (discount_sensitivity), as a ratio to the average customer:")
        print(f"  {'persona':15} {'hand-set':>8} {'ratio':>6} {'Hillstrom':>9} {'90% range':>14} {'used':>6}")
        for p, old, old_ratio, hs_ratio, (lo, hi), new in hs_rows:
            print(f"  {p:15} {old:8.3f} {old_ratio:6.2f} {hs_ratio:9.2f} {f'{lo:.2f} to {hi:.2f}':>14} {new:6.3f}"
                  + ("  <- changed" if new != old else ""))
        print(f"Wrote {args.out_dir / 'response_model_calibrated.yaml'} (used by evaluate.py)")
    print(f"\nWrote {args.out_dir / 'calibration.json'} and {args.out_dir / 'personas_calibrated.yaml'}")
    print("Next: python generate_data.py   (regenerates customers with the calibrated personas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
