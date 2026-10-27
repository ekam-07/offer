"""Demo-first video (about 3.5 minutes): little slide reading, mostly the real app and the real
Telegram messages, animated. Kinds as in video/explainer, plus "phone" (animated Telegram chat).
"""
VOICE = "en-US-AndrewMultilingualNeural"
RATE, PITCH = "-2%", "-4Hz"

SCENES = [
    {"id": "hook", "kind": "hook",
     "narration": "Online stores lose money on every discount. Most of it goes to shoppers who would buy anyway. "
                  "It teaches people to wait for sales, and too many messages make them unsubscribe."},
    {"id": "reveal", "kind": "reveal",
     "narration": "So we built the AI Offer Engine. Let me show you how it works, from customer data to the message on their phone."},
    {"id": "list", "kind": "demo",
     "narration": "It starts with customer data: orders, browsing, carts, wishlists and consent. "
                  "Every shopper is one line here, searchable, and built to stay fast with lakhs of customers."},
    {"id": "customer", "kind": "demo",
     "narration": "Open a shopper. The engine has turned their data into simple signals, like how likely they are to buy anyway. "
                  "Then Claude, our AI, picks the offer, and thirty-one business rules check it, with the reason in plain words."},
    {"id": "spend", "kind": "demo",
     "narration": "The key is spending as little as possible. Free nudges come first: cart reminders, points reminders, early sale access. "
                  "Paid offers, like free delivery or rupees off, are used only when the numbers say they pay."},
    {"id": "phone", "kind": "phone",
     "narration": "Here's a real example, from our Telegram bot. Karthik left a water purifier in his cart. "
                  "First, he gets a friendly reminder. It costs us nothing. "
                  "Days pass, and he still hasn't bought it. "
                  "So now, and only now, the engine sends a discount: free delivery, with a single-use code that only he can use. "
                  "One reminder, then one offer. Never spam, and never a discount before a free nudge has had its chance."},
    {"id": "signup", "kind": "demo",
     "narration": "And it all runs on its own. When a new customer signs up, the engine decides within seconds, without anyone pressing a button."},
    {"id": "cart", "kind": "demo",
     "narration": "If she already holds a live offer, it sends nothing new. One live offer at a time."},
    {"id": "measure", "kind": "journey",
     "narration": "How do we know it works? We measure it on customers calibrated with real data: "
                  "Flipkart prices, a real store's browsing and carts, and a sixty-four thousand shopper experiment. "
                  "On guessed data the numbers looked bigger. On real-calibrated data they're honest, "
                  "and our improvements took the AI to seven thousand six hundred rupees of extra margin a week."},
    {"id": "results", "kind": "results",
     "narration": "That's three times the profit of a blanket discount, with eighty-eight percent less spent on discounts."},
    {"id": "mvp", "kind": "cards", "kicker": "Why we win", "title": "What makes it the best solution",
     "narration": "What makes it different? It optimises profit, not clicks. It never sells at a loss, in any category. "
                  "The AI is always checked by rules, and explains every decision. "
                  "It tries free nudges before discounts, adds smart offers like bought together and wishlist price alerts, "
                  "and delivers automatically, straight to the customer's phone.",
     "cols": 4,
     "cards": [{"icon": "💰", "title": "Profit, not clicks", "sub": "every offer must earn more than it costs", "cue": "profit"},
               {"icon": "🔒", "title": "Never at a loss", "sub": "10% margin kept on any category", "cue": "loss"},
               {"icon": "🛡️", "title": "AI, always checked", "sub": "31 rules + automatic fallback", "cue": "checked"},
               {"icon": "💬", "title": "Explains itself", "sub": "plain-words reason for every decision", "cue": "explains"},
               {"icon": "🛒", "title": "Free nudges first", "sub": "reminder → discount only if no buy", "cue": "nudges", "accent": "#2ee6b8"},
               {"icon": "🧺", "title": "Smart new offers", "sub": "bought together · wishlist alerts · perks", "cue": "smart", "accent": "#2ee6b8"},
               {"icon": "⚡", "title": "Runs on its own", "sub": "events + a daily check", "cue": "automatically", "accent": "#2ee6b8"},
               {"icon": "📲", "title": "Straight to the phone", "sub": "Telegram today, any channel next", "cue": "phone", "accent": "#2ee6b8"}]},
    {"id": "tagline", "kind": "tagline", "narration": "Smarter offers. Zero wasted discounts. More profit."},
    {"id": "end", "kind": "end", "narration": "AI Offer Engine. Every offer, only when it pays. We're looking for pilot partners and investors."},
]
