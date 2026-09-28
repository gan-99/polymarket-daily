// Odds Shift — renders the latest digest data into the landing page
const $ = id => document.getElementById(id);

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("os-theme"); } catch {}
  document.documentElement.setAttribute("data-theme", saved === "dark" ? "dark" : "light");
  const btn = $("themeToggle");
  if (btn) btn.textContent = saved === "dark" ? "☀ Light" : "🌙 Dark";
}

function money(v) {
  const n = Number(v) || 0;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}k`;
  return `$${n.toFixed(0)}`;
}

function pct(v) { return `${(Number(v) * 100).toFixed(1)}%`; }

function esc(s) { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; }

function card(m) {
  const chg = Number(m.chg1d);
  const cls = chg > 0 ? "up" : "down";
  const arrow = chg > 0 ? "▲" : "▼";
  return `<article class="card">
    <h3>${esc(m.q)}</h3>
    <div class="row">
      <span>${esc(m.label)} <b>${pct(m.price)}</b></span>
      ${Number.isFinite(chg) && m.chg1d !== null
        ? `<span class="${cls}">${arrow} ${pct(Math.abs(chg))} 24h</span>` : ""}
      <span class="chip">${money(m.vol24)} traded</span>
      <span class="chip">${esc(m.cat || "")}</span>
      ${m.url ? `<a href="${m.url}" target="_blank" rel="noopener">market ↗</a>` : ""}
    </div>
  </article>`;
}

function insights(list) {
  const movers = list.filter(m => m.chg1d !== null)
    .sort((a, b) => Math.abs(Number(b.chg1d)) - Math.abs(Number(a.chg1d)));
  const byVol = [...list].sort((a, b) => Number(b.vol24) - Number(a.vol24));
  const contested = list.filter(m => m.price >= 0.42 && m.price <= 0.58 && Number(m.vol24) > 25000)
    .sort((a, b) => Number(b.vol24) - Number(a.vol24));
  const longshots = list.filter(m => m.price <= 0.12 && Number(m.vol24) > 20000)
    .sort((a, b) => Number(b.vol24) - Number(a.vol24));

  const items = [];
  if (movers[0]) items.push(`<b>Biggest swing:</b> ${esc(movers[0].q)} moved
    <span class="${Number(movers[0].chg1d) > 0 ? "up" : "down"}">
    ${Number(movers[0].chg1d) > 0 ? "▲" : "▼"} ${pct(Math.abs(Number(movers[0].chg1d)))}</span> in 24h.`);
  if (byVol[0]) items.push(`<b>Where the crowd lives:</b> ${esc(byVol[0].q)} — ${money(byVol[0].vol24)} traded in a day.`);
  if (contested[0]) items.push(`<b>Coin flip with real money:</b> ${esc(contested[0].q)} priced ${pct(contested[0].price)} with ${money(contested[0].vol24)} behind it.`);
  if (longshots[0]) items.push(`<b>Long shot people are paying for:</b> ${esc(longshots[0].q)} at ${pct(longshots[0].price)}.`);
  items.push(`<b>Scope:</b> ${list.length} liquid, unresolved markets screened.`);

  const el = $("insights");
  if (el) el.innerHTML = `<ul>${items.map(i => `<li>${i}</li>`).join("")}</ul>
    <p class="note">Gan — facts are generated, jokes are yours. This is the block to write into.</p>`;
}

function render(list) {
  insights(list);
  const movers = list.filter(m => m.chg1d !== null)
    .sort((a, b) => Math.abs(Number(b.chg1d)) - Math.abs(Number(a.chg1d)))
    .slice(0, 8);
  const el = $("movers");
  if (el) el.innerHTML = movers.map(card).join("");
}

async function boot() {
  initTheme();
  const t = $("themeToggle");
  if (t) t.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    try { localStorage.setItem("os-theme", next); } catch {}
    document.documentElement.setAttribute("data-theme", next);
    t.textContent = next === "dark" ? "☀ Light" : "🌙 Dark";
  });
  const form = $("signup");
  if (form) form.addEventListener("submit", e => {
    e.preventDefault();
    const b = form.querySelector("button");
    b.textContent = "Thanks — check your inbox";
    b.disabled = true;
  });
  try {
    render(await (await fetch("latest.json")).json());
  } catch {
    const el = $("movers");
    if (el) el.innerHTML = `<p class="note">Couldn't load latest.json — run the digest script and copy it into /site.</p>`;
  }
}

boot();
