"""Records the live demo for the pitch video from the demo server (preview "offer-demo", port 5001).

Each step lasts at least as long as its narration (video/pitch/build/<id>.mp3), and the start/end
times are saved to build/demo_marks.json so make_pitch.py can cut the recording to match the voice.
The new customer and the cart are real events: the app (AI + rules) decides live while recording.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
BUILD = HERE / "build"
URL = "http://localhost:5001"
W, H = 1600, 900

sys.path.insert(0, str(HERE))
from script import SCENES  # noqa: E402

CURSOR = """
(() => {
  if (document.getElementById('fake-cursor')) return;
  const c = document.createElement('div');
  c.id = 'fake-cursor';
  c.style.cssText = 'position:fixed;z-index:99999;width:22px;height:22px;border-radius:50%;pointer-events:none;' +
    'background:rgba(42,120,214,.35);border:2px solid #2a78d6;transform:translate(-50%,-50%);left:-50px;top:-50px;' +
    'transition:width .12s,height .12s,background .12s';
  document.body.appendChild(c);
  document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  document.addEventListener('mousedown', () => { c.style.width = c.style.height = '34px'; c.style.background = 'rgba(42,120,214,.6)'; }, true);
  document.addEventListener('mouseup', () => { c.style.width = c.style.height = '22px'; c.style.background = 'rgba(42,120,214,.35)'; }, true);
})();
"""


def narration_seconds(scene_id):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(BUILD / f"{scene_id}.mp3")], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(2)) * 60 + float(m.group(3))


def main():
    steps = {s["id"]: narration_seconds(s["id"]) + 0.9 for s in SCENES if s["kind"] == "demo"}
    marks = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(BUILD / "rec"),
                                  record_video_size={"width": W, "height": H}, color_scheme="light")
        page = ctx.new_page()
        t_video = time.monotonic()  # the recording starts with the page
        page.add_init_script(CURSOR)
        page.goto(URL)
        page.wait_for_selector("#rows tr[data-id]")
        page.evaluate("() => { document.getElementById('now').value = '2026-10-16T14:00'; }")
        page.evaluate("() => load()")
        page.wait_for_timeout(1500)
        mouse = page.mouse
        pos = [W / 2, H / 2]

        def move_to(target, steps_=28):
            box = page.locator(target).first.bounding_box() if isinstance(target, str) else None
            x, y = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2) if box else target
            mouse.move(x, y, steps=steps_)
            pos[:] = [x, y]

        def click(target):
            page.locator(target).first.scroll_into_view_if_needed()
            move_to(target)
            page.wait_for_timeout(250)
            mouse.down(); page.wait_for_timeout(90); mouse.up()  # a real click, where the cursor is

        def scroll(dy, steps_=12):
            for _ in range(steps_):
                mouse.wheel(0, dy / steps_)
                page.wait_for_timeout(30)

        def step(scene_id, actions):
            start = time.monotonic() - t_video
            actions()
            need = steps[scene_id] - (time.monotonic() - t_video - start)
            if need > 0:
                page.wait_for_timeout(int(need * 1000))
            marks[scene_id] = [round(start, 2), round(time.monotonic() - t_video, 2)]
            print(f"{scene_id:16} {marks[scene_id]}", flush=True)

        def dashboard():
            move_to((300, 380)); page.wait_for_timeout(500)
            move_to("#stats .tile.ai"); page.wait_for_timeout(1800)
            move_to("#offerFilter"); page.wait_for_timeout(1200)
            scroll(560); page.wait_for_timeout(600)
            move_to("#rows tr[data-id] >> nth=3"); page.wait_for_timeout(700)
            move_to("#pager button[data-page='2']"); page.wait_for_timeout(800)

        def customer():
            click("#search")
            page.keyboard.type("Kabir", delay=110)
            page.wait_for_timeout(900)
            click("#rows tr[data-id] >> nth=0")
            page.wait_for_selector("#drawer.open .why")
            page.wait_for_timeout(1200)
            move_to("#drawerBody .bubble"); page.wait_for_timeout(1300)
            page.locator("#drawerBody .why").scroll_into_view_if_needed()
            move_to("#drawerBody .why-row >> nth=1"); page.wait_for_timeout(900)
            move_to("#drawerBody .why-row >> nth=3")

        def bundle():
            click("#drawerClose"); page.wait_for_timeout(300)
            page.fill("#search", ""); page.evaluate("() => { state.q = ''; }")
            page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})"); page.wait_for_timeout(700)
            click("button[data-offer=BUNDLE_SUGGEST]")
            page.wait_for_timeout(900)
            page.locator("#offerSummary").scroll_into_view_if_needed()
            move_to("#offerSummary .osum-title"); page.wait_for_timeout(1000)
            click("#rows tr[data-id] >> nth=0")
            page.wait_for_selector("#drawer.open .why"); page.wait_for_timeout(600)
            move_to("#drawerBody .bubble")

        def signup():
            click("#drawerClose"); page.wait_for_timeout(300)
            click("button[data-offer='']")
            page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})"); page.wait_for_timeout(600)
            page.evaluate("() => { window.prompt = (q) => q.startsWith('New') ? 'Ananya Rao' : 'Beauty'; }")
            click("#newCustomer")
            page.wait_for_selector("#drawer.open .why", timeout=90000)
            page.wait_for_timeout(700)
            move_to("#drawerBody .bubble")

        def cart():
            page.locator("#drawerBody button[data-trigger=cart_abandoned]").scroll_into_view_if_needed()
            click("#drawerBody button[data-trigger=cart_abandoned]")
            page.wait_for_function("document.querySelector('#banner').innerText.includes('cart')", timeout=90000)
            page.wait_for_selector("#drawer.open .why", timeout=30000)
            page.wait_for_timeout(600)
            page.locator("#drawerBody .why-row >> nth=4").scroll_into_view_if_needed()
            move_to("#drawerBody .why-row >> nth=4")

        for scene_id, fn in (("demo_dashboard", dashboard), ("demo_customer", customer), ("demo_bundle", bundle),
                             ("demo_signup", signup), ("demo_cart", cart)):
            step(scene_id, fn)
        page.wait_for_timeout(500)
        video_path = page.video.path()
        ctx.close()
        browser.close()
    (BUILD / "demo_marks.json").write_text(json.dumps({"video": str(video_path), "marks": marks}, indent=1))
    print("saved", video_path)


if __name__ == "__main__":
    main()
