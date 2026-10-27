"""Promo / pitch video in the style of the reference (dark stage, app in a browser window, smooth
camera moves, callouts, captions, music). Each scene: id, narration, and what make_promo.py shows."""
VOICE = "en-US-AvaMultilingualNeural"
RATE = "+4%"

SCENES = [
    {"id": "intro", "narration": "Online stores lose money on every discount. Most of it goes to shoppers who would buy anyway. "
                                  "It teaches people to wait for sales, and too many messages make them unsubscribe."},
    {"id": "reveal", "narration": "Our AI Offer Engine fixes that."},
    {"id": "dashboard", "narration": "For every customer, Claude decides whether to make an offer, which one, and how big. "
                                      "Then thirty-one business rules check every decision before it goes out."},
    {"id": "customer", "narration": "Open any shopper, and the reason is right there, in plain words anyone can follow."},
    {"id": "bundle", "narration": "New offer types, like bought together, grow the basket instead of cutting the price."},
    {"id": "signup", "narration": "When a new customer signs up, the engine decides on its own, in seconds."},
    {"id": "cart", "narration": "And if they already hold an offer, it sends nothing new. No spam, and no stacked discounts."},
    {"id": "results", "narration": "In our simulation, on real-data-calibrated customers, it earns three times the profit of a blanket discount, "
                                    "while spending eighty-eight percent less on discounts."},
    {"id": "tagline", "narration": "Smarter offers. Zero wasted discounts. More profit."},
    {"id": "end", "narration": "AI Offer Engine. Every offer, only when it pays."},
]
