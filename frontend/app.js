"use strict";
const $ = id => document.getElementById(id);
const big = n => n == null || isNaN(n) ? "-" : (Math.abs(n) >= 1e12 ? (n / 1e12).toFixed(2) + " trillion" : Math.abs(n) >= 1e9 ? (n / 1e9).toFixed(2) + " billion" : Math.abs(n) >= 1e6 ? (n / 1e6).toFixed(1) + " million" : fmt(n));
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n, d = 0) => n == null || isNaN(n) ? "-" : Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const et = iso => iso ? new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }) + " ET" : "none supplied";
const TABS = [["home", "Home"], ["levels", "Key levels"], ["bias", "Bias and plan"], ["session", "Session"], ["regime", "Regime"], ["overview", "All symbols"], ["sheet", "Pre-market sheet"],
  ["chain", "Options chain"], ["gex", "GEX by strike"], ["zerodte", "0DTE GEX"], ["flip", "Gamma flip"], ["flows", "Charm and vanna"], ["oi", "Open interest"], ["volume", "Volume"], ["heatmap", "Activity heatmap"], ["preopen", "Overnight changes"],
  ["iv", "IV by strike"], ["surface", "Vol surface"], ["move", "Expected move"], ["delta", "Delta exposure"], ["journal", "Journal"], ["scorecard", "Scorecard"], ["react", "Level reactions"], ["flow", "Unusual volume"],
  ["events", "Events"], ["history", "History"], ["status", "Data status"], ["phone", "Phone access"]];
const TABICON = { home: "home", levels: "key_levels", bias: "insights", session: "live_charts", regime: "market_data", overview: "watchlist", sheet: "reports", chain: "search", gex: "options_analytics",
  zerodte: "gamma", flip: "logout", flows: "options_flow", oi: "open_interest", volume: "volume", heatmap: "tools", preopen: "news", iv: "implied_volatility", surface: "data_feeds", move: "market_data",
  delta: "delta", journal: "account", scorecard: "reports", react: "alerts", flow: "options_flow", events: "calendar", history: "news", status: "settings", phone: "help" };
const RB = [[128, 0, 255], [47, 139, 245], [27, 224, 214], [127, 233, 122], [255, 211, 77], [255, 122, 46], [255, 0, 0]];
const RCS = RB.map((c, i) => [i / 6, `rgb(${c})`]);
function rgbAt(t) { t = Math.max(0, Math.min(1, t)) * 6; const i = Math.min(5, Math.floor(t)), u = t - i; return "rgb(" + RB[i].map((v, j) => Math.round(v + (RB[i + 1][j] - v) * u)).join(",") + ")"; }
const pickIdx = (n, m) => n <= m ? [...Array(n).keys()] : [...new Set([...Array(m).keys()].map(i => Math.round(i * (n - 1) / (m - 1))))];
const cleanNote = c => `Cleaning: ${esc(c.method)} Used ${fmt(c.stats.used)} contracts; dropped ${fmt(c.stats.zero_bid)} with zero bid, ${fmt(c.stats.wide_spread)} with wide spreads, ${fmt(c.stats.no_iv)} without IV, ${fmt(c.stats.bad_iv)} with out-of-range IV, ${fmt(c.stats.itm_skipped)} in-the-money.`;
const S = { u: null, tab: "home", busy: false, hmf: "volume", hms: "total", hmw: "0.04", hmm: "oi_change", hmx: "8", ivx: "strike", ivotm: true, ivsm: true, svx: "strike", svview: "both", svotm: true, cats: new Set(["gex0_call_wall", "gex0_put_wall", "gex0_flip", "gamma_flip", "gex_concentration", "open_interest", "volume", "expected_move", "custom", "oi_by_expiry", "volume_by_expiry", "oi_mid", "volume_mid", "gex_call_zone", "gex_put_zone", "gex_pos_zone", "gex_neg_zone", "oi_call_zone", "oi_put_zone", "volume_call_zone", "volume_put_zone", "expected_move_ext", "charm_sell_zone", "charm_buy_zone", "vanna_pos_zone", "vanna_neg_zone", "dex_pos_zone", "dex_neg_zone", "new_call_zone", "new_put_zone"]), lvtop: 2, lvexp: 3, lvmid: 2, lvmov: 3, lvkey: 10, lvnear: 0, lvq: "", lvqc: { gex: 8, oi: 2, vol: 1, move: 2, charm: 2, vanna: 2, dex: 1, new: 2 }, zoom: 1, det: {}, touch: 0 };
const UIKEYS = ["tab", "u", "hmf", "hms", "hmw", "hmm", "hmx", "ivx", "ivotm", "ivsm", "svx", "svview", "svotm", "lvtop", "lvexp", "lvmid", "lvmov", "lvkey", "lvnear", "lvq", "lvqc", "zoom"];
function loadUI() {
  try {
    const j = JSON.parse(localStorage.getItem("nqes.ui") || "{}");
    const qc0 = S.lvqc;
    UIKEYS.forEach(k => { if (j[k] !== undefined) S[k] = j[k]; });
    S.lvqc = { ...qc0, ...S.lvqc };                       // counts saved before a family existed start at its default
    if (Array.isArray(j.cats)) S.cats = new Set([...j.cats, ...[...S.cats].filter(c => !(j.known || []).includes(c))]);
    S.det = j.det || {}; S.savedConv = j.conv; S.savedMethod = j.method;
  } catch (e) { /* settings just start fresh */ }
  applyZoom();
}
function saveUI() {
  try {
    const o = {}; UIKEYS.forEach(k => o[k] = S[k]);
    o.cats = [...S.cats]; o.known = [...ALLCATS]; o.det = S.det; o.conv = $("conv").value; o.method = $("method").value;
    localStorage.setItem("nqes.ui", JSON.stringify(o));
  } catch (e) { /* private mode or storage full: nothing to save */ }
}
const QPRESET = { gex: { gex: 8, oi: 2, vol: 1, move: 2, charm: 2, vanna: 2, dex: 1, new: 2 }, bal: { gex: 3, oi: 3, vol: 2, move: 2, charm: 2, vanna: 2, dex: 1, new: 2 },
  tv: { gex: 16, oi: 8, vol: 6, move: 8, charm: 6, vanna: 6, dex: 4, new: 6 } };
const QNAMES = [["gex", "GEX"], ["oi", "Open interest"], ["vol", "Volume"], ["move", "Expected move"], ["charm", "Charm"], ["vanna", "Vanna"], ["dex", "Dealer delta"], ["new", "New positions"]];
const quotaFor = () => { const q = S.lvq === "custom" ? S.lvqc : QPRESET[S.lvq]; return q ? QNAMES.map(([k]) => `${k}:${q[k] || 0}`).join(",") : undefined; };
const selParams = () => (S.lvq ? { quota: quotaFor() } : { key: S.lvkey, near: S.lvnear });
function applyZoom() { document.documentElement.style.setProperty("--z", S.zoom); }
const userBusy = () => Date.now() - S.touch < 30000;
function persistDetails() {
  $("view").querySelectorAll("details[data-k]").forEach(d => { const k = d.dataset.k; if (k in S.det) d.open = S.det[k]; d.ontoggle = () => { S.det[k] = d.open; saveUI(); }; });
}
const CATCOL = { gex0_call_wall: "#22d3ee", gex0_put_wall: "#ff4d8d", gex0_flip: "#ffd166", gamma_flip: "#e6b422", gex_concentration: "#2f8bf5", open_interest: "#ff7a2e", volume: "#3fb96a", expected_move: "#7db7ff", expected_move_ext: "#8e9bff", custom: "#ffffff", oi_by_expiry: "#ff7a2e", volume_by_expiry: "#3fb96a", oi_mid: "#ff7a2e", volume_mid: "#3fb96a",
  gex_call_zone: "#3fb96a", gex_put_zone: "#e5534b", gex_pos_zone: "#2f8bf5", gex_neg_zone: "#a371f7", oi_call_zone: "#ff9f43", oi_put_zone: "#d9480f", volume_call_zone: "#2ec4b6", volume_put_zone: "#f06292",
  charm_sell_zone: "#e76f51", charm_buy_zone: "#2a9d8f", vanna_pos_zone: "#c77dff", vanna_neg_zone: "#ffb703", dex_pos_zone: "#4cc9f0", dex_neg_zone: "#f72585", new_call_zone: "#b5e48c", new_put_zone: "#ff6b6b" };
const FAMILIES = [["flip", "Gamma flip", ["gamma_flip"], "#e6b422"], ["gex", "GEX zones", ["gex_call_zone", "gex_put_zone", "gex_pos_zone", "gex_neg_zone", "gex_concentration", "gex0_call_wall", "gex0_put_wall", "gex0_flip"], "#2f8bf5"],
  ["oi", "Open interest", ["open_interest", "oi_call_zone", "oi_put_zone", "oi_by_expiry", "oi_mid"], "#ff9f43"], ["vol", "Volume", ["volume", "volume_call_zone", "volume_put_zone", "volume_by_expiry", "volume_mid"], "#2ec4b6"],
  ["move", "Expected moves", ["expected_move", "expected_move_ext"], "#7db7ff"], ["charm", "Charm (est.)", ["charm_sell_zone", "charm_buy_zone"], "#e76f51"],
  ["vanna", "Vanna (est.)", ["vanna_pos_zone", "vanna_neg_zone"], "#c77dff"], ["dex", "Dealer delta (est.)", ["dex_pos_zone", "dex_neg_zone"], "#4cc9f0"],
  ["new", "New positions", ["new_call_zone", "new_put_zone"], "#b5e48c"], ["mine", "My levels", ["custom"], "#ffffff"]];
const ALLCATS = new Set(FAMILIES.flatMap(f => f[2]));
const GROUPS = [["Today", ["home", "levels", "bias", "session", "regime", "overview", "sheet"]], ["Options", ["chain", "gex", "zerodte", "flip", "flows", "oi", "volume", "heatmap", "preopen"]],
  ["Volatility", ["iv", "surface", "move", "delta"]], ["Review", ["journal", "scorecard", "react", "flow", "events", "history"]], ["App", ["status", "phone"]]];
const HELP = {
  home: ["Today at a glance: the lean and why, the regime, and where price sits against the levels that matter.", "The ladder shows the key levels above and below price at their real distances, in futures points once a basis is saved. Open Bias and plan for the full reasoning, Key levels for the complete list."],
  session: ["How the session is unfolding: dealer gamma by strike through the day, price inside its expected-move cone, whether dealers are long or short gamma at the current price, and the call vs put volume race.", "Charts fill in as the app collects data during the day (a point about every 2 minutes). Use the Day box to look back at earlier sessions. The GEX map shows NET gamma per strike: blue is positive (dealers dampen moves there), purple is negative (they add to moves)."],
  zerodte: ["Gamma from today's expiry only (0DTE). Same-day options carry the most gamma per contract, so they drive most of the intraday dealer hedging and pinning.", "Bars are 0DTE GEX by strike near price. The 0DTE call wall, put wall and flip are also level types on the Levels tab and in the TradingView paste text. After the close, the next expiry takes over and the page says so."],
  preopen: ["What changed overnight and how fragile the market is before the bell: the gamma curve, the overnight change in GEX and open interest by strike, and implied volatility and skew across days.", "The gamma curve is total dealer gamma if price moved to each level: where it crosses zero is the flip, and the steeper it falls below, the faster moves can get there. Overnight change needs stored data from two sessions."],
  journal: ["Your trade journal. Log a trade and the app records which level, regime and bias you traded into, so you can see where your best trades come from.", "Enter prices in the units you trade (NQ or ES points); with a saved basis the app matches them to the mapped levels. Stats group your results by the nearest level type, the regime and whether you traded with or against the bias."],
  scorecard: ["Which levels actually work, and whether the regime call matched the day: how often each level type held after a touch and how far price went, and each day's regime next to its real range.", "Built from the app's own level reaction log and stored prices, so it gets more reliable with weeks of data. Small samples are marked. Descriptive, not proof of an edge."],
  phone: ["Open the dashboard on your phone. On the same Wi-Fi it works right away; from anywhere it uses Tailscale, a free private network app, so nothing is exposed to the internet.", "Turning it on asks for a password, lets other devices on your network reach this computer, and restarts the app. Windows or macOS may ask once to allow Q DATA through the firewall or to accept incoming connections: allow it."],
  levels: ["The short list of price levels and zones that matter most right now, built from option positioning. A zone is a band of neighbouring strikes, not a single price.", "Each row is one level or zone, highest price first. Score is how important it ranks (size x type x closeness to price). Use Show to switch between the most important, the closest to price, or everything. Copy the paste text into the TradingView indicator to draw them. These are estimates from delayed data, not signals."],
  bias: ["A scorecard of what option positioning leans toward today: bullish, bearish or mixed, and how much to trust that reading.", "Each row is one clue with its own lean; the verdict is their total. It describes positioning, not a forecast. Event days and stale data lower the trust."],
  regime: ["Is today likely to be a pinned, mean-reverting day or one that can trend and expand? A scorecard that combines the gamma flip, volatility level and shape, skew, how much price has already moved, and scheduled events.", "Each row is one measure with its own lean (calm, neutral or unstable); the label is just their total, with the rule shown below. A tendency of how option hedging behaves, not a forecast of direction. The thresholds are my own and not backtested, and the volatility comparison gets better after about 10 sessions of stored history."],
  overview: ["The daily bias for every symbol you track, side by side, plus whether related symbols agree.", "Green leans bullish, red bearish, grey mixed. NDX and QQQ (or SPX and SPY) move together, so agreement is a consistency check, not extra proof."],
  sheet: ["A one-page summary of today's bias, events and levels to read before the open.", "Use the Print button to save it as a PDF."],
  chain: ["The raw option chain: every contract with its price, implied volatility, volume and open interest.", "Use the filters to narrow it down. A zero open interest is real, not missing."],
  gex: ["Estimated gamma exposure by strike: how much hedging the option positions could force in each direction.", "Bars up are positive GEX (dealer hedging tends to calm price under the standard sign scenario); bars down are negative (it can speed moves). It is modeled from open interest, and the Dealer sign scenario box at the top changes it."],
  flip: ["The estimated price where modeled dealer gamma changes sign.", "Above it moves tend to be calmer; below it they can be bigger (under the standard sign scenario). Treat it as a zone, not a line: the scenarios table shows how much it shifts with the assumptions."],
  oi: ["Open interest: contracts still open from before today, by strike. It updates once a day.", "Tall bars are strikes with a lot of positions, which can act as magnets or barriers. The change view shows where positions were added or removed since the last session."],
  volume: ["Contracts traded today by strike, with unusually busy strikes flagged.", "A flagged strike is trading far more than the rest of today's chain. Volume does not say who bought or sold."],
  heatmap: ["Where the activity is: a strike by expiry heatmap of new positions, volume, open interest or modeled dealer flows, with the prices where it is concentrated.", "Each row is a strike and each column an expiry; brighter or deeper color means more. The bars on the right add up each strike across expiries. Hot spots are bands of neighbouring strikes with the most activity, listed with their futures price once a basis is saved. The activity center is the price that splits the activity in half. The yellow dotted line is the current price."],
  flows: ["Charm and vanna: how dealer hedging may shift as time passes and as implied volatility moves, plus how much delta dealers hold at each strike. All modeled estimates.", "Charm: as the day goes on, option deltas drift, and dealers hedge that drift. The drift-to-close figure is how much they would need to buy or sell by 16:00 ET if price and IV stayed put; it is biggest on 0DTE afternoons. Vanna: when IV falls, dealer deltas change too, so a vol crush can force buying or selling. The sign of each depends on the dealer-positioning assumption in Settings."],
  iv: ["Implied volatility across strikes (the smile or skew) and across expiries (term structure).", "A higher left side means puts are priced richer than calls. The other chart shows whether near expiries cost more or less volatility than far ones."],
  surface: ["The whole volatility picture in one view: strike, expiry and implied volatility. The 3D view and the heatmap show the same data, and Both shows them together.", "Drag to rotate the 3D view, scroll to zoom, and use the buttons above each chart to zoom, reset or fill the screen. Your view and settings are remembered."],
  move: ["How far option prices say the market may travel by each expiry, up and down.", "The table lists the straddle, 1 sigma and 2 sigma moves and the price levels they imply; the cone shows how the range widens with time. 1 sigma is about a 68% range if the usual bell-curve assumption held. Real markets move beyond it more often."],
  delta: ["How directional the option positions are, by strike and at different prices.", "Delta exposure is how much of the option positions behaves like holding the underlying. It is modeled and depends on the sign scenario."],
  react: ["A log of what price did when it touched earlier levels.", "It only starts to mean something after weeks of data. Held means price was still on the side it approached from."],
  flow: ["Trade-by-trade options flow is not available in this version.", "Nothing is drawn here because the app has no trade feed."],
  events: ["Scheduled releases and expirations that can move price more than options imply.", "You maintain this list. The starter entries came from published calendars; check them against the official sites."],
  history: ["How the key numbers changed over time.", "Pick a metric to see its history; the levels chart shows the gamma flip, walls and expected-move edges through the session."],
  status: ["Is the data flowing? Each data source, its timing and any errors.", "If another tab says there is no data, start here."]
};
function addHelp() {
  const first = $("view").querySelector(".panel"), h = HELP[S.tab];
  if (!first || !h || first.querySelector(".lede")) return;
  const p = document.createElement("p"); p.className = "lede"; p.textContent = h[0];
  const d = document.createElement("details"); d.className = "help"; d.dataset.k = "help-" + S.tab;
  d.innerHTML = `<summary>How to read this</summary><p>${esc(h[1])}</p>`;
  const h2 = first.querySelector("h2"); if (!h2) return;
  h2.insertAdjacentElement("afterend", p); (first.querySelector(".metabar") || p).insertAdjacentElement("afterend", d);
}
const LAY = (t, o = {}) => Object.assign({ title: { text: t, x: 0, xanchor: "left", font: { size: 14, color: "#E7ECF5", family: "Manrope, Segoe UI, sans-serif" } }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "#AEB7CC", family: "Manrope, Segoe UI, sans-serif", size: 12 }, hoverlabel: { bgcolor: "#162036", bordercolor: "#2A3554", font: { color: "#E7ECF5" } },
  margin: { l: 60, r: 20, t: 44, b: 80 }, xaxis: { gridcolor: "#1E2840", zerolinecolor: "#2A3554" }, yaxis: { gridcolor: "#1E2840", zerolinecolor: "#2A3554" }, legend: { orientation: "h", y: -0.22, x: 0 } }, o);
const PCFG = { displayModeBar: "hover", displaylogo: false, scrollZoom: true, responsive: true, doubleClick: "reset+autosize", modeBarButtonsToRemove: ["select2d", "lasso2d", "toggleSpikelines"] };
const ZOOM = {};                                        // zoom and rotation you set on each chart, kept across the automatic refreshes
const DEFAULT_EYE = { x: 1.55, y: -1.75, z: 0.85 };

async function api(path, params) {
  const q = new URLSearchParams(Object.entries(Object.assign({}, params, S.src ? { source: S.src } : {})).filter(([, v]) => v != null && v !== "")).toString();
  const r = await fetch("/api" + path + (q ? "?" + q : ""));
  const j = await r.json().catch(() => null);
  if (!r.ok) { const d = j && j.detail; throw { status: r.status, msg: (d && d.reason) || (typeof d === "string" ? d : "Request failed"), last: d && d.last_error }; }
  return j;
}
const exps = () => [...$("exp").selectedOptions].map(o => o.value).filter(Boolean).join(",") || "all";
const base = () => ({ underlying: S.u, expiration: exps(), convention: $("conv").value });

function metaBar(m) {
  if (!m) return "";
  const t = m.source_timestamp ? new Date(m.source_timestamp).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }) + " ET" : "no source time";
  return `<div class="metabar"><span class="badge ${esc(m.data_status)}">${esc(m.data_status.replace(/_/g, " "))}</span><span>${esc(m.provider)} data as of ${t}</span>
  <details><summary>Details</summary><div class="full"><span>Symbol ${esc(m.underlying)}</span><span>Source time: ${et(m.source_timestamp)}</span><span>Retrieved: ${et(m.retrieved_at)}</span><span>Calculated: ${esc(m.calculated_at_et)}</span>
  <span>${esc(m.served_from)}</span><span>${esc(m.freshness.note)}</span>${m.spot_note ? `<span>Price note: ${esc(m.spot_note)}</span>` : ""}</div></details></div>`;
}
const panel = (title, m, body) => `<div class="panel"><h2>${esc(String(title).replace(/(^|[^A-Za-z0-9])_([A-Z]{2,})/g, "$1$2"))}</h2>${metaBar(m)}${body}</div>`;
const note = (t, bad) => `<div class="msg ${bad ? "bad" : ""}">${esc(t)}</div>`;
function showError(e) {
  $("view").innerHTML = `<div class="panel"><h2>No data to show</h2>${note(e.msg || "The backend is not reachable. Is start.bat still running?", true)}
  ${e.last ? `<p class="dim">Last provider error: ${esc(e.last.kind)}: ${esc(e.last.message)}</p>` : ""}
  <p class="dim">Nothing is drawn when there is no real data. Open the Status tab for details.</p></div>`;
}
function plot(div, traces, layout) {
  const el = $(div);
  if (!window.Plotly) { el.textContent = "Chart library did not load (needs internet access for the chart script)."; return; }
  const key = S.tab + ":" + S.u + ":" + div, z = ZOOM[key], L = Object.assign({}, layout);
  el._origLayout = layout; el._zkey = key;
  if (z) {
    if (z.x) L.xaxis = Object.assign({}, L.xaxis, { range: z.x, autorange: false });
    if (z.y) L.yaxis = Object.assign({}, L.yaxis, { range: z.y, autorange: false });
    if (z.cam) L.scene = Object.assign({}, L.scene, { camera: z.cam });
  }
  wrapChart(el);
  Plotly.react(el, traces, L, PCFG).then(() => {
    if (!el._hooked) { el._hooked = true; hookChart(el); }
    const h = el.parentNode.querySelector(".zh");
    if (h) h.textContent = el._fullLayout && el._fullLayout.scene ? "Drag to rotate. Scroll to zoom." : "Scroll to zoom. Drag to select an area. Double-click to reset.";
  });
}
function wrapChart(el) {
  if (el.parentNode.classList.contains("chartwrap")) return;
  const w = document.createElement("div"); w.className = "chartwrap";
  el.parentNode.insertBefore(w, el);
  const bar = document.createElement("div"); bar.className = "zbar";
  bar.innerHTML = '<span class="zh"></span><button data-z="in" title="Zoom in">Zoom +</button><button data-z="out" title="Zoom out">Zoom -</button><button data-z="reset" title="Back to the full view">Reset</button><button data-z="full" title="Fill the screen (Esc to close)">Full screen</button>';
  w.appendChild(bar); w.appendChild(el);
  bar.onclick = e => {
    const a = e.target.dataset.z; if (!a) return; S.touch = Date.now();
    if (a === "in") zoomBy(el, 0.7); else if (a === "out") zoomBy(el, 1.4); else if (a === "reset") resetZoom(el); else toggleFull(w, el);
  };
}
function hookChart(el) {
  el.on("plotly_relayout", ev => {
    const z = ZOOM[el._zkey] || (ZOOM[el._zkey] = {});
    for (const [k, v] of Object.entries(ev)) {
      if (k === "xaxis.autorange") { if (v) delete z.x; } else if (k === "yaxis.autorange") { if (v) delete z.y; }
      else if (k === "xaxis.range[0]") (z.x = z.x || [])[0] = v; else if (k === "xaxis.range[1]") (z.x = z.x || [])[1] = v;
      else if (k === "yaxis.range[0]") (z.y = z.y || [])[0] = v; else if (k === "yaxis.range[1]") (z.y = z.y || [])[1] = v;
      else if (k === "xaxis.range") z.x = v; else if (k === "yaxis.range") z.y = v;
      else if (k === "scene.camera") z.cam = v; else if (k === "scene.camera.eye") z.cam = Object.assign({}, z.cam, { eye: v });
    }
    S.touch = Date.now();
  });
}
function zoomBy(el, f) {
  const fl = el._fullLayout; if (!fl) return;
  if (fl.scene) { const eye = (fl.scene.camera && fl.scene.camera.eye) || DEFAULT_EYE; Plotly.relayout(el, { "scene.camera.eye": { x: eye.x * f, y: eye.y * f, z: eye.z * f } }); return; }
  const u = {};
  for (const k of ["xaxis", "yaxis"]) { const ax = fl[k]; if (!ax || !ax.range) continue; const a = ax.r2l(ax.range[0]), b = ax.r2l(ax.range[1]), c = (a + b) / 2, h = (b - a) / 2 * f; u[k + ".range"] = [ax.l2r(c - h), ax.l2r(c + h)]; }
  if (Object.keys(u).length) Plotly.relayout(el, u);
}
function resetZoom(el) {
  delete ZOOM[el._zkey];
  if (el.data && el._origLayout) Plotly.react(el, el.data, el._origLayout, PCFG);
}
function toggleFull(w, el) {
  w.classList.toggle("full"); document.body.classList.toggle("nofs", !!document.querySelector(".chartwrap.full"));
  setTimeout(() => { if (window.Plotly) Plotly.Plots.resize(el); }, 60);
}
document.addEventListener("keydown", e => { if (e.key === "Escape") { const w = document.querySelector(".chartwrap.full"); if (w) toggleFull(w, w.querySelector(".chart") || w.lastChild); } });
const BUSY_SEL = ".chartwrap, textarea, input:not([type=checkbox]):not([type=radio])";
document.addEventListener("pointerdown", e => { if (e.target.closest && e.target.closest(BUSY_SEL) && $("view").contains(e.target)) S.touch = Date.now(); });
document.addEventListener("keydown", e => { if (e.target.closest && e.target.closest("textarea, input:not([type=checkbox]):not([type=radio])") && $("view").contains(e.target)) S.touch = Date.now(); });
document.addEventListener("wheel", e => { if (e.target.closest && e.target.closest(".chartwrap")) S.touch = Date.now(); }, { passive: true });

const R = {
  async levels() { await R.levelsTable(); await priceChart(); },
  async levelsTable() {
    const [lv, mk] = await Promise.all([api("/analytics/levels", { underlying: S.u, convention: $("conv").value, method: $("method").value, top: S.lvtop, expiration: exps(), by_expiry: S.lvexp, mid: S.lvmid, moves: S.lvmov, ...selParams() }), api("/markets")]);
    S.lv = lv; const m = lv.meta, root = lv.mapping.futures_root, fut = mk.markets[S.u] || {};
    const keyMode = lv.selection.mode !== "all", shown = keyMode ? lv.zones : lv.levels.filter(l => S.cats.has(l.category));
    const dot = c => `<span class="dot" style="background:${CATCOL[c] || "#999"}"></span>`;
    const why = l => {
      if (keyMode) { const it = l.inputs.members.map(m => `${esc(m.label)} ${fmt(m.value, 0)}`), rest = it.slice(3);
        return `<span class="dim">${it.slice(0, 3).join("; ")}</span>${rest.length ? ` <details class="more"><summary>+${rest.length} more</summary><span class="dim">${rest.join("; ")}</span></details>` : ""}`; }
      const first = String(l.method).split(". ")[0];
      return `<span class="dim">${esc(first)}</span>${first.length < String(l.method).length - 1 ? ` <details class="more"><summary>details</summary><span class="dim">${esc(l.method)}</span></details>` : ""}`;
    };
    const rows = shown.slice().sort((a, b) => b.value - a.value).map(l => {
      const mp = l.mapped, pct = Math.round((l.importance || 0) * 100);
      return `<tr><td>${dot(l.category)}${esc(l.label)}${l.category === "custom" && !keyMode ? ` <button data-del="${l.custom_id}" title="Remove this level">x</button>` : ""}</td>
      <td class="num">${l.low != null ? `${fmt(l.low, 0)} to ${fmt(l.high, 0)}<br><span class="dim">strongest ${fmt(l.value, 0)}</span>` : fmt(l.value, 2)}</td>
      <td class="num">${mp && mp.mapped != null ? `<b>${l.low != null && l.mapped_low != null ? fmt(l.mapped_low, 0) + " to " + fmt(l.mapped_high, 0) : fmt(mp.mapped, 1)}</b>${mp.status && mp.status !== "ok" ? ` <span class="badge ${esc(mp.status)}">${esc(mp.status)}</span>` : ""}` : "-"}</td>
      <td><span class="score"><i style="width:${pct * 0.5}px"></i><b>${pct}</b></span></td>
      <td>${why(l)}</td><td class="dim">${l.first_seen ? etStamp(l.first_seen).slice(11) : "-"}</td><td class="rel-${l.reliability}">${l.reliability}</td></tr>`;
    }).join("");
    const map = lv.mapping, d = map.diagnostics || {}, warns = [...new Set(lv.levels.flatMap(l => (l.mapped && l.mapped.warnings) || []))];
    const sel = (id, opts) => `<select id="${id}">${opts.map(([v, n]) => `<option value="${v}">${n}</option>`).join("")}</select>`;
    const cnt = [["0", "Off"], ["1", "Nearest expiry"], ["2", "Next 2 expiries"], ["3", "Next 3 expiries"], ["5", "Next 5 expiries"]];
    $("view").innerHTML = panel(`Key levels for ${S.u}${root ? " mapped to " + root : ""}`, m, `
      <div class="toolbar"><label>Show<select id="lvkey"><option value="all">All levels</option><optgroup label="Most important"><option value="k6">Key levels: top 6</option><option value="k8">Key levels: top 8</option><option value="k10">Key levels: top 10</option><option value="k12">Key levels: top 12</option><option value="k15">Key levels: top 15</option></optgroup><optgroup label="Set count per type"><option value="qgex">GEX-heavy (GEX 8, OI 2, volume 1, move 2, charm 2, vanna 2, dealer delta 1, new 2)</option><option value="qbal">Balanced (GEX 3, OI 3, volume 2, move 2, charm 2, vanna 2, dealer delta 1, new 2)</option><option value="qtv">Send extra, trim in TradingView (GEX 16, OI 8, volume 6, move 8, charm 6, vanna 6, dealer delta 4, new 6)</option><option value="qcustom">Custom counts...</option></optgroup><optgroup label="Closest to price"><option value="n8">Nearest 8</option><option value="n14">Nearest 14</option><option value="n20">Nearest 20</option><option value="n30">Nearest 30</option></optgroup></select></label>
        <div class="chips" title="Switch whole families of levels on or off">${FAMILIES.map(([k, n, cs, col]) => `<label class="chip" style="--c:${col}"><input type="checkbox" data-fam="${k}" ${cs.every(c => S.cats.has(c)) ? "checked" : ""}><span>${n}</span></label>`).join("")}</div></div>
      ${S.lvq === "custom" ? `<div class="row quota" title="How many zones of each kind to show. The gamma flip and your own levels are always shown on top.">${QNAMES.map(([k, n]) => `<label>${n}<input type="number" min="0" max="20" step="1" data-q="${k}" value="${S.lvqc[k] || 0}" style="width:4.5em"></label>`).join("")}<span class="hint">Gamma flip and your own levels are always shown.</span></div>` : ""}
      <p class="status"><b>${keyMode ? `Showing ${lv.zones.length} of ${lv.selection.available} zones (${lv.selection.mode === "nearest" ? "the closest to price" : lv.selection.mode === "custom" ? "per-type counts: " + QNAMES.map(([k, n]) => `${n} ${lv.selection.used[k]}/${lv.selection.quota[k]}`).join(", ") : "the most important"}).` : `Showing all ${lv.levels.length} levels.`}</b>
        ${exps() === "all" ? "Using every expiration in the data." : "Using only the expirations chosen in the Expiration box."} A zone is a band of neighbouring strikes.</p>
      <details class="adv" data-k="lv-more"><summary>More settings: how many levels of each kind</summary><div class="body"><div class="row">
        <label>Strikes kept per type${sel("lvtop", [[2, "2"], [3, "3"], [5, "5"], [10, "10"]])}<span class="hint">How many zones of each kind to build.</span></label>
        <label>Mid-size zones${sel("lvmid", [["0", "Off"], ["1", "1 per type"], ["2", "2 per type"], ["3", "3 per type"]])}<span class="hint">Extra, smaller zones for variety.</span></label>
        <label>Expected-move zones${sel("lvmov", cnt)}<span class="hint">Up and down, for each expiry.</span></label>
        <label>Open interest and volume by expiry${sel("lvexp", cnt)}<span class="hint">One set of zones per expiry.</span></label></div></div></details>
      <details class="adv" data-k="lv-mine"><summary>Add your own level</summary><div class="body"><div class="row"><label>Price<input id="cu_price" size="10" placeholder="e.g. 30205"></label><label>Name<input id="cu_label" size="18" placeholder="e.g. Quant GEX 205"></label>
        <label>Price is in<select id="cu_units"><option value="underlying">${esc(S.u)} units</option>${root ? `<option value="futures">${esc(root)} points (needs a saved basis)</option>` : ""}</select></label>
        <button class="go" id="cu_add">Add level</button></div><span class="hint">Levels you type are kept and shown in the table, the chart and the indicator text.</span></div></details>
      ${root ? `<details class="adv" data-k="lv-nq" ${map.available ? "" : "open"}><summary>Convert to ${root} ${map.available ? "(done)" : "(set this once to see " + root + " numbers)"}</summary><div class="body">
        <div class="row"><label>${root} minus ${esc(S.u)} (basis)<input id="fb" size="10" placeholder="e.g. 260"></label><button class="go" id="fbsave">Save basis</button>
          <span class="dim">${map.typed_basis ? `Saved basis: <b>${fmt(map.typed_basis.value, 2)}</b> (${fmt(map.typed_basis.age_minutes, 0)} min ago).` : `Easiest way: on TradingView read ${root} and ${esc(S.u)} at the same moment and type ${root} minus ${esc(S.u)} here once.`}</span></div>
        <div class="row"><label>${root} contract<input id="fc" value="${esc((map.roll && map.roll.contract) || "")}" size="8"></label><label>${root} price<input id="fp" size="10" placeholder="e.g. 21500.25"></label>
          <label>Price as of (ET, optional)<input id="fa" size="10" placeholder="HH:MM"></label><button id="fsave">Save ${root} price</button>
          <span class="dim">${esc(S.u)} reference: ${fmt(m.spot, 2)} at ${et(m.spot_timestamp)}. Enter the ${root} price from that same moment.</span></div></div></details>` : ""}
      <div class="actions"><button class="go" id="ftxt">Copy levels for the indicator</button>${root ? `<button id="fpine">Copy Pine code</button><button id="fpinedl">Download .pine</button><button id="fcopy">Copy ${root} levels as text</button>` : ""}</div>
      ${root && map.roll && map.roll.note ? note(map.roll.note, map.roll.status === "expired") : ""}${root && warns.length ? note("Mapping warnings: " + warns.join(" ")) : ""}
      ${root && !map.available ? note(map.note || "No futures price entered yet, so levels are shown in " + S.u + " units only.") : ""}
      <div class="scroll tall"><table><tr><th>Level</th><th>${esc(S.u.replace(/^_/, ""))}</th><th>${root || "Futures"} estimate</th><th>Score</th><th>${keyMode ? "What lines up here" : "Where it comes from"}</th><th>Since (ET)</th><th>Trust</th></tr>${rows || "<tr><td colspan=7>No levels available</td></tr>"}</table></div>
      <p class="hint">${esc(lv.note)} Trust rule: ${esc(lv.meta.reliability_rule)}</p>
      ${d.available ? `<p class="hint">Mapping check on ${d.n} stored pairs: ratio error ${fmt(d.ratio.mae, 2)}, basis error ${fmt(d.basis.mae, 2)} (mean absolute, futures points). Best so far: ${d.best}.</p>` : `<p class="hint">Mapping accuracy: ${esc(d.note || "not measured yet")}</p>`}
      <details class="adv" data-k="lv-paste" open><summary>Paste into the TradingView indicator</summary><div class="body">
        <p class="dim">Click the box, press Ctrl+A then Ctrl+C (or use the button), and paste it into the indicator's Levels setting. It holds exactly the rows in the table above.</p>
        <textarea id="indtext" readonly spellcheck="false" style="width:100%;height:230px;font:calc(13px*var(--z)) ui-monospace,Menlo,Consolas,monospace"></textarea>
        <div class="row"><button class="go" id="indcopy">Copy this text</button><span class="dim" id="indnote"></span></div></div></details>`);
    { const it = indicatorText(lv, m, root); $("indtext").value = it.text;
      $("indnote").textContent = `${it.count} levels, ${it.mapped ? "as estimated " + root + " points" : "in " + S.u + " units. Save a basis above to get " + root + " points"}.`;
      $("indtext").onclick = () => $("indtext").select();
      $("indcopy").onclick = async () => { $("indtext").select(); try { await navigator.clipboard.writeText(it.text); $("indcopy").textContent = "Copied"; } catch (e) { document.execCommand("copy"); $("indcopy").textContent = "Copied (or press Ctrl+C)"; } }; }
    $("lvtop").value = String(S.lvtop); $("lvtop").onchange = () => { S.lvtop = +$("lvtop").value; render(); };
    $("lvkey").value = S.lvq ? "q" + S.lvq : S.lvnear ? "n" + S.lvnear : S.lvkey ? "k" + S.lvkey : "all";
    $("lvkey").onchange = () => { const v = $("lvkey").value; S.lvq = v[0] === "q" ? v.slice(1) : ""; S.lvkey = v[0] === "k" ? +v.slice(1) : 0; S.lvnear = v[0] === "n" ? +v.slice(1) : 0; render(); };
    document.querySelectorAll("[data-q]").forEach(i => i.onchange = () => { S.lvqc = { ...S.lvqc, [i.dataset.q]: Math.max(0, Math.min(20, Math.round(+i.value || 0))) }; render(); });
    $("lvmov").value = String(S.lvmov); $("lvmov").onchange = () => { S.lvmov = +$("lvmov").value; render(); };
    $("lvmid").value = String(S.lvmid); $("lvmid").onchange = () => { S.lvmid = +$("lvmid").value; render(); };
    $("lvexp").value = String(S.lvexp); $("lvexp").onchange = () => { S.lvexp = +$("lvexp").value; render(); };
    $("cu_add").onclick = async () => {
      try { const r = await fetch("/api/custom-levels" + (S.src ? "?source=" + S.src : ""), { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ underlying: S.u, label: $("cu_label").value || "Custom level", value: parseFloat($("cu_price").value), units: $("cu_units").value }) });
        if (!r.ok) { const j = await r.json(); throw new Error(typeof j.detail === "string" ? j.detail : "Could not save"); } S.cats.add("custom"); render(); }
      catch (e) { alert("Could not add: " + e.message); }
    };
    document.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => { await fetch(`/api/custom-levels/${b.dataset.del}?underlying=${encodeURIComponent(S.u)}${S.src ? "&source=" + S.src : ""}`, { method: "DELETE" }); render(); });
    document.querySelectorAll("[data-fam]").forEach(c => c.onchange = () => { const f = FAMILIES.find(x => x[0] === c.dataset.fam); f[2].forEach(k => c.checked ? S.cats.add(k) : S.cats.delete(k)); render(); });
    const bs = $("fbsave");
    if (bs) bs.onclick = async () => {
      try { const r = await fetch("/api/basis", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root, basis: parseFloat($("fb").value) }) });
        if (!r.ok) throw new Error((await r.json()).detail); $("method").value = "typed_basis"; render(); } catch (e) { alert("Could not save: " + e.message); }
    };
    const cp = $("fcopy");
    if (cp) cp.onclick = async () => {
      const lines = lv.levels.filter(l => S.cats.has(l.category) && l.mapped && l.mapped.mapped != null).sort((a, b) => b.mapped.mapped - a.mapped.mapped)
        .map(l => `${l.label}: ${fmt(l.mapped.mapped, 2)}`);
      if (!lines.length) return alert("No " + root + " levels yet. Save a basis or a " + root + " price first.");
      const txt = `${root} levels (estimates, ${S.u} ${et(m.source_timestamp)})\n` + lines.join("\n");
      try { await navigator.clipboard.writeText(txt); cp.textContent = "Copied"; } catch (e) { prompt("Copy this text:", txt); }
    };
    const pineGet = async () => api("/export/pine", { underlying: S.u, convention: $("conv").value, method: $("method").value, categories: [...S.cats].join(","), top: S.lvtop, expiration: exps(), by_expiry: S.lvexp, mid: S.lvmid, moves: S.lvmov, ...selParams() });
    const pc = $("fpine"), pd = $("fpinedl");
    if (pc) pc.onclick = async () => { try { const r = await pineGet(); try { await navigator.clipboard.writeText(r.code); pc.textContent = `Copied ${r.levels} levels`; } catch (e) { showText("Pine code", r.code); } } catch (e) { alert("Could not build Pine code: " + (e.msg || e.message)); } };
    if (pd) pd.onclick = async () => { try { const r = await pineGet(); download("options_levels.pine", r.code); pd.textContent = "Downloaded"; } catch (e) { alert("Could not build Pine code: " + (e.msg || e.message)); } };
    const tx = $("ftxt");
    if (tx) tx.onclick = async () => { const it = indicatorText(lv, m, root); try { await navigator.clipboard.writeText(it.text); tx.textContent = `Copied ${it.count} levels`; } catch (e) { showText("Levels for the indicator", it.text); } };
    const sv = $("fsave");
    if (sv) sv.onclick = async () => {
      const t = $("fa").value.trim(); let as_of = null;
      if (t) { const [h, mi] = t.split(":").map(Number); const n = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" })); n.setHours(h, mi, 0, 0);
        const off = new Date() - new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" })); as_of = new Date(n.getTime() + off).toISOString(); }
      try { await fetch("/api/futures-price", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root, price: parseFloat($("fp").value), contract: $("fc").value, as_of }) }).then(async r => { if (!r.ok) throw new Error((await r.json()).detail); }); render(); }
      catch (e) { alert("Could not save: " + e.message); }
    };
  },
  async chain() {
    const p = base(); const right = $("cr") ? $("cr").value : "all";
    const j = await api("/options/chain", { underlying: p.underlying, expiration: p.expiration, right, strike_min: $("ck1") ? $("ck1").value : "", strike_max: $("ck2") ? $("ck2").value : "", limit: 500 });
    const rows = j.contracts.map(c => `<tr><td>${c.expiry}</td><td class="num">${fmt(c.strike, 2)}</td><td>${c.right}</td><td class="num">${fmt(c.bid, 2)}</td><td class="num">${fmt(c.ask, 2)}</td><td class="num">${fmt(c.last, 2)}</td>
      <td class="num">${fmt(c.volume)}</td><td class="num">${fmt(c.oi)}</td><td class="num">${c.iv == null ? "-" : fmt(c.iv * (c.iv > 3 ? 1 : 100), 1) + "%"}</td>
      <td class="num">${fmt(c.delta, 3)}</td><td class="num">${fmt(c.gamma, 5)}</td><td class="num">${fmt(c.theta, 3)}</td><td class="num">${fmt(c.vega, 3)}</td><td class="dim">${esc(c.ticker)}</td></tr>`).join("");
    $("view").innerHTML = panel("Options chain", j.meta, `<div class="row"><label>Type<select id="cr"><option value="all">Calls and puts</option><option value="C">Calls</option><option value="P">Puts</option></select></label>
      <label>Strike from<input id="ck1" size="8"></label><label>to<input id="ck2" size="8"></label><button id="capply">Apply</button><span class="dim">${fmt(j.total_matching)} contracts match, showing up to 500. "-" means the provider supplied no value.</span></div>
      <div class="scroll"><table><tr><th>Expiry</th><th>Strike</th><th>C/P</th><th>Bid</th><th>Ask</th><th>Last</th><th>Volume</th><th>Open int.</th><th>IV</th><th>Delta</th><th>Gamma</th><th>Theta</th><th>Vega</th><th>Contract</th></tr>${rows}</table></div>`);
    $("cr").value = right; $("capply").onclick = render;
  },
  async gex() {
    const j = await api("/analytics/gex", base()), d = j.data, m = j.meta, K = d.strikes.map(s => s.strike);
    $("view").innerHTML = panel(`Modeled gamma exposure, ${S.u}`, m, `<div id="c1" class="chart"></div>
      ${note("Modeled, not observed. Open interest does not show who owns each contract, so the sign comes from the scenario selected above (" + d.convention + ").")}
      <p class="dim">Formula: ${esc(d.formula)}. Units: ${esc(d.units)}. Contracts used: ${d.contracts_used.provider} with provider gamma, ${d.contracts_used.model} with modeled gamma; excluded: ${d.contracts_excluded.no_open_interest} without open interest, ${d.contracts_excluded.no_gamma_or_iv} without gamma or IV. Total net: ${big(d.total_net_gex)}. Click a bar for its contracts.</p><div id="inspect"></div>`);
    plot("c1", [{ type: "bar", x: K, y: d.strikes.map(s => s.call_gex), name: "Calls", marker: { color: "#2f8bf5" } }, { type: "bar", x: K, y: d.strikes.map(s => s.put_gex), name: "Puts", marker: { color: "#ff7a2e" } },
      { type: "scatter", mode: "lines", x: K, y: d.strikes.map(s => s.net_gex), name: "Net", line: { color: "#fff", width: 2 } }],
      LAY("GEX by strike ($ delta per 1% move)", { barmode: "relative", shapes: [{ type: "line", xref: "x", yref: "paper", x0: m.spot, x1: m.spot, y0: 0, y1: 1, line: { color: "#fff", dash: "dot" } }], xaxis: { title: "Strike (" + S.u + " price units)", gridcolor: "#1E2840" } }));
    $("c1").on && $("c1").on("plotly_click", ev => { const s = d.strikes.find(x => x.strike === ev.points[0].x); if (!s) return;
      $("inspect").innerHTML = `<h3>Strike ${fmt(s.strike, 2)}</h3><table><tr><th>Contract</th><th>Expiry</th><th>Open int.</th><th>Gamma</th><th>Source</th><th>Exposure</th></tr>${s.contributions.map(c => `<tr><td>${esc(c.ticker)}</td><td>${c.expiry}</td><td class="num">${fmt(c.oi)}</td><td class="num">${fmt(c.gamma, 5)}</td><td>${c.gamma_source}</td><td class="num">${fmt(c.exposure)}</td></tr>`).join("")}</table>`; });
  },
  async flip() { await R.flipMain(); await scenariosPanel(); },
  async flipMain() {
    const j = await api("/analytics/gamma-flip", base()), d = j.data;
    $("view").innerHTML = panel("Estimated gamma flip", j.meta, `${d.found ? `<div class="grid"><div class="card">Estimated flip<b>${fmt(d.flip, 2)}</b></div><div class="card">Reliability<b>${esc(d.reliability)}</b></div>
      <div class="card">Modeled exposure just below / above<b>${big(d.exposure_below)} / ${big(d.exposure_above)}</b></div><div class="card">Contracts used<b>${d.contracts_used}</b></div></div>` : note("No valid crossing was found, so no flip level is shown.", true)}
      ${note(d.note)}<div id="c1" class="chart"></div><p class="dim">Method: ${esc(d.method)}. The result depends on the sign scenario and on the quality of IV and open interest.</p>`);
    if (d.grid.length) plot("c1", [{ type: "scatter", mode: "lines", x: d.grid.map(g => g.price), y: d.grid.map(g => g.total_gex), line: { color: "#2f8bf5", width: 2.5 }, name: "Total modeled GEX" }],
      LAY("Total modeled GEX at hypothetical prices", { shapes: [{ type: "line", xref: "x", yref: "paper", x0: j.meta.spot, x1: j.meta.spot, y0: 0, y1: 1, line: { color: "#fff", dash: "dot" } }, { type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: "#e5534b" } }].concat(d.found ? [{ type: "line", xref: "x", yref: "paper", x0: d.flip, x1: d.flip, y0: 0, y1: 1, line: { color: "#e6b422", dash: "dash" } }] : []) }));
  },
  async oi() {
    await bars("/analytics/oi", "Open interest by strike", "Open interest", d => note("Open interest is the end-of-previous-trading-day figure and does not change during the session. Each stored snapshot keeps its own copy, so changes between sessions can be compared below."));
    const h = await api("/history/oi-change", { underlying: S.u }), box = document.createElement("div");
    box.className = "panel";
    box.innerHTML = h.available ? `<h2>Open interest change between sessions</h2><div id="c2" class="chart"></div><p class="dim">Latest stored snapshot (${et(h.to)}) compared with an earlier session (${et(h.from)}). Only contracts present in both are compared. Positive means more open contracts.</p>`
      : `<h2>Open interest history</h2>${note(h.reason)}`;
    $("view").appendChild(box);
    if (h.available) plot("c2", [{ type: "bar", x: h.change_by_strike.map(r => r.strike), y: h.change_by_strike.map(r => r.call), name: "Calls", marker: { color: "#3fb96a" } }, { type: "bar", x: h.change_by_strike.map(r => r.strike), y: h.change_by_strike.map(r => r.put), name: "Puts", marker: { color: "#e5534b" } }],
      LAY("Change in open interest by strike", { barmode: "group", yaxis: { title: "Contracts", gridcolor: "#1E2840" } }));
  },
  async volume() {
    let flagged = [];
    await bars("/analytics/volume", "Options volume by strike", "Contracts traded", (d, j) => { const u = j.unusual_volume; flagged = u.flagged || [];
      return note("Session volume does not say who bought or sold.") + (u.available ? `<h3>Unusual volume (same-chain comparison)</h3>${flagged.length ? `<table><tr><th>Strike</th><th>Total volume</th><th>Times the median strike</th><th>Robust z</th></tr>${flagged.map(f => `<tr><td>${fmt(f.strike, 2)}</td><td class="num">${fmt(f.volume)}</td><td class="num">${fmt(f.times_median, 1)}x</td><td class="num">${fmt(f.robust_z, 1)}</td></tr>`).join("")}</table>` : "<p class='dim'>No strike stands out from the rest of today's chain.</p>"}<p class="dim">${esc(u.method)}</p>` : note(u.note)); });
    if (flagged.length && window.Plotly && $("c1")) Plotly.addTraces("c1", [{ type: "scatter", mode: "markers", x: flagged.map(f => f.strike), y: flagged.map(f => f.volume), name: "Unusual", marker: { symbol: "diamond", size: 11, color: "#ffd34d", line: { color: "#000", width: 1 } }, hovertemplate: "Unusual: %{x}<br>total volume %{y}<extra></extra>" }]);
  },
  async heatmap() {
    const want = { underlying: S.u, measure: S.hmm, side: S.hms, window: S.hmw, expiries: S.hmx, convention: $("conv").value, method: $("method").value };
    let j;
    try { j = await api("/analytics/activity", want); } catch (e) { throw e; }
    const M = [["oi_change", "New positions (open interest change since the last session)"], ["volume", "Volume today"], ["oi", "Open interest"], ["gex", "Modeled GEX"], ["charm", "Modeled charm (est.)"], ["vanna", "Modeled vanna (est.)"], ["dex", "Modeled dealer delta (est.)"]];
    const modeled = ["gex", "charm", "vanna", "dex"].includes(S.hmm);
    const ctl = `<div class="toolbar">
      <label>Show<select id="hmm">${M.map(([v, n]) => `<option value="${v}">${n}</option>`).join("")}</select></label>
      <label>Side<select id="hms"><option value="total">Calls + puts</option><option value="call">Calls only</option><option value="put">Puts only</option>${modeled ? "" : '<option value="net">Calls minus puts</option>'}</select></label>
      <label>Strikes within<select id="hmw"><option value="0.015">1.5% of price</option><option value="0.02">2% of price</option><option value="0.04">4% of price</option><option value="0.08">8% of price</option><option value="0">All strikes</option></select></label>
      <label>Expirations<select id="hmx"><option value="2">Next 2</option><option value="4">Next 4</option><option value="8">Next 8</option><option value="15">Next 15</option><option value="30">Up to 30</option></select></label></div>`;
    const wire = () => { $("hmm").value = S.hmm; $("hms").value = modeled && S.hms === "net" ? "total" : S.hms; $("hmw").value = S.hmw; $("hmx").value = S.hmx;
      ["hmm", "hms", "hmw", "hmx"].forEach(id => $(id).onchange = () => { S.hmm = $("hmm").value; S.hms = $("hms").value; S.hmw = $("hmw").value; S.hmx = $("hmx").value; render(); }); };
    if (!j.available) { $("view").innerHTML = panel(`Activity heatmap, ${S.u}`, j.meta, ctl + note(j.reason)); wire(); return; }
    const d = j.data, m = j.meta, root = j.futures_root, fut = v => v == null ? "" : `<i class="fut">${esc(root)} ${fmt(v, 0)}</i>`;
    const px = v => fmt(v, v % 1 ? 2 : 0);
    const unitTxt = d.modeled ? big : (v => fmt(v));
    const meanCol = h => ({ call: "#3fb96a", put: "#e5534b", positive: d.measure === "oi_change" ? "#3fb96a" : d.measure === "charm" ? "#e76f51" : "#4cc9f0", negative: d.measure === "oi_change" ? "#e5534b" : d.measure === "charm" ? "#2a9d8f" : "#f72585" }[h.side]);
    const hot = d.hot_spots.map((h, i) => `<tr><td><b>#${i + 1}</b></td><td class="num"><b>${px(h.price)}</b><br><span class="dim">${px(h.low)} to ${px(h.high)}</span></td>
      <td class="num">${h.futures != null ? `<b>${fmt(h.futures, 0)}</b><br><span class="dim">${fmt(h.futures_low, 0)} to ${fmt(h.futures_high, 0)}</span>` : "-"}</td>
      <td><span class="dot" style="background:${meanCol(h)}"></span>${esc(h.meaning)}</td>
      <td><span class="share"><i style="width:${Math.round(h.share * 100)}%;background:${meanCol(h)}"></i></span> ${fmt(h.share * 100, 0)}%</td>
      <td class="num">${h.distance_pct >= 0 ? "+" : ""}${fmt(h.distance_pct, 2)}%</td><td>${h.top_expiry ? esc(h.top_expiry.slice(5)) : "-"}</td></tr>`).join("");
    const above = d.share_above, below = d.share_below;
    const tiles = `<div class="hm-tiles">
      <div class="card hm-big"><span>Activity center</span><b>${d.center != null ? px(d.center) : "-"}</b>${fut(d.center_futures)}<em>Half the activity in view sits above this price, half below.</em></div>
      <div class="card"><span>Biggest hot spot</span><b>${d.hot_spots[0] ? px(d.hot_spots[0].price) : "-"}</b>${d.hot_spots[0] ? fut(d.hot_spots[0].futures) : ""}<em>${d.hot_spots[0] ? esc(d.hot_spots[0].meaning) + ", " + fmt(d.hot_spots[0].share * 100, 0) + "% of the total" : "none"}</em></div>
      <div class="card"><span>Price now</span><b>${px(m.spot)}</b>${fut(d.spot_futures)}<em>${above != null ? `${fmt(above * 100, 0)}% of activity above, ${fmt(below * 100, 0)}% below` : ""}</em></div>
      ${above != null ? `<div class="card"><span>Above vs below price</span><div class="tilt"><i style="width:${Math.round(above * 100)}%"></i></div><em>${above > 0.6 ? "Weighted above price" : below > 0.6 ? "Weighted below price" : "Spread on both sides"}</em></div>` : ""}</div>`;
    $("view").innerHTML = panel(`${esc(d.title)}, ${S.u}`, m, ctl + `<div class="readout">${esc(d.summary)}</div>` + tiles +
      (d.strikes.length ? `<div id="c1" class="chart" style="height:${Math.min(1250, Math.max(520, d.strikes.length * 16 + 140))}px"></div>` : note("Nothing in this window. Widen the strikes or add expirations.", true)) +
      `<h3>Hot spots: where the activity is concentrated</h3>
      <div class="scroll"><table class="hot"><tr><th></th><th>${esc(S.u.replace(/^_/, ""))} price (band)</th><th>${root || "Futures"} price</th><th>What it is</th><th>Share of activity</th><th>From price</th><th>Main expiry</th></tr>${hot || "<tr><td colspan=7>None</td></tr>"}</table></div>
      ${!j.mapped && root ? note(`Save a basis on the Key levels tab to see ${root} prices here. ${j.mapping_note || ""}`) : ""}
      ${d.modeled ? note("Modeled estimate. The dealer side comes from the positioning assumption in Settings, not from observed positions.") : ""}
      <p class="hint">${d.measure === "oi_change" && j.oi_from ? `Compared with the open interest stored ${esc(et(j.oi_from))}. ` : ""}Units: ${esc(d.units)}. ${esc(d.hot_rule)} ${d.color_max && d.color_max < d.max ? `Colors stop getting stronger at ${unitTxt(d.color_max)} so smaller cells stay visible.` : ""} Hover a cell for its exact value.</p>`);
    wire();
    if (!d.strikes.length) return;
    const ys = d.strikes.map(k => px(k)), xs = d.expiries.map((e, i) => `${e.slice(5)} (${fmt(d.dte[i], d.dte[i] < 1 ? 1 : 0)}d)`);
    let near = 0; d.strikes.forEach((k, i) => { if (Math.abs(k - m.spot) < Math.abs(d.strikes[near] - m.spot)) near = i; });
    const sg = v => v == null ? null : Math.sign(v) * Math.sqrt(Math.abs(v)), cm = d.color_max || d.max || 1;
    const green = d.measure === "oi_change" || (d.side === "net" && !d.modeled);
    const cs = d.signed ? (green ? [[0, "#ff4d5e"], [0.25, "#8a1f33"], [0.5, "#0D1322"], [0.75, "#1f6b45"], [1, "#4dff9a"]] : [[0, "#ff3d9a"], [0.25, "#6e1f5c"], [0.5, "#0D1322"], [0.75, "#145a7a"], [1, "#4cc9f0"]])
      : [[0, "#0D1322"], [0.12, "#1b2a6b"], [0.32, "#3D8BFF"], [0.52, "#22d3c5"], [0.74, "#ffd34d"], [1, "#ff4d3d"]];
    const fr = d.signed ? [-1, -.4, -.1, 0, .1, .4, 1] : [0, .05, .2, .45, 1], tv = fr.map(f => f * cm);
    const hov = d.modeled ? "%{customdata:,.3s}" : "%{customdata:,.0f}";
    const prof = d.profile, pcol = prof.map(v => d.signed ? (v >= 0 ? (green ? "#3fb96a" : "#4cc9f0") : (green ? "#e5534b" : "#f72585")) : "#3D8BFF");
    const hotIdx = d.hot_spots.map(h => d.strikes.indexOf(h.price));
    const shapes = [{ type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: near, y1: near, line: { color: "#ffd34d", width: 2, dash: "dot" } }]
      .concat(d.hot_spots.map((h, i) => ({ type: "rect", xref: "paper", yref: "y", x0: 0, x1: 0.79, y0: Math.min(...h.members.map(k => d.strikes.indexOf(k)).filter(x => x >= 0), hotIdx[i]) - 0.5, y1: Math.max(...h.members.map(k => d.strikes.indexOf(k)), hotIdx[i]) + 0.5, line: { color: "#ffffff", width: i ? 1 : 2 }, fillcolor: "rgba(0,0,0,0)" })));
    const ann = d.hot_spots.map((h, i) => ({ xref: "paper", yref: "y", x: 1, y: hotIdx[i], xanchor: "right", showarrow: false, bgcolor: "rgba(10,15,28,.82)", bordercolor: "#fff", borderwidth: i ? 0 : 1, borderpad: 3,
      text: `<b>#${i + 1} ${px(h.price)}</b>${h.futures != null ? `  ${root} ${fmt(h.futures, 0)}` : ""}`, font: { size: 11, color: "#fff" } }))
      .concat([{ xref: "paper", yref: "y", x: 0, y: near, xanchor: "left", yanchor: "bottom", showarrow: false, text: `price ${px(m.spot)}${d.spot_futures != null ? ` (${root} ${fmt(d.spot_futures, 0)})` : ""}`, font: { size: 11, color: "#ffd34d" }, bgcolor: "rgba(10,15,28,.75)" }]);
    plot("c1", [
      { type: "heatmap", x: xs, y: ys, z: d.z.map(r => r.map(sg)), customdata: d.z, colorscale: cs, zmid: d.signed ? 0 : undefined, zmin: d.signed ? -sg(cm) : 0, zmax: sg(cm), xgap: 2, ygap: 1, hoverongaps: false,
        hovertemplate: `Strike %{y}<br>Expiry %{x}<br>${hov} ${esc(d.units)}<extra></extra>`,
        colorbar: { orientation: "h", thickness: 10, x: 0, xanchor: "left", y: -0.1, yanchor: "top", len: 0.79, title: { text: d.units, side: "top" }, tickmode: "array", tickvals: tv.map(sg), ticktext: tv.map(v => d.modeled ? big(v) : fmt(v)) } },
      { type: "bar", orientation: "h", x: prof, y: ys, xaxis: "x2", yaxis: "y", marker: { color: pcol }, hovertemplate: `Strike %{y}<br>all expiries: ${d.modeled ? "%{x:,.3s}" : "%{x:,.0f}"}<extra></extra>` }],
      LAY("", { margin: { l: 70, r: 14, t: 16, b: 120 }, showlegend: false,
        xaxis: { domain: [0, 0.79], gridcolor: "#1E2840", tickangle: -30, side: "bottom" },
        xaxis2: { domain: [0.81, 1], gridcolor: "#1E2840", zerolinecolor: "#5D6884", title: { text: "All expiries", font: { size: 11 } }, showticklabels: false },
        yaxis: { type: "category", categoryorder: "array", categoryarray: ys, autorange: "reversed", gridcolor: "#1E2840", title: "Strike", dtick: Math.max(1, Math.round(ys.length / 32)) },
        shapes, annotations: ann }));
  },
  async flows() {
    const j = await api("/analytics/greeks", base()), d = j.data, m = j.meta, K = d.strikes.map(s => s.strike);
    const t = d.totals, dr = d.drift_to_close;
    const sideTxt = { charm: { positive: "dealers sell as time passes", negative: "dealers buy as time passes" }, vanna: { positive: "dealers buy if IV falls", negative: "dealers sell if IV falls" }, dex: { positive: "dealers long delta", negative: "dealers short delta" } };
    const zrows = ["charm", "vanna", "dex"].flatMap(k => j.zones[k].map(z => ({ k, ...z }))).sort((a, b) => b.center - a.center).map(z =>
      `<tr><td><span class="dot" style="background:${{ charm: { positive: "#e76f51", negative: "#2a9d8f" }, vanna: { positive: "#c77dff", negative: "#ffb703" }, dex: { positive: "#4cc9f0", negative: "#f72585" } }[z.k][z.side]}"></span>${{ charm: "Charm", vanna: "Vanna", dex: "Dealer delta" }[z.k]}</td>
      <td class="num"><b>${fmt(z.center, 0)}</b><br><span class="dim">${fmt(z.low, 0)} to ${fmt(z.high, 0)}</span></td><td>${esc(sideTxt[z.k][z.side])}</td><td class="num">${big(z.magnitude)}</td></tr>`).join("");
    const vSent = t.vanna === 0 ? "" : `If IV falls 1 point, dealers would need to ${t.vanna > 0 ? "BUY" : "SELL"} about $${big(Math.abs(t.vanna))} of ${esc(S.u.replace(/^_/, ""))} to stay hedged (the reverse if IV rises).`;
    $("view").innerHTML = panel(`Charm and vanna, ${S.u}`, m, `<div class="grid">
      <div class="card ${dr > 0 ? "bear" : dr < 0 ? "bull" : ""}">Charm drift to the close<b>${dr === 0 ? "none" : (dr > 0 ? "Sell " : "Buy ") + "$" + big(Math.abs(dr))}</b><span class="dim">${fmt(d.hours_to_close, 1)} hours left</span></div>
      <div class="card">Charm per day (all strikes)<b>${t.charm > 0 ? "Sell " : "Buy "}$${big(Math.abs(t.charm))}</b><span class="dim">if price and IV held for a day</span></div>
      <div class="card ${t.vanna > 0 ? "bull" : "bear"}">Vanna (per 1 IV point)<b>$${big(t.vanna)}</b><span class="dim">${t.vanna > 0 ? "IV down = dealer buying" : "IV down = dealer selling"}</span></div>
      <div class="card">Dealer delta now<b>$${big(t.dex)}</b><span class="dim">${t.dex > 0 ? "dealers net long" : "dealers net short"}</span></div></div>
      <div class="readout">${esc(d.drift_note)} ${vSent}</div>
      <div id="c1" class="chart"></div><div id="c2" class="chart"></div><div id="c3" class="chart"></div>
      <h3>Zones</h3><div class="scroll"><table><tr><th>Kind</th><th>Strike (band)</th><th>What it means</th><th>Size</th></tr>${zrows || "<tr><td colspan=4>None</td></tr>"}</table></div>
      ${note(j.note)}<p class="hint">${esc(d.rules.charm)}</p><p class="hint">${esc(d.rules.vanna)}</p><p class="hint">${esc(d.rules.dex)} Contracts used: ${fmt(d.contracts_used)}. These zones are also level types on Key levels and in the TradingView paste text, each with its own settings group.</p>`);
    const spotLine = [{ type: "line", xref: "x", yref: "paper", x0: m.spot, x1: m.spot, y0: 0, y1: 1, line: { color: "#ffd34d", dash: "dot" } }];
    const bars = (div, key, title, pos, neg) => plot(div, [{ type: "bar", x: K, y: d.strikes.map(s => s[key]), marker: { color: d.strikes.map(s => s[key] >= 0 ? pos : neg) }, hovertemplate: "Strike %{x}<br>%{y:,.3s}<extra></extra>" }],
      LAY(title, { shapes: spotLine, showlegend: false, xaxis: { title: "Strike", gridcolor: "#1E2840" }, yaxis: { gridcolor: "#1E2840", title: "$ delta" } }));
    bars("c1", "charm", "Charm by strike ($ delta per day; up = dealers sell as time passes)", "#e76f51", "#2a9d8f");
    bars("c2", "vanna", "Vanna by strike ($ delta per 1 IV point; up = dealers buy if IV falls)", "#c77dff", "#ffb703");
    bars("c3", "dex", "Dealer delta by strike ($ of underlying)", "#4cc9f0", "#f72585");
  },
  async iv() {
    const j = await api("/analytics/iv", { underlying: S.u, expiration: exps(), otm_only: S.ivotm, smooth: S.ivsm }), m = j.meta, pc = j.percentile, sp = m.spot;
    $("view").innerHTML = panel(`IV by strike, ${S.u}`, m, `<div class="row">
      <label>X axis<select id="ivx"><option value="strike">Strike</option><option value="moneyness">Moneyness (strike / spot)</option></select></label>
      <label><span><input type="checkbox" id="ivotm" ${S.ivotm ? "checked" : ""}> Out-of-the-money options only</span></label>
      <label><span><input type="checkbox" id="ivsm" ${S.ivsm ? "checked" : ""}> Remove isolated spikes</span></label>
      <span class="dim">Pick expirations in the box at the top, or leave it on All to see the first four.</span></div>
      ${j.smiles.length ? `<div id="c1" class="chart" style="height:440px"></div><div id="c2" class="chart"></div>` : note("Not enough clean quotes to draw a smile. Try unticking the filters, or wait for the market to open.", true)}
      <p class="dim">${cleanNote(j.cleaning)}</p>
      <p class="dim">Percentile: ${pc.available ? fmt(pc.value * 100, 0) + "th percentile of " + pc.observations + " stored observations" : esc(pc.note) + ` (have ${pc.observations} observations over ${pc.days} days)`}. Historical volatility: ${esc(j.historical_volatility.reason)}</p>`);
    $("ivx").value = S.ivx;
    $("ivx").onchange = () => { S.ivx = $("ivx").value; render(); }; $("ivotm").onchange = () => { S.ivotm = $("ivotm").checked; render(); }; $("ivsm").onchange = () => { S.ivsm = $("ivsm").checked; render(); };
    if (!j.smiles.length) return;
    const X = p => S.ivx === "strike" ? p.strike : p.moneyness, n = j.smiles.length;
    const traces = j.smiles.map((r, i) => ({ type: "scatter", mode: "lines+markers", x: r.points.map(X), y: r.points.map(p => p.iv * 100), name: `${r.expiry} (${fmt(r.dte, 1)}d)`,
      line: { color: rgbAt(n > 1 ? i / (n - 1) : 0), width: 2.5 }, marker: { size: 4 }, hovertemplate: `${r.expiry}<br>%{x}<br>IV %{y:.2f}%<extra></extra>` }));
    plot("c1", traces, LAY("Cleaned IV smile, one line per expiry", { hovermode: "closest", xaxis: { title: S.ivx === "strike" ? "Strike" : "Strike / spot", gridcolor: "#1E2840", tickformat: S.ivx === "strike" ? ",d" : ".3f" }, yaxis: { title: "IV %", gridcolor: "#1E2840", ticksuffix: "%" },
      shapes: [{ type: "line", xref: "x", yref: "paper", x0: S.ivx === "strike" ? sp : 1, x1: S.ivx === "strike" ? sp : 1, y0: 0, y1: 1, line: { color: "#fff", dash: "dot", width: 1.5 } }] }));
    plot("c2", [{ type: "scatter", mode: "lines+markers+text", x: j.term_structure.map(t => t.dte), y: j.term_structure.map(t => t.iv * 100), text: j.term_structure.map(t => (t.iv * 100).toFixed(1) + "%"), textposition: "top center",
      fill: "tozeroy", fillcolor: "rgba(27,224,214,.10)", line: { color: "#1be0d6", width: 3 }, marker: { size: 9 }, hovertemplate: "%{x:.1f} days<br>IV %{y:.2f}%<extra></extra>" }],
      LAY("ATM IV by days to expiry", { xaxis: { title: "Days to expiry", gridcolor: "#1E2840", range: j.term_structure.length ? [Math.min(...j.term_structure.map(t => t.dte)) - 1.5, Math.max(...j.term_structure.map(t => t.dte)) + 1.5] : undefined }, yaxis: { title: "IV %", gridcolor: "#1E2840", ticksuffix: "%" }, showlegend: false }));
  },
  async surface() {
    const j = await api("/analytics/surface", { underlying: S.u, otm_only: S.svotm, smooth: true, min_points: 6 }), m = j.meta, d = j.data;
    const ctl = `<div class="row"><label>View<select id="svview"><option value="3d">3D surface</option><option value="heat">Heatmap</option><option value="both">Both</option></select></label>
      <label>X axis<select id="svx"><option value="strike">Strike</option><option value="moneyness">Moneyness (strike / spot)</option></select></label>
      <label><span><input type="checkbox" id="svotm" ${S.svotm ? "checked" : ""}> Out-of-the-money options only</span></label></div>`;
    if (!d.available) { $("view").innerHTML = panel(`Volatility surface, ${S.u}`, m, ctl + note(d.note + " Increase MAX_DTE or STRIKE_WINDOW in .env, or wait until the market is open and quotes fill in.", true) + `<p class="dim">${cleanNote(j.cleaning)}</p>`); }
    else {
      const wantHeat = S.svview !== "3d", want3d = S.svview !== "heat";
      $("view").innerHTML = panel(`Volatility surface, ${S.u}`, m, ctl + (want3d ? `<div id="c1" class="chart" style="height:560px"></div>` : "") + (wantHeat ? `<div id="c2" class="chart" style="height:520px"></div>` : "") +
        `<p class="dim">${esc(d.note)} Colors run from low IV (purple) to high IV (red). The walls show the IV term structure at five strikes (left) and the skew at five expiries (back). ${cleanNote(j.cleaning)}</p>`);
      const sp = m.spot, X = S.svx === "strike" ? d.strikes : d.strikes.map(k => k / sp), Z = d.z, all = Z.flat().filter(v => v != null), lo = Math.min(...all), hi = Math.max(...all), nz = v => (v - lo) / ((hi - lo) || 1);
      if (want3d) {
        const tr = [{ type: "surface", x: X, y: d.dte, z: Z, colorscale: RCS, cmin: lo, cmax: hi, connectgaps: true, hovertemplate: "X %{x}<br>%{y:.1f} days<br>IV %{z:.2f}%<extra></extra>", colorbar: { thickness: 14, len: .7, title: { text: "IV %" } } }];
        pickIdx(X.length, 5).forEach(ki => { const y = [], z = []; d.dte.forEach((t, di) => { if (Z[di][ki] != null) { y.push(t); z.push(Z[di][ki]); } });
          if (z.length > 1) tr.push({ type: "scatter3d", mode: "lines", x: y.map(() => X[0]), y, z, line: { width: 4, color: rgbAt(nz(z.reduce((a, b) => a + b, 0) / z.length)) }, hoverinfo: "skip", showlegend: false }); });
        pickIdx(d.dte.length, 5).forEach(di => { const x = [], z = []; X.forEach((k, ki) => { if (Z[di][ki] != null) { x.push(k); z.push(Z[di][ki]); } });
          if (z.length > 1) tr.push({ type: "scatter3d", mode: "lines", x, y: x.map(() => d.dte[d.dte.length - 1]), z, line: { width: 4, color: rgbAt(nz(z.reduce((a, b) => a + b, 0) / z.length)) }, hoverinfo: "skip", showlegend: false }); });
        const ax = t => ({ title: { text: t, font: { color: "#ddd" } }, color: "#ddd", gridcolor: "#4a4a4a", backgroundcolor: "#000", showbackground: true });
        plot("c1", tr, { paper_bgcolor: "#000", font: { color: "#ddd" }, margin: { l: 0, r: 0, t: 0, b: 0 }, scene: { xaxis: ax(S.svx === "strike" ? "Strike" : "Strike / spot"), yaxis: ax("Days to expiry"), zaxis: ax("IV %"), aspectmode: "manual", aspectratio: { x: 1.3, y: 1, z: .7 }, camera: { eye: { x: 1.55, y: -1.75, z: .85 } } } });
      }
      if (wantHeat) plot("c2", [{ type: "heatmap", x: X, y: d.expiries.map((e, i) => `${e} (${fmt(d.dte[i], 1)}d)`), z: Z, colorscale: RCS, zmin: lo, zmax: hi, xgap: 1, ygap: 1, hovertemplate: "Strike/ratio %{x}<br>%{y}<br>IV %{z:.2f}%<extra></extra>", colorbar: { thickness: 14, title: { text: "IV %" } } }],
        LAY("IV heatmap (rows are expirations)", { xaxis: { title: S.svx === "strike" ? "Strike" : "Strike / spot", gridcolor: "#1E2840", tickformat: S.svx === "strike" ? ",d" : ".3f" }, yaxis: { type: "category", autorange: "reversed", gridcolor: "#1E2840" }, margin: { l: 150, r: 20, t: 44, b: 48 } }));
    }
    $("svview").value = S.svview; $("svx").value = S.svx;
    $("svview").onchange = () => { S.svview = $("svview").value; render(); }; $("svx").onchange = () => { S.svx = $("svx").value; render(); }; $("svotm").onchange = () => { S.svotm = $("svotm").checked; render(); };
  },
  async move() { await R.moveOne(); await movesTop(); },
  async moveOne() {
    const j = await api("/analytics/expected-move", { underlying: S.u, expiration: exps() === "all" ? "" : exps().split(",")[0] }), d = j.data, a = j.actual;
    const actual = a.available ? `<h3>Actual move versus expected</h3><div class="grid">
      <div class="card">Move since ${et(a.reference_time)}<b>${fmt(a.move_points, 2)} pts</b>${fmt(a.move_pct * 100, 2)}% from ${fmt(a.reference_price, 2)} (${a.observations} observations)</div>
      <div class="card">Expected move<b>${fmt(a.expected_move, 2)}</b>from the options</div>
      <div class="card">Used so far<b>${a.fraction_of_expected == null ? "-" : fmt(a.fraction_of_expected * 100, 0) + "%"}</b>of the expected move</div>
      ${a.futures ? `<div class="card">${esc(a.futures.root)} (typed-in prices)<b>${fmt(a.futures.move_points, 1)} pts</b>${fmt(a.futures.first, 2)} to ${fmt(a.futures.last, 2)}</div>` : ""}</div>
      <div style="background:#0b0d10;border:1px solid var(--line);border-radius:6px;height:12px;margin:10px 0"><div style="width:${Math.min(100, (a.fraction_of_expected || 0) * 100)}%;height:100%;background:var(--acc);border-radius:6px"></div></div>${note(a.note)}`
      : `<h3>Actual move versus expected</h3>${note(a.note)}`;
    $("view").innerHTML = panel(`Expected move, ${S.u}`, j.meta, !d.available ? note(d.note, true) : `<div class="grid">
      <div class="card">Reference price<b>${fmt(d.reference_price, 2)}</b></div><div class="card">Expiry<b>${d.expiry}</b>${fmt(d.horizon_days, 2)} days</div>
      ${d.straddle ? `<div class="card">ATM straddle (strike ${fmt(d.straddle.strike, 2)})<b>+/- ${fmt(d.straddle.price, 2)}</b>${fmt(d.straddle.lower, 2)} to ${fmt(d.straddle.upper, 2)}</div>` : ""}
      ${d.iv_1sd ? `<div class="card">One std. dev. from ATM IV ${fmt(d.iv_1sd.atm_iv * 100, 1)}%<b>+/- ${fmt(d.iv_1sd.move, 2)}</b>${fmt(d.iv_1sd.lower, 2)} to ${fmt(d.iv_1sd.upper, 2)}</div>` : ""}</div>
      ${note(d.note + " " + j.note)}<p class="dim">Straddle = call mid + put mid at the strike nearest spot. One std. dev. = spot x ATM IV x sqrt(time to expiry). Values are in ${esc(S.u)} units.</p>${actual}`);
  },
  async delta() {
    const j = await api("/analytics/delta-exposure", base()), d = j.data, pr = d.profile;
    $("view").innerHTML = panel(`Modeled delta exposure, ${S.u}`, j.meta, `<div id="c1" class="chart"></div>${note(d.note)}
      <p class="dim">Formula: ${esc(d.formula)}. Units: ${esc(d.units)}. Total: ${big(d.total)}. Contracts: ${d.contracts_used.provider} provider delta, ${d.contracts_used.model} modeled.</p>
      ${pr.available ? `<div id="c2" class="chart"></div><p class="dim">Profile: ${esc(pr.method)}. ${pr.contracts_used} contracts. Same sign scenario as above (${esc(pr.convention)}).</p>` : note(pr.note)}`);
    plot("c1", [{ type: "bar", x: d.strikes.map(s => s.strike), y: d.strikes.map(s => s.delta_exposure), marker: { color: d.strikes.map(s => s.delta_exposure >= 0 ? "#2f8bf5" : "#ff7a2e") } }],
      LAY("Delta exposure by strike", { shapes: [{ type: "line", xref: "x", yref: "paper", x0: j.meta.spot, x1: j.meta.spot, y0: 0, y1: 1, line: { color: "#fff", dash: "dot" } }] }));
    if (pr.available) plot("c2", [{ type: "scatter", mode: "lines", x: pr.grid.map(g => g.price), y: pr.grid.map(g => g.total_delta), line: { color: "#2f8bf5", width: 2.5 }, name: "Total modeled delta" }],
      LAY("Total modeled delta if price were here", { shapes: [{ type: "line", xref: "x", yref: "paper", x0: j.meta.spot, x1: j.meta.spot, y0: 0, y1: 1, line: { color: "#fff", dash: "dot" } }], xaxis: { title: "Hypothetical price", gridcolor: "#1E2840" } }));
  },
  async bias() {
    const j = await api("/analytics/bias", { underlying: S.u, convention: $("conv").value }), d = j.data, m = j.meta, L = d.levels, em = L.expected_move;
    const col = d.verdict.startsWith("Leans bull") ? "#3fb96a" : d.verdict.startsWith("Leans bear") ? "#e5534b" : "#8a8f98", cf = d.confidence;
    const rows = d.signals.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.reading)}</td><td style="color:${x.scored ? leanCol(x.lean) : "#8a8f98"};font-weight:600">${x.scored ? leanTxt(x.lean) : "Info only"}</td><td class="dim">${esc(x.why)}</td></tr>`).join("");
    $("view").innerHTML = panel(`Daily bias, ${S.u}`, m, `
      <div class="msg" style="border-color:${col};background:#0f1318"><b style="font-size:22px;color:${col}">${esc(d.verdict)}</b>
        <span class="dim"> score ${d.score > 0 ? "+" : ""}${d.score} from ${d.scored_signals} scored signals. Confidence in the read: <b>${esc(cf.label)}</b> (${cf.points} of ${cf.of}${cf.reasons.length ? "; " + esc(cf.reasons.join(", ")) : ""}).</span>
        <br>${esc(d.day_type.label)}. <span class="dim">${esc(d.day_type.why)}</span></div>
      <div class="grid"><div class="card">Price<b>${fmt(L.spot, 2)}</b></div><div class="card">Gamma flip<b>${L.flip == null ? "none" : fmt(L.flip, 2)}</b></div>
        <div class="card">Call wall<b>${L.call_wall == null ? "none" : fmt(L.call_wall, 2)}</b>by ${esc(L.walls_basis)}</div><div class="card">Put wall<b>${L.put_wall == null ? "none" : fmt(L.put_wall, 2)}</b>by ${esc(L.walls_basis)}</div>
        <div class="card">Expected move range<b>${em ? fmt(em.low, 0) + " to " + fmt(em.high, 0) : "n/a"}</b>${em ? esc(em.method) : ""}</div></div>
      <h3>Signals</h3><div class="scroll"><table><tr><th>Signal</th><th>Reading</th><th>Lean</th><th>How to read it</th></tr>${rows}</table></div>
      <h3>What would change the view</h3><ul>${d.what_would_change.map(x => `<li>${esc(x)}</li>`).join("") || "<li class='dim'>Not enough levels yet.</li>"}</ul>
      <h3>Read this with care</h3><ul class="dim">${d.cautions.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`);
  },
  async regime() {
    const j = await api("/analytics/regime", { underlying: S.u, convention: $("conv").value }), d = j.data, m = j.meta, c = regCol(d.label), off = j.futures_offset, root = j.futures_root;
    const lean = x => !x.available ? ["Not available", "#8a8f98"] : !x.scored ? ["Info", "#8a8f98"] : x.lean >= 2 ? ["Calm", "#3fb96a"] : x.lean === 1 ? ["Leans calm", "#3fb96a"] : x.lean === 0 ? ["Neutral", "#8a8f98"] : x.lean === -1 ? ["Leans unstable", "#e5534b"] : ["Unstable", "#e5534b"];
    const rows = d.dimensions.map(x => { const [t, k] = lean(x); return `<tr><td><b>${esc(x.name)}</b></td><td>${esc(x.reading)}</td><td style="color:${k};font-weight:600;white-space:nowrap">${t}</td><td class="dim">${esc(x.why)}</td></tr>`; }).join("");
    const g = d.gamma;
    $("view").innerHTML = panel(`Market regime, ${S.u}`, m, `
      <div class="msg" style="border-color:${c};background:#0f1318"><b style="font-size:1.7em;color:${c}">${esc(d.label)}</b>
        <span class="dim"> confidence ${esc(d.confidence)}; score ${d.total > 0 ? "+" : ""}${d.total} from ${d.dimensions_available} measures</span><p style="margin:6px 0 0">${esc(d.meaning)}</p></div>
      ${d.event_today_high ? note("A high-importance event is scheduled today. It can break any regime.") : ""}
      ${g ? `<div class="grid"><div class="card">Gamma flip<b>${fmt(g.flip, 0)}</b>${off != null ? `${esc(root)} about ${fmt(g.flip + off, 0)}` : ""}</div>
        <div class="card">Price vs flip<b>${g.distance_points > 0 ? "+" : ""}${fmt(g.distance_points, 0)} pts</b>${fmt(g.distance_pct, 2)}%${g.in_expected_moves != null ? `, ${fmt(g.in_expected_moves, 1)} expected moves` : ""}</div>
        <div class="card">3-week IV<b>${d.iv.mid != null ? fmt(d.iv.mid * 100, 1) + "%" : "-"}</b>nearest expiry past today: ${d.iv.front != null ? fmt(d.iv.front * 100, 1) + "%" : "-"}</div></div>` : ""}
      <h3>The measures</h3><div class="scroll"><table><tr><th>Measure</th><th>Reading</th><th>Lean</th><th>Why it counts</th></tr>${rows}</table></div>
      <h3>Where price sits</h3>${d.notes.map(n => `<p>${esc(n)}</p>`).join("")}
      <h3>What would change it</h3><ul>${d.what_would_change.map(n => `<li>${esc(n)}</li>`).join("")}</ul>
      <details class="adv" data-k="rg-rule"><summary>How the label is decided</summary><div class="body"><pre style="white-space:pre-wrap;font:inherit" class="dim">${esc(d.rule)}</pre></div></details>
      <p class="hint">${esc(d.caution)} History stored: ${d.history_sessions.iv_mid} sessions of 3-week volatility, ${d.history_sessions.skew_25d} of skew.</p>`);
  },
  async overview() {
    const j = await api("/analytics/bias-overview", { convention: $("conv").value });
    const colOf = l => l === 1 ? "#3fb96a" : l === -1 ? "#e5534b" : "#8a8f98";
    const rng = (z, off) => z ? `${fmt(z.low, 0)} to ${fmt(z.high, 0)}${off != null ? ` <span class="dim">(${fmt(z.low + off, 0)} to ${fmt(z.high + off, 0)})</span>` : ""}` : '<span class="dim">none found</span>';
    const cards = j.rows.map(r => {
      const head = `<b style="font-size:17px">${esc(r.underlying)}${r.futures_root ? ` <span class="dim" style="font-weight:400">tracks ${esc(r.futures_root)}</span>` : ""}</b>`;
      if (!r.available) return `<div class="card">${head}<span class="dim">${esc(r.reason || "No data yet.")}</span></div>`;
      const off = r.futures_offset, c = colOf(r.lean), em = r.expected_move, z = r.zones;
      return `<div class="card" style="border-left:4px solid ${c}">${head}
        <span style="color:${c};font-size:18px;font-weight:700">${esc(r.verdict)}</span> <span class="dim">score ${r.score > 0 ? "+" : ""}${r.score}, confidence ${esc(r.confidence)}</span>
        <div style="margin:8px 0;line-height:1.7">
          <span class="dim">Regime</span> <b style="display:inline;font-size:14px;color:${regCol(r.regime.label)}">${esc(r.regime.label)}</b> <span class="dim">(${esc(r.regime.confidence)} confidence)</span><br>
          Price <b style="display:inline;font-size:14px">${fmt(r.spot, 2)}</b>${off != null ? ` <span class="dim">(${esc(r.futures_root)} about ${fmt(r.spot + off, 1)})</span>` : ""}<br>
          ${esc(r.day_type)}${r.flip != null ? ` <span class="dim">(gamma flip ${fmt(r.flip, 0)}, price ${r.above_flip ? "above" : "below"})</span>` : ""}<br>
          <span style="color:#3fb96a">Call wall zone</span> ${rng(z.call, off)}<br><span style="color:#e5534b">Put wall zone</span> ${rng(z.put, off)}<br>
          <span style="color:#2f8bf5">Positive GEX zone</span> ${rng(z.positive, off)}<br><span style="color:#a371f7">Negative GEX zone</span> ${rng(z.negative, off)}<br>
          <span style="color:#ff9f43">Call OI zone</span> ${rng(z.oi_call, off)}<br><span style="color:#d9480f">Put OI zone</span> ${rng(z.oi_put, off)}<br>
          <span style="color:#2ec4b6">Call volume zone</span> ${rng(z.volume_call, off)}<br><span style="color:#f06292">Put volume zone</span> ${rng(z.volume_put, off)}<br>
          ${em ? `Expected move ${fmt(em.low, 0)} to ${fmt(em.high, 0)}<br>` : ""}
          <span class="badge ${esc(r.data_status)}">${esc(r.data_status.replace(/_/g, " "))}</span> <span class="dim">${et(r.source_timestamp)}</span></div>
        <button data-open="${esc(r.underlying)}">Open full daily bias</button></div>`;
    }).join("");
    $("view").innerHTML = `<div class="panel"><h2>Market overview: daily bias for every symbol</h2>
      <div class="msg"><b>${esc(j.summary)}</b>${j.cross ? " " + esc(j.cross) : ""}</div>
      ${j.groups.length ? `<ul>${j.groups.map(g => `<li style="color:${g.state === "disagree" ? "#e6b422" : "inherit"}">${esc(g.text)}</li>`).join("")}</ul>` : ""}
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">${cards}</div>
      ${note(j.note)}<p class="dim">Numbers in brackets are ${"futures"} estimates from the basis you saved on the Levels tab (index symbols only). The market overview follows the Dealer sign scenario box at the top.</p></div>`;
    document.querySelectorAll("[data-open]").forEach(b => b.onclick = async () => {
      S.u = b.dataset.open; $("u").value = S.u; await loadExps(); S.tab = "bias";
      $("tabs").querySelectorAll("[data-t]").forEach(x => x.classList.toggle("on", x.dataset.t === "bias")); render();
    });
  },
  async sheet() {
    const [lv, b, vol] = await Promise.all([api("/analytics/levels", { underlying: S.u, convention: $("conv").value, method: $("method").value, top: S.lvtop, by_expiry: S.lvexp, mid: S.lvmid, moves: S.lvmov, ...selParams() }),
      api("/analytics/bias", { underlying: S.u, convention: $("conv").value }), api("/analytics/volume", { underlying: S.u })]);
    const rgj = await api("/analytics/regime", { underlying: S.u, convention: $("conv").value }).catch(() => null);
    const evs = (await api("/events", { days: 3 })).events, m = lv.meta, d = b.data, root = lv.mapping.futures_root, mapped = (lv.selection.mode !== "all" ? lv.zones : lv.levels).some(x => x.mapped && x.mapped.mapped != null);
    const col = d.verdict.startsWith("Leans bull") ? "#3fb96a" : d.verdict.startsWith("Leans bear") ? "#e5534b" : "#8a8f98";
    const rows = (lv.selection.mode !== "all" ? lv.zones : lv.levels).slice().sort((a, c) => c.value - a.value).map(x => {
      const nq = x.mapped && x.mapped.mapped != null ? x.mapped.mapped : null, dist = x.value - m.spot;
      return `<tr><td>${esc(x.label)}</td><td class="num">${fmt(x.value, 2)}</td><td class="num">${nq == null ? "-" : `<b>${fmt(nq, 1)}</b>`}</td><td class="num" style="color:${dist > 0 ? "#3fb96a" : "#e5534b"}">${dist > 0 ? "+" : ""}${fmt(dist, 1)}</td><td>${x.zone ? "zone of " + x.inputs.members.length : esc(x.category.replace(/_/g, " "))}</td><td class="rel-${x.reliability}">${x.reliability}</td></tr>`;
    }).join("");
    const unusual = (vol.unusual_volume && vol.unusual_volume.flagged) || [];
    $("view").innerHTML = `<div class="panel sheet"><div class="noprint" style="float:right"><button class="go" id="prn">Print / save as PDF</button></div>
      <h1>Pre-market sheet: ${esc(S.u)}${root ? " to " + esc(root) : ""}</h1>
      <div class="metabar"><span>Source: <b>${esc(m.provider)}</b></span><span>Data time: ${et(m.source_timestamp)}</span><span>Status: <span class="badge ${esc(m.data_status)}">${esc(m.data_status.replace(/_/g, " "))}</span></span><span>Printed ${new Date().toLocaleString("en-US", { timeZone: "America/New_York" })} ET</span></div>
      <div class="msg" style="border-color:${col}"><span class="big" style="color:${col}">${esc(d.verdict)}</span> (confidence ${esc(d.confidence.label)}). ${esc(d.day_type.label)}. <span class="dim">${esc(d.day_type.why)}</span></div>
      ${rgj ? `<p><b>Regime:</b> <b style="color:${regCol(rgj.data.label)}">${esc(rgj.data.label)}</b> (confidence ${esc(rgj.data.confidence)}). <span class="dim">${esc(rgj.data.meaning)}</span></p>` : ""}
      <p><b>Scheduled events (next 3 days):</b> ${evs.length ? evs.map(e => `${e.days_away === 0 ? "today" : e.days_away === 1 ? "tomorrow" : "in " + e.days_away + " days"}${e.time ? " " + e.time + " ET" : ""} ${esc(e.name)} (${esc(e.importance)})`).join("; ") : "none listed"}</p>
      <h3>Levels, highest first (${mapped ? esc(root) + " estimates" : esc(S.u) + " units; type a basis on the Levels tab for " + esc(root || "futures")})</h3>
      <table><tr><th>Level</th><th>${esc(S.u)}</th><th>${esc(root || "Futures")} estimate</th><th>vs price (${fmt(m.spot, 2)})</th><th>Type</th><th>Reliability</th></tr>${rows || "<tr><td colspan=6>No levels</td></tr>"}</table>
      ${d.levels.expected_move ? `<p><b>Expected move:</b> ${fmt(d.levels.expected_move.low, 0)} to ${fmt(d.levels.expected_move.high, 0)} (${esc(S.u)} units, ${esc(d.levels.expected_move.method)}). It is a statistical estimate, not a limit.</p>` : ""}
      <p><b>Unusual volume strikes:</b> ${unusual.length ? unusual.slice(0, 6).map(f => fmt(f.strike, 0) + " (" + fmt(f.volume) + ")").join(", ") : "none flagged"}</p>
      <h3>Signals</h3><table><tr><th>Signal</th><th>Reading</th><th>Lean</th></tr>${d.signals.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.reading)}</td><td style="color:${x.scored ? leanCol(x.lean) : "#8a8f98"}">${x.scored ? leanTxt(x.lean) : "Info"}</td></tr>`).join("")}</table>
      <h3>If price...</h3><ul>${d.what_would_change.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
      <p class="dim">${esc(d.cautions.join(" "))} ${esc(lv.note)}</p></div>`;
    $("prn").onclick = () => window.print();
  },
  async react() {
    const j = await api("/analytics/reactions", { underlying: S.u }), pc = v => v == null ? "-" : fmt(v * 100, 0) + "%";
    const recent = j.sessions.flatMap(s => s.touches.map(t => Object.assign({ date: s.date }, t))).sort((a, c) => (c.time || "").localeCompare(a.time || "")).slice(0, 30);
    $("view").innerHTML = `<div class="panel"><h2>Level reactions, ${esc(S.u)}</h2>
      ${j.total_touches ? "" : note("No level touches recorded yet. The app keeps the first set of levels each session and compares them with the prices it observes, so this fills in over days of running.")}
      <h3>Summary by level type (${j.sessions.length} session${j.sessions.length === 1 ? "" : "s"} stored, ${j.total_touches} touches)</h3>
      <table><tr><th>Level type</th><th>Touches</th><th>Held after 15 min</th><th>Held after 30 min</th><th>Enough data?</th></tr>
      ${j.summary.map(r => `<tr><td>${esc(r.category.replace(/_/g, " "))}</td><td class="num">${r.touches}</td><td class="num">${pc(r.held_pct_15)} of ${r.measured_15}</td><td class="num">${pc(r.held_pct_30)} of ${r.measured_30}</td><td>${r.enough_data ? "10+ touches" : '<span class="dim">too few to conclude</span>'}</td></tr>`).join("") || "<tr><td colspan=5 class='dim'>Nothing yet</td></tr>"}</table>
      <h3>Recent touches</h3><div class="scroll"><table><tr><th>Date</th><th>Time (ET)</th><th>Level</th><th>Price</th><th>Approach</th><th>After 15 min</th><th>After 30 min</th></tr>
      ${recent.map(t => `<tr><td>${t.date}</td><td>${et(t.time).replace(/^[A-Za-z]+ \d+, /, "")}</td><td>${esc(t.label)}</td><td class="num">${fmt(t.level, 2)}</td><td>${t.approach}</td>
        <td>${t.held_15 == null ? "-" : t.held_15 ? "held" : "broke"} <span class="dim">${t.move_15 == null ? "" : (t.move_15 > 0 ? "+" : "") + fmt(t.move_15, 1)}</span></td><td>${t.held_30 == null ? "-" : t.held_30 ? "held" : "broke"} <span class="dim">${t.move_30 == null ? "" : (t.move_30 > 0 ? "+" : "") + fmt(t.move_30, 1)}</span></td></tr>`).join("") || "<tr><td colspan=7 class='dim'>None</td></tr>"}</table></div>
      <p class="dim">${esc(j.method)} Tolerance: ${j.tolerance_pct}% of the level.</p>${note(j.note)}</div>`;
  },
  async events() {
    const j = await api("/events", { days: 400 }), today = etStamp(new Date().toISOString()).slice(0, 10);
    $("view").innerHTML = `<div class="panel"><h2>Scheduled events</h2>${note("Big releases and expirations can move price far more than the options implied. You maintain this list. The starter entries came from published Fed and BLS calendars and expiration rules; check them against the official sites before relying on them.")}
      <div class="row"><label>Date<input id="ev_d" type="date" value="${today}"></label><label>Time (ET, optional)<input id="ev_t" size="6" placeholder="08:30"></label>
        <label>Name<input id="ev_n" size="26" placeholder="e.g. FOMC rate decision"></label><label>Importance<select id="ev_i"><option>high</option><option>medium</option><option>low</option></select></label>
        <button class="go" id="ev_add">Add event</button></div>
      <table><tr><th>Date</th><th>Time (ET)</th><th>Event</th><th>Importance</th><th>When</th><th></th></tr>
      ${j.events.map(e => `<tr><td>${e.date}</td><td>${esc(e.time || "all day")}</td><td>${esc(e.name)}${e.note ? ` <span class="dim">${esc(e.note)}</span>` : ""}</td><td><span class="badge ${e.importance === "high" ? "stale" : e.importance === "medium" ? "premarket" : ""}">${e.importance}</span></td>
        <td>${e.days_away === 0 ? "<b>today</b>" : e.days_away === 1 ? "tomorrow" : "in " + e.days_away + " days"}</td><td><button data-evdel="${e.id}">Remove</button></td></tr>`).join("") || "<tr><td colspan=6 class='dim'>No upcoming events. Add some above.</td></tr>"}</table></div>`;
    $("ev_add").onclick = async () => {
      const r = await fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date: $("ev_d").value, time: $("ev_t").value.trim(), name: $("ev_n").value, importance: $("ev_i").value }) });
      if (!r.ok) { const d = (await r.json()).detail; return alert("Could not add: " + (typeof d === "string" ? d : "check the fields")); } render();
    };
    document.querySelectorAll("[data-evdel]").forEach(b => b.onclick = async () => { await fetch("/api/events/" + b.dataset.evdel, { method: "DELETE" }); render(); });
  },
  async flow() { const j = await api("/options/flow"); $("view").innerHTML = `<div class="panel"><h2>Options flow</h2>${note(j.reason, true)}</div>`; },
  async history() { await R.historyMain(); await historyLevels(); },
  async historyMain() {
    const name = $("hm") ? $("hm").value : "total_net_gex";
    const [h, sn] = await Promise.all([api("/history/metric", { underlying: S.u, name }), api("/history/snapshots", { underlying: S.u, limit: 20 })]);
    $("view").innerHTML = `<div class="panel"><h2>History for ${esc(S.u)}</h2><div class="row"><label>Metric<select id="hm">${["total_net_gex", "gamma_flip", "atm_iv_front", "expected_move_straddle", "pc_ratio_volume", "pc_ratio_oi"].map(n => `<option>${n}</option>`).join("")}</select></label></div>
      <div id="c1" class="chart"></div>${h.points.length < 2 ? note("Not enough stored observations yet. History builds up while the app runs.") : ""}
      <h3>Stored snapshots (newest first)</h3><div class="scroll"><table><tr><th>ID</th><th>Retrieved</th><th>Source time</th><th>Spot</th><th>Contracts</th></tr>${sn.snapshots.map(s => `<tr><td>${s.id}</td><td>${et(s.retrieved_at)}</td><td>${et(s.source_ts)}</td><td class="num">${fmt(s.spot, 2)}</td><td class="num">${s.n_contracts}</td></tr>`).join("")}</table></div></div>`;
    $("hm").value = name; $("hm").onchange = render;
    plot("c1", [{ type: "scatter", mode: "lines+markers", x: h.points.map(p => p.calculated_at), y: h.points.map(p => p.value), line: { color: "#2f8bf5" } }], LAY(name, { yaxis: { gridcolor: "#1E2840", tickformat: name === "total_net_gex" ? ".3s" : undefined } }));
  },
  async status() {
    const s = await api("/status");
    const rows = Object.entries(s.underlyings).map(([u, v]) => `<tr><td>${esc(u)}</td><td><span class="badge ${esc(v.data_status)}">${esc(v.data_status.replace(/_/g, " "))}</span></td><td>${et(v.snapshot_source_timestamp)}</td><td>${et(v.last_attempt)}</td><td>${et(v.last_success)}</td><td>${et(v.last_new_data)}</td><td>${v.consecutive_failures}</td><td>${v.last_error ? esc(v.last_error.kind + ": " + v.last_error.message) : ""}</td></tr>`).join("");
    $("view").innerHTML = `<div class="panel"><h2>System status</h2><p>Data sources: ${s.available_sources.map(n => `<b>${esc(n.label)}</b> ${n.enabled ? '<span class="badge ok">on</span>' : `<span class="badge unavailable">off</span> <span class="dim">${esc(n.reason)}</span>`}`).join(" &nbsp; ")}. Showing: <b>${esc(s.source)}</b>.</p><p>Provider: <b>${esc(s.provider)}</b>. ${s.requires_key ? `API key configured: <b>${s.api_key_configured ? "yes" : "NO"}</b>. ` : "No API key needed for this provider. "}Data timing: <b>${esc(s.options_plan)}</b>. Market: <span class="badge ${esc(s.market_state)}">${esc(s.market_state)}</span> (${esc(s.now_et)}). Next open: ${et(s.next_open_et)}. Polling every ${s.poll_seconds}s (slower when closed).</p>
      <table><tr><th>Underlying</th><th>Data</th><th>Source time</th><th>Last attempt</th><th>Last success</th><th>Last new data</th><th>Failures</th><th>Last error</th></tr>${rows}</table>
      <h3>Recent provider errors</h3><table><tr><th>Time</th><th>Underlying</th><th>Kind</th><th>Message</th></tr>${s.recent_errors.map(e => `<tr><td>${et(e.at)}</td><td>${esc(e.underlying)}</td><td>${esc(e.kind)}</td><td>${esc(e.message)}</td></tr>`).join("") || "<tr><td colspan=4>None</td></tr>"}</table></div>`;
  },
};

async function bars(path, title, ytitle, extra) {
  const j = await api(path, base()), d = j.data, K = d.strikes.map(s => s.strike);
  $("view").innerHTML = panel(`${title}, ${S.u}`, j.meta, `<div id="c1" class="chart"></div>${extra(d, j)}
    <div class="grid"><div class="card">Calls<b>${fmt(d.total_calls)}</b></div><div class="card">Puts<b>${fmt(d.total_puts)}</b></div><div class="card">Put/call ratio<b>${d.put_call_ratio == null ? "-" : fmt(d.put_call_ratio, 2)}</b></div></div>
    <h3>Largest concentrations</h3><table><tr><th>Strike</th><th>Calls</th><th>Puts</th><th>Share of total</th></tr>${d.top.map(t => `<tr><td>${fmt(t.strike, 2)}</td><td class="num">${fmt(t.call)}</td><td class="num">${fmt(t.put)}</td><td class="num">${fmt(t.share_of_total * 100, 1)}%</td></tr>`).join("")}</table><p class="dim">${esc(d.note)}</p>`);
  plot("c1", [{ type: "bar", x: K, y: d.strikes.map(s => s.call), name: "Calls", marker: { color: "#3fb96a" } }, { type: "bar", x: K, y: d.strikes.map(s => s.put), name: "Puts", marker: { color: "#e5534b" } }],
    LAY(title, { barmode: "group", yaxis: { title: ytitle, gridcolor: "#1E2840" }, shapes: [{ type: "line", xref: "x", yref: "paper", x0: j.meta.spot, x1: j.meta.spot, y0: 0, y1: 1, line: { color: "#fff", dash: "dot" } }] }));
}

async function movesTop() {
  const mv = await api("/analytics/moves", { underlying: S.u, n: 6 }), m = mv.meta, sp = m.spot, root = mv.futures_root, fx = mv.basis != null;
  const lv = x => x == null ? "-" : fmt(x, 0);
  const ev = r => r.events.length ? r.events.map(e => `<span class="badge ${e.importance === "high" ? "stale" : "premarket"}">${esc(e.name)} ${e.date.slice(5)}</span>`).join(" ") : '<span class="dim">none listed</span>';
  const cell = (r, k, dir, col) => { const l = r[k + "_levels"]; return `<td class="num" style="color:${col}">${l ? lv(l[dir]) : "-"}${fx && l ? ` <span class="dim">(${lv(l[dir + "_futures"])})</span>` : ""}</td>`; };
  const rows = mv.rows.map(r => `<tr><td>${r.expiry.slice(5)}</td><td class="num">${fmt(r.days, 1)}</td><td class="num">${r.atm_iv == null ? "-" : fmt(r.atm_iv * 100, 1) + "%"}</td>
    <td class="num">${r.straddle == null ? "-" : "&plusmn; " + fmt(r.straddle, 0)}</td><td class="num">${r.sd1 == null ? "-" : "&plusmn; " + fmt(r.sd1, 0)}</td><td class="num">${r.sd2 == null ? "-" : "&plusmn; " + fmt(r.sd2, 0)}</td>
    ${cell(r, "sd1", "up", "#3fb96a")}${cell(r, "sd1", "down", "#e5534b")}${cell(r, "sd2", "up", "#3fb96a")}${cell(r, "sd2", "down", "#e5534b")}<td>${ev(r)}</td></tr>`).join("");
  const box = document.createElement("div"); box.className = "panel";
  box.innerHTML = `<h2>Expected moves up and down, ${esc(S.u)}</h2>${metaBar(m)}
    <details open><summary><b>How these are worked out (plain English)</b></summary>${(mv.explain || []).map(t => `<p>${esc(t)}</p>`).join("")}</details>
    <div id="cone" class="chart" style="height:420px"></div>
    <div class="scroll"><table><tr><th>Expiry</th><th>Days left</th><th>ATM IV</th><th>Straddle move</th><th>1 sigma move</th><th>2 sigma move</th><th>1 sigma UP</th><th>1 sigma DOWN</th><th>2 sigma UP</th><th>2 sigma DOWN</th><th>Events before expiry</th></tr>${rows}</table></div>
    <p class="dim">Levels are ${esc(S.u)} units${fx ? `; the numbers in brackets are ${esc(root)} estimates using your saved basis` : `. Save a basis on the Levels tab to also see ${esc(root || "futures")} numbers`}. 1 sigma means price finishes inside the range about 68% of the time and 2 sigma about 95%, if the usual bell-curve assumption held. ${esc(mv.note)}</p>`;
  $("view").prepend(box);
  if (!mv.rows.length) return;
  const x = mv.rows.map(r => r.days), st = r => r.straddle || 0;
  plot("cone", [
    { type: "scatter", mode: "lines", x, y: mv.rows.map(r => sp - r.sd2), name: "2 sigma down", line: { color: "#e5534b", width: 1, dash: "dot" } },
    { type: "scatter", mode: "lines", x, y: mv.rows.map(r => sp + r.sd2), name: "2 sigma up", line: { color: "#3fb96a", width: 1, dash: "dot" }, fill: "tonexty", fillcolor: "rgba(125,183,255,.08)" },
    { type: "scatter", mode: "lines", x, y: mv.rows.map(r => sp - r.sd1), name: "1 sigma down", line: { color: "#e5534b", width: 2 } },
    { type: "scatter", mode: "lines", x, y: mv.rows.map(r => sp + r.sd1), name: "1 sigma up", line: { color: "#3fb96a", width: 2 }, fill: "tonexty", fillcolor: "rgba(125,183,255,.18)" },
    { type: "scatter", mode: "lines+markers", x, y: mv.rows.map(r => sp + st(r)), name: "straddle up", line: { color: "#7db7ff", width: 1.5, dash: "dash" }, marker: { size: 5 } },
    { type: "scatter", mode: "lines+markers", x, y: mv.rows.map(r => sp - st(r)), name: "straddle down", line: { color: "#7db7ff", width: 1.5, dash: "dash" }, marker: { size: 5 } },
    { type: "scatter", mode: "lines", x: [Math.min(...x), Math.max(...x)], y: [sp, sp], name: "price now", line: { color: "#fff", width: 1.5 } }],
    LAY("Expected-move cone: how far the options say price can travel by each expiry", { xaxis: { title: "Days until expiry", gridcolor: "#1E2840" }, yaxis: { gridcolor: "#1E2840", tickformat: ",.0f" }, legend: { orientation: "h", y: -0.25 } }));
}

async function eventsBanner() {
  try {
    const j = await api("/events", { days: 3 });
    $("evbanner").innerHTML = j.events.filter(e => e.days_away <= 1 || e.importance === "high").slice(0, 4).map(e => {
      const when = e.days_away === 0 ? "TODAY" : e.days_away === 1 ? "Tomorrow" : "In " + e.days_away + " days";
      return `<div class="msg ${e.importance === "high" ? "bad" : ""}" style="margin:0 0 8px"><b>${when}${e.time ? " " + e.time + " ET" : ""}: ${esc(e.name)}</b> <span class="dim">(${esc(e.importance)} importance). ${e.importance === "high" && e.days_away === 0 ? "Expect larger, jumpier moves than the options implied; levels can break more easily." : ""}</span></div>`;
    }).join("");
  } catch (e) { $("evbanner").innerHTML = ""; }
}

async function priceChart() {
  const lv = S.lv; if (!lv) return;
  const h = await api("/history/prices", { underlying: S.u }), sp = lv.meta.spot, root = lv.mapping.futures_root, box = document.createElement("div");
  const COL = CATCOL;
  const ticked = lv.selection.mode !== "all" ? lv.zones : lv.levels.filter(l => S.cats.has(l.category));
  const lvls = ticked;
  const H = Math.max(500, Math.min(950, 300 + lvls.length * 24));
  box.className = "panel";
  box.innerHTML = `<h2>Price this session vs key levels (${esc(S.u)} units${root ? "; the label also shows the " + esc(root) + " estimate when one is available" : ""})</h2>
    <p class="dim">The chart draws the same ${lvls.length} ${lv.selection.mode !== "all" ? "zones" : "levels"} as the table and the paste text. Change them with the <b>Show</b> menu and the level-type boxes at the top of this tab.</p>
    <div id="cpx" class="chart" style="height:${H}px"></div>
    <p class="dim">${h.points.length} price observation${h.points.length === 1 ? "" : "s"} this session. ${esc(h.note)}</p>`;
  $("view").appendChild(box);
  const t = h.points.map(p => p.t); let x0 = t.length ? new Date(t[0]) : new Date(), x1 = t.length ? new Date(t[t.length - 1]) : new Date();
  if (x1 - x0 < 3600e3) { x0 = new Date(x0 - 1800e3); x1 = new Date(+x1 + 1800e3); }
  const vals = lvls.flatMap(l => l.low != null ? [l.low, l.high] : [l.value]).concat(h.points.map(p => p.price), [sp]), lo = Math.min(...vals), hi = Math.max(...vals), pad = (hi - lo) * 0.04 || sp * 0.005;
  const top = hi + pad, bot = lo - pad, plotH = H - 70, ppu = plotH / (top - bot);
  // spread the labels out so none sit on top of another; a short leader line connects each label to its level
  const arr = lvls.slice().sort((a, b) => b.value - a.value).map(l => ({ l, pos: (top - l.value) * ppu }));
  let prev = -1e9; arr.forEach(o => { o.lab = Math.max(o.pos, prev + 14); prev = o.lab; });
  let nxt = plotH + 14; for (let i = arr.length - 1; i >= 0; i--) { arr[i].lab = Math.min(arr[i].lab, nxt - 14); nxt = arr[i].lab; }
  const short = l => l.label.replace(/High |Large |modeled |Estimated /gi, "") + " " + fmt(l.value, 0) + (l.mapped && l.mapped.mapped != null && l.mapped.status !== "invalid" ? " | " + (root || "") + " " + fmt(l.mapped.mapped, 0) : "");
  plot("cpx", [{ type: "scatter", mode: "lines+markers", x: t, y: h.points.map(p => p.price), line: { color: "#fff", width: 2 }, marker: { size: 4 }, name: S.u }],
    LAY("", { showlegend: false, margin: { l: 70, r: 360, t: 20, b: 50 }, xaxis: { type: "date", range: [x0.toISOString(), x1.toISOString()], gridcolor: "#1E2840" }, yaxis: { range: [bot, top], gridcolor: "#1E2840", tickformat: ",.0f" },
      shapes: lvls.filter(l => l.low != null).map(l => ({ type: "rect", xref: "x", yref: "y", x0: (l.first_seen && new Date(l.first_seen) > x0 ? new Date(l.first_seen) : x0).toISOString(), x1: x1.toISOString(), y0: l.low, y1: l.high, fillcolor: (COL[l.category] || "#999") + "33", line: { color: COL[l.category] || "#999", width: 1 }, layer: "below" }))
        .concat(lvls.map(l => ({ type: "line", xref: "x", yref: "y", x0: (l.first_seen && new Date(l.first_seen) > x0 ? new Date(l.first_seen) : x0).toISOString(), x1: x1.toISOString(), y0: l.value, y1: l.value, line: { color: COL[l.category] || "#999", width: 1.4, dash: l.category === "expected_move" ? "dot" : "solid" } }))),
      annotations: arr.map(o => ({ xref: "paper", yref: "y", x: 1, y: o.l.value, xanchor: "left", axref: "pixel", ayref: "pixel", ax: 16, ay: Math.round(o.lab - o.pos), showarrow: true, arrowhead: 0, arrowwidth: 0.8,
        arrowcolor: COL[o.l.category] || "#999", text: short(o.l), font: { size: 10, color: COL[o.l.category] || "#999" } })) }));
}
function etStamp(iso) {
  if (!iso) return null;
  const f = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(iso)).map(p => [p.type, p.value]));
  return `${f.year}-${f.month}-${f.day} ${f.hour}:${f.minute}`;
}
// which TradingView settings group a row belongs to (gex, oi, vol, move, flip, mine). A zone that holds the flip or your own level stays in that group.
const FAMOF = { gamma_flip: "flip", custom: "mine", expected_move: "move", expected_move_ext: "move" };
function famOf(l) {
  const cats = [l.category, ...((l.inputs && l.inputs.members) || []).map(m => m.category)];
  if (cats.includes("custom")) return "mine";
  if (cats.includes("gamma_flip")) return "flip";
  if (l.slot) return l.slot;
  const c = l.category;
  return FAMOF[c] || (c.startsWith("gex") ? "gex" : c.startsWith("oi") || c === "open_interest" ? "oi" : c.startsWith("volume") ? "vol" : c.startsWith("charm") ? "charm" : c.startsWith("vanna") ? "vanna" : c.startsWith("dex") ? "dex" : c.startsWith("new_") ? "new" : "other");
}
function indicatorText(lv, m, root) {
  const src = lv.selection.mode !== "all" ? lv.zones : lv.levels.filter(l => S.cats.has(l.category));
  const rows = src.slice().sort((a, b) => b.value - a.value).map(l => {
    const mp = l.mapped && l.mapped.mapped != null && l.mapped.status !== "invalid" ? l.mapped.mapped : l.value;
    const st = etStamp(l.first_seen), ok = l.mapped && l.mapped.mapped != null && l.mapped.status !== "invalid";
    const base = `${mp.toFixed(2)}, ${l.label.replace(/[,"]/g, "")}, ${l.category}`, tail = `${Math.round((l.importance || 0) * 100)}, ${famOf(l)}`;
    if (l.low != null) return `${base}, ${st || ""}, ${(ok && l.mapped_low != null ? l.mapped_low : l.low).toFixed(2)}, ${(ok && l.mapped_high != null ? l.mapped_high : l.high).toFixed(2)}, ${tail}`;
    return `${base}, ${st || ""}, , , ${tail}`;
  });
  const mapped = src.some(l => l.mapped && l.mapped.mapped != null && l.mapped.status !== "invalid");
  const st = etStamp(m.source_timestamp);
  return { count: rows.length, mapped, text: `// ${S.u} levels, ${et(m.source_timestamp)}. ${mapped ? "Estimated " + root + " points" : S.u + " units (no " + root + " basis typed in yet)"}\n` + (st ? `// @start ${st}\n` : "") + rows.join("\n") };
}
function showText(title, text) {
  const box = document.createElement("div"); box.className = "panel";
  box.innerHTML = `<h2>${esc(title)}</h2><p class="dim">Select all (Ctrl+A) and copy (Ctrl+C).</p><textarea style="width:100%;height:240px;background:#0b0d10;color:#e8eaed;border:1px solid #262c34;border-radius:6px;font:12px monospace" readonly></textarea>`;
  box.querySelector("textarea").value = text; $("view").prepend(box);
}
function download(name, text) { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
const regCol = l => /^(Pinned|Calm)/.test(l) ? "#3fb96a" : /^(Trending|Leaning unstable)/.test(l) ? "#e5534b" : /^Transition/.test(l) ? "#e6b422" : "#8a8f98";
const leanTxt = l => l > 0 ? "Bullish" : l < 0 ? "Bearish" : "Neutral", leanCol = l => l > 0 ? "#3fb96a" : l < 0 ? "#e5534b" : "#8a8f98";

async function scenariosPanel() {
  const j = await api("/analytics/scenarios", { underlying: S.u }), d = j.data, box = document.createElement("div");
  box.className = "panel";
  box.innerHTML = `<h2>Scenarios side by side</h2><div class="scroll"><table><tr><th>Weighting</th><th>Gamma flip</th><th>Total modeled GEX</th><th>Biggest positive GEX strikes</th><th>Biggest negative GEX strikes</th><th>Notes</th></tr>
    ${d.rows.map(r => `<tr><td>${esc(r.label)}</td><td class="num">${r.flip == null ? "none found" : fmt(r.flip, 2)}</td><td class="num">${big(r.total_gex)}</td><td>${r.top_positive_strikes.map(k => fmt(k, 0)).join(", ") || "-"}</td><td>${r.top_negative_strikes.map(k => fmt(k, 0)).join(", ") || "-"}</td><td class="dim">${esc(r.found ? "" : r.note)}</td></tr>`).join("")}</table></div>
    ${d.flip_spread != null ? note(`The two weightings put the flip ${fmt(d.flip_spread, 1)} points (${fmt(d.flip_spread_pct * 100, 2)}%) apart. ${d.flip_spread_pct > 0.005 ? "That is a big gap, so treat the flip as a zone, not a line." : "They agree closely."}`) : ""}
    <p class="dim">${esc(d.sign_note)}</p>`;
  $("view").appendChild(box);
}

async function historyLevels() {
  const h = await api("/history/levels", { underlying: S.u }), box = document.createElement("div");
  box.className = "panel";
  box.innerHTML = `<h2>Levels through the day (${esc(h.date)})</h2><div id="chl" class="chart" style="height:420px"></div><p class="dim">${h.price.length} price observations. ${esc(h.note)}</p>`;
  $("view").appendChild(box);
  const L = [["gamma_flip", "Gamma flip", "#e6b422", "solid"], ["call_wall", "Call wall", "#3fb96a", "solid"], ["put_wall", "Put wall", "#e5534b", "solid"], ["em_high", "Move high", "#7db7ff", "dot"], ["em_low", "Move low", "#7db7ff", "dot"]];
  plot("chl", [{ type: "scatter", mode: "lines", x: h.price.map(p => p.t), y: h.price.map(p => p.price), name: "Price", line: { color: "#fff", width: 2 } }]
    .concat(L.filter(([k]) => h.levels[k].length).map(([k, n, c, d]) => ({ type: "scatter", mode: "lines+markers", marker: { size: 6 }, x: h.levels[k].map(p => p.t), y: h.levels[k].map(p => p.value), name: n, line: { color: c, width: 1.6, dash: d, shape: "hv" } }))),
    LAY("Price and levels over the session", { legend: { orientation: "h", y: -0.2 }, xaxis: { gridcolor: "#1E2840" } }));
}
async function render() {
  if (S.busy) { S.again = true; return; }                  // something changed while a refresh was running: run again right after it
  S.busy = true; $("clock").textContent = "Updating...";
  saveUI();
  try { await R[S.tab](); } catch (e) { showError(e); } finally { S.busy = false; }
  if (S.again) { S.again = false; return render(); }
  addHelp(); persistDetails(); eventsBanner();
  $("clock").textContent = "Updated " + new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
}
const AL = Object.assign({ on: false, pct: 0.1, sound: true, notify: false, cats: ["gamma_flip", "gex_concentration", "open_interest", "volume", "expected_move"] }, JSON.parse(localStorage.getItem("alerts") || "{}"));
const alerted = {};
function saveAlerts() { localStorage.setItem("alerts", JSON.stringify(AL)); $("alertbtn").textContent = "Alerts: " + (AL.on ? "on" : "off"); }
function beep() { try { const c = new (window.AudioContext || window.webkitAudioContext)(), o = c.createOscillator(), g = c.createGain(); o.connect(g); g.connect(c.destination); o.frequency.value = 880; g.gain.value = 0.15; o.start(); o.stop(c.currentTime + 0.35); } catch (e) { } }
function toast(html) {
  const d = document.createElement("div"); d.className = "toastmsg"; d.innerHTML = `<button>Close</button>${html}`; d.querySelector("button").onclick = () => d.remove(); $("toast").appendChild(d); setTimeout(() => d.remove(), 120000);
}
function drawAlertPanel() {
  const cats = [["gamma_flip", "Gamma flip"], ["gex_concentration", "GEX"], ["open_interest", "Open interest"], ["volume", "Volume"], ["expected_move", "Expected move"]];
  $("alerts").innerHTML = `<h2>Level alerts</h2><div class="row"><label><span><input type="checkbox" id="al_on" ${AL.on ? "checked" : ""}> Alerts on</span></label>
    <label>Alert when price is within (% of price)<input id="al_pct" size="6" value="${AL.pct}"></label>
    <label><span><input type="checkbox" id="al_sound" ${AL.sound ? "checked" : ""}> Sound</span></label><label><span><input type="checkbox" id="al_notify" ${AL.notify ? "checked" : ""}> Desktop notification</span></label></div>
    <div class="row">${cats.map(([k, n]) => `<label><span><input type="checkbox" data-ac="${k}" ${AL.cats.includes(k) ? "checked" : ""}> ${n}</span></label>`).join("")}</div>
    <p class="dim">Alerts only work while this page is open in a browser tab. They use the app's data, which is about 15 minutes delayed, and they pause when the market is closed or data is stale. Each level alerts at most once per 30 minutes.</p><div id="al_status" class="dim"></div>`;
  $("al_on").onchange = async () => { AL.on = $("al_on").checked; if (AL.on && AL.notify && "Notification" in window) await Notification.requestPermission(); saveAlerts(); alertTick(); };
  $("al_pct").onchange = () => { AL.pct = Math.max(0.01, parseFloat($("al_pct").value) || 0.1); saveAlerts(); };
  $("al_sound").onchange = () => { AL.sound = $("al_sound").checked; saveAlerts(); if (AL.sound) beep(); };
  $("al_notify").onchange = async () => { AL.notify = $("al_notify").checked; if (AL.notify && "Notification" in window) await Notification.requestPermission(); saveAlerts(); };
  document.querySelectorAll("[data-ac]").forEach(c => c.onchange = () => { AL.cats = [...document.querySelectorAll("[data-ac]")].filter(x => x.checked).map(x => x.dataset.ac); saveAlerts(); });
}
async function alertTick() {
  const stEl = $("al_status"), say = t => { if (stEl) stEl.textContent = t; };
  if (!AL.on || !S.u) return say(AL.on ? "" : "Alerts are off.");
  try {
    const j = await api("/analytics/levels", { underlying: S.u, ...selParams() }), spot = j.meta.spot, ds = j.meta.data_status;
    if (j.selection.mode !== "all") j.levels = j.zones;
    if (!["live", "delayed"].includes(ds)) return say(`Paused: data status is "${ds.replace(/_/g, " ")}". Alerts run while the market is open and data is updating.`);
    const near = j.levels.filter(l => AL.cats.includes(l.category) && Math.abs(l.value - spot) / spot * 100 <= AL.pct);
    say(`Watching ${j.levels.filter(l => AL.cats.includes(l.category)).length} levels. Price ${fmt(spot, 2)}. ${near.length} within ${AL.pct}%.`);
    for (const l of near) {
      const key = S.src + S.u + l.category + Math.round(l.value);
      if (alerted[key] && Date.now() - alerted[key] < 30 * 60e3) continue;
      alerted[key] = Date.now();
      const mp = l.mapped && l.mapped.mapped != null ? ` (about ${fmt(l.mapped.mapped, 1)} in ${j.mapping.futures_root})` : "", dist = l.value - spot;
      const msg = `${l.label} ${fmt(l.value, 2)}${mp} is ${fmt(Math.abs(dist), 1)} points ${dist > 0 ? "above" : "below"} price ${fmt(spot, 2)}.`;
      toast(`<b>Level alert</b><br>${esc(msg)}<br><span class="dim">Data is delayed; check the live chart.</span>`);
      if (AL.sound) beep();
      if (AL.notify && "Notification" in window && Notification.permission === "granted") new Notification("Level alert", { body: msg });
    }
  } catch (e) { say("Could not check levels right now."); }
}

async function boot() {
  const nameOf = Object.fromEntries(TABS);
  if (!nameOf[S.tab]) S.tab = "levels";
  $("tabs").innerHTML = GROUPS.map(([g, ks]) => `<div class="grp"><span class="gl">${g}</span>${ks.map(k => `<button data-t="${k}" class="${k === S.tab ? "on" : ""}">${TABICON[k] ? `<img class="ti" src="icons/${TABICON[k]}.png" alt="">` : ""}${nameOf[k]}</button>`).join("")}</div>`).join("");
  $("conv").value = S.savedConv || "standard"; if (S.savedMethod) $("method").value = S.savedMethod;
  $("zm").onclick = () => { S.zoom = Math.max(0.8, +(S.zoom - 0.1).toFixed(2)); applyZoom(); saveUI(); };
  $("zp").onclick = () => { S.zoom = Math.min(1.7, +(S.zoom + 0.1).toFixed(2)); applyZoom(); saveUI(); };
  $("tabs").onclick = e => { const bt = e.target.closest && e.target.closest("[data-t]"), t = bt && bt.dataset.t; if (!t) return; document.body.classList.remove("navopen"); S.tab = t; $("tabs").querySelectorAll("[data-t]").forEach(b => b.classList.toggle("on", b.dataset.t === t)); render(); };
  ["conv", "method", "exp"].forEach(id => $(id).onchange = render);
  $("reload").onclick = render;
  $("setbtn").onclick = () => { $("controls").hidden = !$("controls").hidden; };
  $("setclose").onclick = () => { $("controls").hidden = true; };
  $("navbtn").onclick = () => document.body.classList.toggle("navopen");
  saveAlerts(); drawAlertPanel();
  $("alertbtn").onclick = () => { const a = $("alerts"); a.style.display = a.style.display === "none" ? "block" : "none"; };
  setInterval(alertTick, 30000);
  try {
    const st0 = await api("/status"), saved = localStorage.getItem("src");
    S.src = saved && st0.available_sources.some(n => n.name === saved && n.enabled) ? saved : st0.default_source;
    $("src").innerHTML = st0.available_sources.map(n => `<option value="${n.name}" ${n.enabled ? "" : "disabled"}>${esc(n.label)}${n.enabled ? "" : " (not set up)"}</option>`).join("");
    $("src").value = S.src;
    $("src").onchange = async () => { S.src = $("src").value; localStorage.setItem("src", S.src); await useSource(); render(); };
    $("u").onchange = async () => { S.u = $("u").value; await loadExps(); render(); };
    await useSource();
  } catch (e) { return showError(e); }
  render();
  setInterval(async () => { try { setState(await api("/status")); } catch (e) { $("mstate").textContent = "backend unreachable"; $("mstate").className = "badge stale"; } if (!userBusy()) render(); }, 20000);
}
async function useSource() {
  const st = await api("/status"), us = Object.keys(st.underlyings);
  S.u = us.includes(S.u) ? S.u : us[0]; $("u").innerHTML = us.map(u => `<option value="${u}">${u.replace(/^_/, "")}</option>`).join(""); $("u").value = S.u;
  await loadExps(); setState(st);
}
async function loadExps() {
  try { const e = await api("/options/expirations", { underlying: S.u }); $("exp").innerHTML = e.expirations.map(x => `<option value="${x}">${x}</option>`).join(""); } catch (e) { $("exp").innerHTML = ""; }
}
// Desktop app only: a small bar when a new version is ready. In the browser version /api/desktop/info does not exist and nothing shows.
async function desktopTick() {
  let j; try { const r = await fetch("/api/desktop/info"); if (!r.ok) return; j = await r.json(); } catch (e) { return; }
  let bar = $("updbar");
  if (!bar) { bar = document.createElement("div"); bar.id = "updbar"; $("evbanner").before(bar); }
  const u = j.update, v = u.latest;
  const msg = u.state === "ready" ? `Version ${esc(v)} is downloaded (you have ${esc(u.current)}). It installs by itself after the market closes, or now:`
    : u.state === "available" ? `Version ${esc(v)} is available (you have ${esc(u.current)}).`
    : u.state === "downloading" ? `Downloading version ${esc(v)}... ${Math.round(u.progress * 100)}%` : "";
  bar.innerHTML = msg ? `<div class="msg" style="margin:0 0 8px;display:flex;gap:10px;align-items:center;flex-wrap:wrap"><b>${msg}</b>${["ready", "available"].includes(u.state) ? '<button class="go" id="updgo">Restart and update</button>' : ""}${u.notes ? `<details class="more"><summary>What changed</summary><span class="dim" style="white-space:pre-wrap">${esc(u.notes)}</span></details>` : ""}</div>` : "";
  const b = $("updgo");
  if (b) b.onclick = async () => { b.disabled = true; b.textContent = "Updating, the app will reopen..."; await fetch("/api/desktop/update/install", { method: "POST" }).catch(() => null); };
}
function setState(st) {
  $("mstate").textContent = "Market " + st.market_state.replace(/_/g, " "); $("mstate").className = "badge " + st.market_state;
  const x = (st.underlyings || {})[S.u];
  $("tick").innerHTML = x && x.spot != null ? `<b>${fmt(x.spot, 2)}</b><span class="sub">${esc(S.u.replace(/^_/, ""))}${x.data_status ? ", " + esc(x.data_status.replace(/_/g, " ")) : ""}</span>` : "";
}
loadUI();
boot();
desktopTick(); setInterval(desktopTick, 60000);
