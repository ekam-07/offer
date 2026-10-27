"""Delivery layer: the only place that "sends" an offer. Any channel (Telegram, Discord,
WhatsApp, email) plugs in here later; until then it runs in dry-run mode.

Safety, from rules.yaml `delivery`:
- quiet hours (R11, 22:00-08:00 IST) -> nothing is sent; the decision stays READY
- kill_switch: true      -> nothing is sent, decisions are marked BLOCKED_AT_SEND
- mode: dry_run          -> log what WOULD be sent (status DRY_RUN), send nothing
- consent is checked again at SEND time (R1), per channel, so a /stop that arrives
  between decision and send is respected
- replies are scanned for complaint keywords -> flagged for a human
"""
import inspect
import json
import os
from datetime import datetime

from . import consent, coupons, offer_log
from .config import RULES
from .rules import in_quiet_hours

CHANNELS = {}  # name -> callable(customer, message) -> None; registered by a bot later


def register_channel(name, send_fn):
    CHANNELS[name] = send_fn


def mode():
    """dry_run or live: rules.yaml delivery.mode, or DELIVERY_MODE in the environment / .env."""
    if os.getenv("FORCE_DRY_RUN") == "1":  # e.g. the demo copy of the app: never really send, whatever .env says
        return "dry_run"
    return (os.getenv("DELIVERY_MODE") or RULES["delivery"]["mode"]).strip()


def deliver(row, customer, channel=None, now=None):
    """Send (or dry-run) one READY decision. Returns the new status."""
    now = now or datetime.now()
    cfg = RULES["delivery"]
    channel = channel or cfg["default_channel"]
    if row.get("status") != "READY":
        return row.get("status")
    if in_quiet_hours(now):
        return "READY"  # R11: never send 22:00-08:00 IST; stays READY for the morning window
    if cfg["kill_switch"]:
        status, note = "BLOCKED_AT_SEND", "kill switch is on"
    elif not consent.allows_channel(customer, channel):
        status, note = "BLOCKED_AT_SEND", f"R1: no consent for {channel} at send time"
    else:
        message = row["message"]
        if (row.get("est_cost_inr") or 0) > 0:
            # Paid offers carry a unique, single-use code tied to this customer (coupons.py).
            # Added here, by trusted code, after the message has passed the R15 checks.
            message += f" Your personal code: {coupons.issue(row, now)} (single use, only for you)."
        send = CHANNELS.get(channel)
        if mode() == "dry_run" or send is None:
            status, note = "DRY_RUN", f"would send via {channel}"
        else:
            try:
                if len(inspect.signature(send).parameters) >= 3:
                    send(customer, message, row)  # channels that add buttons need the offer
                else:
                    send(customer, message)
                status, note = "SENT", f"sent via {channel}"
            except Exception as e:
                if type(e).__name__ == "NoChat":  # nobody to send to: not a failure, just not deliverable
                    offer_log.update(row["id"], status="BLOCKED_AT_SEND", channel=channel,
                                     reason=f"{row.get('reason', '')} [{e}]")
                    return "BLOCKED_AT_SEND"  # network/API failure: record it, never lose the offer silently
                offer_log.update(row["id"], status="SEND_FAILED", flagged=1, channel=channel,
                                 review_reasons=json.dumps([f"send failed via {channel}: {type(e).__name__}: {e}"]))
                return "SEND_FAILED"
    offer_log.update(row["id"], status=status, sent_at=now.isoformat(timespec="seconds"), channel=channel,
                     reason=f"{row.get('reason', '')} [{note}]")
    return status


def handle_reply(customer_id, text, now=None):
    """Incoming message from a customer: /stop, /start, or free text checked for complaints."""
    t = (text or "").strip().lower()
    if t in ("/stop", "stop", "unsubscribe"):
        consent.opt_out(customer_id, source=t, now=now)
        return "opted_out"
    if t in ("/start", "start"):
        consent.opt_in(customer_id, source=t, now=now)
        return "opted_in"
    if t in ("1", "2"):  # answer to Pick your perk
        with offer_log.connect() as conn:
            last = conn.execute("SELECT * FROM offer_log WHERE customer_id = ? AND offer_id = 'PERK_CHOICE' "
                                "ORDER BY id DESC LIMIT 1", (customer_id,)).fetchone()
        at = (now or datetime.now()).isoformat()
        if last and last["status"] in ("READY", "SENT", "DRY_RUN") and (last["valid_until"] or "") > at:
            perk = "FREE_SHIPPING" if t == "1" else "BONUS_POINTS"
            consent.record_perk(customer_id, perk, now=now)
            return f"perk_chosen:{perk}"
    hits = [k for k in RULES["review"]["complaint_keywords"] if k in t]
    if hits:
        with offer_log.connect() as conn:
            last = conn.execute("SELECT id FROM offer_log WHERE customer_id = ? ORDER BY id DESC LIMIT 1",
                                (customer_id,)).fetchone()
        if last:
            offer_log.update(last["id"], flagged=1, review_reasons=json.dumps([f"complaint keywords in reply: {hits}"]))
        return "flagged_for_review"
    return "noted"
