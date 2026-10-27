# Offer policy evaluation

200 customers (customers.json), 1000 simulated weeks, decisions at 2026-10-22 14:00. All policies face the same simulated customers and random draws.

AI policy: 181 decided by the agent, 0 fell back to rules, 0 flagged.

## Results per week (average)

| Policy | Messaged | Purchases | Extra purchases | Discount cost | Wasted on buy-anyway | Net margin | Extra net margin | Cost / extra purchase | Opt-outs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No offers | 0 | 34.4 | +0.0 ± 0.0 | ₹0 | ₹0 | ₹24,964 | +0 ± 0 | - | 0.0 |
| 10% to everyone | 185 | 58.1 | +23.7 ± 4.4 | ₹12,223 | ₹8,421 | ₹23,896 | -1,069 ± 2,847 | ₹516 | 1.7 |
| Rules | 154 | 54.1 | +19.7 ± 4.0 | ₹3,335 | ₹1,685 | ₹32,041 | +7,077 ± 3,056 | ₹169 | 1.4 |
| Rules + AI | 169 | 52.2 | +17.7 ± 3.8 | ₹1,825 | ₹733 | ₹32,444 | +7,480 ± 2,890 | ₹103 | 1.5 |

- **Extra purchases / extra net margin**: compared with sending nothing (± = spread across simulated weeks).
- **Wasted on buy-anyway**: discount paid to customers who would have bought without the offer.

## Extra net margin per customer, by segment (₹ per week)

| Segment | Customers | 10% to everyone | Rules | Rules + AI |
|---|---:|---:|---:|---:|
| DEAL_SEEKER | 33 | +42 | +41 | +36 |
| NEW | 32 | +30 | +32 | +25 |
| DORMANT | 30 | +23 | +24 | +19 |
| AT_RISK | 29 | +6 | +7 | +26 |
| LOYAL | 29 | -88 | +0 | +9 |
| CART_ABANDONER | 27 | +25 | +99 | +99 |
| BROWSER | 13 | -2 | +1 | +11 |
| VIP | 6 | -290 | +169 | +169 |
| POINTS_EXPIRING | 1 | -622 | +102 | +102 |

- **Rules** earns less than the blanket discount for: DEAL_SEEKER. Those segments' caps or offer ladders may be too cautious.
- **Rules + AI** earns less than the blanket discount for: DEAL_SEEKER, NEW, DORMANT. Those segments' caps or offer ladders may be too cautious.

## How you would measure it for real (holdout test)

In one real week you can't see what customers would have done without an offer, so you compare the 165 customers who got the rules policy with the 35 in the control group (holdout).

- Measured uplift in purchase rate: **+22.3% ± 11.7%** (95% interval)
- True uplift (known only in simulation): **+9.4%**
- The interval excludes zero, so the effect is detectable, but the estimate is off from the true value by 12.9%: small groups are noisy.
