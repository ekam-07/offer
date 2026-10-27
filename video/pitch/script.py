"""Investor pitch video: scenes, what's on screen, and what the narrator says.

kind "slide" -> a designed slide (make_pitch.py draws it); kind "demo" -> a step of the live
screen recording (record_demo.py performs it while the narration plays).
Numbers come from data/eval_report_ai_new_features.md (16 Oct, 200 calibrated customers).
"""
VOICE = "en-US-AvaMultilingualNeural"
RATE = "+2%"

SCENES = [
    {"id": "hook", "kind": "slide",
     "narration": "Every sale season, online stores hand out discounts to millions of shoppers. "
                  "Here's the uncomfortable truth: most of that money goes to people who were going to buy anyway."},
    {"id": "problem", "kind": "slide",
     "narration": "In our test store, ten percent off for everyone cost seven thousand rupees a week, "
                  "and two thirds of it went to customers who'd have bought without it. "
                  "Blanket discounts also teach shoppers to wait for a sale, and flood them with messages until they unsubscribe."},
    {"id": "solution", "kind": "slide",
     "narration": "So we built an AI offer engine. For every single customer, it decides whether to make an offer, "
                  "which one, and how big. And only when it actually pays."},
    {"id": "flow", "kind": "slide",
     "narration": "Here's how it flows. The store tells us what shoppers do: sign-ups, carts, orders, wishlists. "
                  "We turn that into simple signals, like how likely they are to buy anyway. "
                  "Claude, our AI, picks the most profitable offer and writes a personal message. "
                  "Then thirty-one business rules check every decision before anything is sent. "
                  "If the AI ever breaks a rule, or goes down, our rules engine takes over automatically. "
                  "Checkout enforces a single-use coupon, and the results flow back, so the profit is measured, not guessed."},
    {"id": "demo_dashboard", "kind": "demo",
     "narration": "Let's see it live. This is the dashboard. The AI has made a hundred and eighty decisions, "
                  "and every one was approved by the rules. Even with lakhs of customers, you search, filter and page instantly."},
    {"id": "demo_customer", "kind": "demo",
     "narration": "Let's open a customer. Instead of a wall of numbers, every decision is explained in plain words: "
                  "who they are, whether they'd buy anyway, what we send, whether it's worth it, and the rule it followed."},
    {"id": "demo_bundle", "kind": "demo",
     "narration": "This is one of our new offer types. Bought together uses the store's own order history "
                  "to suggest the item people usually add next. It grows the basket, instead of cutting the price."},
    {"id": "demo_signup", "kind": "demo",
     "narration": "Now, a brand new customer signs up. Nobody presses a button. "
                  "Within seconds, the system decides on its own, and the reason comes with it."},
    {"id": "demo_cart", "kind": "demo",
     "narration": "A minute later, she leaves something in her cart. The engine sees she already holds a live offer, "
                  "so it sends nothing new. No spam, and no stacked discounts."},
    {"id": "why", "kind": "slide",
     "narration": "So, what makes us different? We optimise profit, not clicks. Every offer keeps at least a ten percent margin, "
                  "in any category. The AI is always checked, never trusted blindly. It explains itself, and it runs on its own. "
                  "And it's calibrated on real public data, including a randomised experiment with sixty-four thousand shoppers."},
    {"id": "results", "kind": "slide",
     "narration": "And the results. In our simulation, on the same customers, the AI engine earns about seven thousand six hundred rupees "
                  "of extra margin a week. That's three times a blanket discount, while spending eighty-eight percent less on discounts."},
    {"id": "ask", "kind": "slide",
     "narration": "Next, we go live: a Telegram pilot with real shoppers, and a webhook that's ready for any store. "
                  "We're looking for pilot partners and investors to take it to market. "
                  "Smarter offers. Real profit. Thank you."},
]
