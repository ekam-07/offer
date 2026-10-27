# Offer policy evaluation

200 customers (customers.json), 1000 simulated weeks, decisions at 2026-10-16 14:00. All policies face the same simulated customers and random draws.

AI policy: 177 decided by the agent, 0 fell back to rules, 3 flagged.

## Results per week (average)

| Policy | Messaged | Purchases | Extra purchases | Discount cost | Wasted on buy-anyway | Net margin | Extra net margin | Cost / extra purchase | Opt-outs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No offers | 0 | 39.8 | +0.0 ± 0.0 | ₹0 | ₹0 | ₹18,345 | +0 ± 0 | - | 0.0 |
| 10% to everyone | 182 | 61.9 | +22.1 ± 4.3 | ₹7,581 | ₹4,834 | ₹19,393 | +1,048 ± 1,820 | ₹343 | 1.6 |
| Rules | 177 | 58.3 | +18.5 ± 4.0 | ₹2,098 | ₹1,029 | ₹24,162 | +5,817 ± 2,057 | ₹113 | 1.5 |
| Rules + AI | 174 | 58.2 | +18.4 ± 4.0 | ₹1,202 | ₹275 | ₹24,936 | +6,591 ± 2,033 | ₹65 | 1.5 |

- **Extra purchases / extra net margin**: compared with sending nothing (± = spread across simulated weeks).
- **Wasted on buy-anyway**: discount paid to customers who would have bought without the offer.

## Extra net margin per customer, by segment (₹ per week)

| Segment | Customers | 10% to everyone | Rules | Rules + AI |
|---|---:|---:|---:|---:|
| DEAL_SEEKER | 37 | +46 | +31 | +30 |
| LOYAL | 31 | -39 | -8 | +8 |
| AT_RISK | 28 | +28 | +38 | +35 |
| CART_ABANDONER | 22 | +26 | +83 | +83 |
| DORMANT | 20 | +20 | +17 | +16 |
| NEW | 19 | +36 | +39 | +37 |
| VIP | 16 | -116 | +24 | +46 |
| BROWSER | 14 | +6 | +11 | +17 |
| REGULAR | 8 | +24 | +29 | +28 |
| NEVER_BOUGHT | 3 | +10 | +12 | +12 |
| POINTS_EXPIRING | 2 | -158 | +83 | +83 |

- **Rules** earns less than the blanket discount for: DEAL_SEEKER, DORMANT. Those segments' caps or offer ladders may be too cautious.
- **Rules + AI** earns less than the blanket discount for: DEAL_SEEKER, DORMANT. Those segments' caps or offer ladders may be too cautious.

## Control group per segment

| Segment | Control | Treated |
|---|---:|---:|
| DEAL_SEEKER | 5 | 32 |
| LOYAL | 3 | 28 |
| AT_RISK | 3 | 25 |
| CART_ABANDONER | 1 | 21 |
| DORMANT | 3 | 17 |
| NEW | 6 | 13 |
| VIP | 2 | 14 |
| BROWSER | 2 | 12 |
| REGULAR | 1 | 7 |
| NEVER_BOUGHT | 0 | 3 |
| POINTS_EXPIRING | 0 | 2 |

- Segments with fewer than 10 controls can't be measured on their own: AT_RISK (3), BROWSER (2), CART_ABANDONER (1), DEAL_SEEKER (5), DORMANT (3), LOYAL (3), NEVER_BOUGHT (0), NEW (6), POINTS_EXPIRING (0), REGULAR (1), VIP (2).

## How you would measure it for real (holdout test)

In one real week you can't see what customers would have done without an offer, so you compare the 174 customers who got the rules policy with the 26 in the control group (holdout).

- Measured uplift in purchase rate: **+19.5% ± 14.1%** (95% interval)
- True uplift (known only in simulation): **+9.3%**
- The interval excludes zero, so the effect is detectable, and it contains the true value.
