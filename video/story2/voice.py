"""Neural voice-over for every scene (edge-tts) plus word timings for captions and cues.

    python video/story2/voice.py          # -> build/<scene>.mp3 + build/words.json
    python video/story2/voice.py hook     # only these scenes (the others are kept)
"""
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import edge_tts

HERE = Path(__file__).parent
BUILD = HERE / "build"
sys.path.insert(0, str(HERE))
from script import PITCH, RATE, SCENES, VOICE  # noqa: E402


def seconds(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


async def one(scene):
    out = BUILD / f"{scene['id']}.mp3"
    for attempt in range(6):  # the stream is sometimes cut short: retry until audio covers every word
        words, audio = [], bytearray()
        comm = edge_tts.Communicate(scene["narration"], VOICE, rate=RATE, pitch=PITCH, boundary="WordBoundary")
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
            elif chunk["type"] == "WordBoundary":
                words.append({"t": chunk["offset"] / 1e7, "d": chunk["duration"] / 1e7, "w": chunk["text"]})
        out.write_bytes(audio)
        expected = len(re.findall(r"[\w'-]+", scene["narration"]))
        if words and len(words) >= expected * .9 and seconds(out) >= words[-1]["t"] + words[-1]["d"] - .05:
            return words
        print(f"  {scene['id']}: retry {attempt + 1}", flush=True)
    raise RuntimeError(f"voice failed for {scene['id']}")


async def main(only):
    BUILD.mkdir(parents=True, exist_ok=True)
    path = BUILD / "words.json"
    words = json.loads(path.read_text()) if path.exists() else {}
    for s in SCENES:
        if only and s["id"] not in only and s["id"] in words:
            continue
        words[s["id"]] = await one(s)
        print(f"{s['id']}: {seconds(BUILD / (s['id'] + '.mp3')):.1f}s, {len(words[s['id']])} words", flush=True)
    path.write_text(json.dumps(words, indent=0))
    print(f"total voice {sum(seconds(BUILD / (s['id'] + '.mp3')) for s in SCENES):.1f}s")


if __name__ == "__main__":
    asyncio.run(main(set(sys.argv[1:])))
