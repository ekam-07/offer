"""Joins the rendered frames, the voice-over (placed at each scene's time) and the music into the final MP4.

    python video/promo/make_promo.py      # -> video/promo/AI_Offer_Engine_Promo.mp4
"""
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
BUILD = HERE / "build"
OUT = HERE / "AI_Offer_Engine_Promo.mp4"


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
    # 2. Music under the voice: quiet, and ducked further whenever she speaks.
    ff("-i", BUILD / "music.wav", "-i", BUILD / "voice.wav", "-filter_complex",
       f"[0:a]atrim=0:{total},volume=0.22[m];[1:a]asplit[vs][vm];"
       "[m][vs]sidechaincompress=threshold=0.03:ratio=6:attack=60:release=500[duck];"
       "[duck][vm]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.0:LRA=9[out]",
       "-map", "[out]", "-ar", "48000", BUILD / "mix.wav")
    # 3. Picture: 2x frames scaled down (supersampled, crisp text), constant 30 fps, high quality.
    ff("-framerate", "30", "-i", BUILD / "frames" / "f%05d.jpg", "-i", BUILD / "mix.wav",
       "-vf", "scale=1920:1080:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p", "-color_range", "tv", "-c:v", "libx264", "-preset", "slow", "-crf", "15",
       "-profile:v", "high", "-r", "30", "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
