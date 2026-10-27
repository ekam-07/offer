# 30-day simulation from 2026-10-22 (30 days)

Thu 22 Oct:  77 offers given, ₹1,951 committed
Fri 23 Oct:  33 offers given, ₹600 committed
Sat 24 Oct:  15 offers given, ₹240 committed
Sun 25 Oct:   7 offers given, ₹110 committed  (festival boost x1.4)
Mon 26 Oct:   4 offers given, ₹60 committed  (festival boost x1.4)
Tue 27 Oct:  20 offers given, ₹895 committed  (festival boost x1.4)
Wed 28 Oct:  16 offers given, ₹590 committed  (festival boost x1.4)
Thu 29 Oct:  24 offers given, ₹276 committed  (festival boost x1.4)
Fri 30 Oct:  15 offers given, ₹195 committed  (festival boost x1.4)
Sat 31 Oct:   7 offers given, ₹110 committed  (festival boost x1.4)
Sun 01 Nov:  16 offers given, ₹883 committed  (festival boost x1.4)
Mon 02 Nov:  17 offers given, ₹331 committed  (festival boost x1.4)
Tue 03 Nov:  18 offers given, ₹200 committed  (festival boost x1.4)
Wed 04 Nov:  12 offers given, ₹150 committed  (festival boost x1.4)
Thu 05 Nov:  24 offers given, ₹80 committed  (festival boost x1.4)
Fri 06 Nov:  26 offers given, ₹528 committed  (festival boost x1.4)
Sat 07 Nov:  17 offers given, ₹145 committed  (festival boost x1.4)
Sun 08 Nov:   7 offers given, ₹150 committed  (festival boost x1.4)
Mon 09 Nov:  11 offers given, ₹110 committed
Tue 10 Nov:  15 offers given, ₹60 committed
Wed 11 Nov:  21 offers given, ₹611 committed
Thu 12 Nov:  20 offers given, ₹115 committed
Fri 13 Nov:  11 offers given, ₹90 committed
Sat 14 Nov:  15 offers given, ₹55 committed
Sun 15 Nov:  11 offers given, ₹157 committed
Mon 16 Nov:  20 offers given, ₹431 committed
Tue 17 Nov:  18 offers given, ₹85 committed
Wed 18 Nov:  13 offers given, ₹30 committed
Thu 19 Nov:  20 offers given, ₹105 committed
Fri 20 Nov:  11 offers given, ₹30 committed

## Rule checks over the whole period (541 offers given)

- PASS  R1 offer after /stop
- PASS  R8 one active offer
- PASS  R8 same offer repeated
- PASS  R9 message gap
- PASS  R9 paid gap
- PASS  R9 messages per 7 days
- PASS  R9 paid per 7 days
- PASS  R10 cooldown
- PASS  R20 coupon interval
- PASS  R31 per-customer spend
- PASS  R13 daily budget
- PASS  R13 pacing

## Coupon codes

- 168 single-use codes issued, 23 redeemed by their owner.
- 8 attempts refused and logged: {'code belongs to another customer': 8} (e.g. classmates sharing codes).

## Arms (per customer over the period)

| Arm | Customers | Offers given | Purchases | Net margin | Discount cost | Redemptions | Opt-outs | Extra purchases vs control | Extra margin vs control |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 26 | 0 | 1.19 | ₹457 | ₹0 | 0.0 | 0 | - | - |
| RULES | 174 | 541 | 1.65 | ₹673 | ₹6 | 23.0 | 4 | +0.46 | ₹+216 ± 223 |

Offers given by: {'RULES': 516, 'EXPLORE': 25} (EXPLORE = random allowed offer for learning, R27).

Control group: 26 customers. Differences smaller than about twice the ± value are within noise; with a classmate-sized pool (~20 people, ~3 controls) a test like this cannot prove anything.

Note: customers' true responses come from the simulator's assumptions (config/response_model.yaml), and the arms contain different customers, so segment mix also differs between arms.