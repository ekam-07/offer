"""Print the offer log.

    python show_log.py              # latest 50 decisions
    python show_log.py --flagged    # only decisions where the agent failed or broke a rule
"""
import argparse
import json
import sys

from src import offer_log

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flagged", action="store_true")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    rows = offer_log.all_rows(flagged_only=args.flagged, limit=args.limit)
    if not rows:
        print("No log entries.")
        return
    for r in rows:
        flag = "  ⚑ FLAGGED" if r["flagged"] else ""
        print(f"#{r['id']} {r['created_at']}  {r['customer_id']} [{r['segment']}]  {r['status']}{flag}")
        print(f"   offer:      {r['offer_id'] or '-'} value={r['value'] or 0} cost=₹{r['est_cost_inr'] or 0:.0f}"
              f" valid_until={(r['valid_until'] or '-')[:16]}")
        print(f"   decided by: {r['decided_by']}  (agent: {r['agent_status']}"
              f"{', ' + r['model'] if r['model'] else ''}{', %d ms' % r['latency_ms'] if r['latency_ms'] else ''})")
        if r["message"]:
            print(f"   message:    {r['message']}")
        print(f"   reason:     {r['reason']}")
        if r["agent_failure"]:
            print(f"   failure:    {r['agent_failure']}")
        for v in json.loads(r["violations"]) if r["violations"] else []:
            print(f"   violation:  {v}")
        print()


if __name__ == "__main__":
    main()
