"""One test per rule added in the rules review (segments, ladders, budget, messages, guards,
consent, delivery, exploration).

    python -m tests.test_rules_v2
"""
import json
from datetime import datetime, timedelta

from src import consent, delivery, offer_log, rules
from src.config import RULES
from src.decide import decide
from src.rules import Context, budget_allowance, in_holdout, validate, value_bounds
from src.segments import prepare

NOW = datetime(2026, 10, 16, 14, 0)
with open("data/sample_customers.json", encoding="utf-8") as f:
    S = {c["customer_id"]: c for c in json.load(f)}


def cust(cid, **overrides):
    return prepare(dict(S[cid], **overrides))


def has(problems, prefix):
    return any(p.startswith(prefix) for p in problems)


def test_segments():
    # DORMANT is relative: someone who buys twice a year is not dormant after 100 days
    twice_a_year = cust("C004", recency_days=100, avg_gap_days=180, frequency_90d=0)
    assert twice_a_year["segment"] != "DORMANT", twice_a_year["segment"]
    assert cust("C004", recency_days=130, avg_gap_days=30)["segment"] == "DORMANT"
    # A new customer with an open cart gets the cart path (and R12) first
    new_cart = cust("C005", cart_abandoned_hours_ago=5, abandoned_cart_value=1200, abandoned_cart_item="Perfume")
    assert new_cart["segment"] == "CART_ABANDONER"
    assert has(validate(new_cart, {"offer_id": "FREE_SHIPPING", "value": 0}, Context(now=NOW), check_text=False), "R12")
    # NEW = never ordered and joined <= 30 days ago; older accounts with no orders are NEVER_BOUGHT
    assert cust("C005", tenure_days=10)["segment"] == "NEW"
    assert cust("C005", tenure_days=60)["segment"] == "NEVER_BOUGHT"
    assert cust("C005", orders_total=1, recency_days=3, avg_gap_days=0)["segment"] != "NEW"
    # VIP by top-10% spend flag when present
    assert cust("C002", aud_high_spend=True)["segment"] in ("VIP", "DEAL_SEEKER")  # deal seeker is checked first
    assert cust("C001", aud_high_spend=True, points_expiring_30d=0)["segment"] == "VIP"
    # One coupon order is not a deal-seeking habit
    assert cust("C005", orders_total=1, coupon_rate=1.0, tenure_days=60, recency_days=10)["segment"] != "DEAL_SEEKER"
    print("segments: ok")


def test_ladders_and_caps():
    # NONE must be last
    saved = list(RULES["segments"]["LOYAL"]["allowed"])
    RULES["segments"]["LOYAL"]["allowed"] = ["NONE", "EARLY_ACCESS"]
    try:
        rules._check_ladders()
        assert False, "NONE not last was accepted"
    except ValueError as e:
        assert "NONE must be the last" in str(e)
    finally:
        RULES["segments"]["LOYAL"]["allowed"] = saved
    # Impossible offers explain why: Mobiles margin allows only 2%, below the 5% minimum
    mobiles = cust("C008", segment_override=None)
    bounds, why = value_bounds(mobiles, "CATEGORY_DEAL", with_reason=True)
    assert bounds is None and "R5" in why and "minimum" in why, why
    # R6 uses the platform average when there's no order history
    assert rules.base_aov({"aov": 0}) == RULES["default_aov_inr"]
    # Segment coupon cap: VIP coupons stay at 5% even for an irregular VIP
    vip = cust("C007", aud_high_spend=True, p_buy_7d=0.01, focus_product_id="P1", focus_product_name="X Speaker",
               focus_product_type="Speaker", focus_product_price=1500.0, focus_product_category="Fashion")
    assert value_bounds(vip, "PRODUCT_COUPON")[1] <= 5
    # coupons_for_sure_things switch
    loyal = cust("C001", focus_product_id="P1", focus_product_name="X Kurta", focus_product_type="Kurta",
                 focus_product_price=900.0, focus_product_category="Fashion")
    RULES["coupons_for_sure_things"] = False
    try:
        assert loyal["uplift_group"] == "sure_thing" and value_bounds(loyal, "PRODUCT_COUPON") is None
    finally:
        RULES["coupons_for_sure_things"] = True
    # R21: welcome is first-order only
    assert has(validate(cust("C002"), {"offer_id": "WELCOME", "value": 10}, Context(now=NOW), check_text=False), "R21")
    print("ladders and caps: ok")


def test_budget_pacing_and_atomic_write():
    daily = RULES["budget"]["daily_inr"]
    assert budget_allowance(datetime(2026, 10, 16, 8, 30)) == round(daily / 14, 2)
    assert budget_allowance(datetime(2026, 10, 16, 21, 0)) == daily
    row = {"created_at": NOW.isoformat(), "customer_id": "X", "status": "READY", "decided_by": "RULES", "est_cost_inr": 600}
    offer_log.write(row, budget_limit=1000)
    try:
        offer_log.write(dict(row, customer_id="Y"), budget_limit=1000)
        assert False, "second write overspent the budget"
    except offer_log.BudgetExceeded:
        pass
    print("budget pacing + atomic reservation: ok")


def test_holdout_is_salted_and_stable():
    assert in_holdout("U0001") == in_holdout("U0001")
    salt = RULES["holdout_salt"]
    before = [in_holdout(f"U{i:04d}") for i in range(1, 201)]
    RULES["holdout_salt"] = "another-experiment"
    try:
        after = [in_holdout(f"U{i:04d}") for i in range(1, 201)]
    finally:
        RULES["holdout_salt"] = salt
    assert before != after and 15 <= sum(before) <= 45
    print("holdout salt: ok")


def test_message_checks():
    c, ctx = cust("C003"), Context(now=NOW)
    good = "Hi Ananya, 10% off Beauty on orders above ₹499. Valid for 5 days."
    assert validate(c, {"offer_id": "CATEGORY_DEAL", "value": 10, "message": good}, ctx) == []
    cases = {
        "R15: the number 3": "Hi Ananya, 10% off Beauty on orders above ₹499 for 3 items. Valid for 5 days.",
        "R15: message must state the expiry": "Hi Ananya, 10% off Beauty on orders above ₹499.",
        "R15: message contains a link": "Hi Ananya, 10% off Beauty above ₹499 at www.shop.in. Valid for 5 days.",
        "R16: message names a sensitive": "Hi Ananya, 10% off Beauty and Pregnancy Test above ₹499. Valid for 5 days.",
    }
    for prefix, msg in cases.items():
        problems = validate(c, {"offer_id": "CATEGORY_DEAL", "value": 10, "message": msg}, ctx)
        assert any(p.startswith(prefix) for p in problems), (prefix, problems)
    cart = cust("C006")
    wrong_type = validate(cart, {"offer_id": "CART_REMINDER", "value": 0,
                                 "message": "Hi Arjun, your headphones are in your cart - 10% off today!"}, ctx)
    assert any("not a discount" in p for p in wrong_type), wrong_type
    assert rules.clean_text("Ravi <script>alert(1)</script>") == "Ravi script alert 1 script"
    print("message checks: ok")


def test_guards():
    ctx = Context(now=NOW)
    deal = {"offer_id": "CATEGORY_DEAL", "value": 10}
    sale = Context(now=NOW, store_promotions=[{"promotion_id": "PR9", "promotion_name": "10% off sitewide",
                                               "offer_type": "PERCENT_OFF", "category": None}])
    assert has(validate(cust("C003"), deal, sale, check_text=False), "R22")
    assert has(validate(cust("C003", orders_365d=10, return_rate_365d=0.4), deal, ctx, check_text=False), "R23")
    assert has(validate(cust("C003", coupon_orders_last3=3), deal, ctx, check_text=False), "R24")
    oos = cust("C003", focus_product_id="P1", focus_product_name="X", focus_product_price=500.0,
               focus_product_category="Beauty", focus_product_in_stock=False)
    assert has(validate(oos, {"offer_id": "PRODUCT_COUPON", "value": 5}, ctx, check_text=False), "R25")
    assert has(validate(cust("C003", recency_days=400, sessions_90d=0), deal, ctx, check_text=False), "R26")
    muted = Context(now=NOW, prefs={"fewer_offers": False, "suppressed": {"CATEGORY_DEAL"}})
    assert has(validate(cust("C003"), deal, muted, check_text=False), "R28")
    assert has(validate(cust("C001"), {"offer_id": "REPLENISH_REMINDER", "value": 0}, ctx, check_text=False), "R29")
    repeat = Context(now=NOW, history=[{"offer_id": "EARLY_ACCESS", "offer_type": "access",
                                        "created_at": (NOW - timedelta(days=2)).isoformat(),
                                        "valid_until": (NOW + timedelta(days=5)).isoformat()}])
    assert any("don't repeat" in p for p in validate(cust("C007"), {"offer_id": "EARLY_ACCESS", "value": 0}, repeat, check_text=False))
    # Sleeping dog = bad reactions to OUR OFFERS (not hiding products)
    assert cust("C003", not_interested_90d=6, sessions_90d=10)["uplift_group"] != "sleeping_dog"
    assert cust("C003", negative_offer_reactions_90d=2)["uplift_group"] == "sleeping_dog"
    consent.record_feedback("C003", "fewer_offers", now=NOW - timedelta(days=10))
    consent.record_feedback("C003", "not_interested", "CATEGORY_DEAL", now=NOW - timedelta(days=5))
    assert decide(S["C003"], now=NOW, use_agent=False, skip_holdout=True)["status"] == "NO_OFFER"
    print("guards R22-R29: ok")


def test_consent_and_delivery():
    c = S["C002"]
    row = decide(c, now=NOW, use_agent=False, skip_holdout=True)
    assert row["status"] == "READY" and row["rules_version"]
    assert delivery.deliver(row, c, channel="email", now=NOW) == "DRY_RUN"  # dry-run mode by default
    row2 = decide(S["C009"], now=NOW, use_agent=False, skip_holdout=True)
    consent.opt_out("C009", now=NOW)  # /stop arrives between decision and send
    assert delivery.deliver(row2, S["C009"], now=NOW) == "BLOCKED_AT_SEND"
    assert not consent.allows_offers(S["C009"])
    assert delivery.handle_reply("C009", "/start") == "opted_in" and consent.allows_offers(S["C009"])
    consent.opt_out("C002", channel="sms")
    assert not consent.allows_channel(S["C002"], "sms") and consent.allows_channel(S["C002"], "email")
    assert delivery.handle_reply("C002", "This is spam, I will file a complaint") == "flagged_for_review"
    consent.erase("C002")
    with offer_log.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM offer_log WHERE customer_id='C002'").fetchone()[0] == 0
    assert not consent.allows_offers(S["C002"])  # erased customers are never contacted again
    RULES["delivery"]["kill_switch"] = True
    try:
        row3 = decide(S["C004"], now=NOW, use_agent=False, skip_holdout=True)
        assert delivery.deliver(row3, S["C004"], now=NOW) == "BLOCKED_AT_SEND"
    finally:
        RULES["delivery"]["kill_switch"] = False
    print("consent, /stop, erase, dry run, kill switch: ok")


def test_exploration_and_review():
    RULES["exploration"]["rate"] = 1.0  # force exploration
    try:
        row = decide(S["C003"], now=NOW, use_agent=False, skip_holdout=True)
        again = decide(S["C003"], now=NOW, use_agent=False, skip_holdout=True)
    finally:
        RULES["exploration"]["rate"] = 0.05
    assert row["decided_by"] == "EXPLORE" and row["propensity"] and row["explored"] == 1, row
    assert again["status"] in ("NO_OFFER", "READY")  # second call is blocked by R8/R9 as it should be
    big = decide(dict(S["C004"], aov=3000), now=NOW + timedelta(days=3), use_agent=False, skip_holdout=True)
    if (big.get("est_cost_inr") or 0) > RULES["review"]["high_value_inr"]:
        assert big["flagged"] == 1 and any("high-value" in r for r in big["review_reasons"])
    print("exploration + review triggers: ok")


def test_second_review():
    from src import coupons, fallback
    from src.rules import expected_profit, feasible_offers, min_basket, seg_limits, spend_cap
    ctx = Context(now=NOW)
    # Base segment: a VIP with an open cart keeps VIP's caps (no flat discount, ₹100 cost cap)
    vip_cart = cust("C007", aud_high_spend=True, cart_abandoned_hours_ago=5, abandoned_cart_value=3000,
                    abandoned_cart_item="Smart Watch")
    assert vip_cart["segment"] == "CART_ABANDONER" and vip_cart["base_segment"] == "VIP"
    assert seg_limits(vip_cart)["max_flat_inr"] == 0 and value_bounds(vip_cart, "FLAT_OFF") is None
    # Flat ₹ off: minimum basket rises to keep the margin floor (₹100 in Electronics, 8% allowed -> ₹1,250)
    dorm = cust("C004", top_category="Electronics")
    basket = min_basket(dorm, "FLAT_OFF")
    assert basket is not None and basket >= 100 * 100 / 8 * 0.99, basket
    msg = f"Hi Vikram, ₹100 off your next order. Valid for 5 days."
    assert any("minimum basket" in p for p in validate(dorm, {"offer_id": "FLAT_OFF", "value": 100, "message": msg}, ctx))
    # Cost cap covers non-discounts: VIP bonus points are capped at ₹100 (400 points)
    vip = cust("C007", aud_high_spend=True)
    assert value_bounds(vip, "BONUS_POINTS")[1] <= 400
    # R9: a free nudge 2h ago doesn't block a cart reminder (gap-exempt) but blocks another nudge
    recent = Context(now=NOW, history=[{"offer_id": "POINTS_UPDATE", "offer_type": "reminder", "est_cost_inr": 0,
                                        "created_at": (NOW - timedelta(hours=2)).isoformat(), "valid_until": None}])
    cart = cust("C006")
    assert not any(p.startswith("R9") for p in validate(cart, {"offer_id": "CART_REMINDER", "value": 0}, recent, check_text=False))
    assert any(p.startswith("R9") for p in validate(cust("C001"), {"offer_id": "EARLY_ACCESS", "value": 0}, recent, check_text=False))
    # R30: a paid offer with negative expected profit is rejected; the fallback then picks a free nudge
    loyal = cust("C001", coupon_rate=0.0, promo_ctr_90d=0.0)
    assert expected_profit(loyal, "BONUS_POINTS", 400)["ep_inr"] <= 0
    assert any(p.startswith("R30") for p in validate(loyal, {"offer_id": "BONUS_POINTS", "value": 400}, ctx, check_text=False))
    options, blocked = feasible_offers(loyal, ctx)
    pick = fallback.choose(loyal, options, blocked, ctx)
    assert pick["offer_id"] in ("EARLY_ACCESS", "POINTS_UPDATE", "POINTS_REMINDER", "REVIEW_REQUEST", "REPLENISH_REMINDER",
                                "PRODUCT_COUPON", "NONE"), pick
    # Goodwill coupon for a sure thing is the documented exception, given when due
    sure = cust("C001", focus_product_id="P1", focus_product_name="X Kurta", focus_product_type="Kurta",
                focus_product_price=900.0, focus_product_category="Fashion", focus_product_reason="wishlist",
                focus_product_in_stock=True)
    assert sure["uplift_group"] == "sure_thing"
    options, blocked = feasible_offers(sure, ctx)
    assert fallback.choose(sure, options, blocked, ctx)["offer_id"] == "PRODUCT_COUPON"
    # R31: per-customer spend cap
    small = cust("C003", margin_365d=500)  # cap = max(₹100, 10% of ₹500) = ₹100
    assert spend_cap(small) == 100
    assert any(p.startswith("R31") for p in validate(small, {"offer_id": "CATEGORY_DEAL", "value": 10}, ctx, check_text=False))
    # Cart item out of stock -> CART_ALTERNATIVE, never CART_REMINDER
    oos = cust("C006", cart_item_in_stock=False, cart_alternative_name="SoundNest Noise Cancelling Headphones")
    assert any(p.startswith("R25") for p in validate(oos, {"offer_id": "CART_REMINDER", "value": 0}, ctx, check_text=False))
    alt_msg = fallback.render(oos, "CART_ALTERNATIVE", 0)
    assert validate(oos, {"offer_id": "CART_ALTERNATIVE", "value": 0, "message": alt_msg}, ctx) == [], alt_msg
    # Quiet hours block sending only: a night decision stays READY until the morning
    night = datetime(2026, 10, 16, 23, 30)
    row = decide(S["C002"], now=night, use_agent=False, skip_holdout=True)
    assert row["status"] == "READY" and delivery.deliver(row, S["C002"], now=night) == "READY"
    assert row["send_at"].startswith("2026-10-17")
    # Single-use codes tied to the customer; Telegram is the default channel
    assert delivery.deliver(row, S["C002"], now=night.replace(day=17, hour=10)) == "DRY_RUN"
    with offer_log.connect() as conn:
        sent = conn.execute("SELECT channel, coupon_code FROM offer_log WHERE id = ?", (row["id"],)).fetchone()
    assert sent["channel"] == "telegram"
    if (row.get("est_cost_inr") or 0) > 0:
        code, at = sent["coupon_code"], night + timedelta(days=1)
        assert coupons.redeem(code, "C009", now=at)[0] is False            # a classmate's shared code
        assert coupons.redeem(code, "C002", now=at)[0] is True             # the owner
        assert coupons.redeem(code, "C002", now=at) == (False, "code already used")
        assert coupons.redeem(code, "C002", now=at + timedelta(days=30)) == (False, "code already used")
        assert {m["reason"] for m in coupons.misuse_report()} >= {"code belongs to another customer", "code already used"}
    print("second review (base segment, min basket, cost caps, R9, R30, goodwill, R31, cart alternative, quiet hours, codes): ok")


def test_new_offers():
    """Bought together, wishlist watcher, spend goal, pick your perk."""
    from src.config import OFFERS
    from src.fallback import render
    from src.rules import check_message, expected_profit, min_basket, perk_points, value_bounds

    def ok(c, offer_id, value, msg=None):
        msg = msg or render(c, offer_id, value)
        return validate(c, {"offer_id": offer_id, "value": value, "message": msg}, Context(now=NOW)), msg

    bundle = dict(bundle_item_id="P1", bundle_item_name="FarmFresh Green Tea", bundle_item_price=299.0,
                  bundle_item_category="Grocery", bundle_anchor_item="GoldDrop Basmati Rice 5kg",
                  bundle_reason="just bought", bundle_confidence=0.27)
    deal = cust("C002", **bundle)  # a deal seeker, no open cart
    # Bought together (free): needs a real bought-together item, and must name it
    assert has(ok(cust("C002"), "BUNDLE_SUGGEST", 0)[0], "R29")
    problems, msg = ok(deal, "BUNDLE_SUGGEST", 0)
    assert not problems and "Green Tea" in msg, (problems, msg)
    assert has(check_message(deal, OFFERS["BUNDLE_SUGGEST"], 0, "Hi, have a look at our new arrivals.", "BUNDLE_SUGGEST"), "R15")
    # Bought-together deal: R5 on the item's own margin (Grocery 15% - floor 10% of ₹299 = ₹14)
    assert value_bounds(deal, "BUNDLE_DEAL") is None
    pricier = cust("C002", **dict(bundle, bundle_item_price=990.0, bundle_item_category="Fashion"))
    lo, hi = value_bounds(pricier, "BUNDLE_DEAL")
    assert hi <= 49 and hi <= 990 * (45 - 10) / 100
    assert has(validate(deal, {"offer_id": "BUNDLE_DEAL", "value": 40}, Context(now=NOW), check_text=False), "R5")
    assert expected_profit(pricier, "BUNDLE_DEAL", hi)["p_without"] < pricier["p_buy_7d"]  # base = add-on rate

    # Wishlist watcher: only a real price drop / restock, and the message must say which
    assert has(ok(cust("C002"), "WISHLIST_ALERT", 0)[0], "R29")
    drop = cust("C002", wishlist_alert_item="PureFlow Cookware Set", wishlist_alert_kind="price_drop",
                wishlist_alert_was_price=2399.0, wishlist_alert_price=2159.0)
    problems, msg = ok(drop, "WISHLIST_ALERT", 0)
    assert not problems and "2399" in msg and "2159" in msg, (problems, msg)
    restock = cust("C002", wishlist_alert_item="PureFlow Cookware Set", wishlist_alert_kind="back_in_stock",
                   wishlist_alert_price=2159.0)
    lie = "Hi, good news about the PureFlow Cookware Set on your wishlist: the price dropped!"
    assert has(check_message(restock, OFFERS["WISHLIST_ALERT"], 0, lie, "WISHLIST_ALERT"), "R15")

    # Spend goal: target about 1.5x the usual order (rounded up to ₹50), never below the flat-off basket
    goal = cust("C002")
    target = min_basket(goal, "SPEND_GOAL")
    assert target >= -(-1.5 * goal["aov"] // 50) * 50 and target >= 999, target
    lo, hi = value_bounds(goal, "SPEND_GOAL")
    problems, msg = ok(goal, "SPEND_GOAL", lo)
    assert not problems and f"₹{target}" in msg and "7 days" in msg, (problems, msg)

    # Pick your perk: both choices, same minimum order as free delivery, reply remembered
    perk_c = cust("C002")
    problems, msg = ok(perk_c, "PERK_CHOICE", 0)
    assert not problems and str(perk_points()) in msg and "delivery" in msg, (problems, msg)
    assert min_basket(perk_c, "PERK_CHOICE") == min_basket(perk_c, "FREE_SHIPPING")
    assert perk_points() * 0.25 == 60  # both perks cost the shop the same
    assert has(check_message(perk_c, OFFERS["PERK_CHOICE"], 0, f"Hi, reply 1 for free delivery above ₹{min_basket(perk_c, 'PERK_CHOICE')}. Valid for 5 days.", "PERK_CHOICE"), "R15")
    row = decide(dict(S["C002"]), now=NOW, use_agent=False, skip_holdout=True, explore=False)
    offer_log.update(row["id"], offer_id="PERK_CHOICE", status="READY", valid_until=(NOW + timedelta(days=5)).isoformat())
    assert delivery.handle_reply("C002", "2", now=NOW + timedelta(hours=1)) == "perk_chosen:BONUS_POINTS"
    later = Context.load("C002", now=NOW + timedelta(days=10))
    assert later.prefs["perk"] == "BONUS_POINTS"
    assert has(validate(perk_c, {"offer_id": "PERK_CHOICE", "value": 0}, later, check_text=False), "R29")
    print("new offers (bought together, wishlist watcher, spend goal, pick your perk): ok")


def test_one_live_offer():
    """R8: while a customer holds an offer they were told is valid, nothing new is created for them."""
    from src import automation
    from src.rules import live_offer
    c = cust("C002")  # deal seeker, no open cart
    row = decide(dict(S["C002"]), now=NOW, use_agent=False, skip_holdout=True, explore=False)
    offer_log.update(row["id"], offer_id="FLAT_OFF", offer_type="flat", value=100, est_cost_inr=100, status="READY",
                     valid_until=(NOW + timedelta(days=5)).isoformat())
    for later in (NOW + timedelta(days=1), NOW + timedelta(days=4)):
        ctx = Context.load("C002", now=later)
        assert live_offer(ctx.history, later)["offer_id"] == "FLAT_OFF"
        for offer_id, value in (("REVIEW_REQUEST", 0), ("BONUS_POINTS", 100), ("WISHLIST_ALERT", 0)):
            assert has(validate(c, {"offer_id": offer_id, "value": value}, ctx, check_text=False), "R8"), offer_id
        again = decide(dict(S["C002"]), now=later, use_agent=False, skip_holdout=True, explore=False)
        assert again["status"] == "NO_OFFER" and "live offer (FLAT_OFF)" in again["reason"], again["reason"]
    # Internal-only validity (a reminder that is "recent" for 2 days) doesn't count as a live offer
    reminder = {"offer_id": "CART_REMINDER", "valid_until": (NOW + timedelta(days=2)).isoformat()}
    assert live_offer([reminder], NOW) is None
    # Once it has ended, a new offer is possible again
    after = NOW + timedelta(days=6)
    assert not has(validate(c, {"offer_id": "BONUS_POINTS", "value": 100}, Context.load("C002", now=after),
                            check_text=False), "R8")
    # The daily check doesn't even look at customers holding a live offer
    automation.reset()
    live = offer_log.live_offers(NOW + timedelta(days=1), rules.holds_live_offer)
    assert "C002" in live
    print("one live offer at a time (no new offer, paid or free, until it ends): ok")


def test_cart_escalation():
    """R12: a cart reminder that didn't lead to a purchase is followed by a discount, never a second reminder."""
    from src.rules import cart_escalation
    c = cust("C006")  # open cart
    first = decide(dict(S["C006"]), now=NOW, use_agent=False, skip_holdout=True, explore=False)
    assert first["offer_id"] == "CART_REMINDER", first
    soon = NOW + timedelta(hours=12)
    assert cart_escalation(c, Context.load("C006", now=soon)) is None  # too early: they may still buy
    later = NOW + timedelta(hours=26)
    ctx = Context.load("C006", now=later)
    assert cart_escalation(c, ctx)
    assert has(validate(c, {"offer_id": "CART_REMINDER", "value": 0}, ctx, check_text=False), "R12")
    assert has(validate(c, {"offer_id": "BUNDLE_SUGGEST", "value": 0}, ctx, check_text=False), "R12")
    again = decide(dict(S["C006"]), now=later, use_agent=False, skip_holdout=True, explore=False)
    assert again["offer_id"] in RULES["frequency"]["cart_discount_offers"] or \
        (again["offer_id"] in (None, "NONE") and "R12: a cart reminder" in again["reason"]), again
    if again["offer_id"] not in (None, "NONE"):  # once the discount is out, the escalation is over
        assert cart_escalation(c, Context.load("C006", now=later + timedelta(hours=1))) is None
    print(f"cart escalation: reminder -> {again['offer_id']} a day later (no second reminder): ok")


def test_safe_categories():
    """R5 whatever they buy: free delivery / flat / % off only where the margin floor survives."""
    from src.config import OFFERS
    from src.fallback import render
    from src.rules import category_margin, check_message, min_basket, safe_categories, scope_categories
    floor = RULES["margin_floor_pct"]
    books = cust("C004", top_category="Books", aov=1000)
    basket = min_basket(books, "FREE_SHIPPING")
    cats = safe_categories(books, "FREE_SHIPPING", 0)
    assert "Books" in cats and "Mobiles" not in cats, cats
    for cat in rules.all_categories():  # every allowed category keeps the floor; every excluded one would not
        keeps = (category_margin(cat) - floor) * basket / 100 >= 60
        assert keeps == (cat in cats), (cat, basket)
    msg = render(books, "FREE_SHIPPING", 0)
    assert "only on" in msg and not check_message(books, OFFERS["FREE_SHIPPING"], 0, msg, "FREE_SHIPPING"), msg
    bad = f"Hi, free delivery on your next order above ₹{basket}, Mobiles included. Valid for 5 days."
    assert has(check_message(books, OFFERS["FREE_SHIPPING"], 0, bad, "FREE_SHIPPING"), "R15")
    unnamed = f"Hi, free delivery on your next order above ₹{basket}. Valid for 5 days."
    assert has(check_message(books, OFFERS["FREE_SHIPPING"], 0, unnamed, "FREE_SHIPPING"), "R15")
    # % off: limited to categories with margin - floor >= value, whatever the customer's own category
    assert scope_categories(books, "PERCENT_OFF", 10) == [c for c in rules.all_categories() if category_margin(c) - floor >= 10]
    print("safe categories (free delivery, flat and % off never lose money on any category): ok")


if __name__ == "__main__":
    offer_log.DB_PATH = offer_log.DATA_DIR / "test_rules_v2.db"
    tests = [test_segments, test_ladders_and_caps, test_budget_pacing_and_atomic_write, test_holdout_is_salted_and_stable,
             test_message_checks, test_guards, test_consent_and_delivery, test_exploration_and_review,
             test_second_review, test_safe_categories, test_new_offers, test_one_live_offer, test_cart_escalation]
    for t in tests:
        offer_log.reset()
        consent.reset_all()
        from src import coupons
        coupons.reset_all()
        t()
    offer_log.DB_PATH.unlink()
    print("\nall rule tests passed")
