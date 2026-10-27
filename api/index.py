"""Vercel entry point: the same dashboard as preview.py, as a serverless function.

Vercel's filesystem is read-only except /tmp and there are no background threads, so each
instance copies the demo databases from data/demo/ into /tmp on cold start. Changes made on
the page (decisions, test events) last until that instance is recycled. Nothing is ever sent:
delivery is forced to dry-run and the Telegram bot is off.
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo"
TMP = Path("/tmp") if os.getenv("VERCEL") else ROOT / "data"

for name, env in (("offers_seed.db", "OFFERS_DB"), ("shop_lite.db", "SHOP_DB")):
    dst = TMP / f"vercel_{name}"
    if not dst.exists():
        shutil.copyfile(DEMO / name, dst)
    os.environ.setdefault(env, str(dst))
os.environ.update(FORCE_DRY_RUN="1", TELEGRAM_DISABLED="1", AUTOMATION="0")

sys.path.insert(0, str(ROOT))
from urllib.parse import parse_qsl, urlencode  # noqa: E402

from preview import app  # noqa: E402

_flask = app.wsgi_app


def _original_path(environ, start_response):
    """vercel.json sends every URL to this function as /api/index?__path=<original path>: put the
    original path back (and drop __path from the query) so Flask's routes match."""
    query = parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    path = next((v for k, v in query if k == "__path"), None)
    if path is not None:
        environ["PATH_INFO"] = path or "/"
        environ["QUERY_STRING"] = urlencode([(k, v) for k, v in query if k != "__path"])
    return _flask(environ, start_response)


app.wsgi_app = _original_path
