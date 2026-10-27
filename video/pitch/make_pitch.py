"""Builds the investor pitch video: designed slides + the live demo recording + neural voice-over.

    python video/pitch/make_pitch.py     # -> video/pitch/AI_Offer_Engine_Pitch.mp4

Needs build/<scene>.mp3 (voice, see script.py) and build/demo_marks.json (record_demo.py).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
BUILD = HERE / "build"
OUT = HERE / "AI_Offer_Engine_Pitch.mp4"
W, H = 1920, 1080
FONTS = Path("C:/Windows/Fonts")
sys.path.insert(0, str(HERE))
from script import SCENES  # noqa: E402

NAVY, NAVY2 = (9, 14, 30), (19, 30, 64)
WHITE, MUTED = (240, 244, 252), (150, 163, 190)
TEAL, BLUE, ORANGE, RED = (45, 212, 191), (77, 141, 255), (251, 146, 60), (248, 113, 113)
CARD, LINE = (22, 31, 58), (44, 58, 98)


def font(size, w="regular"):
    return ImageFont.truetype(str(FONTS / {"regular": "segoeui.ttf", "bold": "segoeuib.ttf", "semi": "seguisb.ttf",
                                           "light": "segoeuil.ttf", "black": "seguibl.ttf"}[w]), size)


EMOJI = ImageFont.truetype(str(FONTS / "seguiemj.ttf"), 109)  # colour emoji renders at 109 px


def emoji(img, ch, xy, size):
    tile = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((70, 70), ch, font=EMOJI, embedded_color=True, anchor="mm")
    tile = tile.resize((size, size), Image.LANCZOS)
    img.paste(tile, (int(xy[0] - size / 2), int(xy[1] - size / 2)), tile)


def background():
    img = Image.new("RGB", (W, H), NAVY)
    grad = Image.new("RGB", (W, H), NAVY2)
    mask = Image.linear_gradient("L").rotate(-35, expand=True).resize((W, H))
    img = Image.composite(grad, img, mask)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse([W - 700, -350, W + 300, 650], fill=(20, 70, 110))
    d.ellipse([-400, H - 450, 500, H + 400], fill=(40, 30, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.55).convert("RGBA")


def wrap(d, text, f, width):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = f"{cur} {wd}".strip()
        if d.textlength(t, font=f) <= width or not cur:
            cur = t
        else:
            lines.append(cur); cur = wd
    return lines + ([cur] if cur else [])


def kicker(d, text, y=110):
    d.rounded_rectangle([120, y, 120 + d.textlength(text, font=font(26, "bold")) + 40, y + 46], 23, fill=(30, 50, 90))
    d.text((140, y + 23), text, font=font(26, "bold"), fill=TEAL, anchor="lm")


def card(d, box, fill=CARD):
    d.rounded_rectangle(box, 28, fill=fill, outline=LINE, width=2)


def footer(d):
    d.text((120, H - 60), "AI Offer Engine", font=font(24, "semi"), fill=MUTED, anchor="lm")


# ---- Slides -------------------------------------------------------------------------------

def slide_hook():
    img = background(); d = ImageDraw.Draw(img)
    emoji(img, "💸", (W // 2, 300), 150)
    d.text((W // 2, 520), "Most discounts are wasted.", font=font(104, "bold"), fill=WHITE, anchor="mm")
    d.text((W // 2, 640), "They go to shoppers who were going to buy anyway.", font=font(46, "light"), fill=MUTED, anchor="mm")
    return [img]


def slide_problem():
    img = background(); d = ImageDraw.Draw(img)
    kicker(d, "THE PROBLEM")
    d.text((120, 240), "Blanket discounts burn margin", font=font(76, "bold"), fill=WHITE, anchor="lm")
    stats = [("🧾", "₹7,371", "a week on 10% off for everyone", ORANGE),
             ("🙈", "2 / 3", "of it went to people who'd buy anyway", RED),
             ("🔕", "Spam", "teaches shoppers to wait for sales, then unsubscribe", BLUE)]
    x0, cw, gap = 120, 530, 55
    for i, (ic, big, small, col) in enumerate(stats):
        x = x0 + i * (cw + gap)
        card(d, [x, 360, x + cw, 860])
        emoji(img, ic, (x + 90, 450), 80)
        d.text((x + 50, 590), big, font=font(104, "bold"), fill=col, anchor="lm")
        for j, ln in enumerate(wrap(d, small, font(36), cw - 100)):
            d.text((x + 50, 690 + j * 50), ln, font=font(36), fill=WHITE)
    d.text((120, 950), "Test store, 200 customers, one week (simulation calibrated on real data)", font=font(26), fill=MUTED, anchor="lm")
    return [img]


def slide_solution():
    img = background(); d = ImageDraw.Draw(img)
    kicker(d, "OUR SOLUTION")
    d.text((120, 250), "An AI offer engine", font=font(96, "bold"), fill=WHITE, anchor="lm")
    d.text((120, 345), "that decides for every customer, and only spends when it pays", font=font(46, "light"), fill=MUTED, anchor="lm")
    qs = [("🤔", "Offer or not?", "Most shoppers need nothing"), ("🎁", "Which offer?", "Reminder, perk, bundle, coupon…"),
          ("📏", "How big?", "Just enough, never at a loss")]
    for i, (ic, t, s) in enumerate(qs):
        x = 120 + i * 585
        card(d, [x, 470, x + 540, 860])
        emoji(img, ic, (x + 270, 580), 110)
        d.text((x + 270, 715), t, font=font(52, "bold"), fill=WHITE, anchor="mm")
        d.text((x + 270, 785), s, font=font(32), fill=MUTED, anchor="mm")
    return [img]


FLOW = [("🛒", "Store events", "sign-ups, carts, orders, wishlists"), ("📊", "Signals", "buy-anyway chance, risk of leaving"),
        ("🤖", "Claude picks", "most profitable offer + message"), ("✅", "31 rules check", "every decision, before sending"),
        ("🎫", "Coupon + message", "single-use, enforced at checkout"), ("📈", "Results", "profit measured vs a control group")]


def slide_flow():
    frames = []
    for shown in range(1, len(FLOW) + 1):
        img = background(); d = ImageDraw.Draw(img)
        kicker(d, "HOW IT FLOWS")
        d.text((120, 240), "From a click in the store to proven profit", font=font(70, "bold"), fill=WHITE, anchor="lm")
        bw, gap, y = 260, 40, 380
        for i, (ic, t, s) in enumerate(FLOW):
            x = 120 + i * (bw + gap)
            on = i < shown
            card(d, [x, y, x + bw, y + 420], fill=CARD if on else (14, 20, 40))
            if on:
                emoji(img, ic, (x + bw // 2, y + 95), 92)
                d.text((x + bw // 2, y + 205), t, font=font(29, "bold"), fill=WHITE, anchor="mm")
                for j, ln in enumerate(wrap(d, s, font(26), bw - 40)):
                    d.text((x + bw // 2, y + 265 + j * 36), ln, font=font(26), fill=MUTED, anchor="mm")
            if i < len(FLOW) - 1:
                ax = x + bw + 6
                d.polygon([(ax, y + 200), (ax + 26, y + 210), (ax, y + 220)], fill=TEAL if i < shown - 1 else LINE)
        if shown >= 4:
            d.rounded_rectangle([120 + 3 * (bw + gap), y + 450, 120 + 4 * (bw + gap) - gap, y + 530], 20, fill=(60, 30, 30))
            d.text((120 + 3 * (bw + gap) + bw // 2, y + 490), "AI fails? Rules take over", font=font(24, "bold"), fill=RED, anchor="mm")
        frames.append(img)
    return frames


WHY = [("💰", "Profit, not clicks", "Every offer must earn more than it costs"),
       ("🔒", "Never sells at a loss", "10% margin kept on any category"),
       ("🤖", "AI, always checked", "31 rules + automatic fallback"),
       ("💬", "Explains itself", "Plain-words reason for every decision"),
       ("⚡", "Runs on its own", "Events + daily check, one offer at a time"),
       ("🔬", "Real-data calibrated", "Flipkart · RetailRocket · 64,000-shopper test")]


def slide_why():
    frames = []
    for shown in range(1, len(WHY) + 1):
        img = background(); d = ImageDraw.Draw(img)
        kicker(d, "WHY WE WIN")
        d.text((120, 240), "Built to protect the margin", font=font(76, "bold"), fill=WHITE, anchor="lm")
        for i, (ic, t, s) in enumerate(WHY):
            col, row = i % 3, i // 3
            x, y = 120 + col * 575, 340 + row * 300
            on = i < shown
            card(d, [x, y, x + 535, y + 260], fill=CARD if on else (14, 20, 40))
            if on:
                emoji(img, ic, (x + 80, y + 80), 76)
                d.text((x + 140, y + 80), t, font=font(40, "bold"), fill=WHITE, anchor="lm")
                for j, ln in enumerate(wrap(d, s, font(32), 470)):
                    d.text((x + 40, y + 150 + j * 44), ln, font=font(32), fill=MUTED)
        frames.append(img)
    return frames


def slide_results():
    img = background(); d = ImageDraw.Draw(img)
    kicker(d, "RESULTS")
    d.text((120, 240), "3× the profit of a blanket discount", font=font(76, "bold"), fill=WHITE, anchor="lm")
    bars = [("10% to everyone", 2571, ORANGE), ("Rules only", 6801, BLUE), ("AI engine", 7635, TEAL)]
    base_y, top_y, x0 = 900, 420, 160
    scale = (base_y - top_y) / 8000
    d.line([x0 - 20, base_y, 1060, base_y], fill=LINE, width=3)
    for i, (label, v, col) in enumerate(bars):
        x = x0 + i * 300
        h = v * scale
        d.rounded_rectangle([x, base_y - h, x + 200, base_y], 18, fill=col)
        d.rectangle([x, base_y - 18, x + 200, base_y], fill=col)
        d.text((x + 100, base_y - h - 40), f"+₹{v:,}", font=font(44, "bold"), fill=WHITE, anchor="mm")
        d.text((x + 100, base_y + 40), label, font=font(30, "semi"), fill=MUTED, anchor="mm")
    d.text((x0 - 20, 380), "Extra margin per week vs sending nothing", font=font(28), fill=MUTED, anchor="lm")
    side = [("88%", "less spent on discounts", TEAL), ("₹51", "per extra sale (vs ₹358)", BLUE), ("+42%", "margin vs no offers", ORANGE)]
    for i, (big, small, col) in enumerate(side):
        y = 360 + i * 190
        card(d, [1180, y, 1800, y + 160])
        d.text((1230, y + 80), big, font=font(84, "bold"), fill=col, anchor="lm")
        lines = wrap(d, small, font(28), 290)
        for j, ln in enumerate(lines):
            d.text((1490, y + 80 + (j - (len(lines) - 1) / 2) * 36), ln, font=font(28), fill=WHITE, anchor="lm")
    d.text((120, 1000), "Simulation: 200 customers, 1,000 simulated weeks, calibrated on Flipkart, RetailRocket and Hillstrom data",
           font=font(24), fill=MUTED, anchor="lm")
    return [img]


def slide_ask():
    img = background(); d = ImageDraw.Draw(img)
    kicker(d, "WHAT'S NEXT")
    steps = [("📲", "Live pilot", "Telegram bot with real shoppers"), ("🔗", "Plug into any store", "Webhook + coupon API ready"),
             ("🤝", "We're looking for", "Pilot partners & investors")]
    for i, (ic, t, s) in enumerate(steps):
        x = 120 + i * 585
        card(d, [x, 230, x + 540, 560])
        emoji(img, ic, (x + 270, 330), 100)
        d.text((x + 270, 450), t, font=font(46, "bold"), fill=WHITE, anchor="mm")
        d.text((x + 270, 510), s, font=font(30), fill=MUTED, anchor="mm")
    d.text((W // 2, 720), "Smarter offers. Real profit.", font=font(110, "bold"), fill=WHITE, anchor="mm")
    d.text((W // 2, 830), "AI Offer Engine", font=font(44, "semi"), fill=TEAL, anchor="mm")
    return [img]


SLIDES = {"hook": slide_hook, "problem": slide_problem, "solution": slide_solution, "flow": slide_flow,
          "why": slide_why, "results": slide_results, "ask": slide_ask}
DEMO_CAPTIONS = {"demo_dashboard": "Live demo · the dashboard", "demo_customer": "Live demo · every decision explained",
                 "demo_bundle": "Live demo · “bought together” offers", "demo_signup": "Live demo · new customer, decided automatically",
                 "demo_cart": "Live demo · one live offer at a time, no spam"}


def caption_png(text, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    f = font(34, "bold")
    tw = d.textlength(text, font=f)
    d.rounded_rectangle([40, H - 110, 40 + tw + 90, H - 40], 35, fill=(9, 14, 30, 230))
    d.ellipse([62, H - 84, 80, H - 66], fill=(248, 80, 80, 255))
    d.text((95, H - 75), text, font=f, fill=WHITE, anchor="lm")
    img.save(path)


# ---- Assembly -------------------------------------------------------------------------------

def seconds(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True)


AUDIO = ["-af", "adelay=300|300,apad,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-c:a", "aac", "-b:a", "192k", "-ac", "2"]
VIDEO = ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30"]


def main():
    marks = json.loads((BUILD / "demo_marks.json").read_text())
    clips = []
    for i, s in enumerate(SCENES, 1):
        sid, voice = s["id"], BUILD / f"{s['id']}.mp3"
        clip = BUILD / f"clip{i:02}_{sid}.mp4"
        if s["kind"] == "slide":
            dur = seconds(voice) + 0.9
            frames = SLIDES[sid]()
            per = dur / len(frames)
            parts = []
            for k, fr in enumerate(frames):
                png = BUILD / f"{sid}_{k}.png"
                fr.convert("RGB").save(png)
                parts.append((png, per))
            # Each frame holds for its share of the narration; a slow push-in keeps the slide alive.
            listfile = BUILD / f"{sid}_frames.txt"
            listfile.write_text("".join(f"file '{p.as_posix()}'\nduration {d:.3f}\n" for p, d in parts) +
                                f"file '{parts[-1][0].as_posix()}'\n")
            zoom = f"fps=30,scale=2304:1296,zoompan=z='min(1+0.00012*on,1.03)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=30"
            ff("-f", "concat", "-safe", "0", "-i", listfile, "-i", voice,
               "-vf", f"{zoom},fade=t=in:st=0:d=0.35,fade=t=out:st={dur - 0.35:.2f}:d=0.35",
               *VIDEO, *AUDIO, "-t", f"{dur:.2f}", clip)
        else:
            start, end = marks["marks"][sid]
            dur = max(end - start, seconds(voice) + 0.9)
            cap = BUILD / f"cap_{sid}.png"
            caption_png(DEMO_CAPTIONS[sid], cap)
            ff("-ss", f"{start:.2f}", "-i", marks["video"], "-i", voice, "-i", cap,
               "-filter_complex", f"[0:v]scale={W}:{H}:flags=lanczos,fps=30,tpad=stop_mode=clone:stop_duration=5[v];"
                                  f"[v][2:v]overlay=0:0,fade=t=in:st=0:d=0.3,fade=t=out:st={dur - 0.3:.2f}:d=0.3[out]",
               "-map", "[out]", "-map", "1:a", *VIDEO, *AUDIO, "-t", f"{dur:.2f}", clip)
        clips.append(clip)
        print(f"{sid:16} {seconds(clip):5.1f}s", flush=True)
    lst = BUILD / "pitch_list.txt"
    lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips))
    ff("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", OUT)
    print(f"Wrote {OUT} ({seconds(OUT) / 60:.2f} min)")


if __name__ == "__main__":
    main()
