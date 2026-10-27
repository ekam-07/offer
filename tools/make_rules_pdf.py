"""Builds Offer_Rules.pdf. Segment, tier, validity and cost tables are read from config/*.yaml,
so the PDF always matches the rules the engine enforces.

    python tools/make_rules_pdf.py Offer_Rules.pdf .
"""
import sys

import yaml
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT, ROOT = sys.argv[1], sys.argv[2]
R = yaml.safe_load(open(f"{ROOT}/config/rules.yaml", encoding="utf-8"))
O = yaml.safe_load(open(f"{ROOT}/config/offers.yaml", encoding="utf-8"))
sys.path.insert(0, ROOT)
from src.config import RULES_VERSION  # noqa: E402

pdfmetrics.registerFont(TTFont("Segoe", r"C:\Windows\Fonts\segoeui.ttf"))
pdfmetrics.registerFont(TTFont("Segoe-Bold", r"C:\Windows\Fonts\segoeuib.ttf"))
pdfmetrics.registerFont(TTFont("Segoe-Italic", r"C:\Windows\Fonts\segoeuii.ttf"))
pdfmetrics.registerFontFamily("Segoe", normal="Segoe", bold="Segoe-Bold", italic="Segoe-Italic")
NAVY, LIGHT, LINE = colors.HexColor("#1f3a5f"), colors.HexColor("#eef2f7"), colors.HexColor("#c9d3e0")
MUTED, WARN_BG = colors.HexColor("#5b6675"), colors.HexColor("#fff4e5")
S = {
    "title": ParagraphStyle("t", fontName="Segoe-Bold", fontSize=17, leading=21, textColor=NAVY),
    "sub": ParagraphStyle("s", fontName="Segoe", fontSize=8.3, leading=10.8, textColor=MUTED),
    "h": ParagraphStyle("h", fontName="Segoe-Bold", fontSize=10.5, leading=13, textColor=NAVY, spaceBefore=7, spaceAfter=3),
    "body": ParagraphStyle("b", fontName="Segoe", fontSize=8.1, leading=10.4),
    "cell": ParagraphStyle("c", fontName="Segoe", fontSize=7.7, leading=9.6),
    "cellb": ParagraphStyle("cb", fontName="Segoe-Bold", fontSize=7.7, leading=9.6),
    "bullet": ParagraphStyle("bl", fontName="Segoe", fontSize=8.1, leading=10.4, leftIndent=10, spaceAfter=1.5),
}
W = A4[0] - 28 * mm


def P(t, s="body"):
    return Paragraph(t, S[s])


def table(rows, widths):
    data = [[P(c, "cellb" if r == 0 or j == 0 else "cell") for j, c in enumerate(row)] for r, row in enumerate(rows)]
    t = Table(data, colWidths=[W * w for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                           ("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("LINEBELOW", (0, 0), (-1, 0), 0.7, NAVY),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2)]))
    return t


def section(title, intro, rows, widths, keep=True):
    parts = [P(title, "h")] + ([P(intro), Spacer(1, 3)] if intro else []) + [table(rows, widths)]
    return KeepTogether(parts) if keep else parts


def rules_table(title, intro, rows):
    return section(title, intro, [["Rule", "What it says"]] + rows, [0.23, 0.77])


st, f, g, b = R["segment_thresholds"], R["frequency"], R["guards"], R["budget"]
story = [
    P("Offer Decision Rules", "title"),
    P(f"Smart Offer Engine · every offer, from the AI or the rules, is checked against these before it is logged · "
      f"source config/rules.yaml + offers.yaml, enforced in src/rules.py · rules version {RULES_VERSION} (stored with "
      f"every decision) · tables below are generated from the config files · all times IST · 23 Oct 2026", "sub"),
    Spacer(1, 3),
]

story.append(rules_table("Step 1 · Can this customer get anything right now?", None, [
    ["R1 Consent", "Only opted-in customers. /stop works immediately and is checked again at SEND time, per channel. "
                   "Telegram is the real channel; email, SMS, push and WhatsApp are simulated. /start opts back in. "
                   "Customers can ask for their data to be erased."],
    ["R18 Control group", f"{R['holdout_pct']}% of customers never get offers. Assigned by a hash of a salt + customer ID, "
                          "so it never changes between decisions. Change the salt only to start a new experiment."],
    ["R11 Quiet hours", f"No SENDING between {f['quiet_hours'][0]}:00 and {f['quiet_hours'][1]:02d}:00 IST. Decisions may run "
                        "at night; they are planned for the morning window."],
    ["R26 Uplift group", "Sleeping dogs (reacted badly to our offers) get no offers. Lost causes (gone and not browsing) get free offers only."],
]))

story.append(section("Step 2 · Segment (first match wins, in this order)",
    "Each customer also gets a BASE SEGMENT: the same, ignoring the open cart. The open cart decides the offer list "
    "(reminder first), but every cap is the stricter of the two, so a VIP with an open cart keeps VIP's limits.",
    [["Segment", "Condition"],
    ["CART_ABANDONER", f"Open cart in the last {st['cart_abandon_window_hours']}h (checked first, so the reminder-first rule can't be skipped)"],
    ["NEW", f"Never ordered, joined ≤ {st['new_max_tenure_days']} days ago (same meaning as the NEW coupon tier)"],
    ["NEVER_BOUGHT", "Never ordered, joined earlier"],
    ["DORMANT", f"No order for max({st['dormant_min_recency_days']} days, {st['dormant_gap_multiple']}× their own usual gap)"],
    ["AT_RISK", f"3+ orders and {st['at_risk_min_gap_ratio']}× later than their usual gap, or churn risk ≥ {st['at_risk_min_churn_risk']}"],
    ["POINTS_EXPIRING", f"{st['points_expiring_min']}+ points expiring within 30 days"],
    ["DEAL_SEEKER", f"{st['deal_seeker_min_orders']}+ orders and coupons on {int(st['deal_seeker_min_coupon_rate'] * 100)}%+ of them"],
    ["VIP", f"Top {st['vip_top_spend_pct']}% by 12-month spend"],
    ["LOYAL", f"Buy-anyway score ≥ {st['loyal_min_would_buy_anyway']}"],
    ["BROWSER", f"{st['browser_min_sessions_no_buy']}+ sessions without buying in 14 days"],
    ["REGULAR", "Everyone else"],
], [0.2, 0.8]))

story.append(rules_table("Definitions", None, [
    ["Usual gap", "Average days between a customer's orders. Undefined with 0-1 orders: then DORMANT uses 90 days only, "
                  "and AT_RISK (3+ orders) doesn't apply. Gap ratio = days since last order / usual gap."],
    ["Churn risk", "A formula, not a trained model: 0.5 × min(gap ratio / 3, 1) + 0.3 × min(days since last order / 120, 1) "
                   "+ 0.2 × (no order in 90 days). 0 for customers who never ordered."],
    ["Buy chance (7 days)", "Estimated chance of buying in the next 7 days WITHOUT an offer, from the customer's non-coupon "
                            "purchase rate, discounted when they are overdue."],
]))

u = R["uplift_groups"]
story.append(section("Uplift groups (each customer gets one)", None, [["Group", "Rule of thumb", "Effect"],
    ["Persuadable", "Everyone not below", "Where offers pay off"],
    ["Sure thing", f"Buy chance in 7 days ≥ {int(u['sure_thing_min_p_buy_7d'] * 100)}% and coupons on < {int(u['sure_thing_max_coupon_rate'] * 100)}% of orders",
     f"Discounts mostly wasted; small, rare coupons only because coupons_for_sure_things = {str(R['coupons_for_sure_things']).lower()}"],
    ["Lost cause", f"No order for {u['lost_cause_min_recency_days']}+ days and no visits in 90 days", "Free offers only (R26)"],
    ["Sleeping dog", f"{u['sleeping_dog_min_negative_reactions_90d']}+ bad reactions to our offers in 90 days ('fewer offers', 'not interested' on an offer, /stop). Hiding products doesn't count", "No offers (R26)"],
], [0.15, 0.45, 0.4]))

seg_rows = [["Segment", "Allowed offers (tie-break order; NONE always last)", "Max %", "Max flat ₹", "Max cost ₹", "Coupon cap"]]
for name in R["segment_order"]:
    s = R["segments"][name]
    seg_rows.append([name, ", ".join(s["allowed"]), f"{s['max_percent']}%", f"₹{s['max_flat_inr']}", f"₹{s['max_offer_cost_inr']}",
                     f"{s['product_coupon_max_percent']}%" if s.get("product_coupon_max_percent") is not None else "tier"])
story.extend(section("R2 · Allowed offers per segment, and R4 caps",
    "The fallback picks the allowed offer with the highest expected profit (R30); free nudges count as EP ≥ 0, so they win "
    "when no paid offer pays. Ties go to the cheaper offer, then this list's order. Max % applies to store-wide % "
    "discounts, Max flat ₹ to flat discounts, and Max cost ₹ to ANY offer's cost (free shipping, points, coupons). "
    "Caps are the stricter of segment and base segment.", seg_rows, [0.16, 0.5, 0.07, 0.09, 0.09, 0.09], keep=False))

story.append(rules_table("Step 3 · How big the offer can be", None, [
    ["R3 Catalog range", "Value must be within the offer's own range (e.g. % off 5–20%, flat ₹50–300, product coupon 5–25%)."],
    ["R4 Segment cap", "% or flat ₹ within the segment's maximum; product coupons within the segment's coupon cap."],
    ["R5 Margin floor", f"A discount must leave {R['margin_floor_pct']}% margin in that category ("
                        + ", ".join(f"{k} {v}%" for k, v in R["category_margin_pct"].items() if k != "default")
                        + "). % offers: the % is capped. Flat ₹ off and free shipping: the minimum basket rises until the cost "
                        "is within the allowed % (₹150 off in Electronics needs a ₹1,880 basket), and the offer is blocked "
                        f"if that exceeds {R['max_min_basket_multiple']}× the average order. Free delivery, flat ₹ off and % off only work "
                        "in categories that keep the floor at that basket (e.g. not Mobiles), and the message names them. "
                        "Impossible offers are skipped with the reason."],
    ["R6 Flat size", f"Flat ₹ off ≤ {int(R['max_flat_share_of_aov'] * 100)}% of the customer's average order (₹{R['default_aov_inr']} "
                     "if they have no history). Below the offer minimum → skipped, next offer tried."],
    ["R21 First order only", f"WELCOME and the FIRST_ORDER coupon tier are only for customers who have never ordered. "
                             f"WELCOME's cost uses ₹{R['default_aov_inr']} as the order value (10% = ₹90)."],
    ["Welcome scope", "Welcome applies only to categories that can afford 10% (Fashion, Home, Beauty, Books)."],
]))

tier_rows = [["Tier", "Who", "Max %", "Max ₹", "Min basket", "At most every"]]
existing = [t for t in R["coupon_tiers"] if not t.get("first_order")]
for t in R["coupon_tiers"]:
    if t.get("first_order"):
        who = "Never ordered (segment NEW or NEVER_BOUGHT)"
    else:
        i = existing.index(t)
        lo, hi = int(t["min_p_buy_7d"] * 100), int(existing[i - 1]["min_p_buy_7d"] * 100) if i else None
        who = (f"Buy chance in 7 days ≥ {lo}%" if hi is None else
               f"Buy chance in 7 days {lo}–{hi}%" if lo else f"Buy chance in 7 days under {hi}%")
    tier_rows.append([t["name"], who, f"{t['max_percent']}%", f"₹{t['max_coupon_inr']}",
                      f"₹{t['min_order_inr']}" if t.get("min_order_inr") else "-", f"{t['coupon_every_days']} days"])
story.append(section("R19 / R20 · Coupon tiers (product coupons)",
    "A product coupon applies to the one product the customer wants most (cart > wishlist > last viewed > popular in "
    "category; never out of stock or sensitive). Frequent buyers always get less, and less often, than occasional, "
    "irregular or first-order customers (checked at startup). FIRST_ORDER is not the most generous tier: new accounts "
    "are the easiest to fake, so it needs a minimum basket. Goodwill exception: with coupons_for_sure_things on, a "
    "customer who buys anyway gets a small coupon when due, although its expected profit is negative.",
    tier_rows, [0.14, 0.36, 0.09, 0.09, 0.12, 0.2]))

story.append(rules_table("Step 4 · Timing and frequency", None, [
    ["R8 Active offer", "While a customer holds an offer they were told is valid (coupon, free delivery, points, goal...), "
                        "they get no new offer of any kind until it ends; the daily check skips them. One active paid "
                        "offer at a time, and never the same offer again while it is still valid."],
    ["R9 Frequency", f"Paid offers: at least {f['paid_min_hours_between']}h apart, at most {f['paid_max_per_7_days']} per 7 days "
                     f"({R['feedback']['fewer_offers_min_hours']}h apart, i.e. one a week, after 'fewer offers'). Any message: "
                     f"at least {f['message_min_hours_between']}h apart, at most {f['message_max_per_7_days']} per 7 days. Cart "
                     "reminders skip the gaps (they only matter inside the 48h window) but count towards the weekly limits."],
    ["R10 Discount cooldown", f"No new discount within {f['discount_cooldown_days']} days of using one."],
    ["R12 Reminder first", f"Anyone with an open cart gets a free cart reminder (or the in-stock alternative) first; paid "
                           f"offers only {f['escalation_wait_hours']}h later. If the reminder doesn't lead to a purchase, the next cart "
                           "message is a discount (product coupon, ₹ off or free delivery) when one pays, never a second reminder."],
    ["R20 Coupon interval", "Product coupons at most every " + " / ".join(f"{t['coupon_every_days']}" for t in R["coupon_tiers"])
                            + " days (" + " / ".join(t["name"] for t in R["coupon_tiers"]) + ")."],
]))

val_rows = [["Offer", "Valid for", "Told to customer", "Cost counted by R13"]]
cost = {"percent": "average order × %", "flat": "the ₹ value", "shipping": f"₹{O['shipping_cost_inr']} shipping",
        "points": f"points × ₹{O['point_value_inr']}", "reminder": "₹0", "access": "₹0", "none": "₹0",
        "bundle": "the ₹ value (only on the add-on item)", "choice": f"₹{O['shipping_cost_inr']} (either perk)"}
for oid, o in O["offers"].items():
    if oid == "NONE":
        continue
    c = "product price × %" if o.get("scope") == "focus_product" else cost[o["type"]]
    val_rows.append([oid, f"{o.get('valid_days', '-')} days", "yes" if o.get("state_validity", True) else "no (internal)", c])
story.append(section("Offer validity and cost", "Validity drives R8 and must be stated honestly in the message (R15). "
                     "Costs are the maximum liability (as if redeemed).", val_rows, [0.25, 0.15, 0.2, 0.4]))

ep = R["expected_profit"]
story.append(rules_table("R30 · Expected profit", "EP = (P_with − P_without) × margin − P_with × cost. Every paid offer needs "
    "EP > 0, except the goodwill coupon. The AI is given each option's EP and the checker recomputes it."
    + (" With a minimum order, a customer who buys because of the offer fills the basket up to it, so their margin "
       "(and a % discount's cost) uses max(typical order, minimum order)." if ep.get("count_basket_topup") else ""), [
    ["P_without", "Buy chance in 7 days without an offer (see Definitions)."],
    ["P_with", "P_without + (1 − P_without) × lift. Lift is the engine's own estimate from observable signals only: "
               f"discount sensitivity = {ep['base_sensitivity']} + {ep['price_signal_weight']} × max(coupon rate, 2 × promo click "
               f"rate) + {ep['churn_weight']} × churn risk (max {ep['max_sensitivity']}), times discount% / (discount% + "
               f"{ep['half_effect_pct']}). Free nudges have fixed lifts when their condition holds."],
    ["margin", "Average order (₹900 if none) × category margin % (for welcome: the eligible categories' margin)."],
    ["cost", "The offer's cost (table above)."],
]))

story.append(rules_table("Step 5 · Budget", None, [
    ["R13 Daily budget", f"₹{b['daily_inr']:,} a day across all customers, counted as {b['cost_basis'].replace('_', ' ')}."],
    ["R13 Pacing", f"Released evenly over {f['quiet_hours'][1]:02d}:00–{f['quiet_hours'][0]}:00: by the end of hour h of the window, at "
                   "most daily × h / 14 may be committed, so an 08:00 rush can't leave evening customers with nothing."],
    ["R13 Atomic", "The final budget check and the log write happen in one database transaction, so two decisions (even "
                   "in two programs) can't both spend the last rupees."],
    ["Expected cost", "Logged with every decision: cost × chance the customer buys while holding the offer. Used to plan "
                      "the budget; the maximum liability above stays the hard cap."],
    ["R31 Per customer", f"Offer cost given to one customer over {R['spend_cap']['window_days']} days ≤ "
                         f"{R['spend_cap']['pct_of_margin_12m']}% of the margin they brought in over 12 months (at least "
                         f"₹{R['spend_cap']['min_inr']}), so one customer can't soak up repeated offers."],
]))

story.append(rules_table("Step 6 · Guards", None, [
    ["R22 No stacking", "No % or flat discount while a store promotion already covers that category (one discount per order)."],
    ["R23 Abuse", f"No paid offers if return rate ≥ {int(g['abuse_max_return_rate'] * 100)}% ({g['abuse_min_orders']}+ orders) or "
                  f"{g['abuse_max_coupon_returns']}+ coupon orders returned."],
    ["R24 Discount training", f"If the last {g['discount_training_last_orders']} orders all used a coupon, no discount now "
                              "(so customers don't learn to wait for deals). Replaces the planned R14."],
    ["R25 Stock", "Never promote an out-of-stock product. If the cart item is out of stock, the cart reminder becomes "
                  "CART_ALTERNATIVE (a similar in-stock product), or nothing."],
    ["Coupon codes", "Every paid offer gets a unique, single-use code tied to the customer, added at send time. A code used "
                     "by anyone else, twice, or after expiry is refused and logged as misuse (shared codes are caught)."],
    ["R28 Feedback", f"'Not interested' suppresses that offer for {R['feedback']['not_interested_suppress_days']} days; "
                     "'fewer offers' slows the customer down; 'stop' opts out."],
    ["R29 Free nudges", "Restock reminders (Grocery/Beauty, at the customer's own reorder cycle), review requests and points "
                        "updates only when their condition holds. They cost nothing, so they are the default when unsure. "
                        "Bought-together only with a real 'bought with' item in stock; wishlist alerts only for a real price "
                        "drop or restock; pick-your-perk is not asked again once the customer has picked."],
]))

story.append(rules_table("Step 7 · The message", None, [
    ["R15 Honest message", f"≤ {R['message']['max_chars']} characters. States the real value and the real expiry. Every number "
                           "must be a term of the offer or a fact about the customer. The text must match the offer type (a "
                           "reminder never mentions a discount). No pressure phrases, no invented promises, no links, emails, "
                           "phone numbers or HTML. Category- and product-limited offers name what they cover."],
    ["R16 Sensitive data", "Never mentions age, gender, religion, caste, income, health and similar, and never personalises "
                           "on sensitive product types (e.g. health products). Customer text is sanitised before use."],
    ["R17 Valid answer", "The AI must return valid JSON with an offer from the catalog."],
]))

flow = [
    "Rules build the allowed offers and value ranges for the customer.",
    "The AI picks the offer with the highest expected profit (may be none); the checker re-checks it against every rule, one retry.",
    "If the AI fails or breaks the rules twice, the rules-only fallback picks the allowed offer with the highest expected profit (a free nudge when no paid offer pays).",
    f"R27 exploration: {int(R['exploration']['rate'] * 100)}% of decisions use a random allowed offer, with its probability "
    "logged, so the system can learn which offers work.",
    "The decision is logged with the rules version and a planned send time (the customer's usual active hour, 08:00–22:00).",
    "Human review is flagged when: the AI failed or broke a rule, an offer costs over "
    f"₹{R['review']['high_value_inr']}, {R['review']['budget_near_pct']}%+ of the daily budget is used, or a reply contains complaint words.",
    f"Delivery runs in {R['delivery']['mode'].replace('_', ' ')} mode with a kill switch, on {R['delivery']['default_channel']}; consent is checked "
    "again at send time and nothing is sent during quiet hours. Paid offers get their single-use code at send time.",
]
story.append(KeepTogether([P("How an offer is chosen", "h")] + [Paragraph(t, S["bullet"], bulletText=f"{i}.") for i, t in enumerate(flow, 1)]))

gaps = Table([[[P("<b>Known limits</b>")] + [Paragraph(t, S["bullet"], bulletText="•") for t in [
    "Duplicate-account detection needs device/address data the dataset doesn't have (the flag exists, always false).",
    "Price-drop and back-in-stock alerts need price and stock history; not built.",
    "One coupon per order at checkout is enforced by the store, not this engine (R22 avoids stacking on store promotions).",
    "With ~20 classmates the control group is ~3 people: results can't be statistically meaningful at that size.",
    "India's DPDP Act: consent withdrawal (/stop) and erasure (consent.erase) are built; a privacy notice and retention policy are still needed.",
]]]], colWidths=[W])
gaps.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WARN_BG), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                          ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
story += [Spacer(1, 6), gaps]


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Segoe", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(14 * mm, 8 * mm, f"Smart Offer Engine · Offer Decision Rules · version {RULES_VERSION}")
    canvas.drawRightString(A4[0] - 14 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


SimpleDocTemplate(OUT, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                  title="Offer Decision Rules").build(story, onFirstPage=footer, onLaterPages=footer)
