#!/usr/bin/env python3
"""
Odds Shift — history & calibration engine (v1)

The moat layer. Instead of describing today's odds, this measures whether the crowd
has historically been *right* — using real resolved markets and their price history.

What it does
  1. BACKFILL: pages through closed Polymarket markets (highest volume first) and keeps
     those that resolved inside the lookback window (default: last 365 days).
  2. HISTORY: for each market, pulls its daily price series from the CLOB API and takes
     the price at a fixed lead time before resolution (default: 7 days).
  3. CALIBRATION: buckets those prices and measures how often the market actually
     resolved YES in each bucket. Well-calibrated = 20% markets resolve 20% of the time.
  4. SCORES: Brier score (mean squared error of the forecast), plus a sports/non-sports
     split, because the favourite–longshot bias is usually worst in sports books.

Everything is cached to history.jsonl so re-runs are cheap. No API key required.

Usage:
    python3 history.py --limit 150 --lead-days 7
    python3 history.py --report-only          # rebuild the report from cache
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import time
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com/prices-history"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "history.jsonl")

SPORT_SLUG_RE = re.compile(
    r"^(nfl|nba|mlb|nhl|ncaa|ufc|f1|epl|ucl|mex|bra|arg|atp|wta|pga|lpga|"
    r"lol|cs2|dota|valorant|afl|nrl|rugby|crint|superbowl|tennis|golf|boxing|mma)-", re.I)


def get_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "odds-shift-history/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.2 * (i + 1))
    return None


def fnum(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def pct(x):
    return f"{x*100:.1f}%"


def load_cache():
    done = {}
    if os.path.exists(CACHE):
        with open(CACHE) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done[r["slug"]] = r
                except json.JSONDecodeError:
                    continue
    return done


def closed_markets(pages=4, page_size=100, min_volume=50_000, lookback_days=400, min_age_days=10):
    """Page closed markets, newest first, filtered to a usable window."""
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for p in range(pages):
        url = f"{GAMMA}?{urllib.parse.urlencode({'closed': 'true', 'limit': page_size, 'offset': p*page_size, 'order': 'volume', 'ascending': 'false'})}"
        data = get_json(url)
        if not data:
            break
        for m in data:
            end = m.get("endDate") or m.get("endDateIso") or ""
            try:
                end_dt = dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
            except ValueError:
                continue
            age = (now - end_dt).days
            if age < min_age_days or age > lookback_days:
                continue
            if fnum(m.get("volume")) < min_volume:
                continue
            try:
                tokens = json.loads(m.get("clobTokenIds") or "[]")
                prices = json.loads(m.get("outcomePrices") or "[]")
                outcomes = json.loads(m.get("outcomes") or "[]")
            except json.JSONDecodeError:
                continue
            if not tokens or not prices:
                continue
            out.append({"market": m, "token": tokens[0],
                        "resolved_yes": 1 if fnum(prices[0], -1) == 1 else 0,
                        "end": end_dt, "outcomes": outcomes})
        time.sleep(0.4)
    return out


def price_at_lead(token, end_dt, lead_days):
    """Price closest to (resolution - lead_days), from the daily series."""
    url = f"{CLOB}?{urllib.parse.urlencode({'market': token, 'interval': 'max', 'fidelity': 1440})}"
    data = get_json(url)
    if not data or "history" not in data or not data["history"]:
        return None
    target = end_dt.timestamp() - lead_days * 86400
    best, best_d = None, None
    for pt in data["history"]:
        d = abs(pt["t"] - target)
        if best_d is None or d < best_d:
            best, best_d = fnum(pt["p"]), d
    if best is None or best <= 0.0 or best >= 1.0:
        return None
    return best


def backfill(limit, lead_days, min_volume, pages=4, min_age_days=10):
    cache = load_cache()
    todo = [c for c in closed_markets(pages=pages, min_volume=min_volume, min_age_days=min_age_days)
            if c["market"]["slug"] not in cache]
    print(f"cache: {len(cache)} · new candidates: {len(todo)} (limit {limit})")
    added = 0
    for c in todo[:limit]:
        m = c["market"]
        price = price_at_lead(c["token"], c["end"], lead_days)
        if price is None:
            continue
        row = {
            "slug": m["slug"],
            "q": (m.get("question") or "")[:140],
            "price": price,
            "lead_days": lead_days,
            "resolved_yes": c["resolved_yes"],
            "volume": fnum(m.get("volume")),
            "end": c["end"].date().isoformat(),
            "sports": bool(SPORT_SLUG_RE.match(m.get("slug") or "")),
            "outcomes": c["outcomes"][:2],
        }
        cache[row["slug"]] = row
        with open(CACHE, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        added += 1
        if added % 25 == 0:
            print(f"  …{added} backfilled")
        time.sleep(0.25)
    print(f"backfilled {added} new rows · cache now {len(cache)}")
    return list(cache.values())


BANDS = [(0.0, .05), (.05, .10), (.10, .20), (.20, .35), (.35, .50),
         (.50, .65), (.65, .80), (.80, .90), (.90, .95), (.95, 1.0)]


def report(rows):
    today = dt.datetime.now().strftime("%d %b %Y")
    non_sports = [r for r in rows if not r.get("sports")]
    out = [f"# Odds Shift — Calibration Report ({today})", "",
           f"_{len(rows)} resolved markets · {len(non_sports)} non-sports · "
           f"price sampled {rows[0]['lead_days'] if rows else 7} days before resolution_", "",
           "## Are the odds real probabilities?", ""]

    def table(subset, label):
        lines = [f"**{label}**", "",
                 "| Price band | Markets | Resolved YES | Actual rate | Gap |",
                 "|---|---|---|---|---|"]
        total_brier, n_brier = 0.0, 0
        for lo, hi in BANDS:
            band = [r for r in subset if lo <= r["price"] < hi]
            if not band:
                continue
            actual = sum(r["resolved_yes"] for r in band) / len(band)
            mid = (lo + hi) / 2
            gap = actual - mid
            lines.append(f"| {int(lo*100)}–{int(hi*100)}% | {len(band)} | "
                         f"{sum(r['resolved_yes'] for r in band)} | {pct(actual)} | "
                         f"{'+' if gap >= 0 else ''}{pct(gap)} |")
        for r in subset:
            total_brier += (r["price"] - r["resolved_yes"]) ** 2
            n_brier += 1
        if n_brier:
            lines += ["", f"**Brier score:** {total_brier/n_brier:.4f} "
                          f"_(0 = perfect, 0.25 = coin-flip guessing; lower is better)_", ""]
        return lines

    out += table(rows, "All markets")
    out += table(non_sports, "Non-sports only")
    sports = [r for r in rows if r.get("sports")]
    if sports:
        out += table(sports, "Sports only")

    # headline read
    longshots = [r for r in rows if r["price"] < 0.10]
    favs = [r for r in rows if r["price"] > 0.90]
    out += ["## Headline", ""]
    if longshots:
        actual = sum(r["resolved_yes"] for r in longshots) / len(longshots)
        avg = sum(r["price"] for r in longshots) / len(longshots)
        out.append(f"- **Long shots (<10%):** {len(longshots)} markets, priced {pct(avg)} on average, "
                   f"resolved YES {pct(actual)} of the time → "
                   f"{'overpriced' if actual < avg else 'underpriced'} by {pct(abs(actual-avg))}.")
    if favs:
        actual = sum(r["resolved_yes"] for r in favs) / len(favs)
        avg = sum(r["price"] for r in favs) / len(favs)
        out.append(f"- **Heavy favourites (>90%):** {len(favs)} markets, priced {pct(avg)} on average, "
                   f"resolved YES {pct(actual)} of the time → "
                   f"{'overpriced' if actual < avg else 'underpriced'} by {pct(abs(actual-avg))}.")
    out += ["", "<!-- Gan: this table is the product. Nobody publishes it. -->", "",
            "Method: price sampled at a fixed lead time before resolution; only markets with "
            "≥ the volume floor included. Not financial advice."]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=150)
    ap.add_argument("--lead-days", type=int, default=7)
    ap.add_argument("--min-volume", type=float, default=50_000)
    ap.add_argument("--pages", type=int, default=4, help="pages of closed markets to scan (100/page)")
    ap.add_argument("--min-age-days", type=int, default=10)
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--out", default="calibration.md")
    args = ap.parse_args()

    if args.report_only:
        rows = list(load_cache().values())
    else:
        rows = backfill(args.limit, args.lead_days, args.min_volume,
                        pages=args.pages, min_age_days=args.min_age_days)
    if not rows:
        print("no data yet — run without --report-only first")
        return
    md = report(rows)
    with open(os.path.join(HERE, args.out), "w") as fh:
        fh.write(md)
    print(f"wrote {args.out} from {len(rows)} resolved markets")


if __name__ == "__main__":
    main()
