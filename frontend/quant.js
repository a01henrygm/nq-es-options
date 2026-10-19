"use strict";
// Tabs added in 1.6: HOD / LOD (projected high and low of the day, with a TradingView indicator) and Quant lab (gamma-regime
// take-profit playbook, mean-reversion test, Monte Carlo of targets, ES/NQ principal components).
// Uses the helpers in app.js and more.js (api, panel, plot, LAY, note, fmt, esc, S, R, card, pct, hline, vline, etx, download, showText).

const QCOL = { short: "#e5534b", long: "#3fb96a", transition: "#e6b422", unknown: "#8a8f98" };
const pc0 = x => x == null ? "-" : (x >= 0.995 ? "100%" : x < 0.005 && x > 0 ? "<1%" : Math.round(x * 100) + "%");
const futTxt = (v, root) => v == null ? "" : `<span class="dim">${esc(root || "fut")} ${fmt(v, 2)}</span>`;

function playbookBanner(pb) {
  const c = QCOL[pb.state] || "#8a8f98";
  return `<div class="msg" style="border-color:${c};background:#0f1318"><b style="font-size:1.6em;color:${c}">${esc(pb.title)}</b>
    <span class="dim"> ${esc(pb.tagline)}</span>
    <p style="margin:6px 0 0">Targets: <b>${esc(pb.r_range)}</b>. Trades: <b>${esc(pb.trades)}</b>.
    ${pb.gamma_at_spot != null ? `<span class="dim">0DTE dealer gamma at price ${big(pb.gamma_at_spot)}.</span>` : ""}</p></div>`;
}

function pineButtons(idB, idD) {
  return `<span class="actions"><button class="go" id="${idB}" title="Projected HOD/LOD ladder, live chances, regime playbook, mean-reversion test, Monte Carlo and ES/NQ split on your TradingView chart">Copy HOD/LOD indicator</button><button id="${idD}">Download .pine</button></span>`;
}

function wirePine(idB, idD) {
  const want = { underlying: S.u, convention: $("conv").value }, get = () => api("/export/hodlod-pine", want);
  const fail = e => alert("Could not build the HOD/LOD indicator: " + (e.msg || e.message));
  const b = $(idB), d = $(idD);
  if (b) b.onclick = async () => { try { const r = await get(); try { await navigator.clipboard.writeText(r.code); b.textContent = `Copied (${r.state} gamma, 1 sd ${fmt(r.sigma_pct * 100, 2)}%)`; } catch (e) { showText("HOD/LOD indicator (Pine)", r.code); } } catch (e) { fail(e); } };
  if (d) d.onclick = async () => { try { const r = await get(); download(`qdata_hodlod_${S.u.replace(/^_/, "")}.pine`, r.code); d.textContent = "Downloaded"; } catch (e) { fail(e); } };
}

Object.assign(R, {
  // ---- HOD / LOD ------------------------------------------------------------------------------------------------------
  async hodlod() {
    const j = await api("/analytics/hodlod", { underlying: S.u, convention: $("conv").value }), D = j.data, d = D.hodlod, pb = D.playbook, m = j.meta, root = D.futures_root;
    const tools = `<div class="toolbar"><span class="dim">The same ladder, chances and regime run live on your chart in the indicator.</span>${pineButtons("hlpine", "hlpinedl")}</div>`;
    if (!d.available) { $("view").innerHTML = panel(`HOD / LOD, ${S.u}`, m, tools + playbookBanner(pb) + note(d.reason)); wirePine("hlpine", "hlpinedl"); return; }
    const pr = d.projection, rowsUp = d.up.slice().reverse(), dn = d.down;
    const row = (x, side) => `<tr${x.hit ? ' class="dim"' : ""}><td><b style="color:${side > 0 ? "#3fb96a" : "#e5534b"}">${side > 0 ? "+" : "-"}${fmt(x.k, 2)} sd</b></td>
      <td class="num"><b>${fmt(x.price, 2)}</b></td><td class="num">${x.futures != null ? fmt(x.futures, 2) : "-"}</td>
      <td class="num">${pc0(x.at_open)}</td><td class="num"><b>${x.hit ? "HIT" : pc0(x.now)}</b></td>
      <td><span class="share"><i style="width:${Math.round((x.hit ? 1 : x.now || 0) * 100)}%;background:${side > 0 ? "#3fb96a" : "#e5534b"}"></i></span></td></tr>`;
    const spotRow = `<tr style="background:#1a2028"><td><b>Price now</b></td><td class="num"><b>${fmt(d.spot, 2)}</b></td><td class="num">${D.spot_futures != null ? fmt(D.spot_futures, 2) : "-"}</td><td colspan="3" class="dim">high so far ${fmt(d.high, 2)}, low so far ${fmt(d.low, 2)}</td></tr>`;
    const walls = d.walls.map(w => `<tr><td>${esc(w.label)}</td><td class="num"><b>${fmt(w.price, 2)}</b></td><td class="num">${w.futures != null ? fmt(w.futures, 2) : "-"}</td><td class="num">${pc0(w.now)}</td></tr>`).join("");
    $("view").innerHTML = panel(`HOD / LOD, ${S.u}`, m, `${tools}${playbookBanner(pb)}
      ${D.open_note ? note(D.open_note) : ""}
      <div class="grid">${card("Open (9:30)", fmt(d.open, 2), futTxt(d.open_futures, root))}
        ${card("1 standard deviation", fmt(d.sigma_open, 1) + " pts", d.sigma_open_futures ? `${esc(root)} ${fmt(d.sigma_open_futures, 1)} pts, ${fmt(d.sigma_open / d.open * 100, 2)}%` : `${fmt(d.sigma_open / d.open * 100, 2)}% of price`)}
        ${card("Range so far", fmt(d.range_sd, 2) + " sd", `${fmt(d.high - d.low, 1)} pts`)}
        ${card("Projected HOD", pr ? fmt(pr.hod.p50, 2) : "-", pr ? `80%: ${fmt(pr.hod.p80, 2)}, 95%: ${fmt(pr.hod.p95, 2)}` : "session closed")}
        ${card("Projected LOD", pr ? fmt(pr.lod.p50, 2) : "-", pr ? `80%: ${fmt(pr.lod.p80, 2)}, 95%: ${fmt(pr.lod.p95, 2)}` : "session closed")}
        ${card("Time left", fmt(D.minutes_left, 0) + " min", d.sigma_remaining ? `remaining 1 sd ${fmt(d.sigma_remaining, 1)} pts` : "")}</div>
      <div id="hlc" class="chart"></div>
      <h3>The ladder</h3><div class="scroll"><table class="hot"><tr><th>Step</th><th>Price</th><th>${esc(root || "Futures")}</th><th>Chance at the open</th><th>Chance now</th><th></th></tr>
        ${rowsUp.map(x => row(x, 1)).join("")}${spotRow}${dn.map(x => row(x, -1)).join("")}</table></div>
      ${walls ? `<h3>Option walls (0DTE)</h3><div class="scroll"><table><tr><th>Level</th><th>Price</th><th>${esc(root || "Futures")}</th><th>Chance of a touch</th></tr>${walls}</table></div>` : ""}
      ${pb.notes.length ? `<h3>Notes</h3>${pb.notes.map(n => `<p>${esc(n)}</p>`).join("")}` : ""}
      <p class="hint">${esc(d.note)} Projected HOD/LOD: the high (low) the rest of the session reaches half the time (50%) or 4 times in 5 (80%), from the remaining expected move.</p>`);
    wirePine("hlpine", "hlpinedl");
    const P = j.price || [];
    if (P.length) {
      const sh = [hline(d.open, "#c7a96b", "dot")];
      d.up.forEach(x => sh.push(hline(x.price, x.k === 1 || x.k === 2 ? "#3fb96a" : "rgba(63,185,106,.45)", "dash")));
      d.down.forEach(x => sh.push(hline(x.price, x.k === 1 || x.k === 2 ? "#e5534b" : "rgba(229,83,75,.45)", "dash")));
      d.walls.forEach(w => sh.push(hline(w.price, w.side === "hod" ? "#22d3ee" : "#ff4d8d", "solid")));
      const ys = [d.open + 1.6 * d.sigma_open, d.open - 1.6 * d.sigma_open, ...P.map(p => p.price)];
      plot("hlc", [{ type: "scatter", mode: "lines", x: P.map(p => etx(p.t)), y: P.map(p => p.price), line: { color: "#fff", width: 2 }, name: S.u }],
        LAY("Today's price against the ladder", { shapes: sh, showlegend: false, yaxis: { range: [Math.min(...ys), Math.max(...ys)], gridcolor: "#222831" } }));
    } else $("hlc").outerHTML = note("No prices stored for today yet. The chart fills in as the app runs.");
  },

  // ---- Quant lab ------------------------------------------------------------------------------------------------------
  async quant() {
    const want = { underlying: S.u, convention: $("conv").value, model: S.qmodel || "auto" };
    if (S.qstop) want.stop = S.qstop;
    const j = await api("/analytics/quant", want), D = j.data, pb = D.playbook, mr = D.mean_reversion, mc = D.monte_carlo, pc = D.pca, m = j.meta, root = D.futures_root || "fut";
    const stopShown = mc.available ? mc.stop_futures : (S.qstop || "");
    const ctl = `<div class="toolbar">
      <label>Stop (${esc(root)} points)<input id="qstop" type="number" min="0.25" step="0.25" value="${stopShown ? fmt(stopShown, 2).replace(/,/g, "") : ""}" style="width:90px"></label>
      <label>Paths<select id="qmodel"><option value="auto">Auto (pull only in long gamma with a real pull)</option><option value="walk">Random walk</option><option value="pull">Pull to the average</option></select></label>
      <button id="qgo" class="go">Run</button>${pineButtons("qpine", "qpinedl")}</div>`;
    const rules = (pb.rules || []).map((r, i) => `<div class="card"><b style="font-size:1.05em">${i + 1}. ${esc(r[0])}</b>${esc(r[1])}</div>`).join("");
    const tg = (pb.targets || []).map(t => `<tr><td>${esc(t.label)}</td><td class="num"><b>${fmt(t.price, 2)}</b></td><td>${esc(t.side)}</td><td class="num">${t.chance != null ? pc0(t.chance) : "-"}</td></tr>`).join("");
    const flips = (pb.flips || []).map(f => `<li>${esc(etx(f.t).slice(11, 16))} ET: ${esc(f.from)} to <b style="color:${QCOL[f.to]}">${esc(f.to)}</b> gamma</li>`).join("");
    const mrBlock = !mr.available ? note(mr.reason) : `<div class="grid">
        ${card("Verdict", `<span style="color:${mr.significant ? "#3fb96a" : mr.lean === "unclear" ? "#e6b422" : "#e5534b"};font-size:.8em">${esc(mr.verdict)}</span>`)}
        ${card("t statistic", fmt(mr.t_stat, 2), `needs ${fmt(mr.t_limit, 1)} or lower`)}
        ${card("Half life", mr.t_stat > -2 || mr.half_life_steps == null ? "none" : mr.half_life_minutes != null ? fmt(mr.half_life_minutes, 0) + " min" : fmt(mr.half_life_steps, 1) + " steps", mr.t_stat > -2 ? "no pull to measure" : "time to close half the gap to the average")}
        ${card("Distance now", (mr.z_now >= 0 ? "+" : "") + fmt(mr.z_now, 2) + " sd", `average ${fmt(mr.mean, 2)}, ${mr.n} prices`)}</div><p class="hint">${esc(mr.note)}</p>`;
    const mcRows = mc.available ? mc.rows.map(r => `<tr><td><b>${r.r} R</b></td><td class="num">${fmt(r.target_points * (D.ratio || 1), 2)}</td>
        <td class="num" style="color:#3fb96a"><b>${pc0(r.long.win)}</b></td><td class="num dim">${pc0(r.long.stop)} / ${pc0(r.long.neither)}</td><td class="num">${(r.long.ev_r >= 0 ? "+" : "") + fmt(r.long.ev_r, 2)}</td>
        <td class="num" style="color:#e5534b"><b>${pc0(r.short.win)}</b></td><td class="num dim">${pc0(r.short.stop)} / ${pc0(r.short.neither)}</td><td class="num">${(r.short.ev_r >= 0 ? "+" : "") + fmt(r.short.ev_r, 2)}</td>
        <td class="num dim">${pc0(r.no_clock)}</td></tr>`).join("") : "";
    const mcBlock = !mc.available ? note(mc.reason) : `<div class="scroll"><table><tr><th>Target</th><th>${esc(root)} pts</th><th>Long: target first</th><th>stop / neither</th><th>Long avg R</th><th>Short: target first</th><th>stop / neither</th><th>Short avg R</th><th>No clock</th></tr>${mcRows}</table></div>
      <div id="qmc" class="chart"></div>
      <div class="grid">${card("Paths end the day with HOD", fmt(mc.hod.p50, 2), `half the time; 80%: ${fmt(mc.hod.p80, 2)}, 95%: ${fmt(mc.hod.p95, 2)}`)}${card("Paths end the day with LOD", fmt(mc.lod.p50, 2), `half the time; 20%: ${fmt(mc.lod.p20, 2)}, 5%: ${fmt(mc.lod.p05, 2)}`)}
        ${card("Model", esc(mc.model), `${mc.paths} paths x ${mc.steps} steps, ${fmt(mc.minutes_left, 0)} min left, remaining 1 sd ${fmt(mc.sigma_remaining, 1)} pts`)}</div>
      <p class="hint">${esc(mc.note)} Avg R counts a stop as -1 R, a target as +R, and a trade still open at the close at its closing distance.</p>`;
    const pcBlock = !pc.available ? note(pc.reason) : `<div class="grid">
        ${card("Shared move (PC1)", pct(pc.pc1_share), "of NQ and ES movement is one common factor")}
        ${card("Correlation", fmt(pc.correlation, 2), `beta ${fmt(pc.beta, 2)} (NQ move per 1% of ES)`)}
        ${card("NQ against ES today", `<span style="color:${Math.abs(pc.residual_z) >= 2 ? "#e6b422" : "inherit"}">${(pc.residual_z >= 0 ? "+" : "") + fmt(pc.residual_z, 2)} z</span>`, `${(pc.residual_cum_pct >= 0 ? "+" : "") + fmt(pc.residual_cum_pct, 3)}% beyond its usual ratio`)}
        ${card("PC1 weights", `NQ ${fmt(pc.pc1_loadings.nq, 2)} / ES ${fmt(pc.pc1_loadings.es, 2)}`, `${pc.n} matched returns (${esc(uName(pc.symbols.nq))} and ${esc(uName(pc.symbols.es))})`)}</div>
      <p><b>${esc(pc.read)}</b></p><p class="hint">${esc(pc.note)}</p>`;
    $("view").innerHTML = panel(`Quant lab, ${S.u}`, m, `${ctl}
      <h3>1. Take profit by regime</h3>${playbookBanner(pb)}<div class="grid wide">${rules}</div>
      ${tg ? `<div class="scroll"><table><tr><th>Target</th><th>Price</th><th>Side</th><th>Chance of a touch today</th></tr>${tg}</table></div>` : ""}
      ${flips ? `<p><b>Regime flips today</b></p><ul>${flips}</ul>` : ""}${(pb.notes || []).map(n => `<p>${esc(n)}</p>`).join("")}
      <h3>2. Mean reversion test</h3>${mrBlock}
      <h3>3. Monte Carlo: target before stop, before the close</h3>${mcBlock}
      <h3>4. ES / NQ principal components</h3>${pcBlock}
      <p class="hint">None of this is backtested. The regime comes from modeled 0DTE dealer gamma; the tests use the prices this app stored today (a point about every 2 minutes). The TradingView indicator runs the same tests on your chart's bars.</p>`);
    $("qmodel").value = S.qmodel || "auto";
    const go = () => { const v = parseFloat($("qstop").value); S.qstop = v > 0 ? v : null; S.qmodel = $("qmodel").value; saveUI(); render(); };
    $("qgo").onclick = go; $("qmodel").onchange = go; $("qstop").onkeydown = e => { if (e.key === "Enter") go(); };
    wirePine("qpine", "qpinedl");
    if (mc.available) {
      const xs = mc.rows.map(r => r.r + " R");
      plot("qmc", [{ type: "bar", x: xs, y: mc.rows.map(r => r.long.win * 100), name: "Long", marker: { color: "#3fb96a" } },
        { type: "bar", x: xs, y: mc.rows.map(r => r.short.win * 100), name: "Short", marker: { color: "#e5534b" } },
        { type: "scatter", mode: "lines+markers", x: xs, y: mc.rows.map(r => r.no_clock * 100), name: "No clock 1/(1+R)", line: { color: "#8a8f98", dash: "dot" } }],
        LAY("Chance the target is hit before the stop and the close", { barmode: "group", yaxis: { title: "%", gridcolor: "#222831" } }));
    }
  }
});

// ---- Level map (1.7): candles, the call at each level, projected candles acting the calls out --------------------------
const CALLCOL = { RESPECT: ["#0f6e56", "#9FE1CB", "#5DCAA5"], CHOP: ["#854f0b", "#FAC775", "#EF9F27"], DISRESPECT: ["#a32d2d", "#F7C1C1", "#E24B4A"] };
const CALLWORD = { RESPECT: "rejects", CHOP: "chops", DISRESPECT: "breaks" };
Object.assign(R, {
  async levelmap() {
    const tf = S.lmtf || 2, j = await api("/charts/level-map", { underlying: S.u, convention: $("conv").value, tf }), m = j.meta;
    const fut = S.lmfut && j.mapped && j.ratio, k = fut ? j.ratio : 1, root = j.futures_root || "fut", unit = fut ? root : uName(S.u);
    const pf = v => fmt(v * k, 2), rg = j.regime, P = j.projection;
    const ctl = `<div class="toolbar">
      <label>Candles<select id="lmtf"><option value="1">1 min</option><option value="2">2 min</option><option value="5">5 min</option><option value="10">10 min</option></select></label>
      <label><input type="checkbox" id="lmalt" ${S.lmalt !== false ? "checked" : ""}> Alternate path</label>
      <label title="${j.mapped ? "" : "Save a futures price or basis to convert"}"><input type="checkbox" id="lmfut" ${fut ? "checked" : ""} ${j.mapped ? "" : "disabled"}> ${esc(root)} points</label>
      <span class="dim">Solid = real, outlined = projected. Each level's tag is what price should do there.</span></div>`;
    const pill = c => `<span style="background:${CALLCOL[c][0]};color:${CALLCOL[c][1]};padding:2px 8px;border-radius:4px;font-weight:600;font-size:.85em;white-space:nowrap">${c}</span>`;
    const rows = j.levels.map(l => `<tr><td class="num"><b>${pf(l.value)}</b>${l.low != null ? `<br><span class="dim">${pf(l.low)} to ${pf(l.high)}</span>` : ""}</td>
      <td>${esc(l.label)}<br><span class="dim">${l.side} price, ${fmt(Math.abs(l.value - j.spot) * k, 1)} pts</span></td><td>${pill(l.call)}</td>
      <td><span class="share"><i style="width:${Math.round(l.strength * 100)}%;background:${CALLCOL[l.call][2]}"></i></span></td>
      <td class="dim">${esc(l.why)}</td>
      <td class="num">${l.record ? `${pct(l.record.held_pct)} held<br><span class="dim">${l.record.n} touches${l.record.enough ? "" : ", small sample"}</span>` : '<span class="dim">no touches logged yet</span>'}</td></tr>`).join("");
    const ev = P.main ? P.main.events.map(e => `${CALLWORD[e.call]} at ${pf(e.value)} (${esc(e.label.split(" / ")[0])})`).join(", then ") : "";
    $("view").innerHTML = panel(`Level map, ${S.u}`, m, `${ctl}
      <div class="msg" style="border-color:${rg.color};background:#0f1318"><b style="font-size:1.4em;color:${rg.color}">${esc(rg.title)}</b> <span class="dim">${esc(rg.tagline)}</span>
        ${ev ? `<p style="margin:6px 0 0">Main path: ${ev}.</p>` : ""}</div>
      <div id="lmc" class="chart" style="height:620px"></div>
      <h3>What each level should do</h3><div class="scroll"><table><tr><th>Price (${esc(unit)})</th><th>Level</th><th>Call</th><th>Strength</th><th>Why</th><th>Track record</th></tr>${rows || '<tr><td colspan="6" class="dim">No key levels within 1.5% of price.</td></tr>'}</table></div>
      <details class="adv" data-k="lm-rule"><summary>How the calls are made</summary><div class="body"><pre style="white-space:pre-wrap;font:inherit" class="dim">${esc(j.rule)}</pre></div></details>
      <p class="hint">${esc(j.note)}</p>`);
    $("lmtf").value = String(tf);
    $("lmtf").onchange = () => { S.lmtf = +$("lmtf").value; saveUI(); render(); };
    $("lmalt").onchange = () => { S.lmalt = $("lmalt").checked; saveUI(); render(); };
    $("lmfut").onchange = () => { S.lmfut = $("lmfut").checked; saveUI(); render(); };
    const hm = t => etx(t).slice(11, 16), C = j.candles, T = C.map(c => hm(c.t));
    const cs = (name, t, arr, inc, dec, op, fill) => ({ type: "candlestick", name, x: t, open: arr.map(c => c.o * k), high: arr.map(c => c.h * k), low: arr.map(c => c.l * k), close: arr.map(c => c.c * k),
      increasing: { line: { color: inc, width: 1 }, fillcolor: fill ? inc : "rgba(0,0,0,0)" }, decreasing: { line: { color: dec, width: 1 }, fillcolor: fill ? dec : "rgba(0,0,0,0)" }, opacity: op, whiskerwidth: 0, hoverinfo: "x+y" });
    const tr = [];
    if (C.length) tr.push(cs("Real", T, C, "#1D9E75", "#E24B4A", 1, true));
    const PT = P.times.map(hm);
    if (P.alt && S.lmalt !== false) tr.push(cs("Alternate", PT.slice(0, P.alt.candles.length), P.alt.candles, "#8a8f98", "#5f5e5a", 0.45, false));
    if (P.main) tr.push(cs("Projected", PT.slice(0, P.main.candles.length), P.main.candles, "#5DCAA5", "#F09595", 0.95, false));
    const sh = [], an = [];
    j.levels.forEach(l => {
      const col = CALLCOL[l.call][2];
      if (l.low != null && l.high > l.low && (l.high - l.low) / j.spot < 0.0025) sh.push({ type: "rect", xref: "paper", x0: 0, x1: 1, y0: l.low * k, y1: l.high * k, fillcolor: col, opacity: 0.07, line: { width: 0 } });
      sh.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: l.value * k, y1: l.value * k, line: { color: col, width: 1.4, dash: l.call === "CHOP" ? "dash" : "solid" } });
      an.push({ xref: "paper", x: 1, xanchor: "left", y: l.value * k, text: `<b>${l.call}</b> ${pf(l.value)}`, showarrow: false, font: { color: CALLCOL[l.call][1], size: 11 }, bgcolor: CALLCOL[l.call][0], borderpad: 3 });
      an.push({ xref: "paper", x: 0.005, xanchor: "left", y: l.value * k, yanchor: "bottom", text: esc(l.label.split(" / ")[0]), showarrow: false, font: { color: col, size: 10 } });
    });
    if (P.main) P.main.events.forEach(e => { const t = PT[e.i]; if (t) an.push({ x: t, y: e.value * k, text: CALLWORD[e.call], showarrow: true, arrowhead: 0, ax: 0, ay: e.call === "RESPECT" ? -28 : 28, font: { color: CALLCOL[e.call][1], size: 11 }, arrowcolor: CALLCOL[e.call][2] }); });
    if (T.length) sh.push(vline(T[T.length - 1], "#9aa3ad", "dot"));
    if (j.open) sh.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: j.open * k, y1: j.open * k, line: { color: "#c7a96b", width: 1, dash: "dot" } });
    plot("lmc", tr, LAY(`${uName(S.u)} ${tf}m${fut ? ` in ${root} points` : ""}`, { shapes: sh, annotations: an, showlegend: true, legend: { orientation: "h", y: 1.06, x: 0.35 },
      xaxis: { rangeslider: { visible: false }, gridcolor: "#1c2229", type: "category", nticks: 14, tickangle: 0 }, yaxis: { side: "right", gridcolor: "#1c2229", tickformat: ",.0f" }, margin: { l: 10, r: 150, t: 40, b: 40 } }));
  }
});

// ---- Chart read (1.8): drop a TradingView screenshot, get it back marked up ------------------------------------------------
const CR = { img: null, w: 0, h: 0, res: null, busy: false, err: "", note: "" };
function crShrink(file) {
  return new Promise((ok, bad) => {
    const fr = new FileReader();
    fr.onload = () => { const im = new Image(); im.onload = () => {
      const sc = Math.min(1, 1600 / im.width), cv = document.createElement("canvas");
      cv.width = Math.round(im.width * sc); cv.height = Math.round(im.height * sc);
      cv.getContext("2d").drawImage(im, 0, 0, cv.width, cv.height);
      ok({ url: cv.toDataURL("image/jpeg", 0.92), w: cv.width, h: cv.height });
    }; im.onerror = () => bad(new Error("That file is not an image.")); im.src = fr.result; };
    fr.onerror = () => bad(new Error("Could not open the file.")); fr.readAsDataURL(file);
  });
}
function crDraw() {
  const cv = $("crcv"); if (!cv || !CR.img) return;
  const im = new Image(); im.onload = () => {
    const W = im.width, H = im.height, g = cv.getContext("2d"); cv.width = W; cv.height = H; g.drawImage(im, 0, 0);
    const r = CR.res; if (!r || r.problems.length) return;
    const a = r.reading.axis, yOf = p => (a.y1 + (p - a.p1) * (a.y2 - a.y1) / (a.p2 - a.p1)) * H, xr = r.reading.plot_right_x * W;
    const fs = Math.max(11, Math.round(W / 110)); g.font = `600 ${fs}px Manrope, Segoe UI, sans-serif`; g.textBaseline = "middle";
    r.levels.forEach(l => {
      const y = yOf(l.price); if (y < 0 || y > H) return;
      const [bg, tx, col] = CALLCOL[l.call];
      if (l.low != null && l.high != null && l.high > l.low) { g.fillStyle = col + "18"; const y1 = yOf(l.high), y2 = yOf(l.low); g.fillRect(0, y1, xr, y2 - y1); }
      g.strokeStyle = col; g.lineWidth = Math.max(1.5, W / 900); g.setLineDash(l.call === "CHOP" ? [8, 5] : []);
      g.beginPath(); g.moveTo(0, y); g.lineTo(xr, y); g.stroke(); g.setLineDash([]);
      const t = `${l.call} ${fmt(l.price, 2)}`, tw = g.measureText(t).width + 12;
      g.fillStyle = bg; g.fillRect(xr - tw - 6, y - fs * 0.75, tw, fs * 1.5); g.fillStyle = tx; g.fillText(t, xr - tw, y);
      g.fillStyle = col; g.font = `500 ${fs - 1}px Manrope, Segoe UI, sans-serif`; g.fillText(l.label.split(" / ")[0], 6, y - fs * 0.8); g.font = `600 ${fs}px Manrope, Segoe UI, sans-serif`;
    });
    const P = r.projection; if (!P) return;
    const drawPath = (path, alt) => {
      const sp = P.spacing * W, bw = Math.max(2, sp * 0.55);
      path.candles.forEach((c, i) => {
        const x = (P.start_x * W) + (i + 1) * sp, up = c.c >= c.o, col = alt ? "#8a8f98" : (up ? "#5DCAA5" : "#F09595");
        g.globalAlpha = alt ? 0.45 : 0.95; g.strokeStyle = col; g.lineWidth = 1; g.setLineDash(alt ? [3, 3] : []);
        g.beginPath(); g.moveTo(x, yOf(c.h)); g.lineTo(x, yOf(c.l)); g.stroke();
        const y1 = yOf(Math.max(c.o, c.c)), y2 = yOf(Math.min(c.o, c.c)); g.strokeRect(x - bw / 2, y1, bw, Math.max(1, y2 - y1));
      });
      g.setLineDash([]); g.globalAlpha = 1;
      if (!alt) path.events.forEach(e => { const x = (P.start_x * W) + (e.i + 1) * sp, y = yOf(e.value) + (e.call === "RESPECT" ? -fs * 1.6 : fs * 1.6);
        g.fillStyle = CALLCOL[e.call][1]; g.textAlign = "center"; g.fillText(CALLWORD[e.call], x, y); g.textAlign = "start"; });
    };
    if (P.alt) drawPath(P.alt, true);
    drawPath(P.main, false);
    g.strokeStyle = "#9aa3ad"; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(P.start_x * W + P.spacing * W / 2, 0); g.lineTo(P.start_x * W + P.spacing * W / 2, H); g.stroke(); g.setLineDash([]);
    const rg = r.regime, t = `${rg.title}  |  targets ${rg.r_range}`; g.font = `700 ${fs + 2}px Manrope, Segoe UI, sans-serif`;
    const tw = g.measureText(t).width + 20; g.fillStyle = "rgba(15,19,24,.88)"; g.fillRect(8, 8, tw, fs * 2.2); g.fillStyle = rg.color; g.fillText(t, 18, 8 + fs * 1.1);
  };
  im.src = CR.img;
}
Object.assign(R, {
  async chartread() {
    const st = await api("/chart-read/status");
    const keyBox = st.configured ? "" : `<div class="msg"><b>Add your Anthropic API key once</b><p style="margin:6px 0">Reading a screenshot uses Claude's vision through your own Anthropic API account
      (a few cents per read). Make a key at console.anthropic.com, paste it here and save. It is stored only in your .env file on this PC and sent only to Anthropic.</p>
      <input id="crkey" type="password" placeholder="sk-ant-..." style="width:340px"> <button id="crkeysave" class="go">Save key</button> <span id="crkeymsg" class="dim"></span></div>`;
    const r = CR.res;
    const pill = c => `<span style="background:${CALLCOL[c][0]};color:${CALLCOL[c][1]};padding:2px 8px;border-radius:4px;font-weight:600;font-size:.85em">${c}</span>`;
    const seenTxt = { not_reached: "not reached yet", respected: "respected so far", broken: "already broken", chopping: "chopping around it", unclear: "unclear" };
    const out = !r ? "" : `
      ${r.problems.length ? note("Could not mark up this screenshot: " + r.problems.join(" "), true) : ""}${r.warnings.map(w => note(w)).join("")}
      <div class="msg" style="border-color:${r.regime.color};background:#0f1318"><b style="font-size:1.3em;color:${r.regime.color}">${esc(r.regime.title)}</b> <span class="dim">${esc(r.regime.tagline)} Targets ${esc(r.regime.r_range)}.</span>
        <p style="margin:6px 0 0"><b>On your chart:</b> ${esc(r.reading.structure || "")} <span class="dim">(${esc(r.reading.symbol || "symbol not visible")}, ${esc(r.reading.timeframe || "timeframe not visible")}, last ${fmt(r.reading.last_price, 2)})</span></p>
        ${r.projection && r.projection.main.events.length ? `<p style="margin:6px 0 0"><b>Main path:</b> ${r.projection.main.events.map(e => `${CALLWORD[e.call]} at ${fmt(e.value, 2)}`).join(", then ")}.</p>` : ""}</div>
      <div class="scroll"><table><tr><th>Price (${esc(r.unit)})</th><th>Level</th><th>Call</th><th>On your chart so far</th><th>Why</th></tr>
        ${r.levels.map(l => `<tr><td class="num"><b>${fmt(l.price, 2)}</b></td><td>${esc(l.label)}</td><td>${pill(l.call)}</td>
          <td>${l.chart_behavior ? `<b>${esc(seenTxt[l.chart_behavior] || l.chart_behavior)}</b>` : '<span class="dim">not noted</span>'}${l.chart_note ? `<br><span class="dim">${esc(l.chart_note)}</span>` : ""}</td>
          <td class="dim">${esc(l.why)}${l.record ? ` Held ${pct(l.record.held_pct)} of ${l.record.n} logged touches.` : ""}</td></tr>`).join("")}</table></div>
      <p class="hint">${esc(r.note)}</p>`;
    $("view").innerHTML = panel(`Chart read, ${S.u}`, null, `${keyBox}
      <div class="toolbar"><span class="dim">Paste a screenshot of your TradingView chart (Ctrl+V), drop it here, or</span>
        <label class="go" style="cursor:pointer;padding:6px 12px;border-radius:6px">Choose image<input id="crfile" type="file" accept="image/*" hidden></label>
        <input id="crnote" placeholder="Optional: anything to tell it (e.g. 1m, 10:42, looking for shorts)" style="flex:1;min-width:260px" value="${esc(CR.note)}">
        <button id="crgo" class="go" ${CR.img && st.configured && !CR.busy ? "" : "disabled"}>${CR.busy ? "Reading..." : "Read chart"}</button>
        ${r && !r.problems.length ? '<button id="crdl">Download marked-up image</button>' : ""}</div>
      ${CR.err ? note(CR.err, true) : ""}
      <div id="crdrop" style="border:1px dashed #3a4350;border-radius:10px;padding:${CR.img ? "6px" : "60px 10px"};text-align:center;color:#8a8f98">
        ${CR.img ? '<canvas id="crcv" style="max-width:100%;height:auto"></canvas>' : "Drop or paste a chart screenshot here. Keep the price scale and your levels visible."}</div>
      ${out}`);
    const take = async f => { if (!f || !f.type.startsWith("image/")) return; try { const s = await crShrink(f); CR.img = s.url; CR.res = null; CR.err = ""; render(); } catch (e) { CR.err = e.message; render(); } };
    $("crfile").onchange = e => take(e.target.files[0]);
    const dz = $("crdrop"); dz.ondragover = e => { e.preventDefault(); dz.style.borderColor = "#2f8bf5"; }; dz.ondragleave = () => dz.style.borderColor = "#3a4350";
    dz.ondrop = e => { e.preventDefault(); take(e.dataTransfer.files[0]); };
    document.onpaste = e => { if (S.tab !== "chartread") return; const it = [...(e.clipboardData || {}).items || []].find(i => i.type.startsWith("image/")); if (it) take(it.getAsFile()); };
    $("crnote").oninput = e => { CR.note = e.target.value; };
    $("crgo").onclick = async () => {
      CR.busy = true; CR.err = ""; render();
      try {
        const resp = await fetch("/api/chart-read" + (S.src ? "?source=" + encodeURIComponent(S.src) : ""), { method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ image: CR.img, underlying: S.u, convention: $("conv").value, note: CR.note }) });
        const j = await resp.json();
        if (!resp.ok) throw new Error(typeof j.detail === "string" ? j.detail : (j.detail && j.detail.reason) || "The read failed.");
        CR.res = j;
      } catch (e) { CR.err = e.message; }
      CR.busy = false; render();
    };
    if ($("crdl")) $("crdl").onclick = () => { const a = document.createElement("a"); a.href = $("crcv").toDataURL("image/png"); a.download = `qdata_chart_read_${uName(S.u)}.png`; a.click(); };
    if ($("crkeysave")) $("crkeysave").onclick = async () => {
      const resp = await fetch("/api/chart-read/key", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key: $("crkey").value }) });
      const j = await resp.json(); $("crkeymsg").textContent = resp.ok ? "Saved." : (j.detail || "Could not save."); if (resp.ok) render();
    };
    crDraw();
  }
});
