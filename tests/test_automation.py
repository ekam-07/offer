"""Automatic decisions: events, the daily check and sending, without anyone pressing Decide.

    python -m tests.test_automation
"""
import json
from datetime import datetime, timedelta

from src import automation, consent, coupons, offer_log
from src.rules import in_holdout

NOW = datetime(2026, 10, 16, 14, 0)  # a normal afternoon (not quiet hours)


def rows_for(cid):
    with offer_log.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM offer_log WHERE customer_id = ? ORDER BY id", (cid,))]


def free_id(prefix):
    """A new customer id that isn't in the 15% control group, so it can get offers."""
    return next(f"{prefix}{i}" for i in range(1, 500) if not in_holdout(f"{prefix}{i}"))


def test_signup():
    cid = free_id("N")
    automation.add_event("signup", cid, {"name": "Riya Sharma", "interest": "Beauty"}, now=NOW)
    done = automation.process_due_events(NOW, use_agent=False)
    assert done and done[0][3].startswith("decided"), done
    c = automation.all_customers()[cid]
    assert c["orders_total"] == 0 and c["top_category"] == "Beauty" and c["consent_telegram"] is True
    assert rows_for(cid) and rows_for(cid)[-1]["segment"] in ("NEW", "NEVER_BOUGHT")
    assert automation.process_due_events(NOW, use_agent=False) == []  # handled once only
    automation.add_event("signup", cid, {"name": "Duplicate"}, now=NOW)
    assert automation.process_due_events(NOW, use_agent=False)[0][3].startswith("skipped")
    print("signup -> decided automatically: ok")


def test_cart_waits_then_reminds():
    cid = free_id("C")
    automation.add_event("signup", cid, {"name": "Kabir Kaur"}, now=NOW)
    automation.process_due_events(NOW, use_agent=False)
    c = automation.all_customers()[cid]
    automation.add_event("cart_abandoned", cid, {"product_id": c["focus_product_id"], "value": 999}, now=NOW)
    assert automation.process_due_events(NOW + timedelta(minutes=30), use_agent=False) == []  # still shopping
    done = automation.process_due_events(NOW + timedelta(minutes=61), use_agent=False)
    signup_offer = rows_for(cid)[0]
    if automation.holds_live_offer(signup_offer["offer_id"]) and signup_offer["status"] == "READY":
        # Their sign-up offer (e.g. the welcome discount) is still live: no new offer, not even a reminder (R8)
        assert done and "NONE" in done[0][3] and "live offer" in rows_for(cid)[-1]["reason"], done
        offer_log.update(signup_offer["id"], valid_until=NOW.isoformat())  # pretend it has ended
        automation.add_event("cart_abandoned", cid, {"product_id": c["focus_product_id"], "value": 999},
                             now=NOW + timedelta(minutes=62), delay_minutes=0)
        done = automation.process_due_events(NOW + timedelta(minutes=62), use_agent=False)
    assert done and "CART_REMINDER" in done[0][3], done
    # A cart left before an order is ignored
    automation.add_event("cart_abandoned", cid, {"product_id": c["focus_product_id"]}, now=NOW + timedelta(hours=2))
    automation.add_event("order_placed", cid, {"product_id": c["focus_product_id"], "total": 999},
                         now=NOW + timedelta(hours=2, minutes=10))
    done = automation.process_due_events(NOW + timedelta(hours=4), use_agent=False)
    results = {kind: res for _, kind, _, res in done}
    assert results["cart_abandoned"].startswith("skipped"), results
    print("abandoned cart waits 1 hour, ignored after an order: ok")


def test_order_then_bundle():
    cid, start = "U0005", NOW  # an existing customer
    before = automation.all_customers()[cid]["orders_total"]
    automation.add_event("order_placed", cid, {"product_id": "P0098", "total": 299}, now=start)
    done = automation.process_due_events(start, use_agent=False)
    assert done[0][3].startswith("updated"), done
    c = automation.all_customers()[cid]
    assert c["orders_total"] == before + 1 and c["recency_days"] == 0
    assert automation.process_due_events(start + timedelta(days=2), use_agent=False) == []  # tip waits 3 days
    done = automation.process_due_events(start + timedelta(days=3, minutes=1), use_agent=False)
    assert done and done[0][1] == "bundle_check", done
    print(f"order -> bought-together check 3 days later: ok ({done[0][3]})")


def test_price_drop_must_be_real():
    automation.add_event("wishlist_price_drop", "U0005", {"item": "Table Lamp", "was_price": 999, "price": 999}, now=NOW)
    assert automation.process_due_events(NOW, use_agent=False)[0][3].startswith("skipped")
    print("fake price drop ignored: ok")


def test_daily_check_and_sending():
    early = NOW.replace(hour=7)
    assert automation.daily_run(early, use_agent=False) is None  # not 08:00 yet
    at8 = NOW.replace(hour=8, minute=5)
    summary = automation.daily_run(at8, use_agent=False)
    assert summary and "customers checked" in summary, summary
    assert automation.daily_run(at8 + timedelta(minutes=30), use_agent=False) is None  # once a day
    assert "skipped (still have a live offer)" in summary
    n_before = len(offer_log.all_rows(limit=100000))
    automation.daily_run(at8 + timedelta(minutes=40), use_agent=False, force=True)  # all decided <20h ago: skipped
    assert len(offer_log.all_rows(limit=100000)) == n_before
    sent = automation.send_due(at8 + timedelta(hours=1))
    assert sent and set(sent.values()) <= {"DRY_RUN", "BLOCKED_AT_SEND", "READY"}, set(sent.values())
    # Next morning: customers still holding a live offer from yesterday are not decided again
    live = offer_log.live_offers(at8 + timedelta(days=1), automation.holds_live_offer)
    before = {r["customer_id"]: r["id"] for r in offer_log.all_rows(limit=100000)[::-1]}
    next_day = automation.daily_run(at8 + timedelta(days=1), use_agent=False)
    assert live and f"{len(live)} skipped" in next_day, (len(live), next_day)
    after = {r["customer_id"]: r["id"] for r in offer_log.all_rows(limit=100000)[::-1]}
    assert all(after[cid] == before[cid] for cid in live)  # no new row at all for them
    stale = automation.send_due(at8 + timedelta(days=3))
    assert not stale  # day-old offers are never sent
    print(f"daily check at 08:00, once, skips recent; sends due offers (test mode): ok ({summary})")


def test_status_and_errors():
    automation.add_event("reply", "U0005", {"text": "stop"}, now=NOW)
    automation.add_event("cart_abandoned", "NOBODY", {}, now=NOW, delay_minutes=0)
    done = automation.process_due_events(NOW, use_agent=False)
    results = {kind: res for _, kind, _, res in done}
    assert results["reply"] == "reply: opted_out" and results["cart_abandoned"].startswith("skipped")
    st = automation.status(NOW)
    assert st["waiting"] >= 0 and "next_daily" in st
    try:
        automation.add_event("teleport", "U0005")
        assert False, "unknown kind accepted"
    except ValueError:
        pass
    print("replies, unknown customers and unknown kinds handled: ok")


if __name__ == "__main__":
    offer_log.DB_PATH = offer_log.DATA_DIR / "test_automation.db"
    for t in (test_signup, test_cart_waits_then_reminds, test_order_then_bundle, test_price_drop_must_be_real,
              test_daily_check_and_sending, test_status_and_errors):
        offer_log.reset()
        consent.reset_all()
        coupons.reset_all()
        automation.reset()
        t()
    offer_log.DB_PATH.unlink()
    print("\nall automation tests passed")
