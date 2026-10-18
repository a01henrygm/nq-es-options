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
