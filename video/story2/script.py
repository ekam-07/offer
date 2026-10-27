"""High-energy, demo-first video (about 3.5 to 4 minutes): an 18-second kinetic hook, then about 80%
live demo (the real app in an iframe, the real Telegram messages animated), then the proof, why we
win, and the end card. Every scene with kind "demo" starts with a step wipe that names the step.
"""
VOICE = "en-US-AndrewMultilingualNeural"
RATE, PITCH = "+7%", "-3Hz"

SCENES = [
    {"id": "hook", "kind": "hook",
     "narration": "Every online store has the same leak. Discounts. "
                  "Two out of every three go to shoppers who would have bought anyway. "
                  "Send a hundred-rupee coupon to three thousand people, and two lakh rupees just vanish. "
                  "Every. Single. Week. "
                  "Worse, shoppers learn to wait for the next sale. "
                  "So what if every offer paid for itself?"},
    {"id": "reveal", "kind": "reveal",
     "narration": "Meet the AI Offer Engine. Let's see it live."},
    {"id": "list", "kind": "demo", "step": "Every shopper, one line",
     "narration": "This is the live dashboard. Two hundred shoppers, each one already decided by AI. "
                  "Every shopper is one clean line: orders, browsing, carts, wishlists and consent. "
                  "Sort it, page through it. It stays fast even with lakhs of customers. Let's find Karthik."},
    {"id": "customer", "kind": "demo", "step": "AI decides, rules check",
     "narration": "Karthik left a seven-thousand-rupee water purifier in his cart, nine hours ago. "
                  "Only a twelve percent chance he buys on his own. "
                  "Claude, our AI, picks the offer: a simple cart reminder. "
                  "Then thirty-one business rules check it, and the reason is written so anyone can understand it."},
    {"id": "spend", "kind": "demo", "step": "Spend as little as possible",
     "narration": "The secret? Spend as little as possible. Free nudges go first: "
                  "twenty-two shoppers get a cart reminder, and it costs zero. "
                  "Paid offers, like free delivery, go out only when the math says they pay."},
    {"id": "phone", "kind": "phone", "step": "Straight to the phone",
     "narration": "Now watch it on a real phone. Karthik gets a friendly reminder. Free. "
                  "Days go by. No purchase. "
                  "So now, and only now, the engine sends a discount: free delivery, with a code only he can use. "
                  "Reminder first. Discount second. Never spam."},
    {"id": "bundle", "kind": "demo", "step": "Bought together",
     "narration": "And it does more than discounts. Bought together. Aditya has a table lamp on his wishlist. "
                  "Eighteen in a hundred lamp buyers also pick up this water purifier, so the engine suggests it. "
                  "No discount, and eighty rupees of expected profit."},
    {"id": "deal", "kind": "demo", "step": "Never at a loss",
     "narration": "When a discount is used, it has to prove itself. Ananya gets forty rupees off a hair dryer, "
                  "and the money rule shows the store still keeps at least a ten percent margin. Never sold at a loss."},
    {"id": "wishlist", "kind": "demo", "step": "Wishlist watcher",
     "narration": "Wishlist watcher. The moment Aarav's wireless mouse drops from twelve hundred to nine hundred rupees, "
                  "he hears about it. Real news, at zero cost."},
    {"id": "perk", "kind": "demo", "step": "Pick your perk",
     "narration": "Pick your perk. Diya hasn't shopped in forty days, so she gets to choose: "
                  "free delivery, or bonus points. Both cost the store the same, but the choice is hers."},
    {"id": "guard", "kind": "demo", "step": "AI, always checked",
     "narration": "And the AI is never trusted blindly. Here, Claude wrote that a price had dropped. It hadn't. "
                  "Rule fifteen caught it, and the message was fixed before anyone saw it."},
    {"id": "signup", "kind": "demo", "step": "Runs on its own",
     "narration": "It all runs by itself. Automatic decisions are on, with a daily check of everyone. "
                  "A new customer signs up, and within seconds, she has a welcome offer. Nobody pressed a button."},
    {"id": "cart", "kind": "demo", "step": "One live offer",
     "narration": "She leaves her cart? She already holds a live offer, so nothing new goes out. One live offer at a time."},
    {"id": "proof", "kind": "proof",
     "narration": "Does it actually make money? We tested it on customers calibrated with real data: "
                  "Flipkart prices, a real store's browsing and carts, and a sixty-four thousand shopper experiment. "
                  "The result? Three times the profit of a blanket discount, with eighty-eight percent less spent on discounts."},
    {"id": "mvp", "kind": "mvp",
     "narration": "Why we win. Profit, not clicks. Never a loss. AI, always checked. "
                  "Free nudges first. Smart new offers. Fully automatic.",
     "cards": [{"icon": "💰", "title": "Profit, not clicks", "sub": "every offer must earn more than it costs", "cue": "Profit"},
               {"icon": "🔒", "title": "Never a loss", "sub": "10% margin kept, any category", "cue": "loss"},
               {"icon": "🛡️", "title": "AI, always checked", "sub": "31 rules + automatic fallback", "cue": "checked"},
               {"icon": "🛒", "title": "Free nudges first", "sub": "reminder → discount only if no buy", "cue": "nudges"},
               {"icon": "🧺", "title": "Smart new offers", "sub": "bought together · wishlist · perks", "cue": "Smart"},
               {"icon": "⚡", "title": "Fully automatic", "sub": "events + daily check → phone", "cue": "automatic"}]},
    {"id": "end", "kind": "end", "narration": "AI Offer Engine. Every offer, only when it pays. Let's build it together."},
]
