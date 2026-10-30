"use strict";
// Playbook tab (1.27.0): a real trading chart (TradingView Lightweight Charts) with EVERY level near price as a zone, three plans (bullish, bearish,
// choppy) with what to do at every one of those levels (role, entry, stop, target), projected candles acting each plan out, and a
// banner with the plan that fits today. Uses the helpers in app.js (api, panel, plot, LAY, esc, fmt, S, R, saveUI, render) and
// pct, etx from more.js.

const PBC = { bullish: "#16a34a", bearish: "#dc2626", choppy: "#d97706" };
const PBCALL = { HOLD: ["#0f6e56", "#9FE1CB", "#26a69a"], CHOP: ["#854f0b", "#FAC775", "#f0a63a"], BREAK: ["#a32d2d", "#F7C1C1", "#ef5350"] };
const PBSCEN = ["bullish", "bearish", "choppy"];
const PBTITLE = { bullish: "Bullish", bearish: "Bearish", choppy: "Choppy" };

const pbA = (hex, a) => `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})`;
// colour of a plan tag: longs green, shorts red, profit-taking amber, "plan off" / "skip" grey
function pbTagCol(tag) {
  const t = (tag || "").toUpperCase();
  if (!t || t === "PLAN OFF" || t === "SKIP" || t === "RANGE BROKE") return ["#2a3142", "#9aa3b5"];
  if (t.startsWith("BUY") || t === "FADE LONG" || (t.startsWith("ADD") && t.includes(">"))) return ["#0f5f3a", "#a7f3c8"];
  if (t.startsWith("SELL") || t === "FADE SHORT" || (t.startsWith("ADD") && t.includes("<"))) return ["#7a1f1f", "#fbc4c4"];
  return ["#7a4a0b", "#fde2a7"];                                     // TP, TP1.., RUNNER, PARTIAL
}
// level filter: all, GEX only, or the majors plus every GEX level
const pbFilter = (lv, m) => lv.filter(l => m === "all" || (m === "gex" ? l.gex : l.major || l.gex));
const pbChip = tag => { const [b, f] = pbTagCol(tag); return tag ? `<span class="pbtag" style="background:${b};color:${f}">${esc(tag)}</span>` : ""; };
const pbPill = c => `<span class="pbpill" style="background:${PBCALL[c][0]};color:${PBCALL[c][1]}">${c}</span>`;
function pbTrade(tr) {
  if (!tr) return "";
  if (tr.side === "flat") return `<div class="pbtr flat">Close below/above ${fmt(tr.stop, 2)} = plan over, go flat</div>`;
  const s = tr.side === "long" ? "Buy" : "Short";
  return `<div class="pbtr ${tr.side}"><b>${s}</b> ${fmt(tr.entry, 2)} <span class="dim">stop</span> ${fmt(tr.stop, 2)}${tr.target != null ? ` <span class="dim">target</span> ${fmt(tr.target, 2)}` : ""}</div>`;
}

// ---- The chart (1.27.0): TradingView Lightweight Charts, bundled in frontend/vendor. A real trading chart: drag to pan, scroll to
// zoom, drag the price scale, crosshair. It is built once and then updated in place every refresh, so it never jumps back.
// Zones, level names and plan tags are drawn on a canvas on top of the chart that follows every pan and zoom.
const PB = { chart: null, el: null, key: null, main: null, plans: {}, lines: [], j: null, sel: null, lv: "all", theme: "dark", live: false, ov: null, tip: null, last: "" };
const PBTH = {
  dark: { bg: "#131722", text: "#b2b5be", grid: "#1c2030", border: "#2a2e39", up: "#26a69a", dn: "#ef5350", ink: "#e7ecf5", dim: "#8a93a8", chip: "rgba(19,23,34,.88)",
    call: { HOLD: "#26a69a", CHOP: "#f0a63a", BREAK: "#ef5350" }, gex: "#5aa9ff", spot: "#2962ff", proj: "rgba(255,255,255,.025)" },
  light: { bg: "#ffffff", text: "#434651", grid: "#f0f3fa", border: "#e0e3eb", up: "#089981", dn: "#f23645", ink: "#131722", dim: "#6a7187", chip: "rgba(255,255,255,.92)",
    call: { HOLD: "#089981", CHOP: "#d98a00", BREAK: "#f23645" }, gex: "#1e66d0", spot: "#2962ff", proj: "rgba(0,0,0,.025)" } };
const PBPLAN = { bullish: ["#22c55e", "#15803d"], bearish: ["#f43f5e", "#b91c1c"], choppy: ["#f59e0b", "#b45309"] };

// Times: the chart has no time zones, so each time is shifted to New York wall-clock time before it is handed over.
const PBETF = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour12: false, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const pbT = iso => { const p = {}; PBETF.formatToParts(new Date(iso)).forEach(x => p[x.type] = x.value);
  return Date.UTC(+p.year, +p.month - 1, +p.day, (+p.hour) % 24, +p.minute, +p.second) / 1000; };
const pbBars = arr => { const out = [], seen = new Set();
  arr.forEach(k => { const t = pbT(k.t); if (!seen.has(t) && k.o != null) { seen.add(t); out.push({ time: t, open: k.o, high: k.h, low: k.l, close: k.c }); } });
  return out.sort((a, b) => a.time - b.time); };
const pbHex = (hex, a) => `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})`;

function pbBuild(el, theme) {
  const T = PBTH[theme];
  const chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: T.bg }, textColor: T.text, fontFamily: "Manrope, Segoe UI, sans-serif", fontSize: 12 },
    grid: { vertLines: { color: T.grid }, horzLines: { color: T.grid } },
    crosshair: { mode: 0, vertLine: { color: T.dim, labelBackgroundColor: "#363a45" }, horzLine: { color: T.dim, labelBackgroundColor: "#363a45" } },
    rightPriceScale: { borderColor: T.border, scaleMargins: { top: 0.06, bottom: 0.06 } },
    timeScale: { borderColor: T.border, timeVisible: true, secondsVisible: false, rightOffset: 4, barSpacing: 9, minBarSpacing: 1 },
    localization: { priceFormatter: p => fmt(p, 2) },
    handleScroll: false, handleScale: false });
  const main = chart.addCandlestickSeries({ upColor: T.up, downColor: T.dn, borderVisible: false, wickUpColor: T.up, wickDownColor: T.dn,
    priceFormat: { type: "price", precision: 2, minMove: 0.25 }, priceLineColor: T.spot, priceLineStyle: 2 });
  const plans = {};
  for (const k of PBSCEN) plans[k] = chart.addCandlestickSeries({ upColor: pbHex(PBPLAN[k][0], 0.35), downColor: pbHex(PBPLAN[k][0], 0.85), borderVisible: true,
    borderUpColor: PBPLAN[k][0], borderDownColor: PBPLAN[k][0], wickUpColor: PBPLAN[k][0], wickDownColor: PBPLAN[k][0], lastValueVisible: false, priceLineVisible: false,
    priceFormat: { type: "price", precision: 2, minMove: 0.25 } });
  return { chart, main, plans };
}

// what the chart shows: candles, the plan(s) projected after the last candle, and every level as a line with a price tag
function pbFill(first) {
  const j = PB.j, T = PBTH[PB.theme], show = PB.sel === "all" ? PBSCEN : [PB.sel];
  PB.main.setData(pbBars(j.candles));
  for (const k of PBSCEN) {
    const on = show.includes(k);
    PB.plans[k].setData(on ? pbBars(j.scenarios[k].path) : []);
    PB.plans[k].applyOptions({ visible: on });
  }
  PB.lines.forEach(l => PB.main.removePriceLine(l)); PB.lines = [];
  pbFilter(j.levels, PB.lv).forEach(l => PB.lines.push(PB.main.createPriceLine({ price: l.price, color: T.call[l.call], lineWidth: l.gex || l.major ? 2 : 1,
    lineStyle: l.call === "CHOP" ? 2 : l.gex || l.major ? 0 : 1, axisLabelVisible: true, title: "" })));
  if (first) pbView("start");
}

function pbView(how) {
  const n = PB.j.candles.length, m = (PB.j.scenarios[PB.sel === "all" ? PB.j.today : PB.sel] || {}).path?.length || 0, ts = PB.chart.timeScale();
  if (how === "all") ts.fitContent();
  else if (how === "price") { ts.scrollToRealTime(); }
  else ts.setVisibleLogicalRange({ from: Math.max(0, n - Math.round(150 / Math.sqrt(PB.j.tf))), to: n + m + 3 });
  PB.main.priceScale().applyOptions({ autoScale: true });
}

// The overlay: zones, level names with the reaction we expect, plan tags, the choppy range and the projected area.
function pbOverlay(force) {
  const c = PB.ov, el = PB.el; if (!c || !PB.chart || !document.body.contains(el)) return;
  const ts = PB.chart.timeScale(), w = ts.width(), h = el.clientHeight - ts.height();
  const vr = ts.getVisibleLogicalRange(), y0 = PB.main.priceToCoordinate(PB.j.spot);
  const key = [w, h, vr && vr.from.toFixed(2), vr && vr.to.toFixed(2), y0 && y0.toFixed(1), PB.lv, PB.sel, PB.theme, PB.j.meta && PB.j.meta.as_of, PB.hover].join("|");
  if (!force && key === PB.last) return; PB.last = key;
  const dpr = window.devicePixelRatio || 1;
  if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); c.style.width = w + "px"; c.style.height = h + "px"; }
  const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
  const T = PBTH[PB.theme], j = PB.j, Y = p => PB.main.priceToCoordinate(p), L = pbFilter(j.levels, PB.lv);
  const zh = Math.max(1, (j.sigma_remaining || j.spot * 0.004) * 0.06);
  // projected area after the last real candle
  const lastT = j.candles.length ? pbT(j.candles[j.candles.length - 1].t) : null, xp = lastT != null ? ts.timeToCoordinate(lastT) : null;
  if (xp != null && xp < w) { g.fillStyle = T.proj; g.fillRect(xp, 0, w - xp, h); g.strokeStyle = T.dim; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(xp + .5, 0); g.lineTo(xp + .5, h); g.stroke(); g.setLineDash([]);
    g.font = "600 11px Manrope, Segoe UI, sans-serif"; g.fillStyle = T.dim; g.fillText(`PROJECTED · ${PBTITLE[PB.sel === "all" ? j.today : PB.sel].toUpperCase()} PLAN`, xp + 8, 16); }
  // choppy range
  const rg = j.scenarios.choppy.range;
  if ((PB.sel === "choppy" || PB.sel === "all") && rg) { const a = Y(rg.high), b = Y(rg.low); if (a != null && b != null) { g.fillStyle = pbHex(PBPLAN.choppy[0], 0.06); g.fillRect(0, a, w, b - a); } }
  // zones
  L.forEach(l => { const z = l.low != null && l.high > l.low, a = Y(z ? l.high : l.price + zh / 2), b = Y(z ? l.low : l.price - zh / 2); if (a == null || b == null) return;
    const hgt = Math.max(3, b - a), col = T.call[l.call]; g.fillStyle = pbHex(col, l.gex || l.major ? 0.17 : 0.08); g.fillRect(0, a - (hgt === 3 ? 1 : 0), w, hgt);
    if (l === PB.hover) { g.strokeStyle = col; g.lineWidth = 1.5; g.strokeRect(0.5, a, w - 1, hgt); g.lineWidth = 1; } });
  // labels: level name + what we expect (left), what the plan does (at the projected line). Important ones first; no overlaps.
  const chip = (x, y, txt, bg, fg, bold, alignRight) => { g.font = `${bold ? 700 : 600} 11px Manrope, Segoe UI, sans-serif`;
    const tw = g.measureText(txt).width + 10, xx = alignRight ? x - tw : x; g.fillStyle = bg; g.beginPath(); g.roundRect ? g.roundRect(xx, y - 9, tw, 18, 4) : g.rect(xx, y - 9, tw, 18); g.fill();
    g.fillStyle = fg; g.fillText(txt, xx + 5, y + 4); return tw; };
  const usedL = [], usedP = [], free = (arr, y) => arr.every(v => Math.abs(v - y) >= 19);
  const plan = PB.sel === "all" ? j.today : PB.sel;
  [...L].sort((a, b) => ((b.gex + b.major) - (a.gex + a.major)) || Math.abs(a.price - j.spot) - Math.abs(b.price - j.spot)).forEach(l => {
    const y = Y(l.price); if (y == null || y < 10 || y > h - 10) return;
    const col = T.call[l.call], E = l.expect || {};
    if (free(usedL, y)) { usedL.push(y); let x = 6;
      if (l.gex) x += chip(x, y, "GEX", T.gex, "#fff", true) + 3;
      x += chip(x, y, (l.name || l.label.split(" / ")[0]) + "  " + fmt(l.price, 2), T.chip, T.ink, l.gex || l.major) + 3;
      chip(x, y, E.tag || l.call, col, PB.theme === "dark" ? "#0b0e14" : "#fff", true); }
    const r = l.react && l.react[plan];
    if (r && r.tag && xp != null && xp < w - 60 && free(usedP, y)) { usedP.push(y); const [bg, fg] = pbTagCol(r.tag); chip(xp + 6, y, r.tag, bg, fg, true); }
  });
}

function pbTipShow(p) {
  const tip = PB.tip; if (!tip) return;
  if (!p || !p.point || p.point.x < 0) { tip.style.display = "none"; if (PB.hover) { PB.hover = null; pbOverlay(); } return; }
  let best = null, bd = 9;
  pbFilter(PB.j.levels, PB.lv).forEach(l => { const y = PB.main.priceToCoordinate(l.price); if (y != null && Math.abs(y - p.point.y) < bd) { bd = Math.abs(y - p.point.y); best = l; } });
  if (best !== PB.hover) { PB.hover = best; pbOverlay(); }
  if (!best) { tip.style.display = "none"; return; }
  const E = best.expect || {}, R = best.react || {}, plan = PB.sel === "all" ? PB.j.today : PB.sel;
  const line = k => R[k] ? `<div class="pbtipp" style="--pb:${PBC[k]}"><b>${PBTITLE[k]}${k === PB.j.today ? " &#9733;" : ""}</b> ${pbChip(R[k].tag)} ${esc(R[k].action)}${pbTrade(R[k].trade)}</div>` : "";
  tip.innerHTML = `<div class="pbtiph">${best.gex ? '<span class="pbgex">GEX</span> ' : ""}<b>${esc(best.label)}</b> <span class="num">${fmt(best.price, 2)}</span>
      <span class="dim">${best.dist >= 0 ? "+" : ""}${fmt(best.dist, 2)}</span></div>
    <div class="pbtipe">${pbPill(best.call)} <b>Expect: ${esc(E.tag || best.call)}</b> ${esc(E.text || "")}</div>
    ${E.if_holds || E.if_breaks ? `<div class="dim">${E.if_holds ? `Holds &rarr; ${esc(E.if_holds)}` : ""}${E.if_holds && E.if_breaks ? " · " : ""}${E.if_breaks ? `Breaks &rarr; ${esc(E.if_breaks)}` : ""}</div>` : ""}
    ${[plan, ...PBSCEN.filter(k => k !== plan)].map(line).join("")}`;
  tip.style.display = "block";
  const W = PB.el.clientWidth, tw = tip.offsetWidth, th = tip.offsetHeight;
  tip.style.left = Math.min(W - tw - 70, p.point.x + 18) + "px"; tip.style.top = Math.max(4, Math.min(PB.el.clientHeight - th - 30, p.point.y + 14)) + "px";
}

function pbLock(on) {                                           // charts need a tap before they move, so page scrolling is not hijacked
  PB.live = on; if (!PB.chart) return;
  PB.chart.applyOptions({ handleScroll: on, handleScale: on });
  const w = PB.el.closest(".pbwrap"); w.classList.toggle("live", on);
  w.querySelector(".pbhint").textContent = on ? "Chart unlocked: drag to move, scroll to zoom, drag the price scale to stretch it. Tap outside the chart to lock it." : "Tap the chart to move or zoom it. Hover a level to see what to do there.";
}

function pbChart(j, sel, lvMode, theme) {
  const el = $("pbchart"), fresh = !(PB.chart && PB.el === el && PB.theme === theme);
  if (!window.LightweightCharts) { el.innerHTML = `<div class="msg bad">The chart script did not load.</div>`; return; }
  const keepRange = !fresh ? null : (PB.chart && PB.key === `${S.u}|${j.tf}` ? PB.chart.timeScale().getVisibleLogicalRange() : null);
  if (fresh) {
    if (PB.chart) { try { PB.chart.remove(); } catch (e) { } }
    el.innerHTML = "";
    Object.assign(PB, pbBuild(el, theme), { el, theme, lines: [], last: "" });
    PB.ov = el.parentNode.querySelector(".pbov"); PB.tip = el.parentNode.querySelector(".pbtip");
    PB.chart.subscribeCrosshairMove(pbTipShow);
    PB.chart.timeScale().subscribeVisibleLogicalRangeChange(() => pbOverlay());
    const loop = () => { if (!document.body.contains(el) || PB.el !== el) return; pbOverlay(); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
    el.addEventListener("click", () => { if (!PB.live) pbLock(true); });
    pbLock(false);
  }
  const first = fresh || PB.key !== `${S.u}|${j.tf}`;
  Object.assign(PB, { j, sel, lv: lvMode, key: `${S.u}|${j.tf}` });
  pbFill(first && !keepRange);
  if (keepRange) PB.chart.timeScale().setVisibleLogicalRange(keepRange);
  pbOverlay(true);
}
document.addEventListener("click", e => { if (PB.live && PB.el && !PB.el.closest(".pbwrap").contains(e.target)) pbLock(false); }, true);
document.addEventListener("keydown", e => { if (e.key === "Escape") { const w = document.querySelector(".pbwrap.full"); if (w) { w.classList.remove("full"); pbOverlay(true); } } });

// What we expect at a level: the call (HOLD / CHOP / BREAK), the reaction (BOUNCE, REJECT, BREAK UP...), why, and where next.
function pbExpect(l) {
  const E = l.expect;
  if (!E) return pbPill(l.call);
  return `${pbPill(l.call)} <b class="pbexptag pb-${l.call}">${esc(E.tag)}</b><div class="pbact">${esc(E.text)}</div>` +
    `${E.if_holds || E.if_breaks ? `<div class="dim pbnext">${E.if_holds ? `Holds &rarr; ${esc(E.if_holds)}` : ""}${E.if_holds && E.if_breaks ? "<br>" : ""}${E.if_breaks ? `Breaks &rarr; ${esc(E.if_breaks)}` : ""}</div>` : ""}` +
    `${E.why ? `<div class="dim pbwhy1">${esc(E.why)}</div>` : ""}${E.record ? `<div class="dim">${esc(E.record)}</div>` : ""}`;
}

// The main table: every level with what to do there in each of the three plans, price now marked in the middle.
function pbTable(j, sel, lvMode) {
  const hl = sel === "all" ? j.today : sel;
  const L = pbFilter(j.levels, lvMode);
  const cell = (l, k) => { const r = l.react && l.react[k]; if (!r) return `<td class="pbc ${k === hl ? "hl" : ""}"><span class="dim">-</span></td>`;
    return `<td class="pbc ${k === hl ? "hl" : ""}" style="--pb:${PBC[k]}">${pbChip(r.tag)} <b>${esc(r.role_title)}</b><div class="pbact">${esc(r.action)}</div>${pbTrade(r.trade)}</td>`; };
  let rows = "", marked = false;
  L.forEach(l => {
    if (!marked && l.price <= j.spot) { marked = true; rows += `<tr class="pbnow"><td colspan="7"><b>PRICE NOW ${fmt(j.spot, 2)}</b></td></tr>`; }
    rows += `<tr class="${l.major ? "major" : ""} ${l.gex ? "gex" : ""}"><td class="num"><b>${fmt(l.price, 2)}</b>${l.low != null && l.high > l.low ? `<div class="dim">${fmt(l.low, 2)}-${fmt(l.high, 2)}</div>` : ""}</td>
      <td>${l.gex ? '<span class="pbgex">GEX</span> ' : ""}${l.major ? "&#9733; " : ""}${esc((l.label || "").split(" / ").slice(0, 3).join(" / "))}${l.chance != null ? `<div class="dim">${pct(l.chance)} chance today</div>` : ""}</td>
      <td class="pbexp">${pbExpect(l)}</td><td class="num dim">${l.dist >= 0 ? "+" : ""}${fmt(l.dist, 2)}</td>${PBSCEN.map(k => cell(l, k)).join("")}</tr>`;
  });
  if (!marked) rows += `<tr class="pbnow"><td colspan="7"><b>PRICE NOW ${fmt(j.spot, 2)}</b></td></tr>`;
  return `<div class="panel"><h2>Every level, every plan</h2>
    <p class="dim">What we expect price to do at each level, and what to do there if the day turns bullish, bearish or choppy. ${esc(PBTITLE[hl])} is highlighted${sel === "all" ? " (today's pick)" : ""}. &#9733; = major level the plans are built around. GEX = every gamma level (GEX strikes and zones, flips, walls), always kept. Entry, stop and target are in ${esc(j.units)}.</p>
    <div class="pbscroll"><table class="pbtable"><tr><th>${esc(j.units)}</th><th>Level</th><th>What we expect there</th><th>From price</th>${PBSCEN.map(k => `<th class="pbc ${k === hl ? "hl" : ""}" style="color:${PBC[k]}">${PBTITLE[k]}${j.today === k ? " &#9733;" : ""}</th>`).join("")}</tr>${rows}</table></div></div>`;
}

function pbCard(k, s) {
  const trades = s.levels.filter(r => r.trade && r.trade.entry != null).sort((a, b) => (b.major - a.major)).slice(0, 5);
  return `<div class="panel pbcard ${s.picked ? "picked" : ""}" style="--pb:${PBC[k]}">
    <div class="pbhead"><h2 style="color:${PBC[k]}">${s.picked ? "&#9733; " : ""}${esc(s.title)}</h2>${s.picked ? `<span class="pbtoday">TODAY'S PICK</span>` : ""}<span class="dim">score ${s.score}</span>
      <button data-pbsel="${k}" class="${S.pbsel === k ? "go" : ""}">Show on chart</button></div>
    <p><b>Plays out if:</b> ${esc(s.trigger)}.</p>
    <p><b>Plan:</b> ${esc(s.plan)}</p>
    <p><b>Targets:</b> ${s.targets.length ? s.targets.map(t => fmt(t, 2)).join(", ") : "-"}</p>
    ${trades.length ? `<div class="pbtrades"><b>Trades in this plan</b>${trades.map(r => `<div>${pbChip(r.tag)} <span class="dim">${esc((r.label || "").split(" / ")[0])} ${fmt(r.price, 2)}</span>${pbTrade(r.trade)}</div>`).join("")}</div>` : ""}
    <p class="pbinvalid"><b>Wrong if:</b> ${esc(s.invalid)}.</p></div>`;
}

Object.assign(R, {
  async playbook() {
    const j = await api("/analytics/playbook", { underlying: S.u, convention: $("conv").value, tf: S.pbtf || 5 });
    const sel = S.pbsel || j.today, t = j.scenarios[j.today], col = PBC[j.today], lvMode = S.pblv || "all", theme = S.pbtheme || "dark";
    const conf = { high: "High confidence", medium: "Medium confidence", low: "Low confidence: the readings disagree" }[j.confidence];
    const reasons = j.reasons.map(r => `<li><b style="color:${PBC[r.scenario]}">+${r.points} ${esc(j.scenarios[r.scenario].title)}</b> ${esc(r.reason)}</li>`).join("");
    const btn = (v, txt) => `<button class="${sel === v ? "go" : ""}" data-pbsel="${v}">${txt}</button>`;
    const tfb = v => `<button class="${(S.pbtf || 5) === v ? "go" : ""}" data-pbtf="${v}">${v}m</button>`;
    const lvb = (v, txt) => `<button class="${lvMode === v ? "go" : ""}" data-pblv="${v}">${txt}</button>`;
    const cnt = j.counts || { all: j.levels.length, major: j.levels.filter(l => l.major).length };
    const top = `
      <div class="pbbanner" style="--pb:${col}">
        <div class="pbbig">TODAY: ${esc(j.banner)}</div>
        <div class="pbsub"><span class="pbconf">${esc(conf)}</span> ${esc(t.trigger)}. <b>Wrong if:</b> ${esc(t.invalid)}.
          <span class="dim">Scores: bullish ${j.scores.bullish}, bearish ${j.scores.bearish}, choppy ${j.scores.choppy}. ${esc(j.regime.title)}.${j.minutes_left ? ` ${fmt(j.minutes_left, 0)} min left.` : ""}</span></div>
        <details class="adv" data-k="pb-why"><summary>Why this plan</summary><ul class="pbwhy">${reasons || "<li class=dim>No reading leans either way.</li>"}</ul></details></div>`;
    const bar = `<div class="pbbar">
        <span class="seg">${btn(j.today, "Today's pick")}${btn("bullish", "Bullish")}${btn("bearish", "Bearish")}${btn("choppy", "Choppy")}${btn("all", "All 3")}</span>
        <span class="seg">${tfb(1)}${tfb(5)}${tfb(15)}</span>
        <span class="seg">${lvb("all", `All levels ${cnt.all}`)}${lvb("gex", `GEX ${cnt.gex ?? ""}`)}${lvb("major", "Major + GEX")}</span>
        <span class="seg"><button data-pbv="start">Now</button><button data-pbv="all">All data</button></span>
        <span class="seg"><button data-pbth="${theme === "dark" ? "light" : "dark"}">${theme === "dark" ? "White chart" : "Dark chart"}</button><button data-pbfull>Full screen</button></span>
        <span class="pbunits dim">${esc(j.units)}${j.mapped ? " (from the index)" : ""} · ${j.tf}m</span></div>`;
    const bottom = `${pbTable(j, sel, lvMode)}
      <div class="pbgrid">${PBSCEN.map(k => pbCard(k, j.scenarios[k])).join("")}</div>
      <details class="adv" data-k="pb-rule"><summary>How the plans and the pick are made</summary><div class="body"><pre style="white-space:pre-wrap;font:inherit" class="dim">${esc(j.rule)}</pre></div></details>
      <p class="hint">${esc(j.note)}</p>`;
    const alive = PB.el && document.body.contains(PB.el) && $("pbtop");
    if (alive) {                                                  // update around the chart; the chart itself is updated in place
      $("pbtop").innerHTML = top; $("pbbarbox").innerHTML = bar; $("pbbottom").innerHTML = bottom;
    } else {
      $("view").innerHTML = panel(`Playbook, ${S.u}`, j.meta, `<div id="pbtop">${top}</div>
        <div class="pbwrap ${theme}"><div id="pbbarbox">${bar}</div>
          <div class="pbstage"><div id="pbchart" class="pbchart2"></div><canvas class="pbov"></canvas><div class="pbtip"></div></div>
          <div class="pbhint dim"></div></div>
        <div id="pbbottom">${bottom}</div>`);
    }
    document.querySelector(".pbwrap").className = `pbwrap ${theme}${PB.live ? " live" : ""}${document.querySelector(".pbwrap.full") ? " full" : ""}`;
    pbChart(j, sel, lvMode, theme);
    const re = () => { saveUI(); render(); };
    document.querySelectorAll("[data-pbsel]").forEach(b => b.onclick = () => { S.pbsel = b.dataset.pbsel === j.today && !b.closest(".pbcard") ? null : b.dataset.pbsel; re(); });
    document.querySelectorAll("[data-pbtf]").forEach(b => b.onclick = () => { S.pbtf = +b.dataset.pbtf; re(); });
    document.querySelectorAll("[data-pblv]").forEach(b => b.onclick = () => { S.pblv = b.dataset.pblv; re(); });
    document.querySelectorAll("[data-pbth]").forEach(b => b.onclick = () => { S.pbtheme = b.dataset.pbth; re(); });
    document.querySelectorAll("[data-pbv]").forEach(b => b.onclick = () => pbView(b.dataset.pbv));
    document.querySelectorAll("[data-pbfull]").forEach(b => b.onclick = () => { document.querySelector(".pbwrap").classList.toggle("full"); setTimeout(() => pbOverlay(true), 50); });
  }
});
