"""Adds the voice-over, the energetic music (ducked under the voice) and the sound effects to the picture.

    python video/story2/make.py      # -> video/story2/AI_Offer_Engine_Demo_v2.mp4
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
BUILD = HERE / "build"
OUT = HERE / "AI_Offer_Engine_Demo_v2.mp4"
sys.path.insert(0, str(HERE))
import audio  # noqa: E402


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True)


def main():
    tl = json.loads((BUILD / "timeline.json").read_text(encoding="utf-8"))
    total = tl["total"]
    # 1. Voice: every scene's narration at its own start time, one track, evened out.
    inputs, chains = [], []
    for i, (sid, sc) in enumerate(tl["scenes"].items()):
        inputs += ["-i", BUILD / f"{sid}.mp3"]
        ms = int(sc["voice"] * 1000)
        chains.append(f"[{i}:a]aresample=48000,adelay={ms}|{ms},apad[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(tl["scenes"])))
    ff(*inputs, "-filter_complex", ";".join(chains) + f";{mix}amix=inputs={len(tl['scenes'])}:normalize=0,"
       f"atrim=0:{total},loudnorm=I=-16:TP=-1.5:LRA=7[v]", "-map", "[v]", "-ac", "2", BUILD / "voice.wav")
    # 2. Music and sound effects, synthesised to the timeline.
    audio.music(total, tl["drop"], tl["final"], BUILD / "music.wav")
    audio.sfx(tl["sfx"], total, BUILD / "sfx.wav")
    # 3. Music ducked under the voice (but kept present), effects on top, then one loudness pass.
    ff("-i", BUILD / "music.wav", "-i", BUILD / "voice.wav", "-i", BUILD / "sfx.wav", "-filter_complex",
       f"[0:a]atrim=0:{total},volume=0.42[m];[1:a]asplit[vs][vm];"
       "[m][vs]sidechaincompress=threshold=0.035:ratio=4:attack=40:release=350[duck];"
       f"[2:a]atrim=0:{total},volume=0.55[fx];"
       "[duck][vm][fx]amix=inputs=3:normalize=0,alimiter=limit=0.95,loudnorm=I=-14:TP=-1.0:LRA=10[out]",
       "-map", "[out]", "-ar", "48000", BUILD / "mix.wav")
    # 4. Mux with the picture rendered by render.py (already H.264, 30 fps, 1080p).
    ff("-i", BUILD / "video.mp4", "-i", BUILD / "mix.wav", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
       "-shortest", "-movflags", "+faststart", OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
