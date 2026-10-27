"""Run the automatic decisions (events + daily check + sending) without the preview page.

    python run_automation.py                 # keep running: a round every 30 s (rules.yaml automation)
    python run_automation.py --once          # one round now, then stop
    python run_automation.py --daily-now     # run the daily check of every customer right now
    python run_automation.py --event signup U9001 '{"name": "Riya Sharma", "interest": "Beauty"}'
    python run_automation.py --status

The preview page (python preview.py) runs the same loop in the background, so you only need this
script when the page isn't running (e.g. on a server).
"""
import argparse
import json
import sys
from datetime import datetime

from src import automation, telegram_bot

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one round, then stop")
    ap.add_argument("--daily-now", action="store_true", help="run the daily check now, whatever the time")
    ap.add_argument("--event", nargs="+", metavar=("KIND", "CUSTOMER_ID"),
                    help=f"queue an event: KIND CUSTOMER_ID [JSON payload]; kinds: {', '.join(automation.KINDS)}")
    ap.add_argument("--rules-only", action="store_true", help="don't call the AI")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    use_agent = False if args.rules_only else None

    if args.event:
        kind, cid = args.event[0], args.event[1]
        payload = json.loads(args.event[2]) if len(args.event) > 2 else {}
        print(f"queued event {automation.add_event(kind, cid, payload)}: {kind} for {cid}")
        args.once = True
    if args.status:
        print(json.dumps(automation.status(), indent=1, ensure_ascii=False))
        return
    if args.daily_now:
        print(automation.daily_run(use_agent=use_agent, force=True))
        print(f"sent: {automation.send_due()}")
        return
    if args.once:
        out = automation.tick(use_agent=use_agent)
        for e in out["events"]:
            print(f"event {e[0]} {e[1]} {e[2]}: {e[3]}")
        print(f"daily check: {out['daily'] or 'not due'}")
        print(f"sent: {len(out['sent'])} ({', '.join(sorted(set(out['sent'].values()))) or 'none'})")
        return
    telegram_bot.install()
    if telegram_bot.configured():
        import threading
        threading.Thread(target=telegram_bot.poll_forever, args=(threading.Event(),), daemon=True).start()
    print(f"Automation running (a round every {automation.CFG['tick_seconds']} s, daily check at "
          f"{automation.CFG['daily_hour']:02d}:00). Ctrl+C to stop.")
    try:
        automation.run_forever()
    except KeyboardInterrupt:
        print(f"\nstopped at {datetime.now():%H:%M:%S}")


if __name__ == "__main__":
    main()
