"""Telegram channel with a fake Telegram (nothing is really sent).

    python -m tests.test_telegram
"""
import os
from datetime import datetime, timedelta

from src import automation, consent, coupons, delivery, offer_log, telegram_bot

NOW = datetime(2026, 10, 16, 14, 0)
SENT = []


def fake_api(method, **params):
    SENT.append((method, params))
    if method == "getMe":
        return {"username": "fake_offer_bot"}
    return {"message_id": len(SENT)}


def update(text=None, chat=111, first="Riya", data=None):
    if data:
        return {"update_id": 1, "callback_query": {"id": "q1", "data": data, "message": {"chat": {"id": chat}}}}
    return {"update_id": 1, "message": {"chat": {"id": chat}, "from": {"first_name": first}, "text": text}}


def setup(test_mode):
    os.environ["TELEGRAM_BOT_TOKEN"] = "123:fake"
    os.environ["TELEGRAM_TEST_MODE"] = "1" if test_mode else "0"
    os.environ["DELIVERY_MODE"] = "live"
    telegram_bot._env = lambda: {"token": "123:fake", "test_mode": test_mode}
    telegram_bot.api = fake_api
    telegram_bot.PER_CHAT_GAP_S = 0
    telegram_bot.install()
    SENT.clear()


def test_test_mode_sends_every_customer_to_the_test_chat():
    setup(test_mode=True)
    telegram_bot.handle_update(update("/test", chat=999, first="Tester"), now=NOW)
    assert telegram_bot.test_chats() == ["999"]
    customers = automation.all_customers()
    picked = [c for c in customers.values() if c.get("opted_in") and c.get("consent_telegram")][:5]
    blocked = next(c for c in customers.values() if c.get("opted_in") and not c.get("consent_telegram"))
    for c in picked + [blocked]:
        offer_log.write({"created_at": NOW.isoformat(timespec="seconds"), "customer_id": c["customer_id"], "segment": "LOYAL",
                         "status": "READY", "offer_id": "FREE_SHIPPING", "offer_type": "shipping", "value": 0,
                         "est_cost_inr": 60, "valid_until": (NOW + timedelta(days=5)).isoformat(),
                         "message": "Hi, free delivery on your next order above ₹299. Valid for 5 days.",
                         "reason": "test", "decided_by": "RULES", "agent_status": "SKIPPED", "flagged": 0,
                         "send_at": (NOW + timedelta(hours=5)).isoformat(timespec="minutes")})
    SENT.clear()
    out = automation.send_due(NOW + timedelta(minutes=1))  # test mode: no waiting for each customer's usual hour
    msgs = [p for m, p in SENT if m == "sendMessage"]
    assert sorted(out.values()) == sorted(["SENT"] * 5 + ["BLOCKED_AT_SEND"]), out
    assert len(msgs) == 5 and all(p["chat_id"] == "999" for p in msgs)
    assert all(p["text"].startswith("🧪 Test · for ") and "Your personal code:" in p["text"] for p in msgs)
    assert all(len(p["reply_markup"]["inline_keyboard"][0]) == 3 for p in msgs)
    # a button press is recorded as feedback for the simulated customer it was for
    data = msgs[0]["reply_markup"]["inline_keyboard"][0][1]["callback_data"]
    telegram_bot.handle_update(update(data=data), now=NOW)
    cid = data.split("|")[1]
    assert "FREE_SHIPPING" in consent.active_prefs(cid, NOW + timedelta(hours=1))["suppressed"]
    print("test mode: every customer's offer goes to the test chat, labelled, with buttons; no-consent blocked: ok")


def test_real_mode_start_stop_and_delete():
    setup(test_mode=False)
    note = telegram_bot.handle_update(update("/start", chat=222, first="Kabir"), now=NOW)
    assert note == "new customer T222" and telegram_bot.customer_for(222) == "T222"
    automation.process_due_events(NOW, use_agent=False)  # the sign-up event decides for them
    assert "T222" in automation.all_customers()
    assert telegram_bot.handle_update(update("/stop", chat=222), now=NOW) == "reply T222: opted_out"
    assert not consent.allows_offers({"customer_id": "T222", "opted_in": True})
    assert telegram_bot.handle_update(update("/start", chat=222), now=NOW) == "opted in T222"
    assert consent.allows_offers({"customer_id": "T222", "opted_in": True})
    # a customer without a linked chat can't be sent to in real mode: blocked, not failed
    try:
        telegram_bot.send({"customer_id": "U0001", "name": "x"}, "hi")
        assert False
    except telegram_bot.NoChat:
        pass
    assert telegram_bot.handle_update(update("/delete", chat=222), now=NOW) == "erased T222"
    assert telegram_bot.customer_for(222) is None
    print("real mode: /start joins, /stop and /start work, /delete erases, unlinked customers blocked: ok")


if __name__ == "__main__":
    offer_log.DB_PATH = offer_log.DATA_DIR / "test_telegram.db"
    for t in (test_test_mode_sends_every_customer_to_the_test_chat, test_real_mode_start_stop_and_delete):
        offer_log.reset(); consent.reset_all(); coupons.reset_all(); automation.reset()
        with offer_log.connect() as conn:
            conn.execute(telegram_bot.SCHEMA); conn.execute("DELETE FROM telegram_chats")
        t()
    try:
        offer_log.DB_PATH.unlink()
    except PermissionError:  # Windows: a connection may still be open; the file is reset next run
        pass
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TEST_MODE", "DELIVERY_MODE"):
        os.environ.pop(k, None)
    print("\nall telegram tests passed")
