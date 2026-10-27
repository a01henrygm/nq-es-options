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
  if (b) b.onclick = async () => { try { const r = await get(); try { await copyText(r.code); b.textContent = `Copied (${r.state} gamma, 1 sd ${fmt(r.sigma_pct * 100, 2)}%)`; } catch (e) { showText("HOD/LOD indicator (Pine)", r.code); } } catch (e) { fail(e); } };
  if (d) d.onclick = async () => { try { const r = await get(); download(`qdata_hodlod_${S.u.replace(/^_/, "")}.pine`, r.code); d.textContent = "Downloaded"; } catch (e) { fail(e); } };
}

// Every HOD / LOD level as one CSV (opens in Excel or Sheets), so the chart can stay clean.
function hodlodCsv(D, u) {
  const d = D.hodlod, root = D.futures_root || "Futures", mv = D.moves;
  const q = v => { const t = v == null ? "" : String(v); return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
  const n = (v, k = 2) => v == null || isNaN(v) ? "" : Number(v).toFixed(k);
  const p = v => v == null ? "" : Math.round(v * 100) + "%";
  const rows = [["Group", "Level", `${uName(u)} price`, `${root} price`, "Chance at the open", "Chance now", "Call / status", "Note"]];
  if (d && d.available) {
    rows.push(["Session", "Open 9:30", n(d.open), n(d.open_futures), "", "", "", ""]);
    rows.push(["Session", "High so far", n(d.high), n(d.high_futures), "", "", "", ""]);
    rows.push(["Session", "Low so far", n(d.low), n(d.low_futures), "", "", "", ""]);
    rows.push(["Session", "Price now", n(d.spot), n(D.spot_futures), "", "", "", ""]);
    rows.push(["Session", "1 standard deviation (pts)", n(d.sigma_open, 1), n(d.sigma_open_futures, 1), "", "", "", ""]);
    d.up.slice().reverse().forEach(x => rows.push(["Ladder", `+${x.k} sd`, n(x.price), n(x.futures), p(x.at_open), x.hit ? "100%" : p(x.now), x.hit ? "HIT" : "", ""]));
    d.down.forEach(x => rows.push(["Ladder", `-${x.k} sd`, n(x.price), n(x.futures), p(x.at_open), x.hit ? "100%" : p(x.now), x.hit ? "HIT" : "", ""]));
    const pr = d.projection;
    if (pr) for (const [side, name] of [["hod", "Projected HOD"], ["lod", "Projected LOD"]])
      for (const k of Object.keys(pr[side])) rows.push(["Projection", `${name} ${k.slice(1)}%`, n(pr[side][k]), n((pr[side + "_futures"] || {})[k]), "", "", "", ""]);
    d.walls.forEach(w => rows.push(["0DTE walls", w.label, n(w.price), n(w.futures), "", p(w.now), "", ""]));
  }
  if (mv && mv.available)
    for (const [arr, side] of [[mv.up, "Moves up"], [mv.down, "Moves down"]])
      arr.forEach(r => rows.push([side, r.label, n(r.price), n(r.futures), "", p(r.chance), r.call, `${r.note} ${r.why || ""}`.trim()]));
  return rows.map(r => r.map(q).join(",")).join("\r\n");
}

function movesBlock(mv, root) {
  if (!mv) return "";
  if (!mv.available) return `<h3>Moves we may encounter</h3>${note(mv.reason)}`;
  const pill = c => `<span style="background:${CALLCOL[c][0]};color:${CALLCOL[c][1]};padding:2px 8px;border-radius:4px;font-weight:600;font-size:.85em;white-space:nowrap">${c}</span>`;
  const rows = (arr, up) => arr.length ? arr.map((r, i) => `<tr><td class="num"><b>${fmt(r.price, 2)}</b>${r.futures != null ? `<br><span class="dim">${esc(root)} ${fmt(r.futures, 2)}</span>` : ""}</td>
      <td>${i + 1}. ${esc(r.label)}<br><span class="dim">${up ? "+" : "-"}${fmt(r.points, 0)} pts, ${fmt(r.sd, 2)} sd away</span></td><td>${pill(r.call)}</td>
      <td class="num"><b>${pc0(r.chance)}</b></td><td>${esc(r.note)}<br><span class="dim">${esc(r.why)}</span></td></tr>`).join("")
    : `<tr><td colspan="5" class="dim">No key levels ${up ? "above" : "below"} price within reach.</td></tr>`;
  const head = `<tr><th>Price</th><th>Level</th><th>Call</th><th>Chance of a touch</th><th>What should happen and why</th></tr>`;
  const r = mv.range;
  return `<h3>Moves we may encounter</h3>
    <div class="msg" style="background:#0f1318">${mv.summary.map(t => `<p style="margin:3px 0">${esc(t)}</p>`).join("")}</div>
    <div class="grid wide">
      <div class="card"><b style="font-size:1.05em;color:#3fb96a">If price goes up</b><div class="scroll"><table>${head}${rows(mv.up, true)}</table></div></div>
      <div class="card"><b style="font-size:1.05em;color:#e5534b">If price goes down</b><div class="scroll"><table>${head}${rows(mv.down, false)}</table></div></div></div>
    ${r && r.stay_inside != null ? `<div class="grid">${card("Stays in the range until the close", pc0(r.stay_inside), `between ${esc(r.low_label.split(" / ")[0])} ${fmt(r.low, 0)}${r.low_futures != null ? ` (${esc(root)} ${fmt(r.low_futures, 0)})` : ""} and ${esc(r.high_label.split(" / ")[0])} ${fmt(r.high, 0)}${r.high_futures != null ? ` (${esc(root)} ${fmt(r.high_futures, 0)})` : ""}`)}
      ${card("Breaks out of it", pc0(1 - r.stay_inside), "touches at least one of the two levels before 16:00")}</div>` : ""}
    <h3>What's driving it</h3><div class="scroll"><table><tr><th>Data</th><th>Reading</th><th>What it means for the move</th></tr>
      ${mv.drivers.map(d => `<tr><td><b>${esc(d.name)}</b></td><td>${esc(d.reading)}</td><td>${esc(d.effect)}</td></tr>`).join("")}</table></div>
    <p class="hint">${esc(mv.note)}</p>`;
}

Object.assign(R, {
  // ---- HOD / LOD ------------------------------------------------------------------------------------------------------
  async hodlod() {
    const j = await api("/analytics/hodlod", { underlying: S.u, convention: $("conv").value }), D = j.data, d = D.hodlod, pb = D.playbook, m = j.meta, root = D.futures_root;
    const tools = `<div class="toolbar"><span class="dim">The same ladder, chances and regime run live on your chart in the indicator (Clean view by default).</span>${pineButtons("hlpine", "hlpinedl")}<button id="hlcsv" title="Every level on this tab (ladder, projections, walls, moves) with index and futures prices and chances, as a spreadsheet">Download levels (CSV)</button></div>`;
    const wireCsv = () => { const b = $("hlcsv"); if (b) b.onclick = () => { download(`qdata_hodlod_levels_${uName(S.u)}_${(m.calculated_at_et || "").slice(0, 10) || "today"}.csv`, hodlodCsv(D, S.u)); b.textContent = "Downloaded"; }; };
    if (!d.available) { $("view").innerHTML = panel(`HOD / LOD, ${S.u}`, m, tools + playbookBanner(pb) + note(d.reason)); wirePine("hlpine", "hlpinedl"); wireCsv(); return; }
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
      <h3>Is the high or low of the day already in?</h3>${alreadyInCards(D.already_in, D.spot_futures ? D.spot_futures / d.spot : 1, root)}
      ${movesBlock(D.moves, root)}
      <div id="hlc" class="chart"></div>
      <h3>The ladder</h3><div class="scroll"><table class="hot"><tr><th>Step</th><th>Price</th><th>${esc(root || "Futures")}</th><th>Chance at the open</th><th>Chance now</th><th></th></tr>
        ${rowsUp.map(x => row(x, 1)).join("")}${spotRow}${dn.map(x => row(x, -1)).join("")}</table></div>
      ${walls ? `<h3>Option walls (0DTE)</h3><div class="scroll"><table><tr><th>Level</th><th>Price</th><th>${esc(root || "Futures")}</th><th>Chance of a touch</th></tr>${walls}</table></div>` : ""}
      ${pb.notes.length ? `<h3>Notes</h3>${pb.notes.map(n => `<p>${esc(n)}</p>`).join("")}` : ""}
      <p class="hint">${esc(d.note)} Projected HOD/LOD: the high (low) the rest of the session reaches half the time (50%) or 4 times in 5 (80%), from the remaining expected move.</p>`);
    wirePine("hlpine", "hlpinedl"); wireCsv();
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
    const mcBlock = !mc.available ? note(mc.reason) : `<div id="qfan" class="chart" style="height:520px"></div>
      <p class="hint">Each thin line is one simulated path of ${esc(D.futures_root || "the index")} from now to the 16:00 close (${mc.fan.paths.length} of ${mc.paths} drawn). Green paths finish above today's price, red below.
        The white line is the middle path, the dashed lines hold 90% of the paths and the dotted lines 50%. The bars on the right show where all ${mc.paths} paths finished.</p>
      <div class="scroll"><table><tr><th>Target</th><th>${esc(root)} pts</th><th>Long: target first</th><th>stop / neither</th><th>Long avg R</th><th>Short: target first</th><th>stop / neither</th><th>Short avg R</th><th>No clock</th></tr>${mcRows}</table></div>
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
      const k = D.ratio || 1, f = mc.fan, t0 = new Date(m.calculated_at || Date.now()).getTime(), tl = f.minutes.map(mn => new Date(t0 + mn * 60000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false }));
      const tr = f.paths.map(pth => ({ type: "scatter", mode: "lines", x: tl, y: pth.map(v => v * k), line: { width: 1, color: pth[pth.length - 1] >= f.start ? "rgba(63,185,106,.28)" : "rgba(229,83,75,.28)" }, hoverinfo: "skip", showlegend: false }));
      const band = (key, dash, w, col, name) => ({ type: "scatter", mode: "lines", x: tl, y: f.bands[key].map(v => v * k), name, line: { dash, width: w, color: col }, hovertemplate: `${name} %{y:,.2f}<extra></extra>` });
      tr.push(band("p05", "dash", 1.6, "#e6b422", "5% (low end)"), band("p95", "dash", 1.6, "#e6b422", "95% (high end)"), band("p25", "dot", 1.4, "#cfd6e0", "25%"), band("p75", "dot", 1.4, "#cfd6e0", "75%"), band("p50", "solid", 2.6, "#ffffff", "Middle path"));
      const h = f.final_hist, mids = h.counts.map((_, i) => (h.lo + (i + 0.5) * h.width) * k);
      tr.push({ type: "bar", orientation: "h", x: h.counts, y: mids, xaxis: "x2", yaxis: "y", marker: { color: mids.map(v => v >= f.start * k ? "#3fb96a" : "#e5534b") }, showlegend: false, hovertemplate: "%{x} paths finished near %{y:,.0f}<extra></extra>" });
      const sp = f.start * k, st = mc.stop * k, r3 = 3 * st, hl = (y, col, txt) => ({ type: "line", xref: "paper", x0: 0, x1: 0.84, y0: y, y1: y, line: { color: col, width: 1, dash: "dash" }, label: { text: txt, font: { color: col, size: 10 }, textposition: "start" } });
      plot("qfan", tr, LAY(`Monte Carlo: ${mc.paths} possible paths to the close`, { showlegend: true, legend: { orientation: "h", y: -0.12 }, hovermode: "closest",
        xaxis: { domain: [0, 0.84], gridcolor: "#1c2229", type: "category", nticks: 10 }, xaxis2: { domain: [0.86, 1], showgrid: false, showticklabels: false, zeroline: false },
        yaxis: { gridcolor: "#1c2229", tickformat: ",.0f", side: "left" },
        shapes: [hl(sp, "#9aa3ad", "now"), hl(sp - st, "#e5534b", "long stop (-" + fmt(st, 2) + ")"), hl(sp + st, "#e5534b", "short stop (+" + fmt(st, 2) + ")"), hl(sp + r3, "#3fb96a", "long 3 R target"), hl(sp - r3, "#3fb96a", "short 3 R target")] }));
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
    const j = await api("/charts/level-map", { underlying: S.u, convention: $("conv").value }), m = j.meta, rg = j.regime, root = j.futures_root || "NQ", ix = uName(S.u);
    const nqOn = j.spot_futures != null, F = v => v == null ? "-" : fmt(v, 2);
    const flt = S.lmcall || "ALL", near = S.lmnear !== false;
    const keep = l => (flt === "ALL" || l.call === flt) && (!near || l.chance == null || l.chance >= 0.03);
    const pill = c => `<span style="background:${CALLCOL[c][0]};color:${CALLCOL[c][1]};padding:3px 10px;border-radius:4px;font-weight:700;font-size:.85em;white-space:nowrap">${c}</span>`;
    const row = l => `<div class="lmrow" style="border-left:4px solid ${CALLCOL[l.call][2]}">
      <div class="lmprice"><b>${nqOn ? F(l.futures) : F(l.value)}</b><span class="dim">${nqOn ? `${esc(ix)} ${fmt(l.value, 0)}` : esc(ix)}</span>
        <span class="dim">${l.points > 0 ? "+" : ""}${fmt(l.points * (nqOn ? j.spot_futures / j.spot : 1), 1)} pts${l.sd != null ? `, ${fmt(l.sd, 2)} sd` : ""}</span></div>
      <div class="lmbody"><div>${pill(l.call)} <b>${esc(l.headline)}</b> <span class="dim">at ${esc(l.label)}</span></div>
        <p>${esc(l.plan)}</p><p class="dim">${esc(l.why)}${l.record ? ` Track record: held ${pct(l.record.held_pct)} of ${l.record.n} logged touches${l.record.enough ? "" : " (small sample)"}.` : ""}</p></div>
      <div class="lmchance"><span class="dim">Chance price gets there today</span><b>${l.chance == null ? "-" : pc0(l.chance)}</b>
        <span class="share"><i style="width:${Math.round((l.chance || 0) * 100)}%;background:${CALLCOL[l.call][2]}"></i></span></div></div>`;
    const above = j.levels.filter(l => l.value > j.spot && keep(l)), below = j.levels.filter(l => l.value <= j.spot && keep(l));
    const hidden = j.levels.length - above.length - below.length;
    const btn = (v, t) => `<button class="${flt === v ? "go" : ""}" data-lm="${v}">${t}</button>`;
    $("view").innerHTML = panel(`Level map, ${S.u}`, m, `
      <div class="msg" style="border-color:${rg.color};background:#0f1318"><b style="font-size:1.4em;color:${rg.color}">${esc(rg.title)}</b> <span class="dim">${esc(rg.tagline)} Targets ${esc(rg.r_range)}.</span>
        <p style="margin:6px 0 0">${j.levels.length} levels: <b style="color:${CALLCOL.RESPECT[2]}">${j.counts.RESPECT} should hold</b>, <b style="color:${CALLCOL.CHOP[2]}">${j.counts.CHOP} should chop</b>, <b style="color:${CALLCOL.DISRESPECT[2]}">${j.counts.DISRESPECT} should break</b>.</p></div>
      <div class="toolbar"><span class="actions">${btn("ALL", "All levels")}${btn("RESPECT", "Hold")}${btn("CHOP", "Chop")}${btn("DISRESPECT", "Break")}</span>
        <label><input type="checkbox" id="lmnear" ${near ? "checked" : ""}> Only levels price can reach today (3%+ chance)</label>
        <span class="dim">${nqOn ? `Prices in ${esc(root)} (${esc((j.futures_info || {}).method || "")}).` : `Prices in ${esc(ix)}.`}${hidden ? ` ${hidden} hidden by the filters.` : ""}</span></div>
      <div class="lm">${above.map(row).join("")}
        <div class="lmnow"><b>PRICE NOW ${nqOn ? F(j.spot_futures) : F(j.spot)}</b><span class="dim">${nqOn ? `${esc(ix)} ${fmt(j.spot, 2)}, ` : ""}${fmt(j.minutes_left, 0)} min left${j.sigma_remaining ? `, 1 sd still to come about ${fmt(j.sigma_remaining * (nqOn ? j.spot_futures / j.spot : 1), 0)} pts` : ""}</span></div>
        ${below.map(row).join("")}</div>
      <details class="adv" data-k="lm-rule"><summary>How the calls are made</summary><div class="body"><pre style="white-space:pre-wrap;font:inherit" class="dim">${esc(j.rule)}</pre></div></details>
      <p class="hint">${esc(j.note)}</p>`);
    document.querySelectorAll("[data-lm]").forEach(b => b.onclick = () => { S.lmcall = b.dataset.lm; saveUI(); render(); });
    $("lmnear").onchange = () => { S.lmnear = $("lmnear").checked; saveUI(); render(); };
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
      <div class="toolbar"><span class="dim">Paste a screenshot of your TradingView chart (${KEY}+V), drop it here, or</span>
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

// ---- Stack map (1.11): only the areas where many different kinds of levels pile up ------------------------------------
function alreadyInCards(a, k, root) {
  if (!a) return "";
  const col = p => p >= 0.8 ? "#3fb96a" : p >= 0.5 ? "#e6b422" : "#e5534b";
  return `<div class="grid">
    <div class="card">Today's high ${fmt(a.high_price * k, 2)}${k !== 1 ? ` ${esc(root)}` : ""}<b style="color:${col(a.high)}">${pc0(a.high)} already in</b>chance no new high before 16:00</div>
    <div class="card">Today's low ${fmt(a.low_price * k, 2)}${k !== 1 ? ` ${esc(root)}` : ""}<b style="color:${col(a.low)}">${pc0(a.low)} already in</b>chance no new low before 16:00</div>
    <div class="card">More likely to hold<b>the ${a.likely_first}</b>${a.likely_first === "high" ? "so the low is the side more likely to be taken out" : "so the high is the side more likely to be taken out"}</div></div>
    <p class="hint">${esc(a.note)}</p>`;
}
Object.assign(R, {
  async stackmap() {
    const want = { underlying: S.u, convention: $("conv").value, min_families: S.smk || 3, tol_pct: S.smt || 0.05 };
    const j = await api("/analytics/stack-map", want), m = j.meta, rg = j.regime, root = j.futures_root || "NQ", ix = uName(S.u);
    const k = j.spot_futures ? j.spot_futures / j.spot : 1, nqOn = k !== 1, F = v => v == null ? "-" : fmt(v * k, 2);
    const pill = c => `<span style="background:${CALLCOL[c][0]};color:${CALLCOL[c][1]};padding:3px 10px;border-radius:4px;font-weight:700;font-size:.85em">${c}</span>`;
    const chips = s => s.family_names.map(n => `<span class="badge" style="margin:0 4px 4px 0">${esc(n)}</span>`).join("");
    const card_ = s => `<div class="lmrow" style="border-left:4px solid ${CALLCOL[s.call][2]}">
      <div class="lmprice"><b>${F(s.center)}</b><span class="dim">${F(s.low)} to ${F(s.high)}</span><span class="dim">${s.points > 0 ? "+" : ""}${fmt(s.points * k, 1)} pts</span>
        <span style="color:${s.tier === "Very stacked" ? "#e6b422" : "#9aa3ad"};font-weight:700;margin-top:4px">${esc(s.tier.toUpperCase())}</span><span class="dim">${s.families.length} kinds, score ${fmt(s.score, 1)}</span></div>
      <div class="lmbody"><div>${pill(s.call)} <b>${esc(s.headline)}</b></div><div style="margin-top:6px">${chips(s)}</div><p>${esc(s.plan)}</p><p class="dim">${esc(s.why)}</p>
        <details><summary class="dim">What is stacked here (${s.members.length})</summary><div class="body">${s.members.map(x => `${F(x.price)} <b>${esc(x.family_name)}</b>: ${esc(x.label)}`).join("<br>")}</div></details></div>
      <div class="lmchance"><span class="dim">Chance price gets there today</span><b>${s.chance == null ? "-" : pc0(s.chance)}</b><span class="share"><i style="width:${Math.round((s.chance || 0) * 100)}%;background:${CALLCOL[s.call][2]}"></i></span></div></div>`;
    const above = j.stacks.filter(s => s.side === "above"), below = j.stacks.filter(s => s.side === "below");
    const inp = j.inputs;
    $("view").innerHTML = panel(`Stack map, ${S.u}`, m, `
      <div class="toolbar"><label>At least<select id="smk">${[2, 3, 4, 5].map(n => `<option value="${n}">${n} different kinds</option>`).join("")}</select></label>
        <label>Within<select id="smt">${[[0.03, "0.03% (tight)"], [0.05, "0.05%"], [0.08, "0.08% (loose)"]].map(([v, t]) => `<option value="${v}">${t} of price, about ${fmt(j.spot * k * v / 100, 0)} pts</option>`).join("")}</select></label>
        <span class="dim">${inp.levels} levels from ${Object.keys(inp.by_family).length} kinds went in. Prices in ${nqOn ? esc(root) : esc(ix)}.</span></div>
      <h3>Is the high or low of the day already in?</h3>${alreadyInCards(j.already_in, k, root)}
      <div id="smc" class="chart" style="height:560px"></div>
      <h3>${j.stacks.length ? `${j.stacks.length} stacked areas` : "No well-stacked areas right now"}</h3>
      ${j.stacks.length ? "" : note("Nothing passes the filter. Try 2 kinds or the looser distance.")}
      <div class="lm">${above.reverse().map(card_).join("")}
        <div class="lmnow"><b>PRICE NOW ${F(j.spot)}</b><span class="dim">${esc(rg.title)}: ${esc(rg.tagline)}</span></div>
        ${below.map(card_).join("")}</div>
      <details class="adv" data-k="sm-in"><summary>Everything that went in</summary><div class="body">${Object.entries(inp.by_family).map(([n, c]) => `${esc(n)}: ${c}`).join("<br>")}</div></details>
      <details class="adv" data-k="sm-rule"><summary>How stacks are found</summary><div class="body"><pre style="white-space:pre-wrap;font:inherit" class="dim">${esc(j.rule)}</pre></div></details>
      <p class="hint">${esc(j.note)}</p>`);
    $("smk").value = String(S.smk || 3); $("smt").value = String(S.smt || 0.05);
    $("smk").onchange = () => { S.smk = +$("smk").value; saveUI(); render(); };
    $("smt").onchange = () => { S.smt = +$("smt").value; saveUI(); render(); };
    const P = j.price, tl = P.map(p => etx(p.t).slice(11, 16)), tr = [], sh = [], an = [];
    if (P.length) tr.push({ type: "scatter", mode: "lines", x: tl, y: P.map(p => p.price * k), name: "Price", line: { color: "#fff", width: 2 }, hovertemplate: "Price %{y:,.2f}<extra></extra>" });
    const pad = Math.max(2, j.spot * k * 0.00012);
    j.stacks.forEach(s => {
      const col = CALLCOL[s.call][2], lo = s.low * k - pad, hi = s.high * k + pad, op = s.tier === "Very stacked" ? 0.34 : 0.2;
      sh.push({ type: "rect", xref: "paper", x0: 0, x1: 1, y0: lo, y1: hi, fillcolor: col, opacity: op, line: { color: col, width: 1 } });
      an.push({ xref: "paper", x: 1, xanchor: "left", y: s.center * k, text: `<b>${s.call}</b> ${F(s.center)} (${s.families.length})`, showarrow: false, font: { color: CALLCOL[s.call][1], size: 11 }, bgcolor: CALLCOL[s.call][0], borderpad: 3 });
      tr.push({ type: "scatter", mode: "markers", x: [tl[tl.length - 1] || ""], y: [s.center * k], marker: { size: 14, color: col, symbol: "diamond" }, showlegend: false,
        hovertemplate: `<b>${s.tier}: ${F(s.center)}</b><br>${s.call}: ${esc(s.headline)}<br>${s.family_names.join(", ")}<extra></extra>` });
    });
    if (j.high != null) { sh.push(hline(j.high * k, "#3fb96a", "dot")); sh.push(hline(j.low * k, "#e5534b", "dot")); }
    const ys = [...j.stacks.flatMap(s => [s.low * k, s.high * k]), ...P.map(p => p.price * k)];
    plot("smc", tr, LAY(`Stacked areas and today's price (${nqOn ? root : ix})`, { shapes: sh, annotations: an, showlegend: false, hovermode: "closest",
      xaxis: { type: "category", nticks: 12, gridcolor: "#1c2229" }, yaxis: { gridcolor: "#1c2229", tickformat: ",.0f", range: ys.length ? [Math.min(...ys) - 20 * k, Math.max(...ys) + 20 * k] : undefined },
      margin: { l: 60, r: 170, t: 40, b: 40 } }));
  }
});

// ---- Game plan (1.12): the whole team votes, the best two or three setups come out -------------------------------------
const GRADECOL = { A: ["#0f6e56", "#9FE1CB"], B: ["#185FA5", "#B5D4F4"], C: ["#854f0b", "#FAC775"], "No trade": ["#5f5e5a", "#D3D1C7"] };
Object.assign(R, {
  async gameplan() {
    const j = await api("/analytics/game-plan", { underlying: S.u, convention: $("conv").value }), m = j.meta;
    if (!j.available) { $("view").innerHTML = panel(`Game plan, ${S.u}`, m, note(j.reason)); return; }
    const root = j.futures_root || "NQ", nqOn = j.spot_futures != null, k = nqOn ? j.spot_futures / j.spot : 1, F = v => v == null ? "-" : fmt(v * k, 2), rg = j.regime;
    const icon = v => v === true ? '<b style="color:#3fb96a">&#10003;</b>' : v === false ? '<b style="color:#e5534b">&#10007;</b>' : '<span class="dim">&ndash;</span>';
    const gb = g => `<span style="background:${GRADECOL[g][0]};color:${GRADECOL[g][1]};padding:4px 12px;border-radius:6px;font-weight:800;font-size:1.1em">${g === "No trade" ? "NO TRADE" : "GRADE " + g}</span>`;
    const card_ = (c, i) => {
      const col = c.side === "LONG" ? "#3fb96a" : "#e5534b", stopPts = c.stop_dist * k, tgtPts = Math.abs(c.target - c.entry) * k;
      return `<div class="gpcard" style="border-top:4px solid ${col}">
        <div class="gphead">${gb(c.grade)}<span class="gpnum">#${i + 1}</span><b style="font-size:1.35em;color:${col}">${c.side} ${c.kind === "fade" ? "FADE" : "BREAK"}</b>
          <span>at the ${esc(c.label)} ${c.source === "stack" ? `(${c.kinds}-kind stack, ${c.call === "RESPECT" ? "HOLD" : "BREAK"})` : `(${c.call === "RESPECT" ? "HOLD" : "BREAK"} level)`}</span></div>
        <div class="gpnums">
          <div><span class="dim">${c.kind === "fade" ? "Entry (limit at the level)" : "Entry (on a push through)"}</span><b>${F(c.entry)}</b></div>
          <div><span class="dim">Stop</span><b style="color:#e5534b">${F(c.stop)}</b><span class="dim">${fmt(stopPts, 1)} pts</span></div>
          <div><span class="dim">Target</span><b style="color:#3fb96a">${F(c.target)}</b><span class="dim">${fmt(tgtPts, 1)} pts = ${fmt(c.r, 1)} R</span></div>
          <div><span class="dim">Price gets to the entry today</span><b>${pc0(c.chance)}</b></div>
          <div><span class="dim">Target before stop and close</span><b>${c.p_win == null ? "-" : pc0(c.p_win)}</b><span class="dim">${c.ev_r == null ? "" : "average " + (c.ev_r >= 0 ? "+" : "") + fmt(c.ev_r, 2) + " R"}</span></div></div>
        <div class="gpvotes"><b>The team: ${c.yes} for, ${c.no} against</b>
          ${c.votes.map(v => `<div>${icon(v.vote)} <b>${esc(v.name)}</b> <span class="${v.vote == null ? "dim" : ""}">${esc(v.reason)}</span></div>`).join("")}</div>
        <p class="dim" style="margin:8px 0 0">${esc(c.why)}</p></div>`;
    };
    const rc = j.record, ai = j.already_in;
    const recRows = rc.by_grade.map(g => `<tr><td>${gb(g.grade)}</td><td class="num">${g.cards}</td><td class="num">${g.target}</td><td class="num">${g.stop}</td><td class="num">${g.open + g.not_filled}</td>
      <td class="num"><b>${g.win_rate == null ? "-" : pc0(g.win_rate)}</b></td><td class="num">${g.avg_r == null ? "-" : (g.avg_r >= 0 ? "+" : "") + fmt(g.avg_r, 2) + " R"}</td></tr>`).join("");
    const outc = { target: '<b style="color:#3fb96a">target</b>', stop: '<b style="color:#e5534b">stop</b>', open: "filled, still open", "not filled": '<span class="dim">not filled</span>' };
    $("view").innerHTML = panel(`Game plan, ${S.u}`, m, `
      <div class="msg" style="border-color:${rg.color};background:#0f1318"><b style="font-size:1.3em;color:${rg.color}">${esc(rg.title)}</b> <span class="dim">${esc(rg.tagline)} Targets ${esc(rg.r_range)}.</span>
        <p style="margin:6px 0 0">Price ${F(j.spot)} ${nqOn ? esc(root) : ""} &middot; ${fmt(j.minutes_left, 0)} min left${ai ? ` &middot; high ${pc0(ai.high)} already in, low ${pc0(ai.low)} already in` : ""}</p></div>
      ${j.cards.length ? `<h3>Top ${j.cards.length} setup${j.cards.length > 1 ? "s" : ""} right now</h3><div class="gpgrid">${j.cards.map(card_).join("")}</div>`
        : `<h3>No trade right now</h3>${note(j.no_trade || "Nothing has more of the team for it than against it.")}`}
      ${j.more.length ? `<details class="adv" data-k="gp-more"><summary>${j.more.length} more setup${j.more.length > 1 ? "s" : ""} (lower ranked)</summary><div class="body gpgrid">${j.more.map((c, i) => card_(c, i + 3)).join("")}</div></details>` : ""}
      ${j.avoid.length ? `<h3>Stay away</h3><div class="scroll"><table><tr><th>Area</th><th>Why not</th></tr>${j.avoid.map(a => `<tr><td class="num"><b>${F(a.level ?? a.price)}</b><br><span class="dim">${esc(a.label)}</span></td>
        <td>${a.reason ? esc(a.reason) : `${a.side} ${a.kind}: ${a.yes} for, ${a.no} against. ` + a.votes.filter(v => v.vote === false).map(v => esc(v.name + ": " + v.reason)).join("; ")}</td></tr>`).join("")}</table></div>` : ""}
      <h3>Track record of the cards</h3>
      ${rc.cards ? `<div class="scroll"><table><tr><th>Grade</th><th>Cards</th><th>Hit target</th><th>Hit stop</th><th>Open or not filled</th><th>Win rate</th><th>Average</th></tr>${recRows}</table></div>
        <details class="adv" data-k="gp-recent"><summary>Latest cards and what happened</summary><div class="body scroll"><table><tr><th>Time</th><th>Card</th><th>Entry / stop / target</th><th>Result</th></tr>
        ${rc.recent.map(r => `<tr><td>${esc(etx(r.t).slice(5, 16))}</td><td>${esc(r.grade)} ${esc(r.side)} ${esc(r.kind)}<br><span class="dim">${esc(r.label)}</span></td><td class="num">${F(r.entry)} / ${F(r.stop)} / ${F(r.target)}</td><td>${outc[r.outcome] || esc(r.outcome)}</td></tr>`).join("")}</table></div></details>
        <p class="hint">${esc(rc.note)}</p>` : `<p class="dim">No cards logged yet. Every top card is saved once per half hour while the app runs and graded against what price did next.</p>`}
      <details class="adv" data-k="gp-rule"><summary>How the team votes</summary><div class="body"><pre style="white-space:pre-wrap;font:inherit" class="dim">${esc(j.rule)}</pre></div></details>
      <p class="hint">${esc(j.note)}</p>`);
  }
});
