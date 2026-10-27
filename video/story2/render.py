"""Renders the high-energy demo video frame by frame (deterministic, no jitter).

A 1920x1080 stage (stage.html) captured at 2x and scaled down, the real app (demo server, port 5001)
inside an iframe, and every motion computed from the time t. Also writes build/timeline.json, which
make.py uses for the voice, music and sound-effect timing.

    python video/story2/render.py          # -> build/video.mp4 (picture only) + build/timeline.json
    FPS=2 python video/story2/render.py    # quick preview frames in build/preview/
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

LEAD = {"hook": .5, "reveal": .35, "proof": .55, "mvp": .45, "end": .5}  # demo scenes: .95 (after the step wipe)
TAIL = {"hook": .7, "reveal": .55, "list": 1.3, "customer": 1.5, "spend": 1.5, "phone": 2.0, "bundle": 1.4, "deal": 1.5,
        "wishlist": 1.4, "perk": 1.5, "guard": 1.6, "signup": 1.9, "cart": 1.7, "proof": 1.1, "mvp": .8, "end": 3.2}
DEMO = [s["id"] for s in SCENES if s["kind"] in ("demo", "phone")]


def seconds(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(2)) * 60 + float(m.group(3))


def norm(w):
    return re.sub(r"[^\w-]", "", w.lower())


class Track:
    """Collects camera keys, highlights, cursor moves, clicks, app actions and sound effects."""

    def __init__(self):
        self.camera = [{"t": 0, "fx": 960, "fy": 545, "s": 1.0}]
        self.highlights, self.cursor, self.clicks, self.cursor_windows, self.actions, self.sfx = [], [], [], [], [], []

    def _key(self, t, target=None, s=1.0, **kw):
        k = {"t": round(t, 3), "s": s}
        if target:
            k["target"] = target
        else:
            k.update(fx=kw.pop("fx", 960), fy=kw.pop("fy", 545))
        k.update(kw)
        return k

    def move(self, t, target=None, s=1.0, dur=.7, whoosh=True, **kw):
        t = max(t, self.camera[-1]["t"])  # a cue that comes early starts the move as soon as the previous one ends
        hold = dict(self.camera[-1], t=round(t, 3))
        self.camera += [hold, self._key(t + dur, target, s, **kw)]
        if whoosh:
            self.sfx.append({"k": "whoosh", "t": t, "g": .28})

    def cut(self, t, target=None, s=1.0, **kw):
        assert t >= self.camera[-1]["t"] - 1e-6, (t, self.camera[-1])
        self.camera += [dict(self.camera[-1], t=round(t, 3)), self._key(t + .001, target, s, **kw)]

    def hl(self, a, b, target, icon, title, sub="", side="left", tone=None, ring=True, pos=None):
        self.highlights.append({"a": round(a, 3), "b": round(b, 3), "target": target, "icon": icon, "title": title, "sub": sub,
                                "side": side, "tone": tone, "ring": ring, "pos": pos})
        self.sfx.append({"k": "pop", "t": a, "g": .7})

    def point(self, t, target=None, xy=None, move=None, **kw):
        c = {"t": round(t, 3)}
        if target:
            c["target"] = target
        if xy:
            c["xy"] = xy
        if move:
            c["move"] = move
        c.update(kw)
        self.cursor.append(c)

    def click(self, t):
        self.clicks.append(round(t, 3))
        self.sfx.append({"k": "click", "t": t, "g": 1.0})

    def act(self, t, name):
        self.actions.append((round(t, 3), name))


def build_timeline():
    words = json.loads((BUILD / "words.json").read_text())
    scenes, t = {}, 0.0
    for s in SCENES:
        lead = LEAD.get(s["id"], .95)
        voice = seconds(BUILD / f"{s['id']}.mp3")
        scenes[s["id"]] = {"a": round(t, 3), "voice": round(t + lead, 3), "b": round(t + lead + voice + TAIL[s["id"]], 3)}
        t = scenes[s["id"]]["b"]
    total = t

    def at(scene, word, n=0, offset=-.06):
        hits = [w for w in words[scene] if norm(w["w"]).startswith(norm(word))]
        if len(hits) <= n:
            raise KeyError(f"cue {word!r} #{n} not found in {scene}")
        return round(scenes[scene]["voice"] + hits[n]["t"] + offset, 3)

    S = {k: v["a"] for k, v in scenes.items()}
    B = {k: v["b"] for k, v in scenes.items()}
    tr = Track()
    sfx = tr.sfx

    # ---------------- hook ----------------
    h1_words = "Every online store has the same leak.".split()
    hw = words["hook"]
    h1 = [{"text": w, "hl": w.startswith("leak"), "at": round(scenes["hook"]["voice"] + hw[i]["t"] - .04, 3)} for i, w in enumerate(h1_words)]
    q_text = "What if every offer paid for itself?".split()
    q_at = [at("hook", "what"), at("hook", "if"), at("hook", "every", 3), at("hook", "offer"), at("hook", "paid"),
            at("hook", "for", 1), at("hook", "itself")]
    q = [{"text": w, "hl": i >= 4, "at": q_at[i]} for i, w in enumerate(q_text)]
    worse = at("hook", "Worse")
    hook = {"h1": h1, "h1out": at("hook", "Discounts") - .08, "h2": at("hook", "Discounts") - .04,
            "tix": at("hook", "Two") - .06, "stamps": [at("hook", "bought"), at("hook", "bought") + .3],
            "good": at("hook", "anyway") + .35, "grid": at("hook", "Send") - .06, "gridlbl": at("hook", "hundred"),
            "red": at("hook", "two", 1) - .05, "vanish": at("hook", "vanish"),
            "stac": at("hook", "every", 2) - .06, "sw": [at("hook", "every", 2), at("hook", "single"), at("hook", "week")],
            "notif": worse - .06, "nts": [worse - .05, worse + .25, worse + .55, worse + .85], "wait": at("hook", "wait"),
            "q": q, "qstart": at("hook", "So") - .06}
    for w in h1[:-1]:
        sfx.append({"k": "tick", "t": w["at"], "g": .8})
    sfx += [{"k": "impact", "t": h1[-1]["at"], "g": .8}, {"k": "boom", "t": hook["h2"], "g": .9}, {"k": "glitch", "t": hook["h2"], "g": .8},
            {"k": "whoosh", "t": hook["tix"], "g": .7}]
    sfx += [{"k": "pop", "t": hook["tix"] + i * .12, "g": .6} for i in range(3)]
    sfx += [{"k": "stamp", "t": s, "g": 1.0} for s in hook["stamps"]] + [{"k": "ding", "t": hook["good"], "g": .8}]
    sfx += [{"k": "whoosh", "t": hook["grid"], "g": .7}, {"k": "down", "t": hook["red"], "g": .9}]
    sfx += [{"k": "tick", "t": hook["red"] + i * .06, "g": .45} for i in range(20)]
    sfx += [{"k": "whoosh", "t": hook["vanish"], "g": .6}]
    sfx += [{"k": "impact", "t": s, "g": 1.0} for s in hook["sw"]]
    sfx += [{"k": "ping", "t": s, "g": .9} for s in hook["nts"]]
    drop = round(S["reveal"] + .25, 3)
    sfx += [{"k": f"riser:{drop - hook['qstart']:.2f}", "t": hook["qstart"], "g": .9}, {"k": "boom", "t": drop, "g": 1.2}]
    shakes = [{"t": h1[-1]["at"], "a": 10, "d": .3}, {"t": hook["h2"], "a": 26, "d": .5}] + \
             [{"t": s, "a": 14, "d": .25} for s in hook["stamps"]] + [{"t": hook["red"], "a": 6, "d": 1.3}] + \
             [{"t": s, "a": 22, "d": .35} for s in hook["sw"]] + [{"t": drop, "a": 30, "d": .6}]
    flashes = [{"t": hook["h2"], "d": .25, "s": .35}] + [{"t": s, "d": .16, "s": .22} for s in hook["sw"]] + [{"t": drop, "d": .6, "s": 1.0}]
    app_in = at("reveal", "see") - .25
    sfx.append({"k": "wipe", "t": app_in, "g": .7})

    # ---------------- demo ----------------
    wipes, steps = [], []
    for i, sid in enumerate(DEMO):
        title = next(s["step"] for s in SCENES if s["id"] == sid)
        wipes.append({"t": S[sid], "n": i + 1, "title": title})
        steps.append({"t": round(S[sid] + .5, 3), "n": i + 1, "title": title})
        sfx.append({"k": "wipe", "t": S[sid] - .05, "g": 1.0})
        sfx.append({"k": "impact", "t": S[sid] + .3, "g": .35})
    cover = lambda sid: S[sid] + .42  # the wipe fully covers the screen here: change the app underneath
    TT = {"ay": 260}  # focus the top part of the (tall) table

    # 01 list
    L = "list"
    tr.cut(cover(L) + .08, None, 1.0)
    tr.move(at(L, "dashboard"), "stats", 1.3, .7)
    tr.hl(at(L, "Two"), at(L, "Every") - .25, "stats", "📊", "200 shoppers, all decided", "180 by AI · 18 held back · ₹4,841 spent today", "below")
    tr.act(at(L, "Every"), "smooth:window:.toolbar:top:.8:30")
    tr.move(at(L, "Every"), "tableTop", 1.12, .8, **TT)
    tr.hl(at(L, "Every") + .8, at(L, "Sort") - .3, "tableTop", "📇", "Every shopper, one line", "orders · browsing · carts · wishlists · consent", ring=False, pos=[1160, 150])
    tr.cursor_windows.append([at(L, "Every") + .6, B[L]])
    tr.point(at(L, "Every") + .6, xy=[1500, 860])
    tr.point(at(L, "Sort") + .05, "sortSel", move=.6)
    tr.click(at(L, "Sort") + .1)
    tr.act(at(L, "Sort") + .15, "sort_chance")
    tr.move(at(L, "Sort") - .35, "toolbar", 1.3, .6)
    tr.hl(at(L, "Sort") + .35, at(L, "page") - .25, "sortSel", "↕️", "Sorted by buy chance", "most likely buyers first", "below")
    tr.act(at(L, "page") - .15, "smooth:window:#pager:end:.9:60")
    tr.move(at(L, "page") - .15, "pager", 1.3, .9)
    tr.point(at(L, "page") + .85, "page2", move=.6)
    tr.click(at(L, "page") + .9)
    tr.act(at(L, "page") + .95, "page2")
    tr.hl(at(L, "page") + 1.0, at(L, "lakhs") - .2, "pager", "📄", "Pages, not an endless list", "25 shoppers per page", "above")
    tr.act(at(L, "lakhs") - .1, "back_to_page1")
    tr.act(at(L, "lakhs") - .05, "smooth:window:.toolbar:top:.8:30")
    tr.move(at(L, "lakhs") - .05, "tableTop", 1.12, .8, **TT)
    tr.hl(at(L, "lakhs") + .6, at(L, "find") - .1, "tableTop", "⚡", "Fast with lakhs of customers", "paged API · search · filters", ring=False, pos=[1160, 150])
    tr.point(at(L, "find") - .1, "search", move=.6, fx=.15)
    tr.click(at(L, "find") - .05)
    tr.move(at(L, "find") - .2, "toolbar", 1.3, .6)
    tr.act(at(L, "find"), "focus_search")
    for i, ch in enumerate("Karthik"):
        tr.act(at(L, "find") + .2 + i * .08, f"type:{ch}")
        sfx.append({"k": "type", "t": at(L, "find") + .2 + i * .08, "g": .9})
    tr.hl(at(L, "Karthik") + .3, B[L] - .1, "search", "🔎", "Search: Karthik", "instant", "below")

    # 02 customer
    C = "customer"
    tr.act(cover(C), "open:U0008")
    tr.cut(cover(C) + .08, "chips", 1.5)
    tr.hl(at(C, "seven"), at(C, "Only") - .15, "cartChip", "🛒", "₹7,689 left in the cart", "9 hours ago", "left")
    tr.hl(at(C, "twelve"), at(C, "Claude") - .3, "chanceChip", "🎯", "12% chance he buys alone", "a small push could help", "left")
    tr.move(at(C, "Claude") - .3, "bubble", 1.55, .6)
    tr.hl(at(C, "Claude") + .35, at(C, "thirty-one") - .3, "bubble", "🤖", "Claude picks: cart reminder", "costs ₹0", "left")
    tr.move(at(C, "thirty-one") - .35, "why", 1.3, .7)
    tr.hl(at(C, "thirty-one") + .35, B[C] - .1, "why", "✅", "31 rules checked it", "and explained it in plain words", "left")

    # 03 spend
    SP = "spend"
    tr.act(cover(SP), "close_and_reset")
    tr.cut(cover(SP) + .08, "offerFilter", 1.35)
    tr.cursor_windows.append([S[SP] + .7, B[SP]])
    tr.point(S[SP] + .7, xy=[1400, 820])
    tr.point(at(SP, "Free") + .3, "cartBtn2", move=.7)
    tr.click(at(SP, "Free") + .35)
    tr.act(at(SP, "Free") + .4, "filter:CART_REMINDER")
    tr.move(at(SP, "Free") + .5, "osum", 1.3, .7)
    tr.hl(at(SP, "twenty-two"), at(SP, "Paid") - .7, "osum", "🆓", "22 shoppers · cost: Free", "a reminder costs ₹0", "below")
    tr.move(at(SP, "Paid") - .7, "offerFilter", 1.3, .5)
    tr.point(at(SP, "Paid") + .05, "shipBtn", move=.6)
    tr.click(at(SP, "Paid") + .1)
    tr.act(at(SP, "Paid") + .15, "filter:FREE_SHIPPING")
    tr.move(at(SP, "Paid") + .3, "osum", 1.3, .6)
    tr.hl(at(SP, "Paid") + .9, B[SP] - .1, "osum", "💰", "Paid only when it pays", "expected profit must beat the cost", "below")

    # 04 phone (the app is hidden: prepare the next step underneath)
    PH = "phone"
    tr.act(S[PH] + 1.5, "pick:BUNDLE_SUGGEST")
    days = at(PH, "Days")
    phone = {"msg0": at(PH, "friendly") - .25, "days": days, "dayT": [round(days + .35 + i * .38, 3) for i in range(5)],
             "msg1": at(PH, "discount") - .15}
    sfx += [{"k": "whoosh", "t": S[PH] + .35, "g": .6}, {"k": "msg", "t": phone["msg0"], "g": 1.0}, {"k": "msg", "t": phone["msg1"], "g": 1.0},
            {"k": "pop", "t": phone["msg0"] + .15, "g": .6}, {"k": "pop", "t": phone["msg1"] + .15, "g": .6}]
    sfx += [{"k": "tick", "t": d, "g": .9} for d in phone["dayT"]]
    sfx += [{"k": "ding", "t": phone["msg1"] + .3, "g": .5}]

    def open_row(sid, row_target, row_id, cue_t, bubble_s=1.55, go=True):
        tr.cut(cover(sid) + .08, "tableTop", 1.15, **TT)
        tr.cursor_windows.append([S[sid] + .75, cue_t + .6])
        tr.point(S[sid] + .75, xy=[1450, 860])
        tr.point(cue_t - .05, row_target, move=.6, fx=.15)
        tr.click(cue_t)
        tr.act(cue_t + .05, f"open:{row_id}")
        if go:
            tr.move(cue_t + .3, "bubble", bubble_s, .6)

    # 05 bundle
    BU = "bundle"
    open_row(BU, "row1", "U0048", at(BU, "Aditya"))
    tr.hl(at(BU, "Aditya") + .9, at(BU, "Eighteen") - .3, "bubble", "🧺", "Bought together · no discount", "lamp on wishlist → water purifier", "left")
    tr.move(at(BU, "Eighteen") - .3, "ruleRow", 1.5, .6)
    tr.hl(at(BU, "Eighteen") + .3, at(BU, "No") - .3, "ruleRow", "📈", "18 in 100 lamp buyers add it", "from real purchase data", "left")
    tr.move(at(BU, "No") - .3, "worthRow", 1.5, .5)
    tr.hl(at(BU, "eighty") - .2, B[BU] - .1, "worthRow", "💰", "+₹80 expected profit", "and it costs ₹0", "left")

    # 06 deal
    D = "deal"
    tr.act(cover(D), "pick:BUNDLE_DEAL")
    open_row(D, "row1", "U0077", at(D, "Ananya"))
    tr.hl(at(D, "Ananya") + .9, at(D, "money") - .3, "bubble", "🏷️", "₹40 off the add-on only", "SilkRoot hair dryer", "left")
    tr.move(at(D, "money") - .3, "ruleRow", 1.5, .6)
    tr.hl(at(D, "money") + .3, B[D] - .1, "ruleRow", "🔒", "Money rule ✓", "still ≥ 10% margin after ₹40 off", "left")

    # 07 wishlist
    W = "wishlist"
    tr.act(cover(W), "pick:WISHLIST_ALERT")
    open_row(W, "row1", "U0149", at(W, "moment") - .1, 1.6)
    tr.hl(at(W, "moment") + .8, at(W, "Real") - .3, "bubble", "👀", "The price really dropped", "₹1,209 → ₹909 · costs ₹0", "left")
    tr.move(at(W, "Real") - .3, "ruleRow", 1.5, .6)
    tr.hl(at(W, "Real") + .3, B[W] - .1, "ruleRow", "✅", "Honesty rule ✓", "only real price drops or restocks", "left")

    # 08 perk
    P = "perk"
    tr.act(cover(P), "pick:PERK_CHOICE")
    open_row(P, "diya", "U0184", at(P, "Diya") - .1, 1.45)
    tr.hl(at(P, "Diya") + .8, at(P, "free") - .3, "bubble", "🎁", "Diya picks her own perk", "40 days since her last order", "left")
    tr.move(at(P, "free") - .3, "perkOpts", 1.8, .6)
    tr.hl(at(P, "free") + .3, at(P, "Both") - .3, "perkOpts", "👆", "Free delivery or 240 points", "she replies 1 or 2", "left")
    tr.move(at(P, "Both") - .3, "whatRow", 1.5, .6)
    tr.hl(at(P, "Both") + .3, B[P] - .1, "whatRow", "⚖️", "Both cost the store the same", "₹60, only if used", "left")

    # 09 guard
    G = "guard"
    tr.act(cover(G), "pick:flagged")
    open_row(G, "vivaan", "U0171", at(G, "Here") - .1, go=False)
    tr.act(at(G, "Here") + .4, "smooth:#drawerBody:#drawerBody .err:center:.6")
    tr.move(at(G, "Here") + .4, "err", 1.55, .6)
    tr.hl(at(G, "caught") - .2, at(G, "fixed") - .35, "err", "🚫", "Caught: rule 15 ✕", "it claimed a price drop that didn't happen", "left", tone="bad")
    sfx.append({"k": "stamp", "t": at(G, "caught") - .2, "g": .9})
    tr.act(at(G, "fixed") - .35, "smooth:#drawerBody:#drawerBody .offer:top:.6")
    tr.move(at(G, "fixed") - .35, "bubble", 1.5, .6)
    tr.hl(at(G, "fixed") + .3, B[G] - .1, "bubble", "✅", "Fixed before sending", "true news: back in stock", "left")

    # 10 signup
    SU = "signup"
    tr.act(cover(SU), "close_and_all")
    tr.cut(cover(SU) + .08, "auto", 1.45)
    tr.hl(at(SU, "Automatic") - .1, at(SU, "new") - .4, "auto", "⚡", "Automatic decisions: ON", "every event + a daily check at 08:00", "above")
    tr.move(at(SU, "new") - .4, "gDecide", 1.4, .6)
    tr.cursor_windows.append([at(SU, "new") - .4, at(SU, "seconds") + .2])
    tr.point(at(SU, "new") - .4, xy=[1500, 860])
    tr.point(at(SU, "signs"), "newCustomer", move=.6)
    tr.click(at(SU, "signs") + .05)
    tr.act(at(SU, "signs") + .1, "signup")
    tr.move(at(SU, "seconds") - .1, "drawerTop", 1.3, .6)
    tr.hl(at(SU, "seconds") + .5, B[SU] - .1, "decider", "✨", "Decided automatically", "Claude + rules · nobody pressed a button", "left")
    sfx.append({"k": "ding", "t": at(SU, "seconds") + .5, "g": .6})

    # 11 cart
    K = "cart"
    tr.act(cover(K), "smooth:#drawerBody:#drawerBody .triggers:center:.05")
    tr.cut(cover(K) + .1, "triggers", 1.4)
    tr.cursor_windows.append([S[K] + .75, at(K, "already")])
    tr.point(S[K] + .75, xy=[1300, 900])
    tr.point(at(K, "leaves") - .05, "cartBtn", move=.6)
    tr.click(at(K, "leaves"))
    tr.act(at(K, "leaves") + .05, "cart")
    tr.act(at(K, "already") - .2, "smooth:#drawerBody:#drawerBody .why:center:.6")
    tr.move(at(K, "already") - .2, "ruleRow", 1.4, .6)
    tr.hl(at(K, "already") + .4, B[K] - .1, "ruleRow", "1️⃣", "One live offer at a time", "nothing new is sent · no spam", "left")

    # ---------------- proof, why we win, end ----------------
    PR = "proof"
    proof = {"src": [at(PR, "Flipkart"), at(PR, "browsing") - .4, at(PR, "sixty-four")], "bars": at(PR, "result"),
             "x3": at(PR, "Three"), "p88": at(PR, "eighty-eight")}
    flashes.append({"t": S[PR], "d": .35, "s": .5})
    sfx += [{"k": "boom", "t": S[PR], "g": .6}] + [{"k": "impact", "t": s, "g": .5} for s in proof["src"]]
    sfx += [{"k": "whoosh", "t": proof["bars"] + i * .25, "g": .6} for i in range(3)]
    sfx += [{"k": "boom", "t": proof["x3"], "g": .9}, {"k": "cash", "t": proof["p88"] + .5, "g": .9}]
    shakes += [{"t": proof["x3"], "a": 18, "d": .4}]
    flashes += [{"t": proof["x3"], "d": .2, "s": .25}]
    MV = "mvp"
    mvp = [dict(c, at=at(MV, c["cue"]) - .02) for c in next(s["cards"] for s in SCENES if s["id"] == MV)]
    flashes.append({"t": S[MV], "d": .3, "s": .4})
    sfx += [{"k": "whoosh", "t": S[MV], "g": .6}] + [{"k": "impact", "t": c["at"], "g": .7} for c in mvp]
    shakes += [{"t": c["at"], "a": 9, "d": .25} for c in mvp]
    E = "end"
    flashes.append({"t": S[E], "d": .5, "s": .6})
    shakes.append({"t": S[E], "a": 16, "d": .45})

    # ---------------- captions: karaoke chunks (not over the big kinetic text) ----------------
    captions = []
    for s in SCENES:
        if s["id"] in ("hook", "reveal", "mvp", "end"):
            continue
        tokens, ws = s["narration"].split(), words[s["id"]]
        if len(tokens) != len(ws):
            tokens = [w["w"] for w in ws]
        cur = []
        for i, w in enumerate(ws):
            cur.append(i)
            nxt = ws[i + 1] if i + 1 < len(ws) else None
            pause = nxt and nxt["t"] - (w["t"] + w["d"]) > .16
            end_punct = tokens[i][-1] in ".,?!:" if i < len(tokens) else False
            if not nxt or len(cur) >= 7 or (pause and len(cur) >= 3) or (end_punct and len(cur) >= 3):
                v = scenes[s["id"]]["voice"]
                captions.append({"a": round(v + ws[cur[0]]["t"], 3), "b": round(v + ws[cur[-1]]["t"] + ws[cur[-1]]["d"] + .25, 3),
                                 "words": [{"w": tokens[j], "t": round(v + ws[j]["t"], 3)} for j in cur]})
                cur = []
    for c, n in zip(captions, captions[1:]):
        c["b"] = min(c["b"], n["a"] - .02)

    tl = {"scenes": scenes, "total": total, "drop": drop, "final": S[E], "appIn": app_in, "hook": hook, "phone": phone,
          "proof": proof, "mvp": mvp, "captions": captions, "wipes": wipes, "steps": steps,
          "demo": [S["list"] + .45, B["cart"]], "appWindows": [[app_in, S["phone"] + .45], [S["bundle"] + .4, B["cart"]]],
          "camera": tr.camera, "highlights": tr.highlights, "cursor": tr.cursor, "clicks": tr.clicks,
          "cursorWindows": tr.cursor_windows, "shakes": shakes, "flashes": flashes,
          "sfx": sorted(sfx, key=lambda e: e["t"])}
    return tl, tr.actions


TARGETS = {
    "stats": "#stats", "auto": "#auto", "toolbar": ".toolbar", "search": "#search", "sortSel": "#sort", "tableTop": ".table-wrap",
    "pager": "#pager", "page2": "#pager button[data-page='2']", "row1": "#rows tr[data-id]", "karthik": "#rows tr[data-id='U0008']",
    "diya": "#rows tr[data-id='U0184']", "vivaan": "#rows tr[data-id='U0171']",
    "chips": "#drawerBody .chips", "cartChip": "#drawerBody .chip||cart left", "chanceChip": "#drawerBody .chip||buy in 7d",
    "bubble": "#drawerBody .bubble", "why": "#drawerBody .why", "whatRow": "#drawerBody .why-row:nth-of-type(4)",
    "worthRow": "#drawerBody .why-row:nth-of-type(5)", "ruleRow": "#drawerBody .why-row:nth-of-type(6)",
    "perkOpts": "#drawerBody .perk-opts", "err": "#drawerBody .err", "decider": "#drawerBody .decider",
    "triggers": "#drawerBody .triggers", "cartBtn": "#drawerBody button[data-trigger=cart_abandoned]",
    "offerFilter": "#offerFilter", "osum": "#offerSummary .osum", "cartBtn2": "button[data-offer=CART_REMINDER]",
    "shipBtn": "button[data-offer=FREE_SHIPPING]", "newCustomer": "#newCustomer", "gDecide": "section[aria-labelledby=g-decide]",
    "drawerTop": "#drawerBody .offer",
}
RECTS_JS = """([targets, t]) => {
  if (window.__tick) window.__tick(t);
  const out = {};
  for (const [k, spec] of Object.entries(targets)) {
    const [sel, text] = spec.split('||');
    const el = text ? [...document.querySelectorAll(sel)].find((e) => e.innerText.includes(text)) : document.querySelector(sel);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (r.width && r.height && r.bottom > 0 && r.top < innerHeight) out[k] = {x: r.left, y: r.top, w: r.width, h: r.height};
  }
  return out;
}"""
HELPER_JS = """() => {
  // smooth, frame-exact scrolling driven by the video time (no browser smooth-scroll timing)
  window.__smooth = (container, target, block, t0, dur, offset) => {
    const win = container === 'window';
    const el = win ? document.scrollingElement : document.querySelector(container);
    const tg = document.querySelector(target);
    if (!el || !tg) return;
    const from = el.scrollTop, r = tg.getBoundingClientRect();
    const cr = win ? {top: 0, height: innerHeight} : el.getBoundingClientRect();
    let to;
    if (block === 'top') to = from + r.top - cr.top - (offset || 0);
    else if (block === 'end') to = from + r.bottom - cr.top - cr.height + (offset || 0);
    else to = from + r.top - cr.top - (cr.height - r.height) / 2;
    to = Math.max(0, Math.min(to, el.scrollHeight - el.clientHeight));
    window.__sc = {el, from, to, t0, dur};
  };
  window.__tick = (t) => {
    const s = window.__sc; if (!s) return;
    const k = Math.min(1, Math.max(0, (t - s.t0) / s.dur));
    const e = k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
    s.el.scrollTop = s.from + (s.to - s.from) * e;
    if (k >= 1) window.__sc = null;
  };
}"""


def do(app, name, t):
    if name.startswith("smooth:"):
        _, container, target, block, dur, *off = name.split(":")
        app.evaluate("(a) => __smooth(...a)", [container, target, block, t, float(dur), float(off[0]) if off else 0])
    elif name == "sort_chance":
        app.evaluate("() => { const s = document.getElementById('sort'); s.value = 'chance'; s.dispatchEvent(new Event('change')); }")
        app.wait_for_timeout(600)
    elif name == "page2":
        app.evaluate("() => { state.page = 2; return load(); }")
        app.wait_for_timeout(400)
    elif name == "back_to_page1":
        app.evaluate("() => { const s = document.getElementById('sort'); s.value = 'name'; state.sort = 'name'; state.page = 1; return load(); }")
        app.wait_for_timeout(400)
    elif name == "focus_search":
        app.evaluate("() => { const s = document.getElementById('search'); s.focus(); s.value = ''; }")
    elif name.startswith("type:"):
        app.evaluate("(ch) => { const s = document.getElementById('search'); s.value += ch; s.dispatchEvent(new Event('input')); }", name[5:])
        if name == "type:k":
            app.wait_for_timeout(900)
    elif name.startswith("open:"):
        cid = name[5:]
        app.wait_for_selector(f"#rows tr[data-id='{cid}']")
        app.evaluate("(id) => document.querySelector(`#rows tr[data-id='${id}']`).click()", cid)
        app.wait_for_selector("#drawer.open .why")
        app.wait_for_timeout(300)
        app.evaluate("() => document.getElementById('drawerBody').scrollTo(0, 0)")
    elif name == "close_and_reset":
        app.evaluate("() => { closeCustomer(); const s = document.getElementById('search'); s.value = ''; state.q = ''; window.scrollTo(0, 0); }")
        app.evaluate("() => load()")
        app.wait_for_timeout(500)
    elif name.startswith("filter:"):
        app.evaluate("(k) => { state.offer = k; reload(); }", name[7:])
        app.wait_for_timeout(700)
        app.evaluate("(a) => __smooth(...a)", ["window", "#offerSummary", "center", t + .7, .6, 0])
    elif name.startswith("pick:"):
        key = name[5:]
        app.evaluate("""(k) => { closeCustomer(); const s = document.getElementById('search'); s.value = ''; state.q = '';
                                 document.getElementById('flaggedOnly').checked = k === 'flagged'; state.offer = k === 'flagged' ? '' : k;
                                 state.sort = 'name'; document.getElementById('sort').value = 'name'; state.page = 1; return load(); }""", key)
        app.wait_for_timeout(700)
        app.evaluate("() => window.scrollTo(0, document.querySelector('.toolbar').getBoundingClientRect().top + scrollY - 30)")
    elif name == "close_and_all":
        app.evaluate("""() => { closeCustomer(); state.offer = ''; document.getElementById('flaggedOnly').checked = false;
                                const s = document.getElementById('search'); s.value = ''; state.q = ''; window.scrollTo(0, 0); }""")
        app.evaluate("() => load()")
        app.wait_for_timeout(500)
    elif name == "signup":
        cid = next(f"N{i:06d}" for i in range(100001, 101000) if not in_holdout(f"N{i:06d}"))
        app.evaluate("""(cid) => sendEvent('signup', cid, {name: 'Riya Sharma', interest: 'Beauty', opted_in: true, channels: ['telegram']},
                                         document.getElementById('newCustomer'))""", cid)
        app.wait_for_selector("#drawer.open .why", timeout=180000)
        app.wait_for_function("() => document.querySelector('#banner').innerText.includes('signup')", timeout=180000)
        app.wait_for_timeout(400)
        app.evaluate("() => document.getElementById('drawerBody').scrollTo(0, 0)")
    elif name == "cart":
        app.evaluate("() => document.querySelector('#drawerBody button[data-trigger=cart_abandoned]').click()")
        app.wait_for_function("() => document.querySelector('#banner').innerText.includes('cart')", timeout=180000)
        app.wait_for_selector("#drawer.open .why")
        app.wait_for_timeout(400)
    else:
        raise KeyError(name)


def main():
    tl, actions = build_timeline()
    (BUILD / "timeline.json").write_text(json.dumps(tl, indent=1, ensure_ascii=False), encoding="utf-8")
    demo = sum(tl["scenes"][s]["b"] - tl["scenes"][s]["a"] for s in DEMO) + tl["scenes"]["reveal"]["b"] - tl["appIn"]
    print(f"total {tl['total']:.1f}s ({tl['total'] / 60:.2f} min), demo {demo:.0f}s = {demo / tl['total']:.0%}, "
          f"{len(tl['captions'])} captions, {len(tl['sfx'])} sfx", flush=True)
    if os.getenv("TIMELINE_ONLY"):
        return
    preview = FPS < 30
    out_dir = BUILD / ("preview" if preview else "frames")
    if preview:
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)  # full renders resume: frames already on disk are kept
    only = os.getenv("ONLY")  # preview a window, e.g. ONLY=60-90 (seconds)
    lo, hi = (float(x) for x in only.split("-")) if only else (0, 1e9)
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
        frame.evaluate(HELPER_JS)
        frame.wait_for_timeout(800)
        pending = sorted(actions)
        n = int(tl["total"] * FPS) + 1
        for i in range(n):
            t = i / FPS
            while pending and pending[0][0] <= t:
                at_, name = pending.pop(0)
                do(frame, name, at_)
            target = out_dir / f"f{i:05d}.jpg"
            if target.exists() or not lo <= t <= hi:
                frame.evaluate("(t) => window.__tick && __tick(t)", t)
                continue
            rects = frame.evaluate(RECTS_JS, [TARGETS, t])
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
