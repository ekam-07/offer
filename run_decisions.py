"""Decide an offer for every customer in a JSON file and write each decision to the offer log.

    python run_decisions.py                    # AI agent + rules (needs ANTHROPIC_API_KEY in .env)
    python run_decisions.py --no-agent         # rules only
    python run_decisions.py --reset --now "2026-10-22 14:00"
"""
import argparse
import json
import sys
from datetime import datetime

from src import offer_log
from src.config import default_customers_file
from src.decide import decide_batch

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", default=str(default_customers_file()))
    ap.add_argument("--no-agent", action="store_true", help="use only the rule-based picker")
    ap.add_argument("--reset", action="store_true", help="clear the offer log first")
    ap.add_argument("--now", help='pretend time, e.g. "2026-10-22 14:00"')
    args = ap.parse_args()

    if args.reset:
        offer_log.reset()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now()
    with open(args.customers, encoding="utf-8") as f:
        customers = json.load(f)

    print(f"{'ID':5} {'SEGMENT':15} {'STATUS':12} {'OFFER':14} {'VALUE':>5} {'BY':6} {'AGENT':15} FLAG")
    for r in decide_batch(customers, now=now, use_agent=not args.no_agent):
        print(f"{r['customer_id']:5} {r['segment']:15} {r['status']:12} {r.get('offer_id') or '-':14} "
              f"{r.get('value') or 0:>5} {r['decided_by']:6} {r['agent_status']:15} {'⚑' if r['flagged'] else ''}")
        if r.get("message"):
            print(f"      msg:    {r['message']}")
        print(f"      reason: {r['reason']}")
        if r.get("agent_failure"):
            print(f"      AGENT FAILURE: {r['agent_failure']}")
        for v in r.get("violations") or []:
            print(f"      violation: {v}")
    print(f"\nLogged to {offer_log.DB_PATH}. View with: python show_log.py [--flagged]")


if __name__ == "__main__":
    main()
