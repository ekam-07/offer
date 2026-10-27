"""Telegram channel: really sends offers, and listens for replies and button presses.

Two ways to use it (.env):
  TELEGRAM_BOT_TOKEN=123:abc            from @BotFather (required)
  TELEGRAM_TEST_MODE=1                  test mode (default): the 200 customers are simulated and have no
                                        Telegram, so EVERY customer's message goes to the test chats instead,
                                        labelled with who it was for. A chat becomes a test chat by sending
                                        /test to the bot.
  TELEGRAM_TEST_MODE=0                  real mode: a message only goes to a customer who linked their own
                                        chat by pressing Start in the bot (they become a real customer).
  DELIVERY_MODE=live                    actually send (otherwise everything stays a dry run)

Every message has buttons: 👍 Interested · 👎 Not interested · ✋ Stop. Replies "1"/"2" answer Pick your perk.
Telegram allows about one message per second per chat, so sending is paced (200 messages ≈ 3-4 minutes).
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from dotenv import load_dotenv

from . import automation, consent, delivery, offer_log
from .config import ROOT

API = "https://api.telegram.org/bot{token}/{method}"
PER_CHAT_GAP_S = 1.1          # Telegram: about 1 message per second to the same chat
_send_lock = threading.Lock()
_last_sent = {}               # chat_id -> time of the last message
SCHEMA = """CREATE TABLE IF NOT EXISTS telegram_chats (chat_id TEXT PRIMARY KEY, customer_id TEXT, kind TEXT,
             name TEXT, linked_at TEXT)"""


class NoChat(Exception):
    """The customer has no Telegram chat to send to (they never pressed Start)."""


def _env():
    load_dotenv(ROOT / ".env", override=True)
    if os.getenv("TELEGRAM_DISABLED") == "1":  # e.g. the demo copy of the app: never touch the real bot
        return {"token": "", "test_mode": True}
    return {"token": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            "test_mode": os.getenv("TELEGRAM_TEST_MODE", "1").strip() != "0"}


def configured():
    return bool(_env()["token"])


def api(method, **params):
    """Call the Telegram Bot API. Retries once after a 'Too Many Requests' with the wait Telegram asks for."""
    token = _env()["token"]
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")
    data = json.dumps(params).encode()
    for attempt in range(3):
        req = urllib.request.Request(API.format(token=token, method=method), data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=params.get("timeout", 0) + 15) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            out = json.loads(e.read() or b"{}")
            if e.code == 429 and attempt < 2:
                time.sleep(float(out.get("parameters", {}).get("retry_after", 2)) + .5)
                continue
            raise RuntimeError(f"Telegram {method} failed: {out.get('description', e)}")
        if not out.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {out.get('description')}")
        return out["result"]
    raise RuntimeError(f"Telegram {method}: still rate limited")


# ---- chats ------------------------------------------------------------------------------------

def _conn():
    conn = offer_log.connect()
    conn.execute(SCHEMA)
    return conn


def link(chat_id, kind, customer_id=None, name=None):
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO telegram_chats VALUES (?, ?, ?, ?, ?)",
                     (str(chat_id), customer_id, kind, name, datetime.now().isoformat(timespec="seconds")))


def unlink(chat_id):
    with _conn() as conn:
        conn.execute("DELETE FROM telegram_chats WHERE chat_id = ?", (str(chat_id),))


def test_chats():
    """Chats that sent /test, plus TELEGRAM_TEST_CHATS (comma-separated chat IDs) for hosts like Vercel
    whose database is wiped on every cold start."""
    fixed = [c.strip() for c in os.getenv("TELEGRAM_TEST_CHATS", "").split(",") if c.strip()]
    with _conn() as conn:
        linked = [r["chat_id"] for r in conn.execute("SELECT chat_id FROM telegram_chats WHERE kind = 'test'")]
    return list(dict.fromkeys(fixed + linked))


def chat_for(customer_id):
    with _conn() as conn:
        r = conn.execute("SELECT chat_id FROM telegram_chats WHERE customer_id = ? AND kind = 'customer'",
                         (customer_id,)).fetchone()
    return r["chat_id"] if r else None


def customer_for(chat_id):
    with _conn() as conn:
        r = conn.execute("SELECT customer_id FROM telegram_chats WHERE chat_id = ? AND kind = 'customer'",
                         (str(chat_id),)).fetchone()
    return r["customer_id"] if r else None


# ---- sending ----------------------------------------------------------------------------------

def _buttons(customer_id, offer_id):
    cb = lambda kind: f"{kind}|{customer_id}|{offer_id or ''}"[:64]  # noqa: E731 (Telegram limit: 64 bytes)
    return {"inline_keyboard": [[{"text": "👍 Interested", "callback_data": cb("interested")},
                                 {"text": "👎 Not interested", "callback_data": cb("not_interested")},
                                 {"text": "✋ Stop", "callback_data": cb("stop")}]]}


def _paced_send(chat_id, text, markup=None):
    with _send_lock:  # one at a time, at most ~1 per second per chat
        wait = PER_CHAT_GAP_S - (time.monotonic() - _last_sent.get(chat_id, 0))
        if wait > 0:
            time.sleep(wait)
        api("sendMessage", chat_id=chat_id, text=text, reply_markup=markup or {})
        _last_sent[chat_id] = time.monotonic()


def send(customer, message, row=None):
    """The delivery channel. A customer who pressed Start always gets their own message. Test mode also
    sends labelled copies to every test chat, so simulated customers' offers are visible somewhere."""
    env = _env()
    if not env["token"]:
        raise NoChat("Telegram is not set up (or disabled for this copy of the app)")
    cid, offer_id = customer["customer_id"], (row or {}).get("offer_id")
    markup = _buttons(cid, offer_id)
    chat = chat_for(cid)
    if env["test_mode"]:
        copies = [c for c in test_chats() if c != chat]
        if not chat and not copies:
            raise NoChat("test mode: no test chat yet (send /test to the bot first)")
        if chat:  # a real person (e.g. a judge who pressed Start): the offer is theirs
            _paced_send(chat, message, markup)
        label = f"🧪 Test · for {customer.get('name') or cid} ({cid}) · {(offer_id or '').replace('_', ' ').lower()}\n\n"
        for c in copies:
            _paced_send(c, label + message, markup)
        return
    if not chat:
        raise NoChat(f"{cid} has no Telegram chat (they never pressed Start)")
    _paced_send(chat, message, markup)


# ---- receiving --------------------------------------------------------------------------------

HELP = ("Commands: /stop to get no more offers, /start to get them again, /mydata to see what we hold, "
        "/delete to erase it. Reply 1 or 2 to pick a perk.")


def _reply(chat_id, text):
    _paced_send(str(chat_id), text)


def handle_update(u, now=None):
    """One update from Telegram (a message or a button press). Returns a short note of what happened."""
    now = now or datetime.now()
    if "callback_query" in u:
        q = u["callback_query"]
        kind, cid, offer_id = (q.get("data", "").split("|") + ["", "", ""])[:3]
        if kind in ("interested", "not_interested", "stop") and cid:
            consent.record_feedback(cid, kind, offer_id or None, now=now)
            note = {"interested": "Thanks! Noted 👍", "not_interested": "Got it, we won't send that offer for a while.",
                    "stop": "Done. No more offers. Send /start to change your mind."}[kind]
            api("answerCallbackQuery", callback_query_id=q["id"], text=note)
            return f"button {kind} for {cid}"
        return "ignored button"
    msg = u.get("message") or {}
    chat_id, text = str(msg.get("chat", {}).get("id", "")), (msg.get("text") or "").strip()
    if not chat_id or not text:
        return "ignored"
    first = (msg.get("from") or {}).get("first_name") or "there"
    low = text.lower()
    if low == "/test":
        link(chat_id, "test", name=first)
        _reply(chat_id, "🧪 This chat now receives the TEST copies of all customers' offers. Send /untest to stop.\n"
                        f"Chat ID: {chat_id} (put it in TELEGRAM_TEST_CHATS on a hosted copy to keep it)")
        return f"test chat added {chat_id}"
    if low == "/untest":
        unlink(chat_id)
        _reply(chat_id, "This chat no longer receives test copies.")
        return f"test chat removed {chat_id}"
    cid = customer_for(chat_id)
    if low.startswith("/start"):
        if cid:
            delivery.handle_reply(cid, "/start", now=now)
            _reply(chat_id, f"Welcome back, {first}! Offers are on again. {HELP}")
            return f"opted in {cid}"
        cid = f"T{chat_id}"
        link(chat_id, "customer", customer_id=cid, name=first)
        automation.add_event("signup", cid, {"name": first, "opted_in": True, "channels": ["telegram"]}, now=now)
        _reply(chat_id, f"Hi {first}! You're in. We'll only message you when we have something worth it, "
                        f"never at night. {HELP}")
        return f"new customer {cid}"
    if not cid:
        _reply(chat_id, "Press /start to join, or /test to receive test copies.")
        return "unknown chat"
    if low == "/mydata":
        rows = offer_log.customer_rows(cid, limit=5)
        lines = [f"• {r['created_at'][:16].replace('T', ' ')} {(r['offer_id'] or 'no offer').replace('_', ' ').lower()} ({r['status']})" for r in rows]
        _reply(chat_id, f"Your ID: {cid}\nLast offers:\n" + ("\n".join(lines) or "none yet") +
                        "\nWe keep your offer history to avoid sending too much. /delete erases it.")
        return f"mydata {cid}"
    if low == "/delete":
        consent.erase(cid, now=now)
        unlink(chat_id)
        _reply(chat_id, "Your data is deleted and you won't get any more messages. Send /start to join again.")
        return f"erased {cid}"
    result = delivery.handle_reply(cid, "/stop" if low == "/stop" else text, now=now)
    if result == "opted_out":
        _reply(chat_id, "Done, no more offers. Send /start any time to change your mind.")
    elif result.startswith("perk_chosen"):
        _reply(chat_id, "Great choice, your perk is saved 🎁")
    elif result == "flagged_for_review":
        _reply(chat_id, "Sorry about that. A person from our team will look at it.")
    return f"reply {cid}: {result}"


def explain_outcome(customer_id, chat_id):
    """After a /start sign-up has been decided and sent: if no offer went out, say why, so someone
    trying the bot (e.g. a judge) isn't left wondering. Returns the status, or None if nothing to say."""
    rows = offer_log.customer_rows(customer_id, limit=1)
    if not rows or rows[0]["status"] in ("SENT", "DRY_RUN"):
        return None
    status = rows[0]["status"]
    text = {
        "HOLDOUT": "No offer for you this time: you're in our control group. 15 in 100 shoppers get no offers, "
                   "so we can measure whether offers really make a difference.",
        "READY": "Your offer is ready, but it's quiet time (10 pm to 8 am), so we never message then. "
                 "Send any message after 8 am to get it.",
        "NO_OFFER": "No offer right now: none would pay for itself yet, so we keep quiet instead of spamming you.",
        "NOT_ELIGIBLE": "No offer right now: you can't receive offers at the moment (for example after /stop).",
    }.get(status, f"No offer sent this time ({status.replace('_', ' ').lower()}).")
    _reply(chat_id, text + " Send /mydata to see what we decided.")
    return status


def poll_forever(stop=None):
    """Long-poll Telegram for messages and button presses (no public URL or webhook needed)."""
    offset = None
    while not (stop and stop.is_set()):
        if not configured():
            time.sleep(10)
            continue
        try:
            updates = api("getUpdates", timeout=25, offset=offset, allowed_updates=["message", "callback_query"])
        except Exception:  # network hiccup: wait and try again
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                handle_update(u)
            except Exception:
                pass


def status():
    env = _env()
    out = {"configured": bool(env["token"]), "test_mode": env["test_mode"], "test_chats": len(test_chats()),
           "delivery_mode": delivery.mode()}
    if env["token"]:
        try:
            out["bot"] = "@" + api("getMe")["username"]
        except Exception as e:
            out["error"] = str(e)
    with _conn() as conn:
        out["linked_customers"] = conn.execute("SELECT COUNT(*) FROM telegram_chats WHERE kind = 'customer'").fetchone()[0]
    return out


def install():
    """Register Telegram as a real delivery channel (used by preview.py / run_automation.py)."""
    delivery.register_channel("telegram", send)
