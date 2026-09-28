#!/usr/bin/env python3
"""
Odds Shift — curated digest generator (v3)

Pulls live markets from the Polymarket Gamma API and emits a curated markdown digest
ordered for a finance-adjacent, globally-minded audience:

  1. Insights of the day
  2. Where the money is (NON-sports)
  3. Geopolitics → Politics → Crypto → Tech & AI → Science & Space → Health →
     Climate → Legal & Courts → Business & Markets → Culture & Entertainment → Other
  4. Sports, kept at the very bottom (saturated, low signal for this audience)

Curation rules:
  • drops near-resolved markets (price >= 0.95 or <= 0.05)
  • one market per event
  • liquidity floor
  • sports never appears in the money section or the insights block

Usage:
    python3 digest.py
    python3 digest.py --out issue.md --json latest.json
    python3 digest.py --sports-at-top     # override, if you ever want it
"""
import argparse
import datetime as dt
import json
import re
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com/markets"

# Ordered exactly as they should appear in the digest (sports deliberately last).
CATEGORY_ORDER = [
    "Geopolitics",
    "Politics & Elections",
    "Crypto",
    "Tech & AI",
    "Science & Space",
    "Health & Medicine",
    "Climate & Environment",
    "Legal & Courts",
    "Business & Markets",
    "Culture & Entertainment",
    "Other",
    "Sports",
]
CATEGORIES = [
    ("Geopolitics", re.compile(r"\b(ceasefire|war|invasion|strike[sd]?\b|missile|nuclear|"
                               r"iran|israel|gaza|lebanon|russia|ukraine|putin|zelensky|"
                               r"china|taiwan|north korea|sanctions|nato|blockade|hostage|"
                               r"conflict|troops|territory|annex|treaty|border)\b", re.I)),
    ("Politics & Elections", re.compile(r"\b(election|president|trump|biden|congress|senate|"
                                        r"parliament|prime minister|vote|poll|government|"
                                        r"impeach|shutdown|governor|mayor|referendum|"
                                        r"cabinet|minister|ballot|primary|nominee)\b", re.I)),
    ("Crypto", re.compile(r"\b(bitcoin|btc|ethereum|eth\b|solana|sol\b|xrp|ripple|doge|"
                          r"crypto|stablecoin|usdt|usdc|binance|coinbase|etf\b|altcoin|"
                          r"halving|memecoin|web3)\b", re.I)),
    ("Tech & AI", re.compile(r"\b(openai|chatgpt|gpt-?\d|anthropic|claude|gemini|llama|"
                             r"nvidia|ai\b|agi|model release|apple|google|microsoft|meta\b|"
                             r"amazon|tesla|robotaxi|self-driving|chip|semiconductor)\b", re.I)),
    ("Science & Space", re.compile(r"\b(spacex|starship|nasa|rocket|launch|mars|moon|lunar|"
                                   r"satellite|asteroid|fusion|quantum|physics|cern|"
                                   r"telescope|jwst|discovery|breakthrough|nobel science)\b", re.I)),
    ("Health & Medicine", re.compile(r"\b(fda|vaccine|virus|outbreak|pandemic|h5n1|bird flu|"
                                     r"cancer|cure|drug approval|clinical trial|who\b|measles|"
                                     r"ebola|health emergency|obesity drug|glp-1)\b", re.I)),
    ("Climate & Environment", re.compile(r"\b(hurricane|cyclone|typhoon|storm|flood|wildfire|"
                                         r"drought|heatwave|temperature record|climate|"
                                         r"emissions|carbon|el niño|la niña|sea ice|glacier)\b", re.I)),
    ("Legal & Courts", re.compile(r"\b(trial|court|verdict|convict|sentence|indict|charge[sd]?\b|"
                                  r"supreme court|appeal|acquit|plea|jury|prosecut|lawsuit|"
                                  r"imprison|extradit)\b", re.I)),
    ("Business & Markets", re.compile(r"\b(fed\b|fomc|rate (cut|hike|decision)|inflation|cpi\b|"
                                      r"recession|gdp|unemployment|tariff|earnings|ipo\b|"
                                      r"merger|acquisition|bankrupt|layoffs|oil price|gold price|"
                                      r"s&p|nasdaq|stock market|opec)\b", re.I)),
    ("Culture & Entertainment", re.compile(r"\b(oscar|grammy|emmy|golden globe|movie|film|album|"
                                           r"song|billboard|celebrity|taylor swift|box office|"
                                           r"netflix|spotify|tiktok|youtube|mrbeast|"
                                           r"time person|award|reality tv|tour|concert)\b", re.I)),
    ("Sports", re.compile(r"\b(nfl|nba|mlb|nhl|ncaa|ufc|f1\b|formula 1|premier league|uefa|"
                          r"champions league|la liga|serie a|bundesliga|tennis|golf|pga|"
                          r"cricket|afl\b|nrl\b|rugby|boxing|spread|o/u|over/under|"
                          r"vs\.|playoffs|super bowl|world cup|olympics|esports|cs2|dota|"
                          r"league of legends|match|fixture)\b", re.I)),
]


def fetch(params):
    url = f"{GAMMA}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "odds-shift/3.0"})
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


SPORTS_SLUG_RE = re.compile(
    r"^(nfl|nba|mlb|nhl|ncaa|ufc|f1|epl|ucl|uel|mex|bra|arg|atp|wta|pga|lpga|"
    r"lol|cs2|dota|valorant|rl|ow|afl|nrl|rugby|crint|superbowl|xfl|cfl|tennis|golf|boxing|mma)-",
    re.I,
)


def classify(q, slug=""):
    """Classify by market slug first (far more reliable), then question text."""
    if slug and SPORTS_SLUG_RE.match(slug):
        return "Sports"
    if slug and re.match(r"^(nfl|nba|mlb|nhl|ncaa|ufc|f1|epl|ucl|lol|cs2|dota|valorant|crint)-.*(spread|total|o-u|over|under)", slug, re.I):
        return "Sports"
    for name, rx in CATEGORIES:
        if rx.search(q):
            return name
    return "Other"


def clean_q(q):
    q = (q or "").strip()
    return q if len(q) <= 130 else q[:127] + "…"


def collect(min_liquidity=4000):
    raw = fetch({"closed": "false", "active": "true", "limit": 500,
                 "order": "volume24hr", "ascending": "false"})
    seen, markets = set(), []
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
        if price >= 0.95 or price <= 0.05:
            continue
        events = m.get("events") or []
        key_src = (events[0].get("slug") if events else m.get("slug") or "")
        key = "-".join(key_src.split("-")[:6]) or key_src
        if key in seen:
            continue
        seen.add(key)
        q = clean_q(m.get("question"))
        slug = m.get("slug") or ""
        markets.append({
            "q": q, "label": outcomes[0], "price": price,
            "chg1d": m.get("oneDayPriceChange"),
            "vol24": m.get("volume24hr"), "vol": m.get("volume"),
            "end": (m.get("endDateIso") or m.get("endDate") or "")[:10],
            "url": f"https://polymarket.com/event/{slug}" if slug else "",
            "cat": classify(q, slug),
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


def insights_block(non_sports, sports):
    movers = [m for m in non_sports if m["chg1d"] is not None]
    top_mover = max(movers, key=lambda m: abs(fnum(m["chg1d"]))) if movers else None
    top_vol = max(non_sports, key=lambda m: fnum(m["vol24"])) if non_sports else None
    contested = sorted([m for m in non_sports if 0.40 <= m["price"] <= 0.60
                        and fnum(m["vol24"]) > 20000], key=lambda m: fnum(m["vol24"]), reverse=True)
    longshots = sorted([m for m in non_sports if m["price"] <= 0.12
                        and fnum(m["vol24"]) > 15000], key=lambda m: fnum(m["vol24"]), reverse=True)
    cats = {}
    for m in non_sports:
        cats[m["cat"]] = cats.get(m["cat"], 0) + 1
    busiest = max(cats.items(), key=lambda kv: kv[1]) if cats else None

    out = ["## 🔍 Insights of the day", ""]
    if top_mover:
        d = fnum(top_mover["chg1d"])
        out.append(f"- **Biggest non-sports swing:** {top_mover['q']} moved "
                   f"{'▲' if d > 0 else '▼'} {pct(abs(d))} in 24h "
                   f"(now {top_mover['label']} {pct(top_mover['price'])}, {money(top_mover['vol24'])} traded).")
    if top_vol:
        out.append(f"- **Where the money is:** {top_vol['q']} — {money(top_vol['vol24'])} in a day "
                   f"({top_vol['cat']}), priced {pct(top_vol['price'])}.")
    if contested:
        m = contested[0]
        out.append(f"- **Genuine coin flip:** {m['q']} at {pct(m['price'])} with {money(m['vol24'])} behind it — "
                   f"nobody knows.")
    if longshots:
        m = longshots[0]
        out.append(f"- **Long shot with believers:** {m['q']} priced {pct(m['price'])} "
                   f"({money(m['vol24'])} wagered).")
    if busiest:
        out.append(f"- **Busiest category:** {busiest[0]} ({busiest[1]} markets). "
                   f"Sports excluded from all of the above — {len(sports)} sports markets were screened "
                   f"and sit at the bottom.")
    out += ["", "<!-- Gan: facts above, humour here. The voice is yours. -->", ""]
    return out


def render(markets, top, sports_at_top=False):
    non_sports = [m for m in markets if m["cat"] != "Sports"]
    sports = [m for m in markets if m["cat"] == "Sports"]
    today = dt.datetime.now().strftime("%a %d %b %Y")

    out = [f"# Odds Shift — {today}", "",
           f"_{len(markets)} markets screened · {len(non_sports)} non-sports · "
           f"{dt.datetime.now().strftime('%H:%M')} local_", ""]
    out += insights_block(non_sports, sports)

    out += section("💰 Where the money is (sports excluded)",
                   sorted(non_sports, key=lambda m: fnum(m["vol24"]), reverse=True)[:top],
                   show_change=False)

    order = [c for c in CATEGORY_ORDER if c not in ("Sports", "Other")]
    if sports_at_top:
        order = ["Sports"] + order
    movers = [m for m in non_sports if m["chg1d"] is not None]
    for cat in order:
        picks = sorted([m for m in movers if m["cat"] == cat],
                       key=lambda m: abs(fnum(m["chg1d"])), reverse=True)[:top]
        if picks:
            out += section(f"📈 {cat}", picks)

    others = sorted([m for m in movers if m["cat"] == "Other"],
                    key=lambda m: abs(fnum(m["chg1d"])), reverse=True)[:3]
    if others:
        out += section("🎲 Other movers", others)

    if sports and not sports_at_top:
        picks = sorted([m for m in sports if m["chg1d"] is not None],
                       key=lambda m: abs(fnum(m["chg1d"])), reverse=True)[:3]
        out += ["---", "", "## 🏟️ Sports (deliberately last — saturated, low signal)", ""]
        for m in picks:
            d = fnum(m["chg1d"])
            out.append(f"- {m['q']} — {m['label']} {pct(m['price'])} "
                       f"({'▲' if d > 0 else '▼'} {pct(abs(d))}) · {money(m['vol24'])}")
        out += ["", f"_{len(sports)} sports markets screened and demoted. If you want them gone "
                    f"entirely, that's a one-line change._", ""]

    out += ["---", "", "Odds are market prices, not probabilities. Not financial advice.",
            "Source: Polymarket public API."]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--sports-at-top", action="store_true")
    args = ap.parse_args()

    markets = collect()
    md = render(markets, args.top, sports_at_top=args.sports_at_top)

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
