# Polymarket Daily → **Odds Shift**

A daily brief on what moved in prediction markets — politics, crypto, tech and culture.
Data is machine-collected; the voice is written by a human.

## What's here

| Path | What it is |
|---|---|
| `digest.py` | The pipeline. Pulls live markets from the Polymarket Gamma API, curates, and emits a markdown digest. |
| `site/` | The landing page (static HTML/CSS/JS). Restyle freely — light theme is the default, dark mode toggles in the nav. |
| `issue-002.md` | A real generated issue (curated, 28 markets screened). |
| `latest.json` | Raw market data for the latest run, consumed by the landing page. |

## Run it

```bash
python3 digest.py                       # print to stdout
python3 digest.py --out issue.md        # write a file
python3 digest.py --json latest.json    # also dump structured data
python3 digest.py --sports              # include a separate sports section
```

No API key. No dependencies — standard library only.

## Curation rules

Raw 24h volume is dominated by sports and near-resolved markets. The pipeline therefore:

1. **Drops near-resolved markets** (price ≥ 0.95 or ≤ 0.05) — if the market already knows, it isn't news.
2. **Keeps one market per event** — no eight variations of the same game.
3. **Applies a liquidity floor** so tiny markets don't masquerade as signal.
4. **Splits by category** — Politics, Crypto, Tech & AI, Culture, Macro — with sports kept separate by design.
5. **Builds an "Insights of the day" block** — the five standout facts, ready for a human to add humour to.

## Preview the site locally

```bash
cd site && python3 -m http.server 3210
# open http://localhost:3210
```

## Roadmap

- [ ] LLM pass: turn the top movers into 2 sentences of "why it matters"
- [ ] Category weighting (less sport, more politics/crypto for a finance-adjacent audience)
- [ ] Archive pages per issue (SEO + shareable links)
- [ ] Weekly deep-dive for the paid tier
- [ ] Mover alerts when a market shifts >15% in an hour

## Notes

Odds are market prices, not probabilities. Nothing here is financial advice, and this
does not tell anyone what to bet on. Source: Polymarket's public API.
