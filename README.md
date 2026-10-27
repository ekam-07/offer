# AI Offer Engine

**Every offer pays for itself.** Most stores send discounts to everyone, and about two out of three go to shoppers who would have bought anyway. This engine decides, for each customer, *which* offer to send (or none), checks every decision against 31 business rules, and delivers it through a Telegram bot.

🎬 **Demo video** (3:48): not stored in the repo; rebuild it with the steps under *Rebuilding the demo video*.

## How it works

```
customer data → features → segment → Claude picks an offer → 31 rules check it → Telegram
                                          │ fails or breaks a rule
                                          └──────────→ rules engine decides instead
```

- **Claude decides first.** It sees the customer's features (cart, last order, wishlist, chance to buy anyway) and returns an offer plus the message, as JSON.
- **Every decision is checked.** 31 rules in [config/rules.yaml](config/rules.yaml) (see [Offer_Rules.pdf](Offer_Rules.pdf)): margins never go below the floor, no stacking with store sales, consent, frequency caps, honest messages (e.g. a "price drop" must be real).
- **A rules fallback** makes the decision whenever the AI fails, times out or breaks a rule, so the store never goes without an answer.
- **Spend as little as possible:** free cart reminders first, discounts only when they pay; bundles, wishlist price-drop alerts, pick-your-perk, at most one live offer per customer.
- **Runs on its own:** sign-ups, abandoned carts and a daily check trigger decisions automatically.

## Results (simulated, 200 customers × 1,000 weeks)

| Policy | Extra net margin / week | Discount wasted on buy-anyway | Cost per extra purchase |
|---|---:|---:|---:|
| 10% to everyone | +₹2,571 | ₹4,834 | ₹358 |
| Rules only | +₹6,801 | ₹932 | ₹103 |
| **Rules + AI** | **+₹7,635** | **₹202** | **₹51** |

Full reports: [data/eval_report.md](data/eval_report.md), 30-day run: [data/sim30_report.md](data/sim30_report.md). Customer behaviour is calibrated on public datasets (Flipkart catalog, RetailRocket clickstream, Hillstrom email test).

## Quick start

Needs Python 3.11+.

```bash
pip install -r requirements.txt
cp .env.example .env            # add ANTHROPIC_API_KEY (and TELEGRAM_BOT_TOKEN if you want the bot)
python generate_data.py         # synthetic customers → data/shop.db, data/customers.json
python run_decisions.py         # decide an offer for every customer (--no-agent: rules only, no API key)
python preview.py               # dashboard at http://127.0.0.1:5000
```

Keep `DELIVERY_MODE=dry_run` in `.env` until you really want Telegram messages to go out.

### Other scripts

| Command | What it does |
|---|---|
| `python run_automation.py --once` | one round of automatic decisions (events + daily check + sending) |
| `python show_log.py --flagged` | decisions where the AI failed or broke a rule |
| `python evaluate.py --no-ai` | compare no offers vs 10% to everyone vs rules (vs AI) |
| `python simulate_30d.py` | 30-day forward simulation with Diwali |
| `python tools/experiment.py` | try rule changes and measure their profit |
| `python calibrate.py` | recalibrate personas from datasets in `data/raw/` |
| `python -m tests.test_pipeline` | tests (also `test_rules_v2`, `test_edge_cases`, `test_automation`, `test_telegram`) |

## Project layout

```
src/          engine: features, segments, agent (Claude), rules, fallback, delivery, Telegram bot, automation
config/       rules.yaml, offers, catalog, personas, response model (rules live in files, not code)
web/          dashboard page served by preview.py
data/         generated customers, CSV dataset, evaluation reports (databases are rebuilt, not committed)
docs/         data dictionary, edge cases, research notes
tests/        rule, pipeline, edge-case, automation and Telegram tests
tools/        experiments, rules PDF builder
video/        scripts that render the demo videos (story2 = latest)
```

## Hosting on Vercel

The repo deploys as-is: import it at [vercel.com/new](https://vercel.com/new) (no build settings needed). `vercel.json` sends every request to [api/index.py](api/index.py), which runs the same Flask app as `preview.py`.

- Optional: add `ANTHROPIC_API_KEY` under Project → Settings → Environment Variables so Claude decides; without it the rules engine decides.
- Each instance starts from the demo data in `data/demo/` (rebuild with `python tools/make_vercel_data.py`), copied into `/tmp`. Changes made on the page are temporary.
- Nothing is ever sent from the hosted copy: delivery is dry-run, the Telegram bot and background automation are off (test events still run when you trigger them on the page).

## Data not in the repo

- **Databases** (`data/*.db`) are rebuilt by `generate_data.py` and `run_decisions.py`.
- **Raw datasets** for calibration go in `data/raw/` (download them yourself): Flipkart e-commerce sample, RetailRocket `events.csv`, Kevin Hillstrom MineThatData email test.

## Rebuilding the demo video

```bash
pip install edge-tts numpy scipy playwright && playwright install msedge   # plus ffmpeg on PATH
cp data/sim_offers.db data/demo_offers.db     # sim_offers.db is written by evaluate.py
PORT=5001 OFFERS_DB=data/demo_offers.db AUTOMATION=1 TELEGRAM_DISABLED=1 FORCE_DRY_RUN=1 python preview.py   # keep running
python video/story2/voice.py && python video/story2/render.py && python video/story2/make.py
```

The render drives the real dashboard on port 5001 (dry-run, Telegram disabled). Voice is a stock neural voice; music and sound effects are synthesised in code, so there are no licensed assets.
