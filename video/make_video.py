"""Builds the explainer video: slides (PIL + matplotlib), voice-over (Windows speech, offline) and MP4 (ffmpeg).

    python video/make_video.py            # writes video/AI_Offer_Engine_Explainer.mp4
    python video/make_video.py --slides   # slides only (to check the layout)

Scenes and narration live in video/script.py. Screenshots come from video/capture.py.
"""
import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from script import SCENES  # noqa: E402

HERE = Path(__file__).parent
BUILD = HERE / "build"
OUT = HERE / "AI_Offer_Engine_Explainer.mp4"
W, H = 1920, 1080
FONTS = Path("C:/Windows/Fonts")
VOICE = "Microsoft Zira Desktop"
PAUSE_S = 0.7

BG, INK, MUTED, LINE = "#f7f8fb", "#14161c", "#52514e", "#dcdfe6"
ACCENT, ACCENT_SOFT = "#2a78d6", "#e6effb"
SERIES = {"blanket": "#eb6834", "rules": "#2a78d6", "ai": "#1baf7a", "none": "#a3a29d"}


def font(size, weight="regular"):
    name = {"regular": "segoeui.ttf", "bold": "segoeuib.ttf", "semi": "seguisb.ttf", "light": "segoeuil.ttf"}[weight]
    return ImageFont.truetype(str(FONTS / name), size)


def rupee(text):
    return text.replace("Rs ", "₹").replace("Rs", "₹")


def wrap(draw, text, f, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=f) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def base(title, idx):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 150], fill="white")
    d.line([0, 150, W, 150], fill=LINE, width=2)
    d.rectangle([0, 0, 14, 150], fill=ACCENT)
    d.text((80, 75), rupee(title), font=font(58, "bold"), fill=INK, anchor="lm")
    d.text((80, H - 40), "AI Offer Engine", font=font(24, "semi"), fill=MUTED, anchor="lm")
    d.text((W - 80, H - 40), f"{idx}/{len(SCENES)}", font=font(24), fill=MUTED, anchor="rm")
    return img, d


def bullets(d, items, box, size=40):
    x0, y, x1, _ = box
    for item in items:
        sub = item.startswith("  ")
        f = font(size - 6 if sub else size)
        indent = 60 if sub else 0
        lines = wrap(d, rupee(item.strip()), f, x1 - x0 - 50 - indent)
        r = 7 if sub else 9
        cy = y + f.size * 0.62
        d.ellipse([x0 + indent, cy - r, x0 + indent + 2 * r, cy + r], fill=ACCENT if not sub else "#8fb4e8")
        for ln in lines:
            d.text((x0 + indent + 40, y), ln, font=f, fill=INK)
            y += int(f.size * 1.32)
        y += int(f.size * 0.45)
    return y


def paste_fit(img, path, box, border=True):
    x0, y0, x1, y1 = box
    im = Image.open(path).convert("RGB")
    scale = min((x1 - x0) / im.width, (y1 - y0) / im.height)
    im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    px, py = x0 + (x1 - x0 - im.width) // 2, y0 + (y1 - y0 - im.height) // 2
    if border:
        ImageDraw.Draw(img).rounded_rectangle([px - 3, py - 3, px + im.width + 2, py + im.height + 2], 6, outline=LINE, width=3)
    img.paste(im, (px, py))
    return px, py, scale


def slide_title(s, idx):
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 18], fill=ACCENT)
    d.text((W // 2, 430), s["title"], font=font(110, "bold"), fill=INK, anchor="mm")
    for i, ln in enumerate(wrap(d, s["subtitle"], font(46, "light"), 1500)):
        d.text((W // 2, 560 + i * 64), ln, font=font(46, "light"), fill=MUTED, anchor="mm")
    d.rounded_rectangle([W // 2 - 60, 660 + 60, W // 2 + 60, 668 + 60], 4, fill=ACCENT)
    d.text((W // 2, 840), "Claude decides  ·  31 rules check  ·  measured on real-data-calibrated customers",
           font=font(30), fill=MUTED, anchor="mm")
    return img


def slide_bullets(s, idx):
    img, d = base(s["title"], idx)
    bullets(d, s["bullets"], (110, 215, W - 110, H - 100))
    return img


def slide_table(s, idx):
    img, d = base(s["title"], idx)
    cols = len(s["header"])
    widths = {2: [0.5, 0.5], 3: [0.22, 0.4, 0.38], 4: [0.31, 0.21, 0.21, 0.27]}[cols]
    x0, x1, y = 90, W - 90, 200
    xs = [x0]
    for wpart in widths:
        xs.append(xs[-1] + int((x1 - x0) * wpart))
    fh, fc = font(32, "bold"), font(31)
    d.rounded_rectangle([x0, y, x1, y + 66], 10, fill=ACCENT)
    for i, h in enumerate(s["header"]):
        d.text((xs[i] + 22, y + 33), h, font=fh, fill="white", anchor="lm")
    y += 66
    row_h_min = 78 if not s.get("notes") else 70
    for r, row in enumerate(s["rows"]):
        cells = [wrap(d, rupee(c), fc, xs[i + 1] - xs[i] - 40) for i, c in enumerate(row)]
        rh = max(row_h_min, max(len(c) for c in cells) * 42 + 26)
        d.rectangle([x0, y, x1, y + rh], fill="white" if r % 2 == 0 else "#eef1f6")
        for i, lines in enumerate(cells):
            ty = y + (rh - len(lines) * 42) // 2
            for ln in lines:
                d.text((xs[i] + 22, ty), ln, font=font(31, "semi") if i == 0 else fc, fill=INK)
                ty += 42
        y += rh
    d.rectangle([x0, 200, x1, y], outline=LINE, width=2)
    if s.get("notes"):
        bullets(d, s["notes"], (110, y + 40, W - 110, H - 90), size=31)
    return img


def slide_flow(s, idx):
    img, d = base(s["title"], idx)
    steps = s["steps"]
    bw, bh, gap = 500, 250, 120
    total = 3 * bw + 2 * gap
    left = (W - total) // 2
    for i, (head, sub) in enumerate(steps):
        row, col = divmod(i, 3)
        col = col if row == 0 else 2 - col  # snake: left-to-right, then right-to-left
        x, y = left + col * (bw + gap), 240 + row * (bh + 170)
        d.rounded_rectangle([x, y, x + bw, y + bh], 22, fill="white", outline=ACCENT, width=4)
        d.rounded_rectangle([x, y, x + bw, y + 74], 22, fill=ACCENT_SOFT)
        d.rectangle([x, y + 50, x + bw, y + 74], fill=ACCENT_SOFT)
        d.rounded_rectangle([x, y, x + bw, y + bh], 22, outline=ACCENT, width=4)
        d.text((x + bw // 2, y + 38), head, font=font(38, "bold"), fill=INK, anchor="mm")
        for j, ln in enumerate(wrap(d, sub, font(32), bw - 60)):
            d.text((x + bw // 2, y + 120 + j * 44), ln, font=font(32), fill=MUTED, anchor="mm")
        if i < len(steps) - 1:
            if row == 0 and col < 2:
                ax, ay = x + bw + 15, y + bh // 2
                d.line([ax, ay, ax + gap - 30, ay], fill=ACCENT, width=6)
                d.polygon([(ax + gap - 30, ay - 14), (ax + gap - 10, ay), (ax + gap - 30, ay + 14)], fill=ACCENT)
            elif row == 0:
                ax, ay = x + bw // 2, y + bh + 15
                d.line([ax, ay, ax, ay + 125], fill=ACCENT, width=6)
                d.polygon([(ax - 14, ay + 125), (ax, ay + 145), (ax + 14, ay + 125)], fill=ACCENT)
            else:
                ax, ay = x - 15, y + bh // 2
                d.line([ax, ay, ax - gap + 30, ay], fill=ACCENT, width=6)
                d.polygon([(ax - gap + 30, ay - 14), (ax - gap + 10, ay), (ax - gap + 30, ay + 14)], fill=ACCENT)
    return img


def slide_image(s, idx):
    img, d = base(s["title"], idx)
    if s.get("side"):
        paste_fit(img, HERE / s["image"], (110, 190, 900, H - 90))
        bullets(d, s["side"], (980, 250, W - 100, H - 100), size=38)
    else:
        paste_fit(img, HERE / s["image"], (70, 180, W - 70, H - 80))
    return img


def slide_highlight(s, idx):
    img, d = base(s["title"], idx)
    if s.get("crop") is None:
        paste_fit(img, HERE / s["image"], (110, 190, 900, H - 90))
        bullets(d, s["lines"], (980, 260, W - 100, H - 100), size=38)
        return img
    boxes = json.loads((HERE / "shots" / "boxes.json").read_text())
    cx0, cy0, cx1, cy1 = s["crop"]
    k = s.get("scale", 1)  # image pixels per CSS pixel (2 for the sharp screenshot)
    full = Image.open(HERE / s["image"]).convert("RGB")
    src = full.crop((cx0 * k, cy0 * k, cx1 * k, cy1 * k))
    if s.get("split"):  # a very wide strip: show its two halves stacked, no boxes
        half = int((s["split"] - cx0) * k) if s["split"] is not True else src.width // 2
        stacked = Image.new("RGB", (max(half, src.width - half), src.height * 2 + 12), "white")
        stacked.paste(src.crop((0, 0, half, src.height)), (0, 0))
        stacked.paste(src.crop((half, 0, src.width, src.height)), (0, src.height + 12))
        stacked.save(BUILD / f"crop_{idx}.png")
        paste_fit(img, BUILD / f"crop_{idx}.png", (60, 210, W - 60, 560))
        bullets(d, s["lines"], (130, 640, W - 130, H - 100), size=42)
        return img
    tmp = BUILD / f"crop_{idx}.png"
    src.save(tmp)
    wide = (cx1 - cx0) / (cy1 - cy0) > 3
    area = (60, 210, W - 60, 560) if wide else (90, 185, 1000, H - 85)
    px, py, sc = paste_fit(img, tmp, area)
    sc *= k
    groups = [[k] for k in s["boxes"]]
    for union in s.get("union", []):
        groups = [g for g in groups if g[0] not in union] + [union]
    for g in groups:
        bs = [boxes[k] for k in g]
        bx0 = min(b["x"] for b in bs) - 6
        by0 = min(b["y"] for b in bs) - 6
        bx1 = max(b["x"] + b["width"] for b in bs) + 6
        by1 = max(b["y"] + b["height"] for b in bs) + 6
        rect = [px + (bx0 - cx0) * sc, py + (by0 - cy0) * sc, px + (bx1 - cx0) * sc, py + (by1 - cy0) * sc]
        d.rounded_rectangle(rect, 10, outline="#eb6834", width=6)
    if wide:
        bullets(d, s["lines"], (130, 600, W - 130, H - 100), size=42)
    else:
        bullets(d, s["lines"], (1070, 260, W - 90, H - 100), size=38)
    return img


def slide_formula(s, idx):
    img, d = base(s["title"], idx)
    d.rounded_rectangle([140, 220, W - 140, 400], 24, fill="white", outline=ACCENT, width=5)
    d.text((W // 2, 310), s["formula"].replace(" x ", " × "), font=font(62, "bold"), fill=INK, anchor="mm")
    y = 470
    for i, ln in enumerate(s["lines"]):
        f = font(40, "semi" if i >= 3 else "regular")
        color = {3: "#127a55", 4: "#b5401a"}.get(i, INK)
        d.text((180, y), rupee(ln).replace(" x ", " × "), font=f, fill=color)
        y += 82 if i == 1 else 70
    return img


def chart(kind):
    plt.rcParams.update({"font.family": "Segoe UI", "font.size": 15, "axes.edgecolor": LINE,
                         "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED})
    path = BUILD / f"chart_{kind}.png"
    if kind == "journey":
        stages = ["Start\n(hand-made data)", "After rule reviews\n(hand-made data)",
                  "Real-data calibration", "Tuned (now)"]
        series = [("10% to everyone", "blanket", [-1069, -1069, 1048, 1048]),
                  ("Rules only", "rules", [7077, 7757, 5065, 5817]),
                  ("AI first + rules", "ai", [7480, 8105, 5857, 6591])]
        fig, ax = plt.subplots(figsize=(17, 8.2), dpi=100)
        bw = 0.26
        for j, (label, key, vals) in enumerate(series):
            xs = [i + (j - 1) * (bw + 0.02) for i in range(len(stages))]
            bars = ax.bar(xs, vals, bw, color=SERIES[key], label=label, zorder=3)
            for b, v in zip(bars, vals):
                ax.text(b.get_x() + b.get_width() / 2, v + (180 if v >= 0 else -180), f"{v:+,}",
                        ha="center", va="bottom" if v >= 0 else "top", fontsize=15, color=INK)
        ax.axvline(1.5, color=MUTED, linestyle=(0, (4, 4)), linewidth=1.5)
        ax.text(0.5, 9300, "Guessed customer behaviour", ha="center", color=MUTED, fontsize=16)
        ax.text(2.5, 9300, "Calibrated from real datasets", ha="center", color=MUTED, fontsize=16)
        ax.set_ylim(-2200, 10000)
        ax.set_xticks(range(len(stages)), stages, fontsize=17, color=INK)
        ax.set_ylabel("₹ extra net margin per week vs no offers")
        ax.axhline(0, color=MUTED, linewidth=1)
    else:
        fig, (ax, ax2) = plt.subplots(1, 2, figsize=(17, 8.2), dpi=100, gridspec_kw={"width_ratios": [1.25, 1]})
        names = ["No offers", "10% to\neveryone", "Rules only", "AI first\n+ rules"]
        keys = ["none", "blanket", "rules", "ai"]
        vals = [18345, 19393, 24162, 24936]
        bars = ax.bar(names, vals, 0.6, color=[SERIES[k] for k in keys], zorder=3)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 300, f"₹{v:,}", ha="center", va="bottom", fontsize=16, color=INK)
        ax.set_title("Net margin per week", fontsize=19, color=INK, loc="left", pad=14)
        ax.set_ylim(0, 28500)
        ax.tick_params(axis="x", labelsize=16, labelcolor=INK)
        n2, k2 = names[1:], keys[1:]
        cost = [343, 113, 65]
        bars = ax2.bar(n2, cost, 0.55, color=[SERIES[k] for k in k2], zorder=3)
        for b, v in zip(bars, cost):
            ax2.text(b.get_x() + b.get_width() / 2, v + 6, f"₹{v}", ha="center", va="bottom", fontsize=16, color=INK)
        ax2.set_title("Discount cost per extra purchase", fontsize=19, color=INK, loc="left", pad=14)
        ax2.set_ylim(0, 400)
        ax2.tick_params(axis="x", labelsize=16, labelcolor=INK)
        for a in (ax2,):
            a.grid(axis="y", color=LINE, zorder=0)
            a.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=LINE, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    if kind == "journey":
        ax.legend(frameon=False, fontsize=17, loc="upper right", bbox_to_anchor=(1, 0.93))
    fig.tight_layout()
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


def slide_chart(s, idx):
    img, d = base(s["title"], idx)
    paste_fit(img, chart(s["chart"]), (60, 175, W - 60, H - 80), border=False)
    return img


RENDER = {"title": slide_title, "bullets": slide_bullets, "table": slide_table, "flow": slide_flow,
          "image": slide_image, "highlight": slide_highlight, "formula": slide_formula, "chart": slide_chart}


def speak_all(texts):
    """One PowerShell run renders every narration to WAV with the offline Windows voice."""
    jobs = []
    for i, t in enumerate(texts, 1):
        (BUILD / f"n{i:02}.txt").write_text(t, encoding="utf-8")
        jobs.append(f"@('{BUILD / f'n{i:02}.txt'}','{BUILD / f'n{i:02}.wav'}')")
    ps = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('{VOICE}')
$s.Rate = 0
foreach ($j in @({','.join(jobs)})) {{
  $s.SetOutputToWaveFile($j[1])
  $s.Speak([IO.File]::ReadAllText($j[0], [Text.Encoding]::UTF8))
}}
$s.SetOutputToNull()
"""
    script = BUILD / "speak.ps1"
    script.write_text(ps, encoding="utf-8-sig")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], check=True)


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slides", action="store_true")
    args = ap.parse_args()
    BUILD.mkdir(exist_ok=True)
    for i, s in enumerate(SCENES, 1):
        RENDER[s["kind"]](s, i).save(BUILD / f"s{i:02}.png")
    print(f"{len(SCENES)} slides in {BUILD}")
    if args.slides:
        return
    speak_all([s["narration"] for s in SCENES])
    clips, total = [], 0.0
    for i in range(1, len(SCENES) + 1):
        dur = wav_seconds(BUILD / f"n{i:02}.wav") + PAUSE_S
        total += dur
        clip = BUILD / f"c{i:02}.mp4"
        fade_out = max(0, dur - 0.35)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(BUILD / f"s{i:02}.png"),
            "-i", str(BUILD / f"n{i:02}.wav"), "-af", f"adelay=250|250,apad=whole_dur={dur:.2f},aresample=44100",
            "-vf", f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out:.2f}:d=0.35,format=yuv420p",
            "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "160k", "-ac", "2", str(clip)], check=True)
        clips.append(clip)
    (BUILD / "list.txt").write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(BUILD / "list.txt"),
                    "-c", "copy", "-movflags", "+faststart", str(OUT)], check=True)
    print(f"Wrote {OUT} ({total / 60:.1f} min)")


if __name__ == "__main__":
    main()
