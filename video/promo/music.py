"""A soft ambient-tech background track, synthesised here (no third-party music, no licence issues).

    python video/promo/music.py 83.0      # -> build/music.wav (seconds)

Pad chords + a gentle plucked arpeggio + sub bass and a light pulse in the middle section.
Am - F - C - G at 96 BPM, one chord per bar, with a fade in and a long ring-out at the end.
"""
import sys
import wave
from pathlib import Path

import numpy as np

SR = 48000
BUILD = Path(__file__).parent / "build"
BPM = 96
BEAT = 60 / BPM
BAR = 4 * BEAT
CHORDS = [[57, 60, 64, 69], [53, 57, 60, 65], [48, 55, 60, 64], [55, 59, 62, 67]]  # Am F C G (MIDI)


def hz(m):
    return 440 * 2 ** ((m - 69) / 12)


def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):  # one-pole, fine for a few million samples
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


def pad_voice(f, n, t0):
    t = np.arange(n) / SR + t0
    sig = np.zeros(n)
    for det in (-0.12, 0.0, 0.12):  # three slightly detuned voices for width
        ff = f * 2 ** (det / 12)
        for h, amp in ((1, 1), (2, .45), (3, .22), (4, .12), (5, .06)):
            sig += amp * np.sin(2 * np.pi * ff * h * t + det * 3)
    return sig


def main(total):
    n = int(total * SR)
    L, R = np.zeros(n), np.zeros(n)
    bars = int(np.ceil(total / BAR)) + 1
    # Pad: each chord fades in/out over the bar edges (crossfaded), slightly different per side.
    for b in range(bars):
        start = b * BAR
        s0, s1 = int(max(0, (start - .6) * SR)), int(min(n, (start + BAR + .9) * SR))
        if s0 >= n:
            break
        seg = s1 - s0
        env = np.ones(seg)
        fade_in, fade_out = min(int(.9 * SR), seg // 2), min(int(1.2 * SR), seg // 2)
        env[:fade_in] = np.linspace(0, 1, fade_in) ** 2
        env[-fade_out:] *= np.linspace(1, 0, fade_out) ** 2
        chord = CHORDS[b % 4]
        for i, m in enumerate(chord):
            v = pad_voice(hz(m), seg, s0 / SR) * env * .05
            pan = .35 + .1 * i
            L[s0:s1] += v * (1 - pan) * 1.4
            R[s0:s1] += v * pan * 1.4
    # Arpeggio: soft plucks on 8th notes, from bar 2, with a ping-pong echo.
    pluck = np.zeros(n)
    step = BEAT / 2
    k = 0
    tpos = BAR * 1
    pattern = [0, 2, 3, 2, 1, 3, 2, 3]
    while tpos < total - 4:
        b = int(tpos // BAR)
        chord = CHORDS[b % 4]
        m = chord[pattern[k % 8]] + 12
        s0 = int(tpos * SR)
        ln = int(.9 * SR)
        if s0 + ln < n:
            tt = np.arange(ln) / SR
            note = (np.sin(2 * np.pi * hz(m) * tt) + .3 * np.sin(4 * np.pi * hz(m) * tt)) * np.exp(-tt * 6)
            pluck[s0:s0 + ln] += note * .045
        tpos += step
        k += 1
    pl, pr = pluck.copy(), np.zeros(n)
    d = int(BEAT * .75 * SR)
    pr[d:] += pluck[:-d] * .6
    pl[2 * d:] += pluck[:-2 * d] * .35
    L += pl
    R += pr + pluck * .4
    # Sub bass on each bar and a light pulse on beats in the middle section.
    for b in range(bars):
        s0 = int(b * BAR * SR)
        if s0 >= n:
            break
        ln = min(int(BAR * SR), n - s0)
        tt = np.arange(ln) / SR
        bass = np.sin(2 * np.pi * hz(CHORDS[b % 4][0] - 12) * tt) * np.minimum(1, tt * 4) * np.exp(-tt * .5) * .08
        L[s0:s0 + ln] += bass
        R[s0:s0 + ln] += bass
    beat_t = BAR * 2
    while beat_t < total * .82:
        s0 = int(beat_t * SR)
        ln = int(.25 * SR)
        if s0 + ln < n:
            tt = np.arange(ln) / SR
            kick = np.sin(2 * np.pi * (48 + 60 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 18) * .09
            L[s0:s0 + ln] += kick
            R[s0:s0 + ln] += kick
        beat_t += BEAT
    # Warmth, overall fade in/out, normalise.
    L, R = lowpass(L, 5200), lowpass(R, 5200)
    fade_in, fade_out = int(2.5 * SR), int(4.5 * SR)
    for ch in (L, R):
        ch[:fade_in] *= np.linspace(0, 1, fade_in)
        ch[-fade_out:] *= np.linspace(1, 0, fade_out) ** 1.5
    peak = max(np.abs(L).max(), np.abs(R).max())
    st = np.stack([L, R], axis=1) / peak * .8
    out = BUILD / "music.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((st * 32767).astype("<i2").tobytes())
    print(f"wrote {out} ({total:.1f}s)")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 83.0)
