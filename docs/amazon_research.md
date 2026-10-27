# How Amazon targets offers, and how our engine could plug into Amazon

Research date: 22 Oct 2026. Every claim links to its source. Items marked **UNVERIFIED** came from
third-party sources or pages we could not fully read; check them before relying on them.

---

## 1. Short answer

- **Amazon does what our engine does**, but publishes little about its own retail targeting. Its
  published research says it targets by **uplift** (who changes behaviour *because of* the offer), not
  by who is most likely to buy, and picks targets with **constrained optimisation** under business
  limits. That is the same idea as our holdout, "wasted on buy-anyway" and budget rules.
- **Outsiders cannot get Amazon's per-customer data and cannot message Amazon buyers with offers.**
  Amazon's API policy forbids using customer personal data for anything but shipping, tax and legal
  needs, and forbids targeting Amazon customers for product marketing.
- **So "integrating with Amazon" means two things:**
  - *On Amazon:* our engine becomes a **decision layer for a seller**. It reads Amazon's
    aggregated reports and recommends *which audience, which discount, which products, which
    budget*. Amazon's own tools then deliver it, mainly **Brand Tailored Promotions** and ad audiences.
  - *Off Amazon:* the per-customer design we built (individual offers and messages) works on a
    seller's **own website**, for example with **Buy with Prime** checkout, using AWS services.

---

## 2. How Amazon itself targets customers (what is public)

| What | Key point | Source |
|---|---|---|
| Item-to-item collaborative filtering (2003) | Behind "Customers who bought this also bought": item B is related to A if A's buyers are unusually likely to buy B. | [Amazon Science](https://www.amazon.science/the-history-of-amazons-recommendation-algorithm) |
| Causal bandits for content targeting (RecSys 2022) | Raw click and purchase rates overstate a widget's value because targeted shoppers often buy anyway. Amazon ranks content by the *estimated causal effect* (uplift models inside contextual bandits), tested on the homepage, product pages and cart. | [paper (PDF)](https://cdn.amazon.science/ee/dd/0709356f4b4ba73e7cae644e8ce6/mitigating-targeting-bias-in-content-recommendation-with-causal-bandits.pdf) |
| Segment Discovery (2024) | **Uplift modelling + constrained optimisation** to choose whom to target, maximising business value under business limits. Argues that targeting by purchase propensity misses the customers who actually respond. | [Amazon Science](https://www.amazon.science/publications/segment-discovery-enhancing-e-commerce-targeting), [arXiv 2409.13847](https://arxiv.org/abs/2409.13847) |
| Price experiments | Amazon Pricing Labs runs controlled price experiments with heterogeneous-treatment-effect methods (causal forests). | [Amazon Science blog](https://www.amazon.science/blog/the-science-of-price-experiments-in-the-amazon-store) |
| Independent study of Amazon logs | At least 75% of recommendation click-throughs would have happened anyway, so CTR is not impact. | [Sharma, Hofman, Watts](https://arxiv.org/pdf/1611.09414) |

**Not public (UNVERIFIED):** how Amazon picks who sees "Deals for you", how cart price-drop alerts
and "still interested?" emails are triggered, and how it sets its own promotion budgets.

**What this means for us:** our design already follows the published approach. That includes
measuring extra purchases against a control group instead of raw redemptions, and the AI's
`p_buy_7d` profit method. Our simulation reproduced the effect Amazon describes: "10% to everyone"
spent 69% of its discount on people who would have bought anyway.

---

## 3. Signals Amazon says it collects

- **Privacy Notice:** "your interaction with products, content, and services". Third-party summaries
  list clickstream, products viewed or searched, visit length, scrolling, clicks and mouse-overs
  (**UNVERIFIED** list).
  [Privacy Notice](https://www.amazon.com/gp/help/customer/display.html?nodeId=GX7NJQ4ZB8MHFRNJ)
- **Interest-based ads:** "browsing history, purchase patterns, search queries";
  "shopping, streaming, and browsing signals".
  [Amazon Ads guide](https://advertising.amazon.com/library/guides/interest-based-advertising)
- **Seller analytics announcement (2024):** "detail page views, add-to-carts, review engagement, search
  and browse behavior, purchase conversion".
  [Amazon announcement](https://sellingpartners.aboutamazon.com/amazon-unveils-powerful-customer-analytics-tools-to-unlock-seller-growth)
- **Shopper controls** that confirm browsing feeds recommendations: Browsing History can be turned off,
  and "Improve Your Recommendations" lets shoppers mark items "Not interested".
  [help page](https://www.amazon.com/gp/help/customer/display.html?nodeId=GXPNZSZPM3UPM2VA)

---

## 4. Terminology dictionary: our names, Amazon's names and standard names

"Amazon term" is the name used in Seller Central, Brand Analytics or Amazon Ads. "GA4" is Google
Analytics 4, the most common web event standard. "Personalize" is Amazon's AWS recommendation
service. These are the names to use if the system should look familiar to Amazon or e-commerce teams.

| Our engine | Amazon term (where) | GA4 event / metric | Amazon Personalize |
|---|---|---|---|
| browsing session | **Sessions** (Business Reports) | `session_start` | `sessionId` (PutEvents) |
| product page view | **Page Views**, **detail page views**; "glance views" (older, **UNVERIFIED**) | `view_item` | `View` event type |
| shown in search or a list | **Impressions** (Search Query Performance) | `view_item_list` | `IMPRESSION` field |
| click on a product | **Clicks** (Search Query Performance) | `select_item` | custom event type |
| add to cart | **Cart Adds** (SQP); **add-to-carts** (Attribution) | `add_to_cart` | custom event type |
| purchase | **Purchases**, **Units Ordered** | `purchase` | `Purchase` event type |
| conversion rate | **Unit Session Percentage** = units ÷ sessions | (derived) | – |
| cart abandoner | **Cart Abandoners** / **Cart remarketing** (Brand Tailored Promotions) | (derived from `add_to_cart` without `purchase`) | – |
| browser (views, no buy) | **Views remarketing** (Sponsored Display, BTP); **Potential New Customers** | (derived) | – |
| loyal / repeat buyer | **Repeat Customers**; Repeat Purchase report | `customer_type` = returning | – |
| VIP | **High-Spend Customers** (BTP) | – | – |
| at risk / dormant | **Lapsed customers** (BTP 2024); "At Risk", "Hibernating" in Customer Loyalty Analytics (**UNVERIFIED**) | GA4 **churn probability** | – |
| new customer | **New-to-brand** (no purchase from the brand in 12 months); **One-time customers** | `customer_type` = new | – |
| recency, frequency, monetary | RFM tiers in Customer Loyalty Analytics: Top Tier, Promising, At Risk, Hibernating (**UNVERIFIED**) | – | Connect Customer Profiles `_order_last_occurrence`, `_orders_count`, `_orders_total_price_sum` |
| average order value | AOV (Business Reports sales ÷ orders) | `value` | `_orders_total_price_average` |
| `p_buy_7d` | – | GA4 **purchase probability** (purchase in next 7 days) | – |
| `churn_risk` | – | GA4 **churn probability** (inactive next 7 days) | – |
| deal seeker / `coupon_rate` | **No Amazon audience by this name found.** Closest: coupon performance reports (per product), "In-market" audiences | `coupon` param; Segment `Coupon Applied` | – |
| offer shown / redeemed / dismissed | Coupon and promotion performance reports | `view_promotion` / `select_promotion` | Next Best Action: `Viewed` / `Taken` / `Not taken` |
| offer type (our catalog) | Coupons, Price Discounts (incl. Prime-only), Lightning Deals, Best Deals, BOGO, Subscribe & Save, Brand Tailored Promotions | `promotion_id`, `promotion_name` | Actions dataset `ACTION_ID` |
| extra purchases vs control group | Uplift / incrementality (Amazon Science) | – | – |
| who to target | **Persuadables** (target), **Sure Things** (skip: buy anyway), **Lost Causes**, **Do-Not-Disturbs** (uplift quadrants) | – | – |

Sources: [Brand Analytics](https://sell.amazon.com/tools/amazon-brand-analytics),
[Sponsored Display audiences](https://advertising.amazon.com/library/guides/sponsored-display-audiences),
[New-to-brand](https://advertising.amazon.com/resources/whats-new/sponsored-display-new-to-brand-metrics),
[GA4 events](https://developers.google.com/analytics/devguides/collection/ga4/reference/events),
[GA4 predictive metrics](https://support.google.com/analytics/answer/9846734),
[Personalize ECOMMERCE schemas](https://docs.aws.amazon.com/personalize/latest/dg/ECOMMERCE-datasets-and-schemas.html),
[Uplift modelling](https://en.wikipedia.org/wiki/Uplift_modelling),
[Unit Session Percentage (Amazon forum)](https://sellercentral.amazon.com/seller-forums/discussions/t/2d907f0bd4e2b28f471aa5a6cb903df9).

---

## 5. What a third party can plug into on Amazon

### 5.1 Data you can get: aggregated only

The **Selling Partner API (SP-API)** gives Brand Registry sellers reports
([report types](https://developer-docs.amazon/sp-api/docs/report-type-values-analytics)):

| Report | What it has | Per customer? |
|---|---|---|
| Search Query Performance | impressions, clicks, cart adds, purchases per search query and product | No |
| Search Catalog Performance | the same funnel per product | No |
| Repeat Purchase | orders, unique customers, repeat-customer %, repeat revenue per product | No |
| Market Basket | products bought together | No |
| Sales and Traffic | sessions, page views, Buy Box %, units, revenue per date or product | No |

- **Notifications API:** hourly `DETAIL_PAGE_TRAFFIC_EVENT` (glance views) and `ITEM_SALES_EVENT_CHANGE`
  per product, both aggregated.
  [notification types](https://developer-docs.amazon/sp-api/docs/notification-type-values)
- **No API gives per-customer browsing, cart or abandonment data.** Order-level buyer data is
  shrinking: Amazon removed buyer email from FBA order data in Jan 2026.
  [release notes](https://developer-docs.amazon/sp-api/docs/sp-api-release-notes)

### 5.2 Promotions: you can read them through the API, but not create them

- **Promotions API v2025-12-01** has three operations: `searchPromotions`, `getPromotion` and
  `getSelection`. **They only read promotions; none creates or updates one** (checked on the docs page).
  [Promotions API](https://developer-docs.amazon/sp-api/docs/promotions-api)
- Coupons, discounts and deals are created in the **Seller Central UI**. Coupons can cover up to 200
  products, last up to 90 days, and Amazon charges a fee per redemption.
  [seller promotions guide](https://sell.amazon.com/blog/seller-promotions)

### 5.3 Brand Tailored Promotions: Amazon's version of our segments

Brand owners pick an **audience** and a discount; **Amazon decides which shoppers see it and delivers it**.
[launch post](https://sell.amazon.com/blog/announcements/brand-tailored-promotions),
[2024 update](https://sellercentral.amazon.com/seller-forums/discussions/t/3c431f5d-7257-49fb-bb63-7e99d9137f3c)

- **Audiences (2023):** Brand Followers, Repeat Customers, Recent Customers, High-Spend Customers,
  Potential New Customers, Cart Abandoners.
- **Added in 2024:**
  - Views remarketing, Cart remarketing, One-time customers, Lapsed customers.
  - In-market Customer and Complementary Product Remarketing (for shoppers outside the brand's
    current customers).
- **Goals:** New Customer Acquisition, Customer Retention, Re-engagement, Cross-sell.
- **Limits:** discount of 10–50%; one use per customer, for one unit.
- **Reported results:** 100,000+ sellers used it, reaching ~8M new and 15M+ repeat customers.
  [Amazon, 2024](https://sellingpartners.aboutamazon.com/amazon-unveils-powerful-customer-analytics-tools-to-unlock-seller-growth)
- **API access:** none found.

**How our segments map to Brand Tailored Promotions audiences:**

| Our segment | Amazon audience | Notes |
|---|---|---|
| CART_ABANDONER | Cart Abandoners / Cart remarketing | direct match |
| LOYAL | Repeat Customers | direct match |
| VIP | High-Spend Customers | direct match |
| AT_RISK, DORMANT | Lapsed customers | goal: Re-engagement |
| NEW | Potential New Customers / One-time customers | goal: New Customer Acquisition |
| BROWSER | Views remarketing | direct match |
| DEAL_SEEKER | none | Amazon doesn't expose discount sensitivity per shopper |
| POINTS_EXPIRING | none | sellers have no loyalty-points program on Amazon |

Our cash discount caps (0–20%) are below the 10–50% Brand Tailored Promotions range, so our
guardrails are stricter than Amazon's minimum. That means for segments where we cap discounts at
0% or 5%, Amazon's tool can't express our choice. Those customers would get "no promotion" instead.

### 5.4 Amazon Ads: audiences, not individuals

- **Amazon Marketing Cloud:** a clean room where "you can only access aggregated, anonymous outputs";
  SQL-built audiences can be activated in ads.
  [AMC](https://advertising.amazon.com/solutions/products/amazon-marketing-cloud)
- **Sponsored Display:** views remarketing (lookback 7–90 days), purchases remarketing (7–365 days),
  plus in-market, lifestyle, interests and life-events audiences.
  [audiences guide](https://advertising.amazon.com/library/guides/sponsored-display-audiences)
- **Amazon Attribution:** measures clicks, detail page views, add-to-carts, purchases and new-to-brand
  from off-Amazon traffic.
  [Attribution](https://advertising.amazon.com/amazon-attribution)

### 5.5 What is NOT allowed (important for our design)

**SP-API Acceptable Use Policy** (checked):
[policy](https://sellercentral.amazon.com/mws/static/policy?documentType=AUP&locale=en_US)
- **4.1** "Do not use Personally Identifiable Information about Customers for any purposes other than
  merchant-fulfilled shipping". Tax and legal uses are also allowed elsewhere in the policy.
- **4.2** "Do not target Amazon Customers for product marketing or review fabrication and modification"
- **4.4** "Do not aggregate data across Authorized Users' businesses or customers obtained through the Amazon Services API"

**Other rules:**
- **Data Protection Policy:** buyer personal data is for tax and shipping on a must-have basis, kept no
  longer than 30 days after delivery, and must be encrypted.
  [DPP](https://sellercentral.amazon.com/mws/static/policy?documentType=DPP&locale=en_US)
- **Buyer messaging:** only messages "necessary to complete an order or to respond to a customer
  service inquiry". Marketing messages, including coupons, are prohibited. The Messaging API has
  no marketing message type.
  [Communication Guidelines](https://sellercentral.amazon.com/help/hub/reference/external/G1701) (login page; from search snippets),
  [Messaging API](https://developer-docs.amazon/sp-api/docs/messaging-api)

**So:** sending our bot's offers (Telegram, Discord, WhatsApp, email) to **Amazon buyers** would break
these rules. On Amazon, offers must go through Amazon's own promotion and ads tools.

### 5.6 Off Amazon: where our per-customer design fits

- **Buy with Prime** puts Amazon checkout on a seller's *own* website. Merchants receive shopper order
  information including email addresses, and send user events (`page-load`, `click`, `widget-viewed`).
  The API is in early access; its data-use terms were not reviewed (**UNVERIFIED**).
  [press release](https://press.aboutamazon.com/2022/4/amazon-unveils-buy-with-prime-expanding-prime-shopping-benefits-beyond-amazon-com),
  [user events](https://documents.buywithprime.amazon.com/bwp-api/v2024-04-01/docs/send-user-events-for-buy-with-prime)
- **AWS building blocks** (Amazon's tech, your own customers):
  - **Amazon Personalize, Next Best Action recipe** (`aws-next-best-action`): ranks *actions*, i.e.
    offers, per user by propensity.
    - An Actions dataset with `ACTION_ID`, `VALUE`, `EXPIRATION_TIMESTAMP` and `REPEAT_FREQUENCY`
      (a frequency cap of up to 30 days).
    - Action interactions `Viewed` / `Taken` / `Not taken`.
    - Needs 50+ taken and 50+ not-taken/viewed interactions within 6 weeks.
    - [docs](https://docs.aws.amazon.com/personalize/latest/dg/native-recipe-next-best-action.html)
  - **Personalize ECOMMERCE domain:**
    - Event types `View` and `Purchase`.
    - Fields `USER_ID`, `ITEM_ID`, `TIMESTAMP`, `EVENT_TYPE`, `EVENT_VALUE`, `IMPRESSION`, `RECOMMENDATION_ID`.
    - [docs](https://docs.aws.amazon.com/personalize/latest/dg/ECOMMERCE-datasets-and-schemas.html)
  - **Messaging:** **Amazon Pinpoint reaches end of support on 30 Oct 2026.**
    - Use **Amazon Connect** Customer Profiles plus outbound campaigns, or **AWS End User Messaging**
      (SMS, push) and **SES** (email).
    - [migration guide](https://docs.aws.amazon.com/pinpoint/latest/userguide/migrate.html)

---

## 6. How our engine should evolve for Amazon

Three ways to deploy the same core (rules + AI + checker + log + evaluation):

1. **Amazon seller decision layer.** This is the realistic "Amazon integration".
   - **Inputs:** SP-API aggregated reports (Sales and Traffic, Search Query Performance,
     Repeat Purchase) and coupon or promotion performance reports.
   - **Decision unit:** *(audience × product group)* instead of one customer. For example: "Cart
     Abandoners for Headphones: 15% off, 14 days, budget ₹X".
   - **Rules:** the same guardrails (margin floor, caps, cooldowns between promotions, budget), plus
     Amazon's own limits such as the 10–50% Brand Tailored Promotions range.
   - **Output:** a recommended promotion plan. A human creates it in Seller Central, because no
     create API exists. The engine then monitors it through the Promotions API.
   - **Measurement:** before/after and audience-vs-rest comparisons from Amazon's reports, since we
     can't run a per-customer holdout on Amazon.
2. **Amazon Ads layer.** The AI's choices become **audience, bid and budget** decisions for Sponsored
   Display or DSP, using AMC audiences. The output is never a message to a person.
3. **Own-storefront mode.** This is what we built.
   - Per-customer offers on the seller's own site or app, possibly with Buy with Prime checkout.
   - Delivered by consented messaging (Connect, SES or our bot).
   - Optionally backed by Personalize Next Best Action.

### Concrete changes worth making to the prototype

1. **Rename events to the standards:** `view_item`, `add_to_cart`, `purchase`, `view_promotion`,
   `select_promotion` (GA4). Keep an export to Personalize `View` / `Purchase`.
2. **Use Amazon's names for metrics and segments where they exist:**
   - metrics: sessions, page views, unit session %, new-to-brand
   - segments: label each one with its Brand Tailored Promotions audience, e.g. CART_ABANDONER →
     "Cart Abandoners"
3. **Log offer outcomes as Viewed / Taken / Not taken.** This matches our Redeem, Not interested and
   Stop buttons, and is the format Personalize Next Best Action trains on.
4. **Add an "Amazon mode" planner** that groups customers into Amazon's audiences and outputs a
   promotion plan (audience, products, discount within 10–50%, duration, budget) that passes the
   same rule checker.
5. **Add a consent and data-source flag per customer** so the engine never messages anyone whose data
   came from Amazon orders, which enforces AUP 4.1 and 4.2 in code.

---

## 7. Caveats

- Amazon's internal targeting is only partly public. Section 2 covers what Amazon has *published*,
  not necessarily what runs in production today.
- Several Seller Central help pages need a login, so some definitions come from Amazon's own forum
  posts or search snippets. Those are noted next to the claims.
- Features change often. Brand Tailored Promotions audience names are from 2023–2024 posts; check the
  current list in Seller Central.
- This is a technical summary, not legal advice. Before building on Amazon data, read the current
  SP-API Acceptable Use Policy and Data Protection Policy in full.
