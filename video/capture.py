"""Screenshots of the preview page for the explainer video (read-only: never clicks Decide or Reset)."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "shots"
URL = "http://localhost:5000"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge")
    page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    page.goto(URL)
    page.wait_for_selector("article.card")
    page.wait_for_timeout(800)
    page.screenshot(path=OUT / "home.png")
    boxes = {}
    for key, sel in {"time": "#now", "shift": "button[data-shift='1']", "shift_end": "button[data-shift='168']",
                     "agent": "label:has(#useAgent)", "decide_all": "#decideAll", "reset": "#reset",
                     "segment": "#segFilter", "flagged": "label:has(#flaggedOnly)", "stats": "#stats",
                     "card": "article.card >> nth=0", "decide_again": "article.card >> nth=0 >> button[data-act=decide]",
                     "history": "article.card >> nth=0 >> button[data-act=history]",
                     "pills": "article.card >> nth=0 >> .offer .row", "chips": "article.card >> nth=0 >> .chips",
                     "bubble": "article.card >> nth=0 >> .bubble", "reason": "article.card >> nth=0 >> .reason"}.items():
        boxes[key] = page.locator(sel).first.bounding_box()
    boxes["agent"]["width"] += 16
    boxes["flagged"]["width"] += 16
    (OUT / "boxes.json").write_text(json.dumps(boxes, indent=1))
    page.locator("header").screenshot(path=OUT / "header.png")
    ai_card = page.locator("article.card", has=page.locator(".by-AGENT")).first
    ai_card.screenshot(path=OUT / "card_ai.png")
    sys_card = page.locator("article.card", has=page.locator(".by-SYSTEM")).first
    sys_card.screenshot(path=OUT / "card_system.png")
    ai_card.locator("button[data-act=history]").click()
    page.wait_for_timeout(800)
    ai_card.screenshot(path=OUT / "card_history.png")
    page.check("#flaggedOnly")
    page.wait_for_timeout(500)
    page.screenshot(path=OUT / "flagged.png")
    flagged = page.locator("article.card.flagged").first
    if flagged.count():
        flagged.screenshot(path=OUT / "card_flagged.png")
    page.uncheck("#flaggedOnly")
    page.select_option("#segFilter", "CART_ABANDONER")
    page.wait_for_timeout(500)
    page.screenshot(path=OUT / "segment_filter.png")
    # Sharp copy for zoomed-in button close-ups (boxes.json stays in CSS pixels).
    hi = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2)
    hi.goto(URL)
    hi.wait_for_selector("article.card")
    hi.wait_for_timeout(800)
    hi.screenshot(path=OUT / "home2x.png")
    browser.close()
print(sorted(x.name for x in OUT.iterdir()))
