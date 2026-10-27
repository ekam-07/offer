"""Tests for rules and the agent -> validator -> fallback pipeline, using a fake agent.

    python -m tests.test_pipeline
"""
import json
from datetime import datetime, timedelta

from src import agent, decide as decide_mod, offer_log
from src.rules import Context, validate
from src.segments import prepare

NOW = datetime(2026, 10, 16, 14, 0)  # a day with no store promotion live (R22)
with open("data/sample_customers.json", encoding="utf-8") as f:
    CUSTOMERS = {c["customer_id"]: c for c in json.load(f)}

ANANYA = CUSTOMERS["C003"]  # AT_RISK, Beauty, max 15%
META = {"model": "fake", "latency_ms": 1, "request_id": "test"}


def fake_agent(*answers):
    """Replace agent.propose with one that returns/raises the given answers in order."""
    queue = list(answers)

    def propose(c, options, ctx, rejected=None):
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return dict(answer), META
    agent.propose = propose


def test_rules():
    c = prepare(ANANYA)
    ctx = Context(now=NOW)
    # 10%: 15% of her ₹2,200 average order (₹330) is above AT_RISK's ₹250 cost cap (R4)
    ok = {"offer_id": "CATEGORY_DEAL", "value": 10, "message": "Hi Ananya, 10% off Beauty, orders above ₹499, valid 5 days."}
    assert validate(c, ok, ctx) == []
    too_big = dict(ok, offer_id="PERCENT_OFF", value=20, message="Hi Ananya, 20% off")
    assert any(v.startswith("R4") for v in validate(c, too_big, ctx))
    pushy = dict(ok, message="Hurry! Last chance for 15% off")
    assert any("R15" in v for v in validate(c, pushy, ctx))
    wrong_value = dict(ok, message="Hi Ananya, 15% off Beauty")
    assert any("does not state the real offer value" in v for v in validate(c, wrong_value, ctx))
    sensitive = dict(ok, message="At your age, 10% off Beauty is a must")
    assert any(v.startswith("R16") for v in validate(c, sensitive, ctx))
    unknown = {"offer_id": "FREE_IPHONE", "value": 1, "message": "x"}
    assert validate(c, unknown, ctx)[0].startswith("R17")
    mobiles = prepare(CUSTOMERS["C008"])  # Mobiles margin 12% -> max 2% off
    assert any(v.startswith("R5") for v in validate(
        mobiles, {"offer_id": "CATEGORY_DEAL", "value": 5, "message": "5% off"}, Context(now=NOW)))
    print("rules: ok")


def test_welcome_scope():
    from src import fallback
    from src.rules import feasible_offers
    # A new customer who only browsed phones (12% margin) still gets the welcome offer,
    # limited to categories that can afford 10% off.
    c = prepare(dict(CUSTOMERS["C005"], top_category="Mobiles"))
    ctx = Context(now=NOW)
    options, _ = feasible_offers(c, ctx)
    welcome = next(o for o in options if o["offer_id"] == "WELCOME")
    assert "Mobiles" not in welcome["applies_only_to_categories"]
    p = fallback.choose(c, options, {}, ctx)
    assert p["offer_id"] == "WELCOME" and "Fashion" in p["message"], p
    assert validate(c, p, ctx) == []
    base = {"offer_id": "WELCOME", "value": 10}
    assert any("does not apply" in v for v in validate(c, dict(base, message="Welcome! 10% off Mobiles and Fashion"), ctx))
    assert any("everything" in v for v in validate(c, dict(base, message="Welcome! 10% off everything, Fashion too"), ctx))
    assert any("must name" in v for v in validate(c, dict(base, message="Welcome! 10% off your first order"), ctx))
    print("welcome scope: ok ->", p["message"])


def test_invented_terms():
    # Real messages the AI wrote in earlier runs, each promising something the catalog never offers.
    ctx = Context(now=NOW)
    cart = prepare(CUSTOMERS["C006"])
    loyal = prepare(CUSTOMERS["C001"])
    vip = prepare(CUSTOMERS["C007"])
    bad = [
        (cart, "CART_REMINDER", "Hi Arjun, your headphones are in your cart. Your cart will be saved for the next 3 days."),
        (vip, "EARLY_ACCESS", "Hi Kavya, early access to our next sale, valid for 7 days once the sale opens."),
        (loyal, "POINTS_REMINDER", "Hi Priya, 100 points expire soon, use them with no minimum order needed. This reminder is valid for 7 days."),
        (prepare(ANANYA), "CATEGORY_DEAL", "Hi Ananya, 15% off Beauty above ₹499, valid for 10 days."),
        (prepare(ANANYA), "CATEGORY_DEAL", "Hi Ananya, 15% off Beauty above ₹299, valid 5 days."),
    ]
    for c, oid, msg in bad:
        value = 15 if oid == "CATEGORY_DEAL" else 0
        problems = validate(c, {"offer_id": oid, "value": value, "message": msg}, ctx)
        assert any(p.startswith("R15") for p in problems), (msg, problems)
    # The same offers written with only catalog facts pass.
    good = [
        (cart, "CART_REMINDER", "Hi Arjun, your Noise Cancelling Headphones (₹3499) are still in your cart."),
        (vip, "EARLY_ACCESS", "Hi Kavya, enjoy early access to our next sale. Valid for 7 days."),
        (loyal, "POINTS_REMINDER", "Hi Priya, 100 of your points expire within 30 days. Use them on your next order."),
    ]
    for c, oid, msg in good:
        assert validate(c, {"offer_id": oid, "value": 0, "message": msg}, ctx) == [], msg
    print("invented terms: ok")


def test_coupon_tiers():
    from src import rules
    from src.rules import coupon_tier, value_bounds
    product = {"focus_product_id": "P0001", "focus_product_name": "StrideMax Running Shoes",
               "focus_product_type": "Running Shoes", "focus_product_price": 1499.0,
               "focus_product_category": "Fashion", "focus_product_reason": "wishlist"}
    regular = prepare(dict(CUSTOMERS["C001"], **product))     # loyal, buys often
    irregular = prepare(dict(CUSTOMERS["C003"], **product))   # at risk
    new = prepare(dict(CUSTOMERS["C005"], **product))         # never ordered
    caps = {name: value_bounds(c, "PRODUCT_COUPON")[1] for name, c in
            (("regular", regular), ("irregular", irregular), ("new", new))}
    assert coupon_tier(regular)["name"] == "FREQUENT" and coupon_tier(new)["name"] == "FIRST_ORDER", caps
    # same product: regular buyers get less than irregular and new buyers (new is not the most generous tier)
    assert caps["regular"] < caps["irregular"] and caps["regular"] < caps["new"] <= caps["irregular"], caps

    ctx = Context(now=NOW)
    msg = "Hi, {v}% off the StrideMax Running Shoes in your wishlist. Valid for 7 days."
    assert validate(regular, {"offer_id": "PRODUCT_COUPON", "value": caps["regular"],
                              "message": msg.format(v=caps["regular"])}, ctx) == []
    too_big = validate(regular, {"offer_id": "PRODUCT_COUPON", "value": caps["new"], "message": msg.format(v=caps["new"])}, ctx)
    assert any(v.startswith("R19") for v in too_big), too_big
    # ₹ cap: 5% of a ₹15,000 phone (₹750) is above the REGULAR tier's ₹100 cap
    phone = prepare(dict(CUSTOMERS["C001"], **dict(product, focus_product_price=15000.0, focus_product_category="Fashion")))
    assert value_bounds(phone, "PRODUCT_COUPON") is None
    assert any("tier cap" in v for v in validate(phone, {"offer_id": "PRODUCT_COUPON", "value": 5}, ctx, check_text=False))
    no_name = validate(new, {"offer_id": "PRODUCT_COUPON", "value": 10, "message": "10% off everything! Valid for 7 days."}, ctx)
    assert any("must name the product" in v for v in no_name) and any("everything" in v for v in no_name), no_name

    # R20: a discount 10 days ago blocks a regular buyer (every 30 days) but not an irregular one (every 7 days)
    past = Context(now=NOW, history=[{"offer_id": "CATEGORY_DEAL", "offer_type": "percent",
                                      "created_at": (NOW - timedelta(days=10)).isoformat(), "valid_until": None}])
    assert any(v.startswith("R20") for v in validate(regular, {"offer_id": "PRODUCT_COUPON", "value": caps["regular"]}, past, check_text=False))
    assert not any(v.startswith("R20") for v in validate(irregular, {"offer_id": "PRODUCT_COUPON", "value": 5}, past, check_text=False))

    # Misordered tiers are refused at startup
    saved = [dict(t) for t in rules.TIERS]
    rules.TIERS[0]["max_percent"] = 50
    try:
        rules._check_tier_order()
        assert False, "misordered tiers were accepted"
    except ValueError as e:
        assert "R19" in str(e)
    finally:
        rules.TIERS[:] = saved
    print(f"coupon tiers: ok -> same product: regular {caps['regular']}%, irregular {caps['irregular']}%, new {caps['new']}%")


def test_agent_ok():
    fake_agent({"offer_id": "CATEGORY_DEAL", "value": 10,
                "message": "Hi Ananya, 10% off Beauty on orders above ₹499. Valid 5 days.",
                "reason": "Late vs usual gap; mid-size category deal."})
    r = decide_mod.decide(ANANYA, now=NOW)
    assert (r["decided_by"], r["agent_status"], r["flagged"]) == ("AGENT", "OK", 0), r
    print("agent ok: ok")


def test_agent_fixed_on_retry():
    fake_agent(
        {"offer_id": "PERCENT_OFF", "value": 20, "message": "Hurry, 20% off!", "reason": "big"},
        {"offer_id": "CATEGORY_DEAL", "value": 10, "message": "Hi Ananya, 10% off Beauty above ₹499. Valid for 5 days.", "reason": "fixed"},
    )
    r = decide_mod.decide(ANANYA, now=NOW)
    assert (r["decided_by"], r["agent_status"], r["flagged"]) == ("AGENT", "OK_AFTER_RETRY", 1), r
    assert any("R4" in v for v in r["violations"])
    print("agent fixed on retry: ok (flagged)")


def test_agent_rejected_twice():
    bad = {"offer_id": "PERCENT_OFF", "value": 20, "message": "20% off", "reason": "big"}
    fake_agent(bad, bad)
    r = decide_mod.decide(ANANYA, now=NOW)
    assert (r["decided_by"], r["agent_status"], r["flagged"]) == ("RULES", "REJECTED", 1), r
    assert r["agent_failure"].startswith("RULE_VIOLATION")
    print("agent rejected twice -> rules: ok (flagged)")


def test_agent_timeout():
    fake_agent(agent.AgentError("TIMEOUT", "no response within 30s"))
    r = decide_mod.decide(ANANYA, now=NOW)
    assert (r["decided_by"], r["agent_status"], r["flagged"]) == ("RULES", "FAILED", 1), r
    assert r["agent_failure"].startswith("TIMEOUT")
    print("agent timeout -> rules: ok (flagged)")


def test_frequency_cap():
    fake_agent(agent.AgentError("TIMEOUT"))
    decide_mod.decide(ANANYA, now=NOW)  # sends an offer
    fake_agent(agent.AgentError("TIMEOUT"))
    r = decide_mod.decide(ANANYA, now=NOW.replace(hour=16))  # 2h later
    assert r["offer_id"] == "NONE", r
    print("frequency cap (R8/R9): ok ->", r["reason"])


def test_parallel_batch_respects_budget():
    import time
    from src import fallback
    from src.config import RULES

    def greedy_slow(c, options, ctx, rejected=None):
        # Slow fake AI that always wants the most expensive allowed offer.
        time.sleep(0.3)
        o = max(options, key=lambda o: o.get("est_cost_inr_at_max") or 0)
        value = o["max_value"]
        return {"offer_id": o["offer_id"], "value": value,
                "message": fallback.render(c, o["offer_id"], value), "reason": "greedy"}, META
    agent.propose = greedy_slow

    with open("data/customers.json", encoding="utf-8") as f:
        batch = json.load(f)[:40]
    budget_before = RULES["budget"]["daily_inr"]
    RULES["budget"]["daily_inr"] = 3000  # tight, so parallel decisions compete for it
    try:
        start = time.monotonic()
        rows = decide_mod.decide_batch(batch, now=NOW, use_agent=True, skip_holdout=True, workers=8)
        elapsed = time.monotonic() - start
    finally:
        RULES["budget"]["daily_inr"] = budget_before
    spent = offer_log.spent_on(NOW)
    asked = sum(r["agent_status"] not in ("SKIPPED", "NOT_NEEDED") for r in rows)
    outdated = sum(r["agent_status"] == "OUTDATED" for r in rows)
    assert len(rows) == 40 and [r["customer_id"] for r in rows] == [c["customer_id"] for c in batch]
    assert spent <= 3000, spent
    assert elapsed < asked * 0.3 / 3, (elapsed, asked)  # well under sequential time
    print(f"parallel batch: ok -> {asked} AI calls in {elapsed:.1f}s (sequential ~{asked * 0.3:.0f}s), "
          f"spent ₹{spent:.0f} of ₹3000, {outdated} AI choices re-decided after budget ran out")


if __name__ == "__main__":
    offer_log.DB_PATH = offer_log.DATA_DIR / "test_offers.db"
    for test in [test_rules, test_welcome_scope, test_invented_terms, test_coupon_tiers, test_agent_ok, test_agent_fixed_on_retry, test_agent_rejected_twice,
                 test_agent_timeout, test_frequency_cap, test_parallel_batch_respects_budget]:
        offer_log.reset()
        test()
    offer_log.DB_PATH.unlink()
    print("\nall tests passed")
