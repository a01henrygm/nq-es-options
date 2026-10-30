"use strict";
// Playbook tab (1.25.0): a TradingView-style candle chart with the biggest levels as zones, three plans for how to react to them
// (bullish, bearish, choppy) with projected candles acting each one out, and a banner with the plan that fits today.
// Uses the helpers in app.js (api, panel, plot, LAY, esc, fmt, S, R, saveUI, render) and pct, etx from more.js.

const PBC = { bullish: "#16a34a", bearish: "#dc2626", choppy: "#d97706" };
const PBCALL = { HOLD: ["#0f6e56", "#9FE1CB", "#26a69a"], CHOP: ["#854f0b", "#FAC775", "#f0a63a"], BREAK: ["#a32d2d", "#F7C1C1", "#ef5350"] };
const PBROLE = { support: "Support (must hold)", resistance: "Resistance to work through", resistance_bear: "Resistance (must hold)", support_bear: "Support to work through",
  target: "Target", edge_top: "Range top", edge_bottom: "Range bottom", middle: "Range middle" };

const pbA = (hex, a) => `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})`;

function pbChart(j, sel) {
  const T = iso => etx(iso);                                     // chart times in Eastern Time on any PC
  const C = j.candles.map(k => Object.assign({}, k, { t: T(k.t) })), sc = {};
  for (const [k, s] of Object.entries(j.scenarios)) sc[k] = Object.assign({}, s, { path: s.path.map(p => Object.assign({}, p, { t: T(p.t) })) });
  const show = sel === "all" ? ["bullish", "bearish", "choppy"] : [sel];
  const allT = C.map(k => k.t).concat(...Object.values(sc).map(s => s.path.map(p => p.t)));
  const x0 = allT[0], x1 = allT.reduce((a, b) => (a > b ? a : b), allT[0]);
  const traces = [{ type: "candlestick", name: "Price", x: C.map(k => k.t), open: C.map(k => k.o), high: C.map(k => k.h), low: C.map(k => k.l), close: C.map(k => k.c),
    increasing: { line: { color: "#26a69a", width: 1 }, fillcolor: "#26a69a" }, decreasing: { line: { color: "#ef5350", width: 1 }, fillcolor: "#ef5350" }, whiskerwidth: 0.3 }];
  for (const k of ["bullish", "bearish", "choppy"]) {
    const s = sc[k], P = s.path; if (!P.length) continue;
    const on = show.includes(k), lead = on && (sel !== "all" || s.picked);
    if (on) traces.push({ type: "candlestick", name: `${s.title} plan${s.picked ? " (today)" : ""}`, x: P.map(p => p.t), open: P.map(p => p.o), high: P.map(p => p.h), low: P.map(p => p.l), close: P.map(p => p.c),
      opacity: lead ? 0.9 : 0.45, increasing: { line: { color: PBC[k], width: 1 }, fillcolor: lead ? pbA(PBC[k], 0.35) : "rgba(0,0,0,0)" },
      decreasing: { line: { color: PBC[k], width: 1 }, fillcolor: lead ? PBC[k] : "rgba(0,0,0,0)" }, whiskerwidth: 0.3 });
    else traces.push({ type: "scatter", mode: "lines", name: `${s.title} plan`, x: [C.length ? C[C.length - 1].t : P[0].t, ...P.map(p => p.t)], y: [j.spot, ...P.map(p => p.c)],
      line: { color: PBC[k], width: 1, dash: "dot" }, opacity: 0.35, hoverinfo: "skip" });
  }
  const zh = Math.max(1, (j.sigma_remaining || j.spot * 0.004) * 0.06);
  const shapes = [], ann = [];
  j.levels.forEach(l => {
    const col = PBCALL[l.call][2], lo = l.low != null && l.high > l.low ? l.low : l.price - zh / 2, hi = l.low != null && l.high > l.low ? l.high : l.price + zh / 2;
    shapes.push({ type: "rect", xref: "x", yref: "y", x0, x1, y0: lo, y1: hi, fillcolor: col, opacity: l.key ? 0.22 : 0.14, line: { width: 1, color: col } });
    shapes.push({ type: "line", xref: "x", yref: "y", x0, x1, y0: l.price, y1: l.price, line: { width: l.key ? 1.6 : 1, color: col, dash: l.call === "CHOP" ? "dash" : "solid" } });
    ann.push({ xref: "paper", x: 0.995, xanchor: "right", yref: "y", y: l.price, yanchor: "bottom", showarrow: false, align: "right",
      text: `<b>${esc(l.label.split(" / ")[0])}</b> ${fmt(l.price, 2)}  <b>${l.call}</b>`, font: { size: 11, color: PBCALL[l.call][1] }, bgcolor: "rgba(19,23,34,.75)" });
  });
  const lastT = C.length ? C[C.length - 1].t : x0;
  shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: j.spot, y1: j.spot, line: { width: 1, color: "#2962ff", dash: "dot" } });
  shapes.push({ type: "line", xref: "x", x0: lastT, x1: lastT, yref: "paper", y0: 0, y1: 1, line: { width: 1, color: "#5d6680", dash: "dash" } });
  ann.push({ xref: "paper", x: 1, xanchor: "left", yref: "y", y: j.spot, showarrow: false, text: `<b>${fmt(j.spot, 2)}</b>`, font: { size: 11, color: "#fff" }, bgcolor: "#2962ff", borderpad: 3 });
  ann.push({ xref: "x", x: lastT, xanchor: "left", yref: "paper", y: 1, yanchor: "top", showarrow: false, text: "  projected  ", font: { size: 11, color: "#8a93a8" } });
  if (!C.length) ann.push({ xref: "paper", x: 0.02, y: 0.98, yref: "paper", showarrow: false, xanchor: "left", text: "No prices stored for today yet: the plans start from the latest price.", font: { color: "#e6b422" } });
  const ax = { gridcolor: "#1e2433", zerolinecolor: "#1e2433", linecolor: "#2a3142", showspikes: true, spikemode: "across", spikethickness: 1, spikedash: "dot", spikecolor: "#6b7385" };
  plot("pbchart", traces, LAY("", {
    plot_bgcolor: "#131722", paper_bgcolor: "#131722", height: 620, margin: { l: 10, r: 78, t: 40, b: 40 }, hovermode: "x", dragmode: "pan",
    xaxis: Object.assign({}, ax, { type: "date", rangeslider: { visible: false }, tickformat: "%H:%M" }),
    yaxis: Object.assign({}, ax, { side: "right", tickformat: ",.2f", fixedrange: false }),
    legend: { orientation: "h", y: 1.01, x: 0, yanchor: "bottom", bgcolor: "rgba(0,0,0,0)" }, shapes, annotations: ann }), { gate: true });
}

function pbCard(k, s, root) {
  const pill = c => `<span class="pbpill" style="background:${PBCALL[c][0]};color:${PBCALL[c][1]}">${c}</span>`;
  const rows = s.levels.map(r => `<tr><td class="num"><b>${fmt(r.price, 2)}</b></td><td>${esc(PBROLE[r.role] || r.role)}<br><span class="dim">${esc((r.label || "").split(" / ").slice(0, 2).join(" / "))}</span></td>
    <td>${pill(r.call)}</td><td>${esc(r.action)}${r.chance != null ? ` <span class="dim">(${pct(r.chance)} chance it is reached today)</span>` : ""}</td></tr>`).join("");
  return `<div class="panel pbcard ${s.picked ? "picked" : ""}" style="--pb:${PBC[k]}">
    <div class="pbhead"><h2 style="color:${PBC[k]}">${s.picked ? "&#9733; " : ""}${esc(s.title)}</h2>${s.picked ? `<span class="pbtoday">TODAY'S PICK</span>` : ""}<span class="dim">score ${s.score}</span>
      <button data-pbsel="${k}" class="${S.pbsel === k ? "go" : ""}">Show on chart</button></div>
    <p><b>Plays out if:</b> ${esc(s.trigger)}.</p>
    <p><b>Plan:</b> ${esc(s.plan)}</p>
    <div class="scroll"><table><tr><th>${esc(root)}</th><th>Level</th><th>Call</th><th>How to react</th></tr>${rows || `<tr><td colspan="4" class="dim">No big levels on this side within reach today.</td></tr>`}</table></div>
    <p><b>Targets:</b> ${s.targets.length ? s.targets.map(t => fmt(t, 2)).join(", ") : "-"}</p>
    <p class="pbinvalid"><b>Wrong if:</b> ${esc(s.invalid)}.</p></div>`;
}

Object.assign(R, {
  async playbook() {
    const j = await api("/analytics/playbook", { underlying: S.u, convention: $("conv").value, tf: S.pbtf || 5 });
    const sel = S.pbsel || j.today, t = j.scenarios[j.today], col = PBC[j.today];
    const conf = { high: "High confidence", medium: "Medium confidence", low: "Low confidence: the readings disagree" }[j.confidence];
    const reasons = j.reasons.map(r => `<li><b style="color:${PBC[r.scenario]}">+${r.points} ${esc(j.scenarios[r.scenario].title)}</b> ${esc(r.reason)}</li>`).join("");
    const btn = (v, txt) => `<button class="${sel === v ? "go" : ""}" data-pbsel="${v}">${txt}</button>`;
    const tfb = v => `<button class="${(S.pbtf || 5) === v ? "go" : ""}" data-pbtf="${v}">${v}m</button>`;
    $("view").innerHTML = panel(`Playbook, ${S.u}`, j.meta, `
      <div class="pbbanner" style="--pb:${col}">
        <div class="pbbig">TODAY: ${esc(j.banner)}</div>
        <div class="pbsub"><span class="pbconf">${esc(conf)}</span> ${esc(t.trigger)}. <b>Wrong if:</b> ${esc(t.invalid)}.
          <span class="dim">Scores: bullish ${j.scores.bullish}, bearish ${j.scores.bearish}, choppy ${j.scores.choppy}. ${esc(j.regime.title)}.${j.minutes_left ? ` ${fmt(j.minutes_left, 0)} min left.` : ""}</span></div>
        <details class="adv"><summary>Why this plan</summary><ul class="pbwhy">${reasons || "<li class=dim>No reading leans either way.</li>"}</ul></details></div>
      <div class="toolbar"><span class="actions">${btn(j.today, "Today's pick")}${btn("bullish", "Bullish")}${btn("bearish", "Bearish")}${btn("choppy", "Choppy")}${btn("all", "All three")}</span>
        <span class="actions">${tfb(1)}${tfb(5)}${tfb(15)}</span>
        <span class="dim">Prices in ${esc(j.units)}${j.mapped ? " (estimated from the index)" : ""}. Zones: green HOLD, amber CHOP, red BREAK.</span></div>
      <div id="pbchart" class="chart"></div>
      <div class="pbgrid">${["bullish", "bearish", "choppy"].map(k => pbCard(k, j.scenarios[k], j.units)).join("")}</div>
      <details class="adv" data-k="pb-rule"><summary>How the plans and the pick are made</summary><div class="body"><pre style="white-space:pre-wrap;font:inherit" class="dim">${esc(j.rule)}</pre></div></details>
      <p class="hint">${esc(j.note)}</p>`);
    pbChart(j, sel);
    document.querySelectorAll("[data-pbsel]").forEach(b => b.onclick = () => { S.pbsel = b.dataset.pbsel === j.today && !b.closest(".pbcard") ? null : b.dataset.pbsel; saveUI(); render(); });
    document.querySelectorAll("[data-pbtf]").forEach(b => b.onclick = () => { S.pbtf = +b.dataset.pbtf; saveUI(); render(); });
  }
});
