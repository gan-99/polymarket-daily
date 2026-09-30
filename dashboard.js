// Odds Shift — signals dashboard
const $ = id => document.getElementById(id);

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("os-theme"); } catch {}
  document.documentElement.setAttribute("data-theme", saved === "dark" ? "dark" : "light");
  const b = $("themeToggle");
  if (b) b.textContent = saved === "dark" ? "☀ Light" : "🌙 Dark";
}

function money(v) {
  const n = Number(v) || 0;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}k`;
  return `$${n.toFixed(0)}`;
}
const pct = v => `${(Number(v) * 100).toFixed(1)}%`;
const esc = s => { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; };

function tagClass(t) {
  if (/noise|wide spread|overpriced|long-shot/i.test(t)) return "tag warn";
  if (/information|disagreement/i.test(t)) return "tag ok";
  return "tag";
}

let SIGNALS = [];

function card(s) {
  const tags = (s.tags || []).map(t => `<span class="${tagClass(t)}">${esc(t)}</span>`).join("");
  return `<article class="card sig">
    <h3>${esc(s.q)}</h3>
    <div>${tags}</div>
    <div class="row" style="margin-top:10px">
      <span>price <b>${pct(s.price)}</b></span>
      <span>fair value est. <b>${pct(s.fair)}</b></span>
      <span class="chip">${money(s.vol24)} 24h</span>
      <span class="score">score ${Number(s.score).toFixed(2)}</span>
    </div>
  </article>`;
}

function draw() {
  const tag = $("tagFilter").value;
  const minVol = Number($("volFilter").value);
  const rows = SIGNALS.filter(s =>
    (!tag || (s.tags || []).includes(tag)) && Number(s.vol24) >= minVol);
  $("count").textContent = `${rows.length} of ${SIGNALS.length} signals`;
  $("signals").innerHTML = rows.length
    ? rows.map(card).join("")
    : `<p class="note">No signals match those filters right now.</p>`;
}

function fillTags() {
  const all = new Set();
  SIGNALS.forEach(s => (s.tags || []).forEach(t => all.add(t)));
  const sel = $("tagFilter");
  [...all].sort().forEach(t => {
    const o = document.createElement("option");
    o.value = t; o.textContent = t;
    sel.appendChild(o);
  });
}

async function loadCalibration() {
  const el = $("calib"), bands = $("calibBands");
  try {
    const md = await (await fetch("calibration.md")).text();
    const lines = md.split("\n");
    const brier = (md.match(/\*\*Brier score:\*\* ([\d.]+)/) || [])[1];
    const count = (md.match(/_(\d+) resolved markets/) || [])[1];
    if (brier) el.innerHTML = `Based on <b>${count || "?"}</b> resolved markets.
      Brier score <b>${brier}</b> <span class="note">(0 = perfect, 0.25 = coin-flip)</span>.`;
    const rows = lines.filter(l => /^\|\s*\d+–\d+%/.test(l))
      .map(l => l.split("|").map(c => c.trim()).filter(Boolean));
    bands.innerHTML = rows.map(r => `
      <div class="panel">
        <h3>${r[0]} band</h3>
        <div class="note">${r[1]} markets · resolved YES ${r[3]}</div>
        <div class="bar"><span style="width:${r[3]}"></span></div>
        <div class="note" style="margin-top:6px">vs ${r[0].split("–")[0]}–${r[0].split("–")[1]} implied · gap ${r[4]}</div>
      </div>`).join("");
  } catch {
    el.textContent = "Calibration data not published yet — it appears after the first cloud run.";
  }
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
  $("tagFilter").addEventListener("change", draw);
  $("volFilter").addEventListener("change", draw);
  $("refresh").addEventListener("click", e => { e.preventDefault(); location.reload(); });

  try {
    SIGNALS = await (await fetch("signals.json")).json();
    fillTags();
    draw();
  } catch {
    $("signals").innerHTML = `<p class="note">signals.json isn't published yet — run engine.py
      --json signals.json and commit it, or wait for the daily cloud run.</p>`;
  }
  loadCalibration();
}

boot();
