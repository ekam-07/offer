"""Long explainer (about 5 minutes) in the reference style. Each scene: id, kind, narration, content.

kind:
  hook      intro headline + pain chips          cards    kicker/title + cards revealed on cue words
  reveal    the app rises in                     formula  expected-profit formula + worked example
  demo:*    live app with camera moves           journey  profit journey chart
  results   bars + stat cards                    tagline / end
Cue words ("cue") reveal a card when the narrator says that word.
"""
VOICE = "en-US-AndrewMultilingualNeural"   # warm, confident male narrator (closest pitch to the reference)
RATE, PITCH = "-2%", "-4Hz"

SCENES = [
    {"id": "hook", "kind": "hook",
     "narration": "Online stores lose money on every discount. Most of it goes to shoppers who would buy anyway. "
                  "It teaches people to wait for sales, and too many messages make them unsubscribe."},
    {"id": "problem", "kind": "cards", "kicker": "The problem", "title": "A blanket discount burns margin",
     "narration": "In our test store, ten percent off for everyone cost seven thousand rupees a week. "
                  "Two thirds of it went to people who were buying anyway. That's not marketing. That's a leak.",
     "cards": [{"icon": "🧾", "big": "₹7,371", "title": "a week on 10% for everyone", "cue": "seven", "accent": "#fb923c"},
               {"icon": "🙈", "big": "2 / 3", "title": "went to buy-anyway shoppers", "cue": "Two", "accent": "#f87171"},
               {"icon": "🚰", "big": "Leak", "title": "not marketing", "cue": "leak", "accent": "#38bdf8"}]},
    {"id": "reveal", "kind": "reveal", "narration": "Meet the AI Offer Engine. It decides, for every single customer, "
                                                     "whether to make an offer, which one, and how big. And only when it pays."},
    {"id": "data", "kind": "cards", "kicker": "The data", "title": "Simulated shoppers, real-world behaviour",
     "narration": "First, the data. We don't use anyone's personal data. Two hundred shoppers are simulated, "
                  "but their behaviour is calibrated on three real public datasets. Flipkart's catalogue gives real Indian prices. "
                  "RetailRocket, a real store with one point four million visitors, gives browsing and carts. "
                  "And Hillstrom, a randomised experiment with sixty-four thousand shoppers, shows who actually reacts to an offer.",
     "cards": [{"icon": "🛡️", "big": "200", "title": "simulated shoppers", "sub": "no personal data used", "cue": "simulated"},
               {"icon": "🏷️", "big": "17,273", "title": "Flipkart products", "sub": "real Indian prices", "cue": "Flipkart's"},
               {"icon": "🛒", "big": "1.4M", "title": "RetailRocket visitors", "sub": "browsing, carts: 73% abandoned", "cue": "RetailRocket"},
               {"icon": "🔬", "big": "64,000", "title": "Hillstrom experiment", "sub": "who really reacts to offers", "cue": "Hillstrom"}]},
    {"id": "params", "kind": "cards", "kicker": "What the engine reads", "title": "45 signals per shopper, 4 simple scores",
     "narration": "For each shopper, the engine reads forty-five signals: their buying history, how much they use coupons, "
                  "what they're searching and adding to cart, their loyalty points, return rate, and consent. "
                  "It turns them into four simple scores: the chance they buy this week anyway, their risk of leaving, "
                  "whether an offer can change their mind, and their customer group.",
     "cols": 4,
     "cards": [{"icon": "🧾", "title": "Buying history", "sub": "orders, gaps, basket size", "cue": "history"},
               {"icon": "🏷️", "title": "Price sensitivity", "sub": "coupon use, promo clicks", "cue": "coupons"},
               {"icon": "🔎", "title": "Intent right now", "sub": "searches, views, cart, wishlist", "cue": "searching"},
               {"icon": "⭐", "title": "Loyalty & risk", "sub": "points, returns, consent", "cue": "loyalty"},
               {"icon": "🎯", "title": "Buy-anyway chance", "sub": "in the next 7 days", "cue": "anyway", "accent": "#2ee6b8"},
               {"icon": "📉", "title": "Risk of leaving", "sub": "late vs their own habit", "cue": "leaving", "accent": "#2ee6b8"},
               {"icon": "🔀", "title": "Can an offer help?", "sub": "persuadable · sure thing · lost cause", "cue": "change", "accent": "#2ee6b8"},
               {"icon": "👥", "title": "Customer group", "sub": "11 groups, e.g. at risk, new, VIP", "cue": "group", "accent": "#2ee6b8"}]},
    {"id": "offers", "kind": "cards", "kicker": "The offers", "title": "Free nudges first, paid offers only when they pay",
     "narration": "The engine can choose free nudges, like a cart reminder, a points reminder or early sale access, "
                  "or paid offers, like rupees off, free delivery or a coupon on one product. "
                  "And four new ideas: bought together, a wishlist price-drop alert, a spend goal, and pick your perk.",
     "cols": 4,
     "cards": [{"icon": "🛒", "title": "Cart reminder", "sub": "free", "cue": "cart"},
               {"icon": "⏳", "title": "Points reminder", "sub": "free", "cue": "points"},
               {"icon": "🎫", "title": "Early sale access", "sub": "free", "cue": "early"},
               {"icon": "🚚", "title": "₹ off · free delivery · coupon", "sub": "paid, only when it pays", "cue": "rupees"},
               {"icon": "🧺", "title": "Bought together", "sub": "new · grows the basket", "cue": "bought", "accent": "#2ee6b8"},
               {"icon": "👀", "title": "Wishlist alert", "sub": "new · real price drops only", "cue": "wishlist", "accent": "#2ee6b8"},
               {"icon": "🎯", "title": "Spend goal", "sub": "new · reach a target, get ₹ off", "cue": "goal", "accent": "#2ee6b8"},
               {"icon": "🎁", "title": "Pick your perk", "sub": "new · delivery or points, same cost", "cue": "perk", "accent": "#2ee6b8"}]},
    {"id": "rules", "kind": "cards", "kicker": "The rules", "title": "31 business rules check every decision",
     "narration": "Thirty-one business rules check every decision. Only shoppers who agreed to messages. "
                  "At least ten percent margin kept on any category, so an offer can never sell at a loss. "
                  "One live offer at a time. No messages at night. A daily budget that can never be overspent. "
                  "And every message must state the real value and expiry, with no pressure words.",
     "cols": 3,
     "cards": [{"icon": "✅", "title": "Consent first", "sub": "only shoppers who opted in", "cue": "agreed"},
               {"icon": "🔒", "title": "Never at a loss", "sub": "10% margin on any category", "cue": "margin"},
               {"icon": "1️⃣", "title": "One live offer", "sub": "nothing new until it ends", "cue": "live"},
               {"icon": "🌙", "title": "Quiet hours", "sub": "10 pm to 8 am: wait for morning", "cue": "night"},
               {"icon": "💰", "title": "Daily budget", "sub": "₹20,000, never overspent", "cue": "budget"},
               {"icon": "💬", "title": "Honest messages", "sub": "real value & expiry, no pressure", "cue": "message"}]},
    {"id": "formula", "kind": "formula",
     "narration": "Every paid offer must pass one test: expected profit. The extra chance of a sale, times the margin, "
                  "minus what the offer costs, paid by everyone who uses it. If a shopper was going to buy anyway, "
                  "the number goes negative, and the offer is blocked."},
    {"id": "ai", "kind": "cards", "kicker": "How a decision is made", "title": "Claude decides. The rules check. Always.",
     "narration": "Here's a single decision. The engine lists only the offers that are allowed, with their expected profit. "
                  "Claude, our AI, reads the rules, picks one, and writes a personal message. The checker tests it against every rule. "
                  "If it breaks one, the AI gets one retry. If it fails again, or the AI is down, the rules engine decides. "
                  "Every decision is logged with who decided, and why.",
     "cols": 3,
     "cards": [{"icon": "📋", "title": "1 · Allowed options", "sub": "with expected profit for each", "cue": "allowed"},
               {"icon": "🤖", "title": "2 · Claude picks", "sub": "offer, value and a personal message", "cue": "Claude"},
               {"icon": "🛡️", "title": "3 · Checker", "sub": "every rule, before anything is sent", "cue": "checker"},
               {"icon": "🔁", "title": "4 · One retry", "sub": "told exactly which rule it broke", "cue": "retry"},
               {"icon": "📘", "title": "5 · Rules backup", "sub": "if the AI fails or is down", "cue": "down"},
               {"icon": "🗂️", "title": "6 · Logged", "sub": "who decided, and why", "cue": "logged"}]},
    {"id": "dashboard", "kind": "demo",
     "narration": "Now the live dashboard. Pick the time to test waiting rules. Let the AI choose, decide for everyone, "
                  "or add a new customer. Filter by group, or by offer type. The tiles show what happened: here, "
                  "one hundred and eighty decisions by the AI, all approved by the rules. And it runs automatically."},
    {"id": "list", "kind": "demo",
     "narration": "Customers aren't a wall of cards. They're a compact list you can search, sort and page through, "
                  "built to stay fast with lakhs of shoppers."},
    {"id": "customer", "kind": "demo",
     "narration": "Open anyone, and the decision explains itself in plain words: who they are, whether they'd buy anyway, "
                  "what we send, whether it's worth it, and the rule we followed."},
    {"id": "bundle", "kind": "demo",
     "narration": "Pick an offer type to see who gets it, and what those shoppers have in common. "
                  "Here, bought together suggests the item people usually add next."},
    {"id": "signup", "kind": "demo",
     "narration": "Now a new customer signs up. Nobody presses a button. The engine decides on its own, in seconds."},
    {"id": "cart", "kind": "demo",
     "narration": "A minute later, she leaves something in her cart. She already holds a live offer, so the engine sends nothing new."},
    {"id": "auto", "kind": "cards", "kicker": "Automatic", "title": "It reacts to the store, and checks everyone daily",
     "narration": "That's automation. A sign-up, an abandoned cart after an hour, an order, or a real price drop "
                  "triggers a decision on its own. Every morning at eight, it checks everyone else, "
                  "skipping anyone who still holds a live offer.",
     "cols": 3,
     "cards": [{"icon": "👋", "title": "Sign-up", "sub": "decided straight away", "cue": "sign-up"},
               {"icon": "🛒", "title": "Cart left 1 hour", "sub": "a friendly reminder", "cue": "abandoned"},
               {"icon": "📦", "title": "Order placed", "sub": "bought-together tip 3 days later", "cue": "order"},
               {"icon": "👀", "title": "Real price drop", "sub": "wishlist alert", "cue": "drop"},
               {"icon": "⏰", "title": "Daily check, 8 am", "sub": "everyone not decided recently", "cue": "morning"},
               {"icon": "1️⃣", "title": "Live offer? Skip", "sub": "no spam, no stacked discounts", "cue": "skipping"}]},
    {"id": "journey", "kind": "journey",
     "narration": "Here's how the profit grew. On our first hand-made data, the AI earned about seven and a half thousand rupees a week. "
                  "Calibrating on real data made the numbers honest, and lower. Then smarter profit estimates, "
                  "safe categories, and the new offers took the AI to seven thousand six hundred rupees a week, "
                  "on realistic customers."},
    {"id": "results", "kind": "results",
     "narration": "Compared with a blanket discount, that's three times the profit, with eighty-eight percent less spent on discounts. "
                  "Each extra sale costs fifty-one rupees, instead of three hundred and fifty-eight."},
    {"id": "integrate", "kind": "cards", "kicker": "Plugging into a store", "title": "Ready for any e-commerce platform",
     "narration": "Plugging it into a real store is simple. The store sends events to our webhook. "
                  "We decide, and create a single-use coupon the checkout enforces. "
                  "The message goes out by app, WhatsApp, SMS or Telegram, and results come back, measured against a control group. "
                  "Consent, opt-out and data deletion are built in.",
     "cols": 4,
     "cards": [{"icon": "🔗", "title": "Webhook in", "sub": "orders, carts, sign-ups", "cue": "webhook"},
               {"icon": "🎫", "title": "Single-use coupon", "sub": "enforced at checkout", "cue": "coupon"},
               {"icon": "📲", "title": "Any channel", "sub": "app · WhatsApp · SMS · Telegram", "cue": "WhatsApp"},
               {"icon": "📈", "title": "Proven results", "sub": "vs a 15% control group", "cue": "control"}]},
    {"id": "tagline", "kind": "tagline", "narration": "Smarter offers. Zero wasted discounts. More profit."},
    {"id": "end", "kind": "end", "narration": "AI Offer Engine. Every offer, only when it pays. "
                                               "We're looking for pilot partners and investors."},
]
