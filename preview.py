"""Local preview page: see which offer each customer gets, who decided it and why.

    python preview.py          # then open http://127.0.0.1:5000
    CUSTOMERS_FILE=data/other.json python preview.py
"""
import json
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import threading

from src import agent, automation, consent, offer_log, telegram_bot
from src.explain import explain
from src.config import OFFERS, RULES, ROOT, default_customers_file
from src.decide import decide_batch
from src.rules import holds_live_offer
from src.segments import prepare

WEB_DIR = ROOT / "web"
CUSTOMERS_FILE = Path(os.getenv("CUSTOMERS_FILE") or default_customers_file())

app = Flask(__name__, static_folder=None)


def load_customers():
    """The customers file plus customers created or changed by automatic events (src/automation.py)."""
    if os.getenv("CUSTOMERS_FILE"):
        with open(CUSTOMERS_FILE, encoding="utf-8") as f:
            return {c["customer_id"]: c for c in json.load(f)}
    return automation.all_customers()


def _row(r):
    """Make a log row JSON-friendly (violations stored as a JSON string in the DB)."""
    if r is None:
        return None
    r = dict(r)
    if isinstance(r.get("violations"), str):
        r["violations"] = json.loads(r["violations"])
    return r


def _now(value):
    return datetime.fromisoformat(value) if value else datetime.now()


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/api/status")
def status():
    return jsonify({
        "agent_configured": agent.configured(),
        "model": agent.MODEL,
        "effort": agent.EFFORT,
        "daily_budget_inr": RULES["budget"]["daily_inr"],
        "holdout_pct": RULES["holdout_pct"],
        "customers_file": CUSTOMERS_FILE.name,
        "offers": {k: {"type": v["type"], "unit": v["unit"], "description": v["description"]} for k, v in OFFERS.items()},
    })


_PREPARED = {"mtime": None, "rows": {}}


def prepared_customers():
    """Customer features with segment and scores, computed once per customers file (they don't
    change with the clock). A real store would keep these in a database table with indexes."""
    mtime = (CUSTOMERS_FILE.stat().st_mtime, automation.live_version())
    if _PREPARED["mtime"] != mtime:
        _PREPARED.update(mtime=mtime, rows={cid: prepare(c) for cid, c in load_customers().items()})
    return _PREPARED["rows"]


SORTS = {
    "name": (lambda c: (c.get("name") or "").lower(), False),
    "chance": (lambda c: c.get("p_buy_7d") or 0, True),
    "risk": (lambda c: c.get("churn_risk") or 0, True),
    "value": (lambda c: c.get("aov") or 0, True),
    "cost": (lambda c: (c["latest"] or {}).get("est_cost_inr") or 0, True),
}


def _offer_key(r):
    return (r.get("offer_id") or "NONE") if r else None


@app.get("/api/customers")
def customers():
    """One page of the customer list: search, filters, sort and paging happen here, so the page
    only ever receives what it shows (works the same for 200 or 2,00,000 customers)."""
    a = request.args
    now = _now(a.get("now"))
    latest = offer_log.latest_per_customer()
    q, seg, offer = (a.get("q") or "").strip().lower(), a.get("segment") or "", a.get("offer") or ""
    flagged = a.get("flagged") == "1"
    page, size = max(1, int(a.get("page", 1))), min(100, max(5, int(a.get("size", 25))))

    rows, summary = [], {"customers": 0, "decided": 0, "ready": 0, "by_ai": 0, "by_rules": 0, "held": 0,
                         "flagged": 0, "kinds": set(), "segments": {}, "offers": {}}
    for cid, c in prepared_customers().items():
        r = latest.get(cid)
        summary["customers"] += 1
        summary["segments"][c["segment"]] = summary["segments"].get(c["segment"], 0) + 1
        if r:
            k = _offer_key(r)
            summary["decided"] += 1
            summary["offers"][k] = summary["offers"].get(k, 0) + 1
            summary["ready"] += r["status"] == "READY"
            summary["by_ai"] += r["decided_by"] == "AGENT"
            summary["by_rules"] += r["decided_by"] == "RULES"
            summary["held"] += r["status"] in ("HOLDOUT", "NOT_ELIGIBLE")
            summary["flagged"] += bool(r["flagged"])
            if r["status"] == "READY":
                summary["kinds"].add(k)
        if seg and c["segment"] != seg or offer and _offer_key(r) != offer or flagged and not (r and r["flagged"]):
            continue
        if q and q not in (c.get("name") or "").lower() and q not in cid.lower():
            continue
        rows.append(dict(c, latest=_row(r)))
    summary["kinds"] = len(summary["kinds"])

    key, desc = SORTS.get(a.get("sort"), SORTS["name"])
    rows.sort(key=key, reverse=desc)
    focus = None
    if offer:  # what the customers getting this offer have in common (the whole filtered set, not just the page)
        n = len(rows) or 1
        segs = {}
        for c in rows:
            segs[c["segment"]] = segs.get(c["segment"], 0) + 1
        focus = {"n": len(rows), "cost": sum((c["latest"] or {}).get("est_cost_inr") or 0 for c in rows),
                 "avg_chance": sum(c.get("p_buy_7d") or 0 for c in rows) / n,
                 "avg_order": sum(c.get("aov") or 0 for c in rows) / n,
                 "avg_risk": sum(c.get("churn_risk") or 0 for c in rows) / n,
                 "by_ai": sum((c["latest"] or {}).get("decided_by") == "AGENT" for c in rows), "segments": segs}
    page_rows = rows[(page - 1) * size: page * size]
    live = offer_log.live_offers(now, holds_live_offer)
    keep = ("customer_id", "name", "segment", "p_buy_7d", "churn_risk", "aov", "top_category", "latest")
    page_out = [dict({k: c.get(k) for k in keep}, live=_row(live.get(c["customer_id"]))) for c in page_rows]
    return jsonify({"rows": page_out, "total": len(rows), "page": page,
                    "size": size, "summary": summary, "focus": focus,
                    "spent_today_inr": offer_log.spent_on(now)})


@app.post("/api/events")
def post_event():
    """Webhook for the store or the Telegram bot: {kind, customer_id, payload, delay_minutes?}.
    process_now=true handles it straight away (for testing from this page)."""
    body = request.get_json(force=True) or {}
    now = _now(body.get("now"))  # the page's chosen time, so test events follow the same clock as its decisions
    try:
        event_id = automation.add_event(body.get("kind"), body.get("customer_id"), body.get("payload") or {},
                                        now=now, delay_minutes=body.get("delay_minutes"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    out = automation.tick(now=now) if body.get("process_now") else None
    return jsonify({"event_id": event_id, "processed": out and [e for e in out["events"] if e[0] == event_id]})


@app.get("/api/automation")
def automation_status():
    out = automation.status()
    out["telegram"] = telegram_bot.status() if telegram_bot.configured() else {"configured": False}
    return jsonify(out)


@app.get("/api/customer/<customer_id>")
def customer(customer_id):
    """Everything about one customer, for the side panel."""
    now = _now(request.args.get("now"))
    c = prepared_customers().get(customer_id)
    if c is None:
        return jsonify({"error": "unknown customer"}), 404
    p = dict(c)
    p["latest"] = _row(offer_log.latest_per_customer().get(customer_id))
    p["active"] = _row(offer_log.active_offers(now).get(customer_id))
    p["perk"] = consent.active_prefs(customer_id, now)["perk"]
    p["simple"] = explain(p, p["latest"])
    return jsonify(p)


@app.post("/api/decide")
def run_decide():
    body = request.get_json(force=True) or {}
    all_customers = load_customers()
    ids = body.get("customer_ids") or list(all_customers)
    now = _now(body.get("now"))
    # Sequential, highest priority first: budget and frequency rules depend on earlier decisions.
    rows = [_row(r) for r in decide_batch([all_customers[cid] for cid in ids], now=now, use_agent=bool(body.get("use_agent")))]
    return jsonify({"rows": rows, "spent_today_inr": offer_log.spent_on(now)})


@app.get("/api/history/<customer_id>")
def history(customer_id):
    return jsonify([_row(r) for r in offer_log.customer_rows(customer_id)])


@app.post("/api/reset")
def reset():
    offer_log.reset()
    return jsonify({"ok": True})


if __name__ == "__main__":
    telegram_bot.install()
    if telegram_bot.configured():  # replies, /start, /stop and buttons from Telegram
        threading.Thread(target=telegram_bot.poll_forever, args=(threading.Event(),), daemon=True).start()
        print(f"Telegram connected: {telegram_bot.status().get('bot')} (test mode: {telegram_bot.status()['test_mode']})")
    if os.getenv("AUTOMATION", "1") != "0":  # automatic decisions in the background (AUTOMATION=0 to turn off)
        threading.Thread(target=automation.run_forever, args=(threading.Event(),), daemon=True).start()
        print(f"Automation on: events every {automation.CFG['tick_seconds']} s, daily check at {automation.CFG['daily_hour']:02d}:00")
    print("Offer preview running at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
