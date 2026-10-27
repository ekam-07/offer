"""Point the Telegram bot at a hosted copy of the app (e.g. on Vercel), or back to local polling.

    python tools/telegram_webhook.py set https://your-app.vercel.app   # Telegram calls <url>/api/telegram
    python tools/telegram_webhook.py info                               # where the bot points now
    python tools/telegram_webhook.py delete                             # back to polling by preview.py

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET from .env. The hosted copy needs the same two
values in its environment variables. While a webhook is set, a local preview.py can't receive messages.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import telegram_bot  # noqa: E402


def main(args):
    cmd = args[0] if args else "info"
    if cmd == "set" and len(args) == 2:
        secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
        if not secret:
            sys.exit("Add TELEGRAM_WEBHOOK_SECRET=<a long random string: letters, digits, _ or -> to .env first.")
        url = args[1].rstrip("/") + "/api/telegram"
        telegram_bot.api("setWebhook", url=url, secret_token=secret, drop_pending_updates=True,
                         allowed_updates=["message", "callback_query"])
        print(f"Webhook set: {url}")
    elif cmd == "delete":
        telegram_bot.api("deleteWebhook")
        print("Webhook removed: run python preview.py to receive messages locally again.")
    elif cmd == "info":
        info = telegram_bot.api("getWebhookInfo")
        print(f"Webhook: {info.get('url') or 'none (local polling)'}")
        print(f"Waiting updates: {info.get('pending_update_count', 0)}")
        if info.get("last_error_message"):
            print(f"Last error: {info['last_error_message']}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    telegram_bot.configured()  # loads .env
    main(sys.argv[1:])
