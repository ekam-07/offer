"""Energetic background music and sound effects, synthesised here (no third-party audio, no licence issues).

    music(total, drop, final)  -> 120 BPM track: a tense heartbeat build under the hook, a drop on the
                                  reveal, a driving groove for the demo, and a final hit on the end card.
    sfx(events, total)         -> every whoosh, click, pop and impact at its time in the timeline.
"""
import wave

import numpy as np
from scipy import signal

SR = 48000
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT
CHORDS = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]  # Am F C G
RNG = np.random.default_rng(7)


def hz(m):
    return 440 * 2 ** ((m - 69) / 12)


def filt(x, kind, f):
    sos = signal.butter(2, f, btype=kind, fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def tt(sec):
    return np.arange(int(sec * SR)) / SR


def add(buf, at, x, gain=1.0):
    s0 = int(at * SR)
    if s0 >= len(buf) or s0 + len(x) <= 0:
        return
    a, b = max(0, s0), min(len(buf), s0 + len(x))
    buf[a:b] += x[a - s0:b - s0] * gain


def noise(sec):
    return RNG.standard_normal(int(sec * SR))


# ---------- instruments ----------
def kick(gain=1.0):
    t = tt(.45)
    f = 45 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 7.5)
    click = filt(noise(.01), "highpass", 2500) * np.exp(-tt(.01) * 400) * .3
    body[:len(click)] += click
    return np.tanh(body * 1.6) * .9 * gain


def clap():
    x = np.zeros(int(.3 * SR))
    for d in (0, .011, .022):
        n = filt(noise(.28), "bandpass", [900, 3200]) * np.exp(-tt(.28) * (30 if d < .02 else 14))
        add(x, d, n[:len(x) - int(d * SR)])
    return x * .5


def hat(open_=False):
    sec = .22 if open_ else .05
    return filt(noise(sec), "highpass", 7500) * np.exp(-tt(sec) * (14 if open_ else 70)) * (.35 if open_ else .22)


def crash():
    return filt(noise(2.2), "highpass", 4000) * np.exp(-tt(2.2) * 2.2) * .45


def saw(f, sec, harm=8):
    t = tt(sec)
    return sum(np.sin(2 * np.pi * f * h * t) / h for h in range(1, harm + 1))


def pluck(f, sec=.35):
    t = tt(sec)
    return sum(np.sin(2 * np.pi * f * h * t) * np.exp(-t * (9 + 5 * h)) / h for h in range(1, 6))


def music(total, drop, final, out):
    n = int((total + .5) * SR)
    drums, synth, bass = np.zeros(n), np.zeros(n), np.zeros(n)
    k0 = -int(drop / BEAT) - 1
    kick_times = []
    beat = k0
    while drop + beat * BEAT < final:
        t = drop + beat * BEAT
        if t >= 0:
            if t < drop:  # hook: heartbeat kick, hats join halfway, a snare roll into the drop
                prog = t / drop
                kick_times.append(t)
                add(drums, t, kick(.55 + .3 * prog))
                if prog > .45:
                    add(drums, t + BEAT / 2, hat(), .8)
                if drop - t <= 2 * BAR + 1e-6:  # roll: 8ths, then 16ths in the last bar
                    sub = 4 if drop - t <= BAR + 1e-6 else 2
                    for i in range(sub):
                        add(drums, t + i * BEAT / sub, clap(), .25 + .5 * (1 - (drop - t) / (2 * BAR)))
            else:
                kick_times.append(t)
                add(drums, t, kick())
                if beat % 2 == 1:
                    add(drums, t, clap())
                add(drums, t + BEAT / 2, hat(True))
                for q in (0, 1, 2, 3):
                    add(drums, t + q * BEAT / 4, hat(), .5 + .3 * (q % 2))
                if beat % 32 == 0:
                    add(drums, t, crash())
        beat += 1
    # harmony: pad under everything (dark in the hook), bass + arpeggio after the drop
    bar = k0 // 4
    while drop + bar * BAR < final:
        t = drop + bar * BAR
        chord = CHORDS[bar % 4]
        if t + BAR > 0:
            pad = sum(saw(hz(m) * 2 ** (d / 1200), BAR + .3, 6) for m in chord for d in (-9, 9))
            env = np.minimum(1, tt(BAR + .3) / .15) * np.minimum(1, (BAR + .3 - tt(BAR + .3)) / .3)
            add(synth, t, pad * env, .016 if t >= drop else .012)
            if t >= drop:
                for e in range(8):  # offbeat-pumping 8th bass
                    add(bass, t + e * BEAT / 2, saw(hz(chord[0] - 24), BEAT / 2 * .9, 10)
                        * np.exp(-tt(BEAT / 2 * .9) * 3), .11)
                pattern = [0, 1, 2, 1, 2, 0, 1, 2, 0, 2, 1, 2, 0, 1, 2, 1]
                for s, p in enumerate(pattern):
                    add(synth, t + s * BEAT / 4, pluck(hz(chord[p] + 12)), .05)
            else:
                add(bass, t, np.sin(2 * np.pi * hz(chord[0] - 24) * tt(BAR)) * np.exp(-tt(BAR) * .8), .14)
        bar += 1
    synth = filt(synth, "lowpass", 2600)
    hook_mask = np.clip((np.arange(n) / SR - drop + .05) / .05, 0, 1)  # brighter after the drop
    synth = synth * (1 - hook_mask) * 1.0 + filt(synth, "lowpass", 5200) * hook_mask
    bass = filt(bass, "lowpass", 700)
    # sidechain pump on everything tonal
    pump = np.ones(n)
    for kt in kick_times:
        if kt >= drop:
            s0 = int(kt * SR)
            ln = min(int(BEAT * SR), n - s0)
            if ln > 0:
                pump[s0:s0 + ln] = np.minimum(pump[s0:s0 + ln], 1 - .65 * np.exp(-tt(ln / SR) / .09))
    tonal = (synth * 2.4 + bass * 1.9) * pump
    # a beat of silence before the drop, and the final hit
    gap = (np.arange(n) / SR > drop - .32) & (np.arange(n) / SR < drop)
    drums[gap] *= .0
    tonal[gap] *= .15
    mix = drums + tonal
    hit = sum(saw(hz(m), 4.5, 6) for m in [45, 57, 60, 64]) * np.exp(-tt(4.5) * 1.1) * .05
    add(mix, final, filt(hit, "lowpass", 3000))
    add(mix, final, kick(1.2))
    add(mix, final, crash(), 1.2)
    mix[int(final * SR) + int(4.5 * SR):] = 0
    mix[:int(.05 * SR)] *= np.linspace(0, 1, int(.05 * SR))
    L = mix + np.concatenate([np.zeros(240), synth[:-240]]) * .25
    R = mix + np.concatenate([np.zeros(480), synth[:-480]]) * .25
    write(out, L, R, .85)


# ---------- sound effects ----------
def whoosh(sec=.55):
    x = noise(sec)
    t = tt(sec)
    env = np.sin(np.pi * t / sec) ** 2
    lo = filt(x, "bandpass", [300, 1200]) * env * (1 - t / sec)
    hi = filt(x, "bandpass", [1500, 6000]) * env * (t / sec)
    return (lo + hi) * .55


def impact(big=False):
    sec = 1.8 if big else .9
    t = tt(sec)
    f = 38 + (140 if big else 110) * np.exp(-t * 12)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * (2.2 if big else 4.5))
    crack = filt(noise(sec), "lowpass", 3000) * np.exp(-t * 18) * .6
    return np.tanh((body + crack) * 1.8) * (.8 if big else .6)


def riser(sec):
    t = tt(sec)
    f = 180 * (8 ** (t / sec))
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * .25
    nz = filt(noise(sec), "highpass", 1500) * .5
    return (tone + nz) * (t / sec) ** 2.2 * .7


def tone(freqs, sec, decay):
    t = tt(sec)
    return sum(np.sin(2 * np.pi * f * t) for f in freqs) * np.exp(-t * decay) / len(freqs)


def sweep(f0, f1, sec, decay=0.0):
    t = tt(sec)
    f = f0 * (f1 / f0) ** (t / sec)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * decay)


def over(*xs):
    """Sum sounds of different lengths."""
    out = np.zeros(max(len(x) for x in xs))
    for x in xs:
        out[:len(x)] += x
    return out


def sfx_sound(kind):
    if kind == "tick":
        return tone([2400], .04, 120) * .25
    if kind == "type":
        return filt(noise(.03), "bandpass", [1800, 5000]) * np.exp(-tt(.03) * 160) * .35
    if kind == "click":
        return over(filt(noise(.02), "highpass", 2000) * np.exp(-tt(.02) * 250) * .5, tone([3100], .03, 140) * .3)
    if kind == "pop":
        return sweep(380, 980, .09, 18) * .32
    if kind == "whoosh":
        return whoosh()
    if kind == "wipe":
        return whoosh(.7) * 1.2
    if kind == "impact":
        return impact()
    if kind == "boom":
        return impact(True)
    if kind == "stamp":
        return np.tanh((tone([90, 140], .3, 16) + filt(noise(.3), "lowpass", 1800) * np.exp(-tt(.3) * 30) * .8) * 2) * .55
    if kind == "ding":
        return tone([1318.5, 1975.5], .9, 5) * .35
    if kind == "ping":  # notification: two quick tones
        x = np.zeros(int(.4 * SR))
        add(x, 0, tone([987.8], .2, 18), .35)
        add(x, .09, tone([1318.5], .3, 12), .35)
        return x
    if kind == "msg":  # incoming chat message
        return over(sweep(600, 1100, .12, 10) * .3, tone([1567.98], .25, 14) * .2)
    if kind == "down":
        return sweep(700, 70, .9, 1.5) * .35
    if kind == "glitch":
        x = filt(noise(.35), "bandpass", [400, 4000]) * (np.sign(np.sin(2 * np.pi * 23 * tt(.35))) > 0) * .4
        return x * np.exp(-tt(.35) * 4)
    if kind == "cash":
        x = np.zeros(int(1.2 * SR))
        add(x, 0, filt(noise(.08), "highpass", 3000) * np.exp(-tt(.08) * 50), .5)
        add(x, .06, tone([2093, 2637, 3136], 1.1, 4), .5)
        return x
    if kind.startswith("riser:"):
        return riser(float(kind[6:]))
    raise KeyError(kind)


def sfx(events, total, out):
    n = int((total + 2) * SR)
    L, R = np.zeros(n), np.zeros(n)
    cache = {}
    for ev in events:
        kind, at, gain, pan = ev["k"], ev["t"], ev.get("g", 1.0), ev.get("p", 0.0)
        if kind not in cache:
            cache[kind] = sfx_sound(kind)
        x = cache[kind]
        add(L, at, x, gain * (1 - max(0, pan)))
        add(R, at, x, gain * (1 + min(0, pan)))
    write(out, L, R, .9, normalise=False)


def write(path, L, R, peak, normalise=True):
    st = np.stack([L, R], axis=1)
    m = np.abs(st).max() or 1
    st = st / m * peak if normalise or m > 1 else st
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(st, -1, 1) * 32767).astype("<i2").tobytes())
