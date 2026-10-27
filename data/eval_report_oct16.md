# Offer policy evaluation

200 customers (customers.json), 1000 simulated weeks, decisions at 2026-10-16 14:00. All policies face the same simulated customers and random draws.

AI policy skipped (--no-ai).

## Results per week (average)

| Policy | Messaged | Purchases | Extra purchases | Discount cost | Wasted on buy-anyway | Net margin | Extra net margin | Cost / extra purchase | Opt-outs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No offers | 0 | 34.4 | +0.0 ± 0.0 | ₹0 | ₹0 | ₹24,964 | +0 ± 0 | - | 0.0 |
| 10% to everyone | 185 | 58.1 | +23.7 ± 4.4 | ₹12,223 | ₹8,421 | ₹23,896 | -1,069 ± 2,847 | ₹516 | 1.7 |
| Rules | 166 | 47.3 | +12.9 ± 3.2 | ₹2,400 | ₹1,431 | ₹30,143 | +5,179 ± 2,690 | ₹186 | 1.6 |

- **Extra purchases / extra net margin**: compared with sending nothing (± = spread across simulated weeks).
- **Wasted on buy-anyway**: discount paid to customers who would have bought without the offer.

## Extra net margin per customer, by segment (₹ per week)

| Segment | Customers | 10% to everyone | Rules |
|---|---:|---:|---:|
| CART_ABANDONER | 35 | +27 | +80 |
| DEAL_SEEKER | 32 | +43 | +5 |
| AT_RISK | 29 | +6 | +8 |
| DORMANT | 27 | +24 | +21 |
| BROWSER | 25 | +13 | +11 |
| LOYAL | 23 | -72 | +7 |
| NEW | 16 | +22 | +26 |
| VIP | 12 | -222 | +35 |
| POINTS_EXPIRING | 1 | -622 | +102 |

- **Rules** earns less than the blanket discount for: DEAL_SEEKER, DORMANT, BROWSER. Those segments' caps or offer ladders may be too cautious.

## Control group per segment

| Segment | Control | Treated |
|---|---:|---:|
| CART_ABANDONER | 6 | 29 |
| DEAL_SEEKER | 7 | 25 |
| AT_RISK | 4 | 25 |
| DORMANT | 3 | 24 |
| BROWSER | 1 | 24 |
| LOYAL | 3 | 20 |
| NEW | 1 | 15 |
| VIP | 1 | 11 |
| POINTS_EXPIRING | 0 | 1 |

- Segments with fewer than 10 controls can't be measured on their own: AT_RISK (4), BROWSER (1), CART_ABANDONER (6), DEAL_SEEKER (7), DORMANT (3), LOYAL (3), NEW (1), POINTS_EXPIRING (0), VIP (1).

## How you would measure it for real (holdout test)

In one real week you can't see what customers would have done without an offer, so you compare the 174 customers who got the rules policy with the 26 in the control group (holdout).

- Measured uplift in purchase rate: **+14.3% ± 13.9%** (95% interval)
- True uplift (known only in simulation): **+6.3%**
- The interval excludes zero, so the effect is detectable, and it contains the true value.
