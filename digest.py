#!/usr/bin/env python3
"""
Polymarket Daily — curated digest generator (v2)

Pulls live markets from the Polymarket Gamma API and emits a curated markdown digest:
  • Insights — the standout facts of the day (built for a human to add humour to)
  • Politics / Crypto / Tech / Culture movers (sports kept separate or excluded)
  • Where the money is
  • Long odds with real money behind them

Curation rules (v2):
  • drops near-resolved markets (price >= 0.95 or <= 0.05)
  • one market per event (no four spreads from the same game)
  • liquidity floor
  • category split so the digest reads like signal, not a sportsbook

Usage:
    python3 digest.py                     # markdown to stdout
    python3 digest.py --out issue.md      # write to file
    python3 digest.py --no-sports         # exclude sports entirely
    python3 digest.py --top 6             # markets per section
"""
import argparse
import datetime as dt
import json
import re
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com/markets"

SPORT_RE = re.compile(
    r"\b(nfl|nba|mlb|nhl|ncaa|ufc|f1|formula 1|premier league|uefa|champions league|"
    r"la liga|serie a|bundesliga|tennis|golf|pga|cricket|afl|nrl|rugby|boxing|"
    r"vs\.?|spread|o/u|over/under|match|game|tournament|playoffs|super bowl|"
    r"world cup|olympics|esports|cs2|dota|league of legends)\b",
    re.I,
)
CATEGORIES = [
    ("Politics", re.compile(r"\b(election|president|trump|biden|congress|senate|parliament|"
                            r"pm\b|prime minister|vote|poll|government|impeach|shutdown|"
                            r"governor|mayor|referendum|party)\b", re.I)),
    ("Crypto", re.compile(r"\b(bitcoin|btc|ethereum|eth|solana|sol|xrp|ripple|doge|crypto|"
                          r"stablecoin|usdt|usdc|binance|coinbase|etf)\b", re.I)),
    ("Tech & AI", re.compile(r"\b(openai|chatgpt|gpt|anthropic|claude|gemini|nvidia|ai\b|"
                             r"model|apple|google|microsoft|tesla|spacex|starship|"
                             r"launch|robot)\b", re.I)),
    ("Culture", re.compile(r"\b(oscar|grammy|emmy|movie|film|album|song|celebrity|taylor swift|"
                           r"box office|netflix|spotify|tiktok|youtube|mrbeast|time person|"
                           r"nobel|award|reality tv|kardashian)\b", re.I)),
    ("Macro & Markets", re.compile(r"\b(fed|rate|inflation|cpi|recession|gdp|unemployment|"
                                   r"tariff|oil|gold|s&p|nasdaq|stock|treasury)\b", re.I)),
]


def fetch(params):
    url = f"{GAMMA}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "polymarket-daily/2.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def pct(x):
    try:
        return f"{float(x) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def money(x):
    v = fnum(x)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}k"
    return f"${v:.0f}"


def classify(question):
    for name, rx in CATEGORIES:
        if rx.search(question):
            return name
    if SPORT_RE.search(question):
        return "Sports"
    return "Other"


def clean_question(q):
    q = (q or "").strip()
    return q if len(q) <= 130 else q[:127] + "…"


def collect(top, min_liquidity=5000):
    raw = fetch({
        "closed": "false", "active": "true", "limit": 500,
        "order": "volume24hr", "ascending": "false",
    })
    seen_events, markets = set(), []
    for m in raw:
        if fnum(m.get("liquidityNum") or m.get("liquidity")) < min_liquidity:
            continue
        try:
            outcomes = json.loads(m.get("outcomes") or "[]")
            prices = json.loads(m.get("outcomePrices") or "[]")
        except json.JSONDecodeError:
            continue
        if not outcomes or not prices:
            continue
        price = fnum(prices[0])
        if price >= 0.95 or price <= 0.05:      # near-resolved: no signal
            continue
        events = m.get("events") or []
        event_key = (events[0].get("slug") if events else m.get("slug") or "").split("-")[0:6]
        event_key = "-".join(event_key) or (m.get("slug") or "")
        if event_key in seen_events:             # one market per event
            continue
        seen_events.add(event_key)
        q = clean_question(m.get("question"))
        markets.append({
            "q": q,
            "label": outcomes[0],
            "price": price,
            "chg1d": m.get("oneDayPriceChange"),
            "vol24": m.get("volume24hr"),
            "vol": m.get("volume"),
            "end": (m.get("endDateIso") or m.get("endDate") or "")[:10],
            "url": f"https://polymarket.com/event/{m.get('slug')}" if m.get("slug") else "",
            "cat": classify(q),
        })
    return markets


def section(title, items, show_change=True):
    out = [f"## {title}", ""]
    if not items:
        return out + ["_Nothing qualified today._", ""]
    for m in items:
        line = f"- **{m['q']}** — {m['label']} {pct(m['price'])}"
        if show_change and m["chg1d"] is not None:
            d = fnum(m["chg1d"])
            line += f" ({'▲' if d > 0 else '▼'} {pct(abs(d))} in 24h)"
        line += f" · {money(m['vol24'])} traded · resolves {m['end'] or 'TBD'}"
        out.append(line)
        if m["url"]:
            out.append(f"  {m['url']}")
    return out + [""]


def build_insights(markets):
    """The 'standouts' block — facts for a human to make funny."""
    def biggest(lst, key, reverse=True):
        return sorted(lst, key=lambda m: fnum(m[key]), reverse=reverse)[0] if lst else None

    movers = [m for m in markets if m["chg1d"] is not None]
    top_mover = biggest(movers, "chg1d")
    top_volume = biggest(markets, "vol24")
    contested = sorted(
        [m for m in markets if 0.42 <= m["price"] <= 0.58 and fnum(m["vol24"]) > 25000],
        key=lambda m: fnum(m["vol24"]), reverse=True)
    longshot = sorted(
        [m for m in markets if m["price"] <= 0.12 and fnum(m["vol24"]) > 20000],
        key=lambda m: fnum(m["vol24"]), reverse=True)

    out = ["## 🔍 Insights of the day", ""]
    if top_mover:
        d = fnum(top_mover["chg1d"])
        out.append(f"- **Biggest swing:** {top_mover['q']} moved "
                   f"{'▲' if d > 0 else '▼'} {pct(abs(d))} in 24 hours "
                   f"(now {top_mover['label']} {pct(top_mover['price'])}, "
                   f"{money(top_mover['vol24'])} traded).")
    if top_volume:
        out.append(f"- **Where the crowd lives:** {top_volume['q']} did "
                   f"{money(top_volume['vol24'])} in a day — "
                   f"{top_volume['label']} at {pct(top_volume['price'])}.")
    if contested:
        m = contested[0]
        out.append(f"- **Coin flip with real money:** {m['q']} is priced "
                   f"{pct(m['price'])} with {money(m['vol24'])} traded — "
                   f"the market genuinely doesn't know.")
    if longshot:
        m = longshot[0]
        out.append(f"- **Long shot people are paying for:** {m['q']} at "
                   f"{pct(m['price'])} with {money(m['vol24'])} behind it.")
    out.append(f"- **Scope:** {len(markets)} liquid, unresolved markets screened "
               f"across {len({m['cat'] for m in markets})} categories.")
    out += ["", "<!-- Gan: this is where your humour goes. Leave the facts, add the voice. -->", ""]
    return out


def render(markets, top, include_sports=False):
    today = dt.datetime.now().strftime("%a %d %b %Y")
    movers = sorted([m for m in markets if m["chg1d"] is not None],
                    key=lambda m: abs(fnum(m["chg1d"])), reverse=True)

    out = [f"# Polymarket Daily — {today}", "",
           f"_{len(markets)} markets screened · "
           f"{dt.datetime.now().strftime('%H:%M')} local_", ""]
    out += build_insights(markets)

    out += section("💰 Where the money is", sorted(
        markets, key=lambda m: fnum(m["vol24"]), reverse=True)[:top], show_change=False)

    for cat in ["Politics", "Crypto", "Tech & AI", "Culture", "Macro & Markets"]:
        picks = [m for m in movers if m["cat"] == cat][:top]
        if picks:
            out += section(f"📈 {cat} movers", picks)

    if include_sports:
        picks = [m for m in movers if m["cat"] == "Sports"][:top]
        if picks:
            out += section("🏟️ Sports (kept separate on purpose)", picks)

    others = [m for m in movers if m["cat"] == "Other"][:3]
    if others:
        out += section("🎲 Other movers worth a look", others)

    out += ["---", "", "Odds are market prices, not probabilities. Not financial advice.",
            "Source: Polymarket public API."]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--no-sports", action="store_true", help="exclude sports entirely (default)")
    ap.add_argument("--sports", action="store_true", help="include a separate sports section")
    args = ap.parse_args()

    markets = collect(args.top)
    md = render(markets, args.top, include_sports=args.sports)

    if args.out:
        with open(args.out, "w") as fh:
            fh.write(md)
        print(f"wrote {args.out} ({len(markets)} markets screened)")
    else:
        print(md)

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(markets, fh, indent=2)
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
