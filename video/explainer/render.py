"""Renders the long explainer frame by frame and pipes the frames straight into ffmpeg (no frame files).

Same approach as video/promo: a 1920x1080 stage (stage.html) captured at 2x and scaled down, the real
app (demo server, port 5001) inside an iframe, and every motion computed from the time t.

    python video/explainer/render.py          # -> build/video.mp4 (picture only) + build/timeline.json
    FPS=2 python video/explainer/render.py    # quick preview frames in build/preview/
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
BUILD = HERE / "build"
FPS = int(os.getenv("FPS", "30"))
APP = "http://localhost:5001/"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
from script import SCENES  # noqa: E402
from src.rules import in_holdout  # noqa: E402

TAIL = {"hook": .7, "problem": .9, "reveal": 1.3, "cards": 1.1, "formula": 1.2, "journey": 1.4, "results": 1.3,
        "tagline": 1.0, "end": 3.0, "dashboard": 1.0, "list": 1.0, "customer": 1.6, "bundle": 1.6, "signup": 1.8, "cart": 1.6}


def seconds(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(2)) * 60 + float(m.group(3))


def norm(w):
    return re.sub(r"[^\w-]", "", w.lower())


def build_timeline():
    words = json.loads((BUILD / "words.json").read_text())
    scenes, t = {}, 0.0
    for s in SCENES:
        lead = .8 if s["id"] == "hook" else .45
        tail = TAIL.get(s["id"], TAIL.get(s["kind"], 1.0))
        voice = seconds(BUILD / f"{s['id']}.mp3")
        scenes[s["id"]] = {"a": round(t, 3), "voice": round(t + lead, 3), "b": round(t + lead + voice + tail, 3)}
        t = scenes[s["id"]]["b"]
    total = t

    def cue(scene, word, after=0, offset=-.12):
        """Time the narrator starts saying `word` (first match at or after word index `after`)."""
        ws = words[scene]
        for i in range(after, len(ws)):
            if norm(ws[i]["w"]).startswith(norm(word)):
                return round(scenes[scene]["voice"] + ws[i]["t"] + offset, 3), i
        raise KeyError(f"cue {word!r} not found in {scene}")

    def at(scene, word, after=0):
        return cue(scene, word, after)[0]

    # Captions: the narration's own words, broken at pauses / punctuation / about 8 words.
    captions = []
    for s in SCENES:
        tokens, ws = s["narration"].split(), words[s["id"]]
        if len(tokens) != len(ws):
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
    headline = [{"text": w, "hl": i >= 5, "at": scenes["hook"]["voice"] + words["hook"][i]["t"]} for i, w in enumerate(head)]
    chips = [at("hook", "anyway"), at("hook", "sales"), at("hook", "unsubscribe")]
    tagline = [at("tagline", "Smarter"), at("tagline", "Zero"), at("tagline", "More")]

    card_scenes = []
    for s in SCENES:
        if s["kind"] != "cards":
            continue
        idx, cards = 0, []
        for c in s["cards"]:
            try:
                time_, idx = cue(s["id"], c["cue"], idx)
            except KeyError:
                time_ = scenes[s["id"]]["voice"] + .6 + len(cards) * .5
            cards.append(dict(c, at=time_))
        card_scenes.append({"id": s["id"], "kicker": s["kicker"], "title": s["title"], "cols": s.get("cols"), "cards": cards})

    formula = {"parts": [at("formula", "extra"), at("formula", "margin"), at("formula", "costs")],
               "examples": [at("formula", "everyone"), at("formula", "anyway")]}
    j0, _ = cue("journey", "first")
    journey = [
        {"label": "Start<br>(hand-made data)", "v": 7480, "color": "#64748b", "at": j0},
        {"label": "After rule<br>reviews", "v": 8105, "color": "#64748b", "at": j0 + .7},
        {"label": "Real-data<br>calibration", "v": 5857, "color": "#38bdf8", "at": at("journey", "Calibrating")},
        {"label": "Smarter profit<br>estimate", "v": 6591, "color": "#2ee6b8", "at": at("journey", "smarter")},
        {"label": "Safe<br>categories", "v": 6616, "color": "#2ee6b8", "at": at("journey", "safe")},
        {"label": "New offers<br>(now)", "v": 7635, "color": "#2ee6b8", "at": at("journey", "new")},
    ]

    # ---- live demo: camera, highlights, cursor, clicks and app actions
    S = {k: v["a"] for k, v in scenes.items()}
    D, L, C, B, G, K = S["dashboard"], S["list"], S["customer"], S["bundle"], S["signup"], S["cart"]
    d_time, d_ai, d_filter, d_type = at("dashboard", "time"), at("dashboard", "Let"), at("dashboard", "Filter"), at("dashboard", "type")
    d_tiles, d_auto = at("dashboard", "tiles"), at("dashboard", "automatically")
    l_sort, l_page = at("list", "sort"), at("list", "page")
    c_open = at("customer", "Open")
    b_type, b_sugg = at("bundle", "type"), at("bundle", "suggests")
    g_new, k_cart, k_live = at("signup", "new"), at("cart", "leaves"), at("cart", "live")

    full = {"fx": 960, "fy": 532, "s": 1.0}
    camera = [dict(full, t=0), dict(full, t=D + .4),
              {"t": d_time + .2, "target": "gTime", "s": 1.55}, {"t": d_ai - .3, "target": "gTime", "s": 1.55},
              {"t": d_ai + .4, "target": "gDecide", "s": 1.55}, {"t": d_filter - .3, "target": "gDecide", "s": 1.55},
              {"t": d_filter + .4, "target": "gShow", "s": 1.55}, {"t": d_type - .3, "target": "gShow", "s": 1.55},
              {"t": d_type + .4, "target": "gOffer", "s": 1.45}, {"t": d_tiles - .3, "target": "gOffer", "s": 1.45},
              {"t": d_tiles + .5, "target": "stats", "s": 1.3}, {"t": d_auto - .4, "target": "stats", "s": 1.3},
              {"t": d_auto + .4, "target": "auto", "s": 1.3}, {"t": L - .1, "target": "auto", "s": 1.3},
              {"t": L + .8, "target": "tableTop", "s": 1.25}, {"t": l_page - .3, "target": "tableTop", "s": 1.25},
              {"t": l_page + .5, "target": "pager", "s": 1.4}, {"t": C - .1, "target": "pager", "s": 1.4},
              {"t": C + .6, "target": "toolbar", "s": 1.35}, {"t": c_open + 1.4, "target": "toolbar", "s": 1.35},
              {"t": c_open + 2.4, "target": "why", "s": 1.32}, {"t": B - .1, "target": "why", "s": 1.32},
              {"t": B + .7, "target": "offerFilter", "s": 1.45}, {"t": b_type + 1.0, "target": "offerFilter", "s": 1.45},
              {"t": b_type + 1.9, "target": "osum", "s": 1.3}, {"t": b_sugg - .2, "target": "osum", "s": 1.3},
              {"t": b_sugg + .8, "target": "bubble", "s": 1.35}, {"t": G - .1, "target": "bubble", "s": 1.35},
              {"t": G + .6, "target": "decide", "s": 1.45}, {"t": g_new + 1.2, "target": "decide", "s": 1.45},
              {"t": g_new + 2.2, "target": "drawerTop", "s": 1.3}, {"t": K - .1, "target": "drawerTop", "s": 1.3},
              {"t": K + .6, "target": "triggers", "s": 1.4}, {"t": k_cart + 1.0, "target": "triggers", "s": 1.4},
              {"t": k_live - .2, "target": "ruleRow", "s": 1.35}, {"t": S["auto"] + .4, "target": "ruleRow", "s": 1.35}]
    highlights = [
        {"a": d_time + .4, "b": d_ai - .2, "target": "gTime", "icon": "🕒", "title": "Test any moment", "sub": "+1 hour · +1 day · +1 week", "side": "right"},
        {"a": d_ai + .6, "b": d_filter - .2, "target": "gDecide", "icon": "⚡", "title": "Choose offers", "sub": "AI on · decide for everyone · add a customer", "side": "right"},
        {"a": d_filter + .6, "b": d_type - .2, "target": "gShow", "icon": "🔍", "title": "Filter the list", "sub": "by group, or what needs a look", "side": "left"},
        {"a": d_type + .6, "b": d_tiles - .2, "target": "gOffer", "icon": "🎁", "title": "By offer type", "sub": "see who gets each offer", "side": "left"},
        {"a": d_tiles + .7, "b": d_auto - .2, "target": "aiTile", "icon": "🤖", "title": "Chosen by Claude", "sub": "180 decisions, all rule-checked", "side": "right"},
        {"a": d_auto + .6, "b": L - .1, "target": "auto", "icon": "⚡", "title": "Runs on its own", "sub": "store events + a daily check", "side": "below"},
        {"a": L + 1.0, "b": l_page - .2, "target": "toolbar", "icon": "🔎", "title": "Search · sort · pages", "sub": "only one page is ever loaded", "side": "below"},
        {"a": l_page + .7, "b": C - .1, "target": "pager", "icon": "⚡", "title": "Built for lakhs of shoppers", "sub": "filtering and paging on the server", "side": "left"},
        {"a": c_open + 2.5, "b": B - .1, "target": "why", "icon": "💬", "title": "Explained in plain words", "sub": "who, buy-anyway chance, worth it, rule", "side": "left"},
        {"a": b_type + 2.0, "b": b_sugg - .1, "target": "osum", "icon": "📊", "title": "Who gets it", "sub": "cost, buy chance, groups", "side": "below"},
        {"a": b_sugg + 1.0, "b": G - .1, "target": "bubble", "icon": "🧺", "title": "Bought together", "sub": "grows the basket, costs nothing", "side": "left"},
        {"a": g_new + 2.3, "b": K - .1, "target": "decider", "icon": "✨", "title": "Decided automatically", "sub": "no button pressed", "side": "left"},
        {"a": k_live, "b": S["auto"] + .3, "target": "ruleRow", "icon": "🛡️", "title": "One live offer at a time", "sub": "no spam, no stacked discounts", "side": "left"},
    ]
    cursor = [{"t": L, "xy": [1500, 900]}, {"t": l_sort, "target": "sortSel", "move": .7},
              {"t": l_page, "target": "page2", "move": .7},
              {"t": C + .2, "target": "page2"}, {"t": C + .9, "target": "search", "fx": .2, "move": .6},
              {"t": c_open, "target": "row0", "fx": .15, "move": .7},
              {"t": B + .2, "target": "row0", "fx": .15}, {"t": b_type + .5, "target": "bundleBtn", "move": .8},
              {"t": b_sugg, "target": "row0", "fx": .15, "move": .7},
              {"t": G + .2, "target": "row0", "fx": .15}, {"t": g_new + .4, "target": "newCustomer", "move": .8},
              {"t": K + .2, "target": "drawerTop", "fy": .9}, {"t": k_cart, "target": "cartBtn", "move": .8}]
    clicks = [l_sort, l_page, C + .95, c_open, b_type + .55, b_sugg, g_new + .45, k_cart + .05]
    cursor_windows = [[L + .2, b_sugg + 1.0], [G, g_new + 2.0], [K, k_cart + 1.4]]
    actions = [(l_sort + .05, "sort_chance"), (l_page + .05, "page2"),
               (C + .2, "back_to_page1"), (C + .95, "focus_search")] + \
              [(C + 1.05 + i * .08, f"type:{ch}") for i, ch in enumerate("Kabir")] + \
              [(c_open + .05, "open_row0"), (c_open + .4, "scroll_why"),
               (B + .1, "close_and_reset"), (b_type + .6, "filter_bundle"), (b_sugg + .05, "open_row0"), (b_sugg + .3, "scroll_bubble"),
               (G + .1, "close_and_all"), (g_new + .5, "signup"), (K + .1, "scroll_triggers"), (k_cart + .1, "cart"), (k_cart + .5, "scroll_rule")]
    tl = {"scenes": scenes, "total": total, "captions": captions, "headline": headline, "chips": chips, "tagline": tagline,
          "cardScenes": card_scenes, "formula": formula, "journey": journey,
          "camera": camera, "highlights": highlights, "cursor": cursor, "clicks": clicks, "cursorWindows": cursor_windows}
    return tl, actions


TARGETS = {
    "gTime": "section[aria-labelledby=g-time]", "gDecide": "section[aria-labelledby=g-decide]",
    "gShow": "section[aria-labelledby=g-show]", "gOffer": "section[aria-labelledby=g-offer]",
    "stats": "#stats", "aiTile": "#stats .tile.ai", "auto": "#auto", "toolbar": ".toolbar", "search": "#search",
    "sortSel": "#sort", "tableTop": ".table-wrap", "pager": "#pager", "page2": "#pager button[data-page='2']",
    "row0": "#rows tr[data-id]", "why": "#drawerBody .why", "offerFilter": "#offerFilter", "osum": "#offerSummary .osum",
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
    if name == "sort_chance":
        app.evaluate("() => { const s = document.getElementById('sort'); s.value = 'chance'; s.dispatchEvent(new Event('change')); }")
        app.wait_for_timeout(600)
    elif name == "page2":
        app.evaluate("() => document.querySelector(\"#pager button[data-page='2']\").click()")
        app.wait_for_timeout(600)
        app.evaluate("() => window.scrollTo(0, document.querySelector('.toolbar').getBoundingClientRect().top + scrollY - 40)")
    elif name == "back_to_page1":
        app.evaluate("() => { const s = document.getElementById('sort'); s.value = 'name'; state.sort = 'name'; state.page = 1; return load(); }")
        app.wait_for_timeout(500)
    elif name == "focus_search":
        app.evaluate("() => { const s = document.getElementById('search'); s.focus(); s.value = ''; }")
    elif name.startswith("type:"):
        app.evaluate("(ch) => { const s = document.getElementById('search'); s.value += ch; s.dispatchEvent(new Event('input')); }", name[5:])
        if name == "type:r":
            app.wait_for_timeout(900)
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
        app.wait_for_timeout(700)
        app.evaluate("() => document.getElementById('offerSummary').scrollIntoView({block: 'center'})")
    elif name == "close_and_all":
        app.evaluate("() => { closeCustomer(); state.offer = ''; window.scrollTo(0, 0); }")
        app.evaluate("() => load()")
        app.wait_for_timeout(500)
    elif name == "signup":
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
    print(f"total {tl['total']:.1f}s ({tl['total'] / 60:.1f} min), {len(tl['captions'])} captions", flush=True)
    preview = FPS < 30
    out_dir = BUILD / ("preview" if preview else "frames")
    if preview:
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)  # full renders resume: frames already on disk are kept
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1 if preview else 2, color_scheme="dark")
        page.goto((HERE / "stage.html").as_uri())
        page.wait_for_function("document.fonts.ready.then(() => true)")
        page.evaluate("(tl) => setup(tl)", tl)
        page.evaluate("(u) => { document.getElementById('app').src = u; }", APP)
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
            target = out_dir / f"f{i:05d}.jpg"
            if target.exists():  # resumed run: the app actions above still replay, the frame is already done
                continue
            rects = frame.evaluate(RECTS_JS, TARGETS)
            page.evaluate("([r, t]) => { setRects(r); renderAt(t); }", [rects, t])
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(page.screenshot(type="jpeg", quality=95))
            tmp.replace(target)
            if i % 300 == 0:
                print(f"frame {i}/{n} (t={t:.1f}s)", flush=True)
        browser.close()
    if not preview:  # encode: 2x frames scaled down (crisp), constant 30 fps
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(FPS), "-i", str(out_dir / "f%05d.jpg"),
                        "-vf", "scale=1920:1080:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p", "-color_range", "tv",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-profile:v", "high", "-r", str(FPS),
                        str(BUILD / "video.mp4")], check=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
