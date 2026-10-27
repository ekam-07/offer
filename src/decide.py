"""Decision pipeline for one customer.

  eligibility (R1 consent incl. /stop, R18 holdout, R26 sleeping dog). R11 quiet hours only
  block SENDING (delivery.py); a decision made at night is planned for the morning window
      -> rule pre-filter: offers + value ranges this customer may get
      -> AI agent proposes one offer
      -> rules.validate()   --fail--> retry agent once with the violations
      -> still failing / agent error --> rule-based fallback
      -> R27: occasionally replace with a random allowed offer, to learn what works
      -> (under a lock + one DB transaction) re-check the budget, write to the offer log
         with the rules version, human-review reasons and a planned send time
"""
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from . import agent, consent, fallback, offer_log
from .config import OFFERS, RULES, RULES_VERSION
from .rules import (Context, budget_allowance, est_cost, expected_profit, feasible_offers, in_holdout, in_quiet_hours,
                    valid_until, validate)
from .segments import prepare

# Serialises the final check + log write, so parallel decisions can't overspend the budget.
_COMMIT_LOCK = threading.Lock()


def _clean(proposal):
    p = dict(proposal)
    try:
        p["value"] = int(p.get("value") or 0)
    except (TypeError, ValueError):
        p["value"] = 0
    if p.get("offer_id") == "NONE":
        p["value"], p["message"] = 0, ""
    return p


def _run_agent(c, options, ctx):
    """Returns (proposal or None, agent_status, failure, violations, meta)."""
    meta = {}
    try:
        first, meta = agent.propose(c, options, ctx)
        first = _clean(first)
        problems = validate(c, first, ctx)
        if not problems:
            return first, "OK", None, [], meta

        second, meta = agent.propose(c, options, ctx, rejected={"proposal": first, "violations": problems})
        second = _clean(second)
        problems_2 = validate(c, second, ctx)
        if not problems_2:
            return second, "OK_AFTER_RETRY", None, ["attempt 1: " + p for p in problems], meta
        all_problems = ["attempt 1: " + p for p in problems] + ["attempt 2: " + p for p in problems_2]
        return None, "REJECTED", "RULE_VIOLATION: agent broke the rules twice", all_problems, meta
    except agent.AgentError as e:
        return None, "FAILED", str(e), [], meta


def priority(customer):
    """Value at stake, used to order a batch so the daily budget (R13) goes to the
    customers where an offer matters most, instead of whoever happens to come first."""
    c = prepare(customer)
    if c["segment"] == "CART_ABANDONER":
        return c["abandoned_cart_value"]
    if c["segment"] in ("NEW", "NEVER_BOUGHT"):
        return 1000  # unknown value, mid priority
    return (c["aov"] or 500) * max(c["churn_risk"], 0.2)


def decide_batch(customers, now=None, use_agent=True, skip_holdout=False, workers=None, explore=True):
    """Decide for many customers, highest priority first. Returns rows in the input order.

    With the AI on, up to `workers` customers are decided at once (AGENT_WORKERS in .env,
    default 8). Rules-only runs are fast, so they stay sequential."""
    ordered = sorted(customers, key=priority, reverse=True)
    workers = workers or (agent.WORKERS if use_agent else 1)
    args = dict(now=now, use_agent=use_agent, skip_holdout=skip_holdout, explore=explore)
    if workers <= 1:
        rows = {c["customer_id"]: decide(c, **args) for c in ordered}
    else:
        # Submitted in priority order, so the most valuable customers reach the budget first.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {c["customer_id"]: pool.submit(decide, c, **args) for c in ordered}
            rows = {cid: f.result() for cid, f in futures.items()}
    return [rows[c["customer_id"]] for c in customers]


def send_time(c, now):
    """Plan the send for the customer's usual active hour inside the 08:00-22:00 window
    (today if still ahead, else tomorrow); without history, send now."""
    quiet_start, quiet_end = RULES["frequency"]["quiet_hours"]
    hour = c.get("active_hour")
    if hour is None:
        if not in_quiet_hours(now):
            return now
        hour = quiet_end  # night decision, no usual hour: first thing in the morning window
    hour = min(max(hour, quiet_end), quiet_start - 1)
    at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return at if at >= now else at + timedelta(days=1)


def _explore(c, options, now):
    """R27: with a small chance, swap in a random allowed offer so we can learn what works.
    Deterministic per customer and day, so re-running a decision gives the same answer."""
    cfg = RULES["exploration"]
    choices = [o for o in options if o["offer_id"] != "NONE"]
    rng = random.Random(f"{c['customer_id']}-{now:%Y-%m-%d}")
    if not cfg["enabled"] or not choices or rng.random() >= cfg["rate"]:
        return None, None
    o = rng.choice(choices)
    value = rng.randint(o["min_value"], o["max_value"]) if o["unit"] != "none" else 0
    if o["unit"] == "inr":
        value = max(o["min_value"], value // 10 * 10)
    proposal = {"offer_id": o["offer_id"], "value": value, "message": fallback.render(c, o["offer_id"], value),
                "reason": f"R27 exploration: random allowed offer ({o['offer_id']}) to learn what works"}
    return proposal, cfg["rate"] / len(choices)


def _review_reasons(row, agent_status, spent_after):
    r = RULES["review"]
    reasons = []
    if agent_status in ("FAILED", "REJECTED"):
        reasons.append("AI failed or broke the rules twice")
    if agent_status == "OK_AFTER_RETRY":
        reasons.append("AI broke a rule on its first attempt")
    if (row.get("est_cost_inr") or 0) > r["high_value_inr"]:
        reasons.append(f"high-value offer (₹{row['est_cost_inr']:.0f} > ₹{r['high_value_inr']})")
    if row.get("status") == "READY" and spent_after >= RULES["budget"]["daily_inr"] * r["budget_near_pct"] / 100:
        reasons.append(f"daily budget {r['budget_near_pct']}%+ used")
    return reasons


def decide(customer, now=None, use_agent=True, skip_holdout=False, explore=True):
    """skip_holdout / explore=False are only for offline policy evaluation, where every policy
    is compared on the same customers; live decisions keep the control group and exploration."""
    now = now or datetime.now()
    # Bad reactions to past offers (feedback buttons, /stop) feed the sleeping-dog check (R26).
    c = prepare(dict(customer, negative_offer_reactions_90d=consent.negative_reactions(customer["customer_id"], now)))
    row = {
        "created_at": now.isoformat(timespec="seconds"),
        "customer_id": c["customer_id"],
        "segment": c["segment"],
        "uplift_group": c.get("uplift_group"),
        "decided_by": "SYSTEM",
        "agent_status": "SKIPPED",
        "flagged": 0,
        "rules_version": RULES_VERSION,
    }

    if not consent.allows_offers(c):
        row.update(status="NOT_ELIGIBLE", reason="R1: customer has not opted in, or sent /stop")
    elif not skip_holdout and in_holdout(c["customer_id"]):
        row.update(status="HOLDOUT", reason="R18: customer is in the control group, no offers (used to measure uplift)")
    elif c.get("uplift_group") == "sleeping_dog":
        row.update(status="NO_OFFER", offer_id="NONE", reason="R26: offers backfire for this customer (sleeping dog)")
    if "status" in row:
        row["id"] = offer_log.write(row)
        return row

    ctx = Context.load(c["customer_id"], now)
    options, blocked = feasible_offers(c, ctx)

    proposal, agent_status, failure, violations, meta = None, "SKIPPED", None, [], {}
    nothing_to_choose = all(o["offer_id"] == "NONE" for o in options)
    if use_agent and nothing_to_choose:
        agent_status = "NOT_NEEDED"  # every offer is blocked: no API call, the rules explain why
    elif use_agent:
        # The slow API call runs outside the lock, so many customers can be decided at once.
        proposal, agent_status, failure, violations, meta = _run_agent(c, options, ctx)

    explored, propensity = (_explore(c, options, now) if explore else (None, None))

    for _attempt in range(3):
        with _COMMIT_LOCK:
            # Re-check against the state *now*: other decisions may have used budget (R13)
            # since this customer's options were computed.
            fresh = Context.load(c["customer_id"], now)
            superseded = []
            chosen, decided_by = proposal, "AGENT"
            if explored is not None and not validate(c, explored, fresh):
                chosen, decided_by = explored, "EXPLORE"
            if chosen is not None and decided_by == "AGENT":
                superseded = validate(c, chosen, fresh)
                if superseded:
                    chosen, agent_status = None, "OUTDATED"
                    violations = violations + ["after other decisions: " + v for v in superseded]

            if chosen is not None:
                reason = ("AI: " + chosen.get("reason", "").strip()) if decided_by == "AGENT" else chosen["reason"]
            else:
                decided_by = "RULES"
                options, blocked = feasible_offers(c, fresh)
                chosen = fallback.choose(c, options, blocked, fresh)
                reason = chosen["reason"]
                if failure:
                    reason = f"Agent failed ({failure.split(':')[0]}), used rules -> {reason}"
                elif agent_status == "NOT_NEEDED":
                    reason = f"AI not asked, no offer is allowed right now -> {reason}"
                elif superseded:
                    reason = f"AI's choice no longer fit after other decisions ({superseded[0]}), used rules -> {reason}"
            try:
                return _write(row, c, chosen, now, reason, decided_by, agent_status, failure, violations, meta,
                              fresh, propensity if decided_by == "EXPLORE" else None)
            except offer_log.BudgetExceeded:
                # Another process spent the budget between our check and the write: decide again.
                proposal, explored = None, None
    raise RuntimeError("could not commit a decision within budget after 3 attempts")


def _write(row, c, proposal, now, reason, decided_by, agent_status, failure, violations, meta, ctx, propensity):
    offer_id = proposal["offer_id"]
    cost = est_cost(c, offer_id, proposal["value"])
    ep = expected_profit(c, offer_id, proposal["value"]) if offer_id != "NONE" else {}
    row = dict(row)
    row.update(
        status="NO_OFFER" if offer_id == "NONE" else "READY",
        offer_id=offer_id,
        offer_type=OFFERS[offer_id]["type"],
        value=proposal["value"],
        est_cost_inr=cost,
        valid_until=valid_until(offer_id, now) if offer_id != "NONE" else None,
        message=proposal.get("message", ""),
        reason=reason,
        decided_by=decided_by,
        agent_status=agent_status,
        agent_failure=failure,
        violations=violations,
        model=meta.get("model"),
        latency_ms=meta.get("latency_ms"),
        request_id=meta.get("request_id"),
        explored=1 if decided_by == "EXPLORE" else 0,
        propensity=propensity,
        send_at=send_time(c, now).isoformat(timespec="minutes") if offer_id != "NONE" else None,
        ep_inr=ep.get("ep_inr"),
        expected_cost_inr=ep.get("expected_cost_inr"),
    )
    reasons = _review_reasons(row, agent_status, ctx.spent_today + (cost if offer_id != "NONE" else 0))
    row["review_reasons"] = reasons
    row["flagged"] = 1 if reasons else 0
    row["id"] = offer_log.write(row, budget_limit=budget_allowance(now) if offer_id != "NONE" else None)
    return row
