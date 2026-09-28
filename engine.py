#!/usr/bin/env python3
"""
Odds Shift — probability engine (v1)

Turns raw prediction-market prices into signals:

  LAYER 1 — METRICS (mechanical)
    • implied probability (raw price)
    • vig-adjusted fair probability (from best bid/ask midpoint)
    • spread (efficiency proxy)
    • momentum: 1h / 1d / 1w / 1m price changes
    • liquidity (24h volume, total volume)

  LAYER 2 — SIGNALS (judgement)
    • information vs noise: size of the move measured against liquidity and spread
    • favourite–longshot bias flags (the documented tendency of long shots to be overpriced)
    • extreme-price asymmetry warnings (little upside, large downside)
    • disagreement: markets priced near 50/50 carrying serious volume

  LAYER 3 — CALIBRATION (the moat)
    • appends a daily snapshot to snapshots.jsonl
    • once ~30+ days accumulate, `--calibrate` reports how often markets at a given
      price actually resolved YES — i.e. whether the crowd is well-calibrated

Usage:
    python3 engine.py                     # signals to stdout
    python3 engine.py --out signals.md
    python3 engine.py --snapshot          # also append today's snapshot
    python3 engine.py --calibrate         # report calibration from stored snapshots

This is analytics, not betting advice. No position sizing, no recommendations.
"""
import argparse
import collections
import datetime as dt
import json
import math
import os
import re
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com/markets"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_FILE = os.path.join(HERE, "snapshots.jsonl")

SPORT_SLUG_RE = re.compile(
    r"^(nfl|nba|mlb|nhl|ncaa|ufc|f1|epl|ucl|mex|bra|arg|atp|wta|pga|lpga|"
    r"lol|cs2|dota|valorant|afl|nrl|rugby|crint|superbowl|tennis|golf|boxing|mma)-", re.I)


def fetch(params):
    url = f"{GAMMA}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "odds-shift-engine/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fnum(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def money(v):
    v = fnum(v)
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}k"
    return f"${v:.0f}"


def pct(x):
    return f"{fnum(x)*100:.1f}%"


def is_sports(slug, question):
    return bool(SPORT_SLUG_RE.match(slug or "")) or bool(
        re.search(r"\b(spread|o/u|over/under)\b", question or "", re.I))


# ---------------------------------------------------------------- layer 1: metrics
def metrics(m):
    try:
        outcomes = json.loads(m.get("outcomes") or "[]")
        prices = json.loads(m.get("outcomePrices") or "[]")
    except json.JSONDecodeError:
        return None
    if not outcomes or not prices:
        return None

    raw = fnum(prices[0])
    bid, ask = fnum(m.get("bestBid")), fnum(m.get("bestAsk"))
    spread = fnum(m.get("spread"))
    mid = (bid + ask) / 2 if 0 < bid < 1 and 0 < ask <= 1 else raw
    # Remove the round-trip cost embedded in the quote, as a better fair-value estimate.
    fair = mid if mid > 0 else raw
    vig = max(0.0, spread / 2)

    return {
        "id": m.get("id"),
        "q": (m.get("question") or "").strip()[:130],
        "slug": m.get("slug") or "",
        "raw": raw,
        "fair": fair,
        "spread": spread,
        "vig_half": vig,
        "chg1h": m.get("oneHourPriceChange"),
        "chg1d": m.get("oneDayPriceChange"),
        "chg1w": m.get("oneWeekPriceChange"),
        "chg1m": m.get("oneMonthPriceChange"),
        "vol24": fnum(m.get("volume24hr")),
        "vol": fnum(m.get("volume")),
        "liq": fnum(m.get("liquidityNum") or m.get("liquidity")),
        "end": (m.get("endDateIso") or m.get("endDate") or "")[:10],
        "sports": is_sports(m.get("slug"), m.get("question")),
    }


# ---------------------------------------------------------------- layer 2: signals
def signals(rows):
    """Return tagged signals. Every tag is explainable in one sentence."""
    out = []
    for r in rows:
        tags = []
        d1, d1w = fnum(r["chg1d"]), fnum(r["chg1w"])
        vol, spread = r["vol24"], r["spread"]

        # information vs noise
        if abs(d1) >= 0.04:
            if vol >= 100_000:
                tags.append(("information move",
                             f"{pct(abs(d1))} move on {money(vol)} of volume — the market repriced on real money"))
            elif vol < 15_000:
                tags.append(("likely noise",
                             f"{pct(abs(d1))} move on only {money(vol)} — thin book, treat with suspicion"))

        # spread = efficiency
        if spread and spread > 0.05:
            tags.append(("wide spread", f"{pct(spread)} bid-ask — price is a guess, not a level"))

        # favourite–longshot bias: documented tendency for long shots to be overpriced
        if r["raw"] <= 0.10 and vol >= 50_000:
            tags.append(("long-shot premium",
                         f"priced {pct(r['raw'])} with {money(vol)} behind it — historically this band resolves "
                         f"less often than its price implies"))
        if r["raw"] >= 0.90 and vol >= 50_000:
            tags.append(("asymmetric favourite",
                         f"{pct(r['raw'])} — small remaining upside, large downside if the tail lands"))

        # disagreement with real money
        if 0.44 <= r["raw"] <= 0.56 and vol >= 50_000:
            tags.append(("genuine disagreement",
                         f"{pct(r['raw'])} with {money(vol)} traded — two sides with conviction"))

        # momentum divergence: short-term move against the weekly trend
        if d1 and d1w and (d1 * d1w < 0) and abs(d1) >= 0.03:
            tags.append(("trend divergence",
                         f"24h moved {'up' if d1 > 0 else 'down'} {pct(abs(d1))} against a "
                         f"{'up' if d1w > 0 else 'down'} week — something changed"))

        # signal score: move size scaled by liquidity and penalised by spread
        liq_factor = math.log10(max(vol, 1) + 1)
        score = abs(d1) * liq_factor / (1 + 10 * spread) if spread else abs(d1) * liq_factor
        if tags and abs(d1) >= 0.02:
            out.append({"row": r, "tags": tags, "score": score})

    out.sort(key=lambda s: s["score"], reverse=True)
    return out


def group_by_event(rows):
    groups = collections.defaultdict(list)
    for r in rows:
        key = "-".join(r["slug"].split("-")[:5]) or r["slug"]
        groups[key].append(r)
    return groups


# ---------------------------------------------------------------- layer 3: calibration
def snapshot(rows):
    ts = dt.datetime.utcnow().isoformat(timespec="seconds")
    with open(SNAPSHOT_FILE, "a") as fh:
        for r in rows:
            fh.write(json.dumps({"ts": ts, "slug": r["slug"], "price": r["raw"],
                                 "vol24": r["vol24"], "end": r["end"]}) + "\n")
    return ts


def calibrate():
    if not os.path.exists(SNAPSHOT_FILE):
        return "No snapshots yet — run with --snapshot daily and come back in a few weeks."
    seen = {}
    with open(SNAPSHOT_FILE) as fh:
        for line in fh:
            try:
                s = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (s["slug"], s["ts"][:10])
            seen[key] = s  # one per market per day
    days = sorted({k[1] for k in seen})
    return (f"Snapshot coverage: {len(seen)} market-days across {len(days)} day(s) "
            f"({days[0]} → {days[-1]}).\nCalibration needs resolved outcomes — once markets "
            f"settle, compare the price band to the resolved side to measure crowd accuracy.")


# ---------------------------------------------------------------- render
def render(rows, sigs, top=10):
    now = dt.datetime.now().strftime("%a %d %b %Y %H:%M")
    non_sports = [r for r in rows if not r["sports"]]
    out = [f"# Odds Shift — Signals ({now})", "",
           f"_{len(rows)} markets · {len(non_sports)} non-sports · "
           f"{len(sigs)} carrying a signal · analytics, not advice_", "",
           "## 🎯 Ranked signals", ""]
    for s in sigs[:top]:
        r = s["row"]
        out.append(f"### {r['q']}")
        out.append(f"price **{pct(r['raw'])}** · fair value est. **{pct(r['fair'])}** · "
                   f"spread {pct(r['spread'])} · 24h {pct(abs(fnum(r['chg1d'])))} · {money(r['vol24'])} · "
                   f"score {s['score']:.2f}")
        for name, why in s["tags"]:
            out.append(f"- **{name}** — {why}")
        if r["slug"]:
            out.append(f"  https://polymarket.com/event/{r['slug']}")
        out.append("")

    out += ["## 📊 Crowd quality snapshot", ""]
    bands = [(0.0, .10), (.10, .25), (.25, .45), (.45, .55), (.55, .75), (.75, .90), (.90, 1.0)]
    for lo, hi in bands:
        n = sum(1 for r in rows if lo <= r["raw"] < hi)
        v = sum(r["vol24"] for r in rows if lo <= r["raw"] < hi)
        if n:
            out.append(f"- **{int(lo*100)}–{int(hi*100)}%** band: {n} markets, {money(v)} traded")
    out += ["", "<!-- Gan: signals above, voice below. -->", "",
            "Not financial advice. No position sizing or recommendations.",
            "Source: Polymarket public API."]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--snapshot", action="store_true", help="append today's snapshot")
    ap.add_argument("--calibrate", action="store_true", help="report calibration coverage")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    if args.calibrate:
        print(calibrate())
        return

    raw = fetch({"closed": "false", "active": "true", "limit": 500,
                 "order": "volume24hr", "ascending": "false"})
    rows = [r for r in (metrics(m) for m in raw) if r]
    rows = [r for r in rows if r["liq"] >= 4000 and 0.02 < r["raw"] < 0.98]

    sigs = signals(rows)
    md = render(rows, sigs, args.top)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(md)
        print(f"wrote {args.out} ({len(rows)} markets, {len(sigs)} signals)")
    else:
        print(md)

    if args.json:
        with open(args.json, "w") as fh:
            json.dump([{"q": s["row"]["q"], "score": s["score"],
                        "tags": [t[0] for t in s["tags"]],
                        "price": s["row"]["raw"], "fair": s["row"]["fair"],
                        "vol24": s["row"]["vol24"]} for s in sigs], fh, indent=2)
        print(f"wrote {args.json}")

    if args.snapshot:
        ts = snapshot(rows)
        print(f"appended snapshot {ts} ({len(rows)} markets)")


if __name__ == "__main__":
    main()
