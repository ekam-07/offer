"""Renders the promo video frame by frame (deterministic: no jitter, no dropped frames).

The stage (stage.html) holds the background, titles, captions and a browser window with the REAL
app (demo server on port 5001) inside an iframe. For every frame we: perform any app action that is
due (type, click, open a customer, trigger an event: the app really decides), read where the
target elements are, call renderAt(t) on the stage, and take a 2x screenshot (downscaled later
for crisp text).

    python video/promo/render.py            # frames -> build/frames/*.jpg + build/timeline.json
"""
import json
import os
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.rules import in_holdout  # noqa: E402

HERE = Path(__file__).parent
BUILD = HERE / "build"
FRAMES = BUILD / "frames"
FPS = int(os.getenv("FPS", "30"))  # FPS=2 for a quick layout preview
APP = "http://localhost:5001/"
sys.path.insert(0, str(HERE))
from script import SCENES  # noqa: E402

LEAD = {"intro": .8}         # silence before the voice starts in a scene
TAIL = {"intro": .9, "reveal": 1.6, "dashboard": 1.0, "customer": 2.2, "bundle": 2.0, "signup": 2.0,
        "cart": 1.8, "results": 1.4, "tagline": .9, "end": 2.4}


def seconds(path):
    import re, subprocess
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(2)) * 60 + float(m.group(3))


def build_timeline():
    words = json.loads((BUILD / "words.json").read_text())
    scenes, t = {}, 0.0
    for s in SCENES:
        lead = LEAD.get(s["id"], .45)
        voice = seconds(BUILD / f"{s['id']}.mp3")
        scenes[s["id"]] = {"a": round(t, 3), "voice": round(t + lead, 3), "b": round(t + lead + voice + TAIL[s["id"]], 3)}
        t = scenes[s["id"]]["b"]
    total = t

    def wt(scene, i):  # absolute time of the i-th spoken word in a scene
        return scenes[scene]["voice"] + words[scene][i]["t"]

    def find(scene, word):
        return next(i for i, w in enumerate(words[scene]) if w["w"].lower().strip(".,") == word.lower())

    # Captions: the narration's own words (with punctuation), broken at pauses or every ~7 words.
    captions = []
    for s in SCENES:
        tokens, ws = s["narration"].split(), words[s["id"]]
        if len(tokens) != len(ws):  # fall back to the spoken words if they don't line up
            tokens = [w["w"] for w in ws]
        cur = []
        for i, w in enumerate(ws):
            cur.append(i)
            nxt = ws[i + 1] if i + 1 < len(ws) else None
            pause = nxt and nxt["t"] - (w["t"] + w["d"]) > .16
            end_punct = tokens[i][-1] in ".,?!:" if i < len(tokens) else False
            if not nxt or len(cur) >= 8 or (pause and len(cur) >= 3) or (end_punct and len(cur) >= 4):
                a = scenes[s["id"]]["voice"] + ws[cur[0]]["t"]
                b = scenes[s["id"]]["voice"] + ws[cur[-1]]["t"] + ws[cur[-1]]["d"] + .25
                captions.append({"a": round(a, 3), "b": round(b, 3), "text": " ".join(tokens[j] for j in cur)})
                cur = []
    for c, n in zip(captions, captions[1:]):
        c["b"] = min(c["b"], n["a"] - .02)

    head = "Online stores lose money on every discount.".split()
    headline = [{"text": w, "hl": i >= 5, "at": wt("intro", i)} for i, w in enumerate(head)]
    chips = [wt("intro", find("intro", "anyway")),
             wt("intro", find("intro", "sales")), wt("intro", find("intro", "unsubscribe"))]
    tagline = [wt("tagline", find("tagline", "Smarter")), wt("tagline", find("tagline", "Zero")), wt("tagline", find("tagline", "More"))]

    S = {k: v["a"] for k, v in scenes.items()}
    D, C, B, G, K = S["dashboard"], S["customer"], S["bundle"], S["signup"], S["cart"]
    full = {"fx": 960, "fy": 532, "s": 1.0}
    camera = [dict(full, t=0), dict(full, t=D + .3),
              {"t": D + 1.6, "target": "stats", "s": 1.32}, {"t": D + 5.2, "target": "stats", "s": 1.32},
              {"t": D + 6.4, "target": "auto", "s": 1.3}, {"t": C - .2, "target": "auto", "s": 1.3},
              {"t": C + .6, "target": "toolbar", "s": 1.35}, {"t": C + 1.9, "target": "toolbar", "s": 1.35},
              {"t": C + 2.9, "target": "why", "s": 1.32}, {"t": B - .2, "target": "why", "s": 1.32},
              {"t": B + .7, "target": "offerFilter", "s": 1.45}, {"t": B + 2.0, "target": "offerFilter", "s": 1.45},
              {"t": B + 3.0, "target": "bubble", "s": 1.35}, {"t": G - .2, "target": "bubble", "s": 1.35},
              {"t": G + .7, "target": "decide", "s": 1.45}, {"t": G + 1.8, "target": "decide", "s": 1.45},
              {"t": G + 2.8, "target": "drawerTop", "s": 1.3}, {"t": K - .2, "target": "drawerTop", "s": 1.3},
              {"t": K + .7, "target": "triggers", "s": 1.4}, {"t": K + 1.7, "target": "triggers", "s": 1.4},
              {"t": K + 2.7, "target": "ruleRow", "s": 1.35}, {"t": S["results"] + .4, "target": "ruleRow", "s": 1.35}]
    highlights = [
        {"a": D + 1.9, "b": D + 5.3, "target": "aiTile", "icon": "🤖", "title": "Chosen by Claude", "sub": "180 decisions, every one rule-checked", "side": "right"},
        {"a": D + 6.6, "b": C - .1, "target": "auto", "icon": "⚡", "title": "Runs on its own", "sub": "store events + a daily check", "side": "below"},
        {"a": C + 3.0, "b": B - .1, "target": "why", "icon": "💬", "title": "Explained in plain words", "sub": "who, buy-anyway chance, worth it, rule", "side": "left"},
        {"a": B + 3.1, "b": G - .1, "target": "bubble", "icon": "🧺", "title": "Bought together", "sub": "grows the basket, costs nothing", "side": "left"},
        {"a": G + 2.9, "b": K - .1, "target": "decider", "icon": "✨", "title": "Decided automatically", "sub": "no button pressed", "side": "left"},
        {"a": K + 2.8, "b": S["results"] + .3, "target": "ruleRow", "icon": "🛡️", "title": "One live offer at a time", "sub": "no spam, no stacked discounts", "side": "left"},
    ]
    cursor = [{"t": C, "xy": [1500, 900]}, {"t": C + .55, "target": "search", "fx": .2, "move": .5},
              {"t": C + 1.75, "target": "row0", "fx": .15, "move": .6},
              {"t": B + .2, "target": "row0", "fx": .15}, {"t": B + 1.2, "target": "bundleBtn", "move": .7},
              {"t": G + .2, "target": "bundleBtn"}, {"t": G + 1.25, "target": "newCustomer", "move": .8},
              {"t": K + .2, "target": "drawerTop", "fy": .9}, {"t": K + 1.2, "target": "cartBtn", "move": .8}]
    clicks = [C + .6, C + 1.8, B + 1.25, G + 1.3, K + 1.25]
    cursor_windows = [[C - .1, B + 2.4], [G, G + 2.2], [K, K + 2.2]]
    actions = [  # (time, name) performed in the app just before that frame
        (C + .6, "focus_search"), (C + .7, "type:K"), (C + .78, "type:a"), (C + .86, "type:b"), (C + .94, "type:i"),
        (C + 1.02, "type:r"), (C + 1.8, "open_row0"), (C + 2.2, "scroll_why"),
        (B + .1, "close_and_reset"), (B + 1.25, "filter_bundle"), (B + 2.1, "open_row0"), (B + 2.4, "scroll_bubble"),
        (G + .1, "close_and_all"), (G + 1.3, "signup"), (K + .1, "scroll_triggers"), (K + 1.25, "cart"), (K + 1.6, "scroll_rule"),
    ]
    tl = {"scenes": scenes, "total": total, "captions": captions, "headline": headline, "chips": chips, "tagline": tagline,
          "camera": camera, "highlights": highlights, "cursor": cursor, "clicks": clicks, "cursorWindows": cursor_windows}
    return tl, actions


TARGETS = {
    "stats": "#stats", "aiTile": "#stats .tile.ai", "auto": "#auto", "toolbar": ".toolbar", "search": "#search",
    "row0": "#rows tr[data-id]", "why": "#drawerBody .why", "offerFilter": "#offerFilter",
    "bundleBtn": "button[data-offer=BUNDLE_SUGGEST]", "bubble": "#drawerBody .bubble", "decide": "#newCustomer",
    "newCustomer": "#newCustomer", "drawerTop": "#drawerBody .offer", "decider": "#drawerBody .decider",
    "triggers": "#drawerBody .triggers", "cartBtn": "#drawerBody button[data-trigger=cart_abandoned]",
    "ruleRow": "#drawerBody .why-row:nth-of-type(6)",
}
RECTS_JS = """(targets) => {
  const out = {};
  for (const [k, sel] of Object.entries(targets)) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (r.width && r.height && r.bottom > 0 && r.top < innerHeight) out[k] = {x: r.left, y: r.top, w: r.width, h: r.height};
  }
  return out;
}"""


def do(app, name):
    if name == "focus_search":
        app.evaluate("() => { const s = document.getElementById('search'); s.focus(); s.value = ''; }")
    elif name.startswith("type:"):
        app.evaluate("(ch) => { const s = document.getElementById('search'); s.value += ch; s.dispatchEvent(new Event('input')); }", name[5:])
        if name == "type:r":
            app.wait_for_timeout(900)  # search debounce + reload
    elif name == "open_row0":
        app.evaluate("() => document.querySelector('#rows tr[data-id]').click()")
        app.wait_for_selector("#drawer.open .why")
        app.wait_for_timeout(200)
    elif name in ("scroll_why", "scroll_bubble", "scroll_triggers", "scroll_rule"):
        sel = {"scroll_why": "#drawerBody .why", "scroll_bubble": "#drawerBody .offer", "scroll_triggers": "#drawerBody .triggers",
               "scroll_rule": "#drawerBody .why"}[name]
        app.evaluate("(s) => document.querySelector(s)?.scrollIntoView({block: 'center'})", sel)
    elif name == "close_and_reset":
        app.evaluate("() => { closeCustomer(); const s = document.getElementById('search'); s.value = ''; state.q = ''; window.scrollTo(0, 0); }")
        app.evaluate("() => load()")
        app.wait_for_timeout(500)
    elif name == "filter_bundle":
        app.evaluate("() => document.querySelector('button[data-offer=BUNDLE_SUGGEST]').click()")
        app.wait_for_timeout(600)
    elif name == "close_and_all":
        app.evaluate("() => { closeCustomer(); state.offer = ''; window.scrollTo(0, 0); }")
        app.evaluate("() => load()")
        app.wait_for_timeout(500)
    elif name == "signup":
        # Same as pressing "A new customer signs up", with an ID outside the 15% control group (a control-group
        # customer would rightly get no offer, which isn't what this scene shows).
        cid = next(f"N{i:06d}" for i in range(100001, 101000) if not in_holdout(f"N{i:06d}"))
        app.evaluate("""(cid) => sendEvent('signup', cid, {name: 'Ananya Rao', interest: 'Beauty', opted_in: true, channels: ['telegram']},
                                         document.getElementById('newCustomer'))""", cid)
        app.wait_for_selector("#drawer.open .why", timeout=120000)
        app.wait_for_function("() => document.querySelector('#banner').innerText.includes('signup')", timeout=120000)
        app.wait_for_timeout(400)
    elif name == "cart":
        app.evaluate("() => document.querySelector('#drawerBody button[data-trigger=cart_abandoned]').click()")
        app.wait_for_function("() => document.querySelector('#banner').innerText.includes('cart')", timeout=120000)
        app.wait_for_selector("#drawer.open .why")
        app.wait_for_timeout(400)


def main():
    tl, actions = build_timeline()
    (BUILD / "timeline.json").write_text(json.dumps(tl, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"total {tl['total']:.1f}s, {len(tl['captions'])} captions")
    if FRAMES.exists():
        shutil.rmtree(FRAMES)
    FRAMES.mkdir(parents=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2, color_scheme="dark")
        page.goto((HERE / "stage.html").as_uri())
        page.wait_for_function("document.fonts.ready.then(() => true)")
        page.evaluate("(tl) => setup(tl)", tl)
        page.evaluate("(u) => { document.getElementById('app').src = u; }", APP)
        app = page.frame_locator("#app")
        page.wait_for_timeout(500)
        frame = next(f for f in page.frames if f.url.startswith(APP))
        frame.wait_for_selector("#rows tr[data-id]")
        frame.add_style_tag(content="*, *::before, *::after { transition: none !important; animation: none !important; } #tip { display: none !important; } ::-webkit-scrollbar { width: 0; height: 0; }")
        frame.evaluate("() => { document.getElementById('now').value = '2026-10-16T14:00'; return load(); }")
        frame.wait_for_timeout(800)
        pending = sorted(actions)
        n = int(tl["total"] * FPS) + 1
        for i in range(n):
            t = i / FPS
            while pending and pending[0][0] <= t:
                do(frame, pending.pop(0)[1])
            rects = frame.evaluate(RECTS_JS, TARGETS)
            page.evaluate("([r, t]) => { setRects(r); renderAt(t); }", [rects, t])
            page.screenshot(path=str(FRAMES / f"f{i:05d}.jpg"), type="jpeg", quality=94)
            if i % 150 == 0:
                print(f"frame {i}/{n} (t={t:.1f}s)", flush=True)
        browser.close()
    print("done")


if __name__ == "__main__":
    main()
