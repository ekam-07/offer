"""Compare offer policies on simulated customer responses (Step 9).

    python evaluate.py                 # no offers vs 10% to everyone vs rules (+ AI if a key is set)
    python evaluate.py --runs 2000 --blanket-pct 15
    python evaluate.py --no-ai         # skip the AI policy even if a key is set (it costs API calls)

Writes data/eval_report.md as well as printing the results.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime

from src.config import DATA_DIR, default_customers_file
from src.rules import in_holdout
from src.simulate import (agent_available, default_now, holdout_experiment, policy_ai, policy_blanket,
                          policy_no_offers, policy_rules, prepare_population, simulate)

sys.stdout.reconfigure(encoding="utf-8")


def inr(x):
    return f"₹{x:,.0f}"


def holdout_verdict(est, half_width, true):
    lo, hi = est - half_width, est + half_width
    if lo <= 0 <= hi:
        return ("The interval includes zero: one week with this many customers can't prove the offers work. "
                "Run longer or with more customers.")
    note = "and it contains the true value." if lo <= true <= hi else \
        f"but the estimate is off from the true value by {abs(est - true):.1%}: small groups are noisy."
    return f"The interval excludes zero, so the effect is detectable, {note}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", default=str(default_customers_file()))
    ap.add_argument("--runs", type=int, default=1000, help="simulated weeks")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--blanket-pct", type=int, default=10)
    ap.add_argument("--now", help='decision time, e.g. "2026-10-22 14:00"')
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args()

    with open(args.customers, encoding="utf-8") as f:
        customers = json.load(f)
    now = datetime.fromisoformat(args.now) if args.now else default_now()
    pop = prepare_population(customers, args.seed)

    policies = {
        "No offers": policy_no_offers(customers, now),
        f"{args.blanket_pct}% to everyone": policy_blanket(customers, now, args.blanket_pct),
        "Rules": policy_rules(customers, now),
    }
    ai_note = None
    if args.no_ai:
        ai_note = "AI policy skipped (--no-ai)."
    elif not agent_available():
        ai_note = "AI policy skipped: no ANTHROPIC_API_KEY in .env."
    else:
        print(f"Asking the AI agent for {len(customers)} customers (one API call each, more on retries)...")
        decisions, stats = policy_ai(customers, now)
        policies["Rules + AI"] = decisions
        ai_note = (f"AI policy: {stats['decided_by_agent']} decided by the agent, {stats['agent_failed']} fell back "
                   f"to rules, {stats['flagged']} flagged.")

    results = {name: simulate(pop, d, args.runs, args.seed) for name, d in policies.items()}

    lines = [f"# Offer policy evaluation", "",
             f"{len(pop)} customers ({args.customers.split('/')[-1].split(chr(92))[-1]}), "
             f"{args.runs} simulated weeks, decisions at {now:%Y-%m-%d %H:%M}. "
             "All policies face the same simulated customers and random draws.", ""]
    if ai_note:
        lines += [ai_note, ""]

    # ---- Main table
    cols = ["Messaged", "Purchases", "Extra purchases", "Discount cost", "Wasted on buy-anyway",
            "Net margin", "Extra net margin", "Cost / extra purchase", "Opt-outs"]
    lines += ["## Results per week (average)", "",
              "| Policy | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
    for name, r in results.items():
        extra = r["incremental_purchases"]
        per_extra = inr(r["discount_cost"] / extra) if extra > 0.05 else "-"
        lines.append(
            f"| {name} | {r['messaged']} | {r['purchases']:.1f} | {extra:+.1f} ± {r['incremental_sd']:.1f} | "
            f"{inr(r['discount_cost'])} | {inr(r['wasted_cost'])} | {inr(r['net_margin'])} | "
            f"{r['incremental_net_margin']:+,.0f} ± {r['incremental_net_margin_sd']:,.0f} | {per_extra} | {r['optouts']:.1f} |")
    lines += ["",
              "- **Extra purchases / extra net margin**: compared with sending nothing (± = spread across simulated weeks).",
              "- **Wasted on buy-anyway**: discount paid to customers who would have bought without the offer.", ""]

    # ---- Per segment
    segments = defaultdict(list)
    for i, c in enumerate(pop):
        segments[c["segment"]].append(i)
    names = [n for n in results if n != "No offers"]
    by_policy = {}
    lines += ["## Extra net margin per customer, by segment (₹ per week)", "",
              "| Segment | Customers | " + " | ".join(names) + " |", "|---|---:|" + "---:|" * len(names)]
    for seg, idx in sorted(segments.items(), key=lambda kv: -len(kv[1])):
        vals = [sum(results[n]["per_customer"]["net_gain"][i] for i in idx) / len(idx) for n in names]
        lines.append(f"| {seg} | {len(idx)} | " + " | ".join(f"{v:+,.0f}" for v in vals) + " |")
        by_policy[seg] = dict(zip(names, vals))
    lines.append("")
    blanket = names[0]
    for policy in names[1:]:
        losing = [s for s, v in by_policy.items() if v[blanket] > v[policy] + 1]
        if losing:
            lines.append(f"- **{policy}** earns less than the blanket discount for: {', '.join(losing)}. "
                         "Those segments' caps or offer ladders may be too cautious.")
    lines.append("")

    # ---- Holdout check: what would a real test measure?
    holdout_ids = {c["customer_id"] for c in customers if in_holdout(c["customer_id"])}
    est, hw, true, n_t, n_c = holdout_experiment(pop, policies["Rules"], holdout_ids, args.seed)
    seg_controls = defaultdict(lambda: [0, 0])
    for c in pop:
        seg_controls[c["segment"]][0 if c["customer_id"] in holdout_ids else 1] += 1
    small = [f"{s} ({n})" for s, (n, _) in sorted(seg_controls.items()) if n < 10]
    lines += ["## Control group per segment", "",
              "| Segment | Control | Treated |", "|---|---:|---:|"]
    lines += [f"| {s} | {n} | {t} |" for s, (n, t) in sorted(seg_controls.items(), key=lambda kv: -sum(kv[1]))]
    lines += ["", f"- Segments with fewer than 10 controls can't be measured on their own: {', '.join(small)}." if small else "", ""]

    lines += ["## How you would measure it for real (holdout test)", "",
              f"In one real week you can't see what customers would have done without an offer, so you compare the "
              f"{n_t} customers who got the rules policy with the {n_c} in the control group (holdout).", "",
              f"- Measured uplift in purchase rate: **{est:+.1%} ± {hw:.1%}** (95% interval)",
              f"- True uplift (known only in simulation): **{true:+.1%}**",
              f"- {holdout_verdict(est, hw, true)}",
              ""]

    report = "\n".join(lines)
    print(report)
    out = DATA_DIR / "eval_report.md"
    out.write_text(report, encoding="utf-8")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
