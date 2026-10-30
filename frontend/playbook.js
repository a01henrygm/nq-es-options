"use strict";
// Playbook tab (1.26.0): a TradingView-style candle chart with EVERY level near price as a zone, three plans (bullish, bearish,
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

function pbChart(j, sel, lvMode) {
  const T = iso => etx(iso);                                         // chart times in Eastern Time on any PC
  const C = j.candles.map(k => Object.assign({}, k, { t: T(k.t) })), sc = {};
  for (const [k, s] of Object.entries(j.scenarios)) sc[k] = Object.assign({}, s, { path: s.path.map(p => Object.assign({}, p, { t: T(p.t) })) });
  const show = sel === "all" ? PBSCEN : [sel];
  const plan = sel === "all" ? j.today : sel;                        // whose tags and hover text the levels show
  const allT = C.map(k => k.t).concat(...Object.values(sc).map(s => s.path.map(p => p.t)));
  const x0 = allT[0], x1 = allT.reduce((a, b) => (a > b ? a : b), allT[0]);
  const lastT = C.length ? C[C.length - 1].t : x0;
  const L = pbFilter(j.levels, lvMode);

  // ---- price range: the candles, the plans and the nearest levels, so the zones fill the chart instead of a thin strip
  const sig = j.sigma_remaining || j.spot * 0.004;
  const ys = [j.spot - 1.1 * sig, j.spot + 1.1 * sig];
  C.forEach(k => ys.push(k.h, k.l));
  show.forEach(k => sc[k].path.forEach(p => ys.push(p.h, p.l)));
  L.filter(l => l.major || Math.abs(l.price - j.spot) <= (l.gex ? 2.5 : 1.6) * sig).forEach(l => ys.push(l.low ?? l.price, l.high ?? l.price));
  let ylo = Math.min(...ys), yhi = Math.max(...ys); const pad = (yhi - ylo) * 0.04; ylo -= pad; yhi += pad;
  const H = ($("pbchart") && $("pbchart").clientHeight) || 720, pxPer = (yhi - ylo) / Math.max(200, H - 86);

  const traces = [{ type: "candlestick", name: "Price", x: C.map(k => k.t), open: C.map(k => k.o), high: C.map(k => k.h), low: C.map(k => k.l), close: C.map(k => k.c),
    increasing: { line: { color: "#26a69a", width: 1 }, fillcolor: "#26a69a" }, decreasing: { line: { color: "#ef5350", width: 1 }, fillcolor: "#ef5350" }, whiskerwidth: 0.3 }];
  for (const k of PBSCEN) {
    const s = sc[k], P = s.path; if (!P.length) continue;
    const on = show.includes(k), lead = on && (sel !== "all" || s.picked);
    if (on) traces.push({ type: "candlestick", name: `${s.title} plan${s.picked ? " (today)" : ""}`, x: P.map(p => p.t), open: P.map(p => p.o), high: P.map(p => p.h), low: P.map(p => p.l), close: P.map(p => p.c),
      opacity: lead ? 0.9 : 0.45, increasing: { line: { color: PBC[k], width: 1 }, fillcolor: lead ? pbA(PBC[k], 0.35) : "rgba(0,0,0,0)" },
      decreasing: { line: { color: PBC[k], width: 1 }, fillcolor: lead ? PBC[k] : "rgba(0,0,0,0)" }, whiskerwidth: 0.3 });
    else traces.push({ type: "scatter", mode: "lines", name: `${s.title} plan`, x: [lastT, ...P.map(p => p.t)], y: [j.spot, ...P.map(p => p.c)],
      line: { color: PBC[k], width: 1, dash: "dot" }, opacity: 0.35, hoverinfo: "skip" });
  }

  const zh = Math.max(1, sig * 0.06);
  const shapes = [], ann = [];
  // choppy range shaded when the choppy plan is on the chart
  const rg = j.scenarios.choppy.range;
  if (show.includes("choppy") && rg) shapes.push({ type: "rect", xref: "paper", x0: 0, x1: 1, yref: "y", y0: rg.low, y1: rg.high, fillcolor: PBC.choppy, opacity: 0.05, line: { width: 0 }, layer: "below" });

  // zones and lines for every level
  L.forEach(l => {
    const col = PBCALL[l.call][2], z = l.low != null && l.high > l.low;
    const lo = z ? l.low : l.price - zh / 2, hi = z ? l.high : l.price + zh / 2;
    shapes.push({ type: "rect", xref: "x", yref: "y", x0, x1, y0: lo, y1: hi, fillcolor: col, opacity: l.major || l.gex ? 0.24 : 0.1, line: { width: l.major || l.gex ? 1 : 0, color: col }, layer: "below" });
    shapes.push({ type: "line", xref: "x", yref: "y", x0, x1, y0: l.price, y1: l.price, line: { width: l.gex ? 2 : l.major ? 1.6 : 0.8, color: col, dash: l.call === "CHOP" ? "dash" : l.major || l.gex ? "solid" : "dot" } });
  });

  // labels: right-axis price tag for every level (like TradingView), name + plan tag where there is room. Majors placed first.
  const placedR = [], placedL = [];
  const room = (arr, y, px) => arr.every(v => Math.abs(v - y) / pxPer >= px);
  [...L].sort((a, b) => ((b.gex + b.major) - (a.gex + a.major)) || Math.abs(a.price - j.spot) - Math.abs(b.price - j.spot)).forEach(l => {
    if (l.price < ylo || l.price > yhi) return;
    const col = PBCALL[l.call];
    if (room(placedR, l.price, 17)) {
      placedR.push(l.price);
      ann.push({ xref: "paper", x: 1, xanchor: "left", yref: "y", y: l.price, showarrow: false, text: `<b>${fmt(l.price, 2)}</b>`,
        font: { size: 10.5, color: "#0b0e14" }, bgcolor: col[2], borderpad: 2 });
      ann.push({ xref: "paper", x: 0.004, xanchor: "left", yref: "y", y: l.price, yanchor: "middle", showarrow: false,
        text: `${l.gex ? '<span style="color:#7cc4ff"><b>GEX</b></span> ' : ""}${l.major || l.gex ? "<b>" : ""}${esc(l.name || l.label.split(" / ")[0])}${l.major || l.gex ? "</b>" : ""} <span style="color:${col[1]}"><b>${esc(l.expect ? l.expect.tag : l.call)}</b></span>`,
        font: { size: l.major || l.gex ? 11 : 10, color: l.major || l.gex ? "#e7ecf5" : "#aab3c5" }, bgcolor: "rgba(19,23,34,.8)" });
    }
    const r = l.react && l.react[plan];
    if (r && r.tag && room(placedL, l.price, 17)) {
      placedL.push(l.price);
      const [b, f] = pbTagCol(r.tag);
      ann.push({ xref: "x", x: lastT, xanchor: "left", yref: "y", y: l.price, showarrow: false, text: `<b>${esc(r.tag)}</b>`,
        font: { size: 10, color: f }, bgcolor: b, borderpad: 2, bordercolor: f, borderwidth: 0.5 });
    }
  });

  // hover anywhere along a level: its reaction in the plan on screen (and the other two)
  const hx = [], hy = [], ht = [];
  const steps = 16, tA = new Date(x0).getTime(), tB = new Date(x1).getTime();
  L.forEach(l => {
    const R = l.react || {};
    const line = k => R[k] ? `<b style="color:${PBC[k]}">${PBTITLE[k]}</b> ${esc(R[k].tag || R[k].role_title)}: ${esc(R[k].action)}` +
      (R[k].trade && R[k].trade.entry != null ? `<br>   ${R[k].trade.side === "long" ? "Buy" : "Short"} ${fmt(R[k].trade.entry, 2)}, stop ${fmt(R[k].trade.stop, 2)}${R[k].trade.target != null ? `, target ${fmt(R[k].trade.target, 2)}` : ""}` : "") : "";
    const order = [plan, ...PBSCEN.filter(k => k !== plan)];
    const E = l.expect || {};
    const txt = `<b>${esc(l.label)}</b>  ${fmt(l.price, 2)}  (${l.dist >= 0 ? "+" : ""}${fmt(l.dist, 2)} from price)<br>` +
      `<b>Expect: ${esc(E.tag || l.call)}</b> ${esc(E.text || "")}${l.chance != null ? `<br>${pct(l.chance)} chance it is reached today` : ""}` +
      `${E.if_holds ? `<br>Holds: next ${esc(E.if_holds)}` : ""}${E.if_breaks ? `   Breaks: next ${esc(E.if_breaks)}` : ""}<br>` +
      order.map(line).filter(Boolean).join("<br>");
    for (let i = 0; i <= steps; i++) { hx.push(new Date(tA + (tB - tA) * i / steps).toLocaleString("sv-SE")); hy.push(l.price); ht.push(txt); }
  });
  if (hx.length) traces.push({ type: "scatter", mode: "markers", x: hx, y: hy, text: ht, hovertemplate: "%{text}<extra></extra>", marker: { size: 10, opacity: 0 },
    showlegend: false, hoverlabel: { bgcolor: "#1b2130", bordercolor: "#3a4358", font: { size: 11.5, color: "#e7ecf5" }, align: "left" } });

  // a line and a date at the start of each day (the chart starts at the earliest stored price, so it can span several days)
  let prevD = null;
  C.forEach(k => { const d = k.t.slice(0, 10); if (prevD && d !== prevD) {
    shapes.push({ type: "line", xref: "x", x0: k.t, x1: k.t, yref: "paper", y0: 0, y1: 1, line: { width: 1, color: "#3a4358" } });
    ann.push({ xref: "x", x: k.t, xanchor: "left", yref: "paper", y: 0, yanchor: "bottom", showarrow: false, text: ` ${d.slice(5)} `, font: { size: 10, color: "#8a93a8" } }); }
    prevD = d; });
  shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: j.spot, y1: j.spot, line: { width: 1, color: "#2962ff", dash: "dot" } });
  shapes.push({ type: "line", xref: "x", x0: lastT, x1: lastT, yref: "paper", y0: 0, y1: 1, line: { width: 1, color: "#5d6680", dash: "dash" } });
  shapes.push({ type: "rect", xref: "x", x0: lastT, x1, yref: "paper", y0: 0, y1: 1, fillcolor: "#ffffff", opacity: 0.018, line: { width: 0 }, layer: "below" });
  ann.push({ xref: "paper", x: 1, xanchor: "left", yref: "y", y: j.spot, showarrow: false, text: `<b>${fmt(j.spot, 2)}</b>`, font: { size: 11, color: "#fff" }, bgcolor: "#2962ff", borderpad: 3 });
  ann.push({ xref: "x", x: lastT, xanchor: "left", yref: "paper", y: 1, yanchor: "top", showarrow: false, text: `  projected: ${esc(PBTITLE[plan])} plan tags  `, font: { size: 11, color: "#8a93a8" } });
  ann.push({ xref: "paper", x: 0, xanchor: "left", yref: "paper", y: 1.005, yanchor: "bottom", showarrow: false,
    text: `<b>${esc(j.units)}</b> ${j.tf}m   <span style="color:#8a93a8">${L.length} levels · hover a level for what to do there</span>`, font: { size: 12, color: "#d1d4dc" } });
  if (!C.length) ann.push({ xref: "paper", x: 0.02, y: 0.94, yref: "paper", showarrow: false, xanchor: "left", text: "No prices stored for today yet: the plans start from the latest price.", font: { color: "#e6b422" } });
  // collapse stretches with no stored prices (overnight, weekends, app closed) so the candles sit next to each other
  const gaps = [], gapMs = Math.max(45, 3 * j.tf) * 60000, ms = v => new Date(v.replace(" ", "T")).getTime();
  for (let i = 1; i < C.length; i++) if (ms(C[i].t) - ms(C[i - 1].t) > gapMs) {
    const a = new Date(ms(C[i - 1].t) + j.tf * 60000).toLocaleString("sv-SE"), b = new Date(ms(C[i].t) - 60000).toLocaleString("sv-SE");
    gaps.push({ bounds: [a, b] });
  }
  const ax = { gridcolor: "#1e2433", zerolinecolor: "#1e2433", linecolor: "#2a3142", showspikes: true, spikemode: "across", spikethickness: 1, spikedash: "dot", spikecolor: "#6b7385" };
  plot("pbchart", traces, LAY("", {
    plot_bgcolor: "#131722", paper_bgcolor: "#131722", margin: { l: 10, r: 80, t: 52, b: 44 }, hovermode: "closest", hoverdistance: 12, dragmode: "pan",
    xaxis: Object.assign({}, ax, { type: "date", rangeslider: { visible: false }, tickformat: "%H:%M\n%b %d", showspikes: false, rangebreaks: gaps }),
    yaxis: Object.assign({}, ax, { side: "right", tickformat: ",.2f", fixedrange: false, range: [ylo, yhi], autorange: false }),
    legend: { orientation: "h", y: 1.0, x: 1, xanchor: "right", yanchor: "bottom", bgcolor: "rgba(0,0,0,0)", font: { size: 11 } }, shapes, annotations: ann }), { gate: true });
}

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
    const sel = S.pbsel || j.today, t = j.scenarios[j.today], col = PBC[j.today], lvMode = S.pblv || "all";
    const conf = { high: "High confidence", medium: "Medium confidence", low: "Low confidence: the readings disagree" }[j.confidence];
    const reasons = j.reasons.map(r => `<li><b style="color:${PBC[r.scenario]}">+${r.points} ${esc(j.scenarios[r.scenario].title)}</b> ${esc(r.reason)}</li>`).join("");
    const btn = (v, txt) => `<button class="${sel === v ? "go" : ""}" data-pbsel="${v}">${txt}</button>`;
    const tfb = v => `<button class="${(S.pbtf || 5) === v ? "go" : ""}" data-pbtf="${v}">${v}m</button>`;
    const lvb = (v, txt) => `<button class="${lvMode === v ? "go" : ""}" data-pblv="${v}">${txt}</button>`;
    const cnt = j.counts || { all: j.levels.length, major: j.levels.filter(l => l.major).length };
    $("view").innerHTML = panel(`Playbook, ${S.u}`, j.meta, `
      <div class="pbbanner" style="--pb:${col}">
        <div class="pbbig">TODAY: ${esc(j.banner)}</div>
        <div class="pbsub"><span class="pbconf">${esc(conf)}</span> ${esc(t.trigger)}. <b>Wrong if:</b> ${esc(t.invalid)}.
          <span class="dim">Scores: bullish ${j.scores.bullish}, bearish ${j.scores.bearish}, choppy ${j.scores.choppy}. ${esc(j.regime.title)}.${j.minutes_left ? ` ${fmt(j.minutes_left, 0)} min left.` : ""}</span></div>
        <details class="adv"><summary>Why this plan</summary><ul class="pbwhy">${reasons || "<li class=dim>No reading leans either way.</li>"}</ul></details></div>
      <div class="toolbar"><span class="actions">${btn(j.today, "Today's pick")}${btn("bullish", "Bullish")}${btn("bearish", "Bearish")}${btn("choppy", "Choppy")}${btn("all", "All three")}</span>
        <span class="actions">${tfb(1)}${tfb(5)}${tfb(15)}</span>
        <span class="actions">${lvb("all", `All levels (${cnt.all})`)}${lvb("gex", `GEX only (${cnt.gex ?? "-"})`)}${lvb("major", `Major + GEX`)}</span>
        <span class="dim">Prices in ${esc(j.units)}${j.mapped ? " (estimated from the index)" : ""}. Zones: green HOLD, amber CHOP, red BREAK. Each label says what we expect there (BOUNCE, REJECT, CHOP, BREAK); the tags past the dashed line show what the selected plan does. The chart starts at the earliest stored price.</span></div>
      <div id="pbchart" class="chart pbchart"></div>
      ${pbTable(j, sel, lvMode)}
      <div class="pbgrid">${PBSCEN.map(k => pbCard(k, j.scenarios[k])).join("")}</div>
      <details class="adv" data-k="pb-rule"><summary>How the plans and the pick are made</summary><div class="body"><pre style="white-space:pre-wrap;font:inherit" class="dim">${esc(j.rule)}</pre></div></details>
      <p class="hint">${esc(j.note)}</p>`);
    pbChart(j, sel, lvMode);
    document.querySelectorAll("[data-pbsel]").forEach(b => b.onclick = () => { S.pbsel = b.dataset.pbsel === j.today && !b.closest(".pbcard") ? null : b.dataset.pbsel; saveUI(); render(); });
    document.querySelectorAll("[data-pbtf]").forEach(b => b.onclick = () => { S.pbtf = +b.dataset.pbtf; saveUI(); render(); });
    document.querySelectorAll("[data-pblv]").forEach(b => b.onclick = () => { S.pblv = b.dataset.pblv; saveUI(); render(); });
  }
});
