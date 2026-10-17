"use strict";
// Tabs added in 1.1: 0DTE GEX, Session charts, Before the open, Scorecard, Journal, Phone access, and the written case on Daily bias.
// Uses the helpers in app.js (api, panel, plot, LAY, note, fmt, big, esc, S, R).

const DIV = [[0, "#7b3fe4"], [0.42, "#3a2a66"], [0.5, "#14181d"], [0.58, "#1d4a7a"], [1, "#3fb6ff"]];     // purple negative, blue positive
const hline = (y, col, dash = "dash") => ({ type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: y, y1: y, line: { color: col, dash, width: 1.3 } });
const vline = (x, col, dash = "dot") => ({ type: "line", xref: "x", yref: "paper", x0: x, x1: x, y0: 0, y1: 1, line: { color: col, dash, width: 1.3 } });
const card = (t, v, sub = "") => `<div class="card">${t}<b>${v}</b>${sub}</div>`;
const uName = u => String(u || "").replace(/^_/, "");                        // Cboe writes _NDX; people say NDX
const etx = iso => new Date(iso).toLocaleString("sv-SE", { timeZone: "America/New_York" });     // chart times in Eastern Time on any PC
const pct = x => x == null ? "-" : Math.round(x * 100) + "%";
const sel = (id, opts, v) => `<select id="${id}">${opts.map(([k, n]) => `<option value="${esc(k)}" ${String(k) === String(v) ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>`;

Object.assign(R, {
  // ---- 0DTE ---------------------------------------------------------------------------------------------------------------
  async zerodte() {
    const j = await api("/analytics/zerodte", { underlying: S.u, convention: $("conv").value }), d = j.data, m = j.meta;
    if (!d.available) { $("view").innerHTML = panel(`0DTE GEX, ${S.u}`, m, note(d.reason, true)); return; }
    const tag = d.is_today ? "0DTE" : "Front expiry", K = d.strikes.map(s => s.strike), g0 = d.exposure_at_spot;
    $("view").innerHTML = panel(`${tag} gamma, ${S.u}`, m, `
      ${d.is_today ? "" : note(`Today's expiry has finished trading, so this shows the next one (${d.expiry}, ${fmt(d.days, 1)} days). It becomes 0DTE on its expiry day.`)}
      <div class="grid">${card("Expiry", esc(d.expiry), d.is_today ? "today (0DTE)" : `${fmt(d.days, 1)} days`)}
        ${card(`${tag} call wall`, d.call_wall == null ? "none" : fmt(d.call_wall, 0), d.call_wall == null ? "" : `${fmt(d.call_wall - m.spot, 0)} pts from price`)}
        ${card(`${tag} put wall`, d.put_wall == null ? "none" : fmt(d.put_wall, 0), d.put_wall == null ? "" : `${fmt(d.put_wall - m.spot, 0)} pts from price`)}
        ${card(`${tag} gamma flip`, d.flip == null ? "none" : fmt(d.flip, 0), d.flip == null ? esc(d.flip_note) : `price is ${m.spot > d.flip ? "above" : "below"}`)}
        ${card("Dealer gamma at price", g0 == null ? "-" : `<span style="color:${g0 >= 0 ? "#3fb96a" : "#e5534b"}">${g0 >= 0 ? "Long" : "Short"}</span>`, g0 == null ? "" : big(g0) + (g0 >= 0 ? ": moves get absorbed" : ": moves can extend"))}
        ${card(`${tag} share of gamma`, pct(d.gross_share), "of all gamma near price")}</div>
      <div id="z1" class="chart"></div><div id="z2" class="chart"></div>
      <p class="dim">${esc(d.rule)} Units: ${esc(d.units)}. Sign scenario: ${esc(d.convention)}. Biggest positive strikes: ${d.top_positive.map(k => fmt(k, 0)).join(", ") || "-"}; biggest negative: ${d.top_negative.map(k => fmt(k, 0)).join(", ") || "-"}.</p>`);
    const sh = [vline(m.spot, "#fff")].concat(d.flip ? [vline(d.flip, "#ffd166", "dash")] : []);
    plot("z1", [{ type: "bar", x: K, y: d.strikes.map(s => s.call_gex), name: "Calls", marker: { color: "#22d3ee" } }, { type: "bar", x: K, y: d.strikes.map(s => s.put_gex), name: "Puts", marker: { color: "#ff4d8d" } },
      { type: "scatter", mode: "lines", x: K, y: d.strikes.map(s => s.net_gex), name: "Net", line: { color: "#fff", width: 2 } }],
      LAY(`${tag} GEX by strike (white dotted = price, yellow dashed = ${tag} flip)`, { barmode: "relative", shapes: sh, xaxis: { title: "Strike", gridcolor: "#262c34" } }));
    const T = j.today, ln = (k, n, c, dash) => T[k] && T[k].length ? [{ type: "scatter", mode: "lines", x: T[k].map(p => etx(p.t)), y: T[k].map(p => p.value), name: n, line: { color: c, width: 2, dash, shape: "hv" } }] : [];
    if (j.price.length) plot("z2", [{ type: "scatter", mode: "lines", x: j.price.map(p => etx(p.t)), y: j.price.map(p => p.price), name: "Price", line: { color: "#fff", width: 2 } }]
      .concat(ln("gex0_call_wall", `${tag} call wall`, "#22d3ee"), ln("gex0_put_wall", `${tag} put wall`, "#ff4d8d"), ln("gex0_flip", `${tag} flip`, "#ffd166", "dash")),
      LAY(`Price against today's ${tag} walls and flip (ET)`, { xaxis: { gridcolor: "#262c34" } }));
    else $("z2").innerHTML = '<p class="dim">The through-the-day chart fills in as the app collects data today.</p>';
  },

  // ---- session charts -----------------------------------------------------------------------------------------------------
  async session() {
    const j = await api("/charts/session", { underlying: S.u, day: S.sday || "", scope: S.sscope || "all" });
    const days = j.days.length ? j.days : [j.day];
    $("view").innerHTML = panel(`Session charts, ${S.u}, ${j.day}`, null, `
      <div class="toolbar"><label>Day${sel("sday", days.map(d => [d, d]), j.day)}</label><label>GEX map uses${sel("sscope", [["all", "All expiries"], ["0dte", "0DTE only"]], j.scope)}</label></div>
      ${j.gex_map.times.length ? "" : note("Nothing stored for this day yet. The charts fill in while the app collects data (about every 2 minutes during the session).")}
      <h3>1. Dealer gamma by strike through the day</h3><div id="s1" class="chart tall"></div><p class="hint">${esc(j.notes.gex_map)} Blue = positive gamma (moves get absorbed), purple = negative (moves can extend). White = price, gold dashed = gamma flip, green / red = call and put walls.</p>
      <h3>2. Price against the expected-move cone</h3><div id="s2" class="chart"></div><p class="hint">${esc(j.notes.cone)}${j.day_move ? ` Today's expected move: ${fmt(j.day_move.points, 0)} points.` : ""}</p>
      <h3>3. Dealer gamma at the current price</h3><div id="s3" class="chart"></div><p class="hint">${esc(j.notes.gamma)} Bars use every expiry; the cyan line is 0DTE only.</p>
      <h3>4. Call vs put volume through the day</h3><div id="s4" class="chart"></div><p class="hint">${esc(j.notes.flow)} When price rises while the net line falls (puts winning), the move has less support.</p>`);
    $("sday").onchange = () => { S.sday = $("sday").value; render(); };
    $("sscope").onchange = () => { S.sscope = $("sscope").value; render(); };
    const px = j.price, priceTr = (yaxis) => ({ type: "scatter", mode: "lines", x: px.map(p => etx(p.t)), y: px.map(p => p.price), name: "Price", line: { color: "#fff", width: 2 }, yaxis });
    const step = (arr, n, c, dash) => arr.length ? [{ type: "scatter", mode: "lines", x: arr.map(p => etx(p.t)), y: arr.map(p => p.value), name: n, line: { color: c, width: 1.6, dash, shape: "hv" } }] : [];
    const G = j.gex_map;
    const pv = px.map(p => p.price), pad = pv.length ? Math.max(0.006 * pv[pv.length - 1], (j.day_move ? j.day_move.points : 0) * 1.5) : 0;
    const yr = pv.length ? [Math.min(...pv) - pad, Math.max(...pv) + pad] : undefined;
    if (G.times.length) plot("s1", [{ type: "heatmap", x: G.times.map(etx), y: G.strikes, z: G.z, colorscale: DIV, zmid: 0, colorbar: { title: "Net GEX", thickness: 12 }, hoverongaps: false, name: "Net GEX",
        hovertemplate: "%{x}<br>Strike %{y}<br>Net GEX %{z:.3s}<extra></extra>" }, priceTr("y")].concat(step(j.flip, "Gamma flip", "#e6b422", "dash"), step(j.call_wall, "Call wall", "#3fb96a"), step(j.put_wall, "Put wall", "#e5534b")),
      LAY("Net GEX by strike over the session (ET)", { yaxis: { title: "Strike / price", gridcolor: "#262c34", range: yr }, margin: { l: 70, r: 20, t: 44, b: 90 } }));
    if (j.cone.length) {
      const C = j.cone, x = C.map(c => etx(c.t));
      plot("s2", [{ type: "scatter", mode: "lines", x, y: C.map(c => c.up2), line: { width: 0 }, hoverinfo: "skip", showlegend: false },
        { type: "scatter", mode: "lines", x, y: C.map(c => c.dn2), fill: "tonexty", fillcolor: "rgba(125,183,255,0.10)", line: { width: 0 }, name: "2 x expected move" },
        { type: "scatter", mode: "lines", x, y: C.map(c => c.up1), line: { width: 0 }, hoverinfo: "skip", showlegend: false },
        { type: "scatter", mode: "lines", x, y: C.map(c => c.dn1), fill: "tonexty", fillcolor: "rgba(125,183,255,0.22)", line: { width: 0 }, name: "1 x expected move" },
        { type: "scatter", mode: "lines", x, y: C.map(c => c.up1), line: { color: "#7db7ff", width: 1, dash: "dot" }, showlegend: false, hoverinfo: "skip" },
        { type: "scatter", mode: "lines", x, y: C.map(c => c.dn1), line: { color: "#7db7ff", width: 1, dash: "dot" }, showlegend: false, hoverinfo: "skip" },
        priceTr("y")], LAY("Price inside the expected-move cone from the 9:30 price", { shapes: j.open ? [hline(j.open.price, "#8a8f98", "dot")] : [] }));
    } else $("s2").innerHTML = '<p class="dim">No cone for this day: it needs a price within 30 minutes of 9:30 and a stored expected move.</p>';
    if (j.gamma_at_spot.length) {
      const g = j.gamma_at_spot;
      plot("s3", [{ type: "bar", x: g.map(p => etx(p.t)), y: g.map(p => p.value), name: "Dealer gamma at price (all expiries)", marker: { color: g.map(p => p.value >= 0 ? "#3fb96a" : "#e5534b") } },
        ...(j.gamma0_at_spot.length ? [{ type: "scatter", mode: "lines", x: j.gamma0_at_spot.map(p => etx(p.t)), y: j.gamma0_at_spot.map(p => p.value), name: "0DTE only", line: { color: "#22d3ee", width: 2 } }] : []),
        priceTr("y2")], LAY("Long gamma (green) or short gamma (red) at the current price", { shapes: [hline(0, "#8a8f98", "solid")], yaxis2: { overlaying: "y", side: "right", showgrid: false, title: "Price" } }));
    } else $("s3").innerHTML = '<p class="dim">Nothing stored yet for this day.</p>';
    if (j.flow.length) {
      const f = j.flow;
      plot("s4", [{ type: "scatter", mode: "lines", x: f.map(p => etx(p.t)), y: f.map(p => p.net), name: "Calls minus puts", fill: "tozeroy", line: { color: "#a35bff", width: 2 }, fillcolor: "rgba(163,91,255,0.15)" },
        { type: "scatter", mode: "lines", x: f.map(p => etx(p.t)), y: f.map(p => p.calls), name: "Calls", line: { color: "#3fb96a", width: 1.2, dash: "dot" } },
        { type: "scatter", mode: "lines", x: f.map(p => etx(p.t)), y: f.map(p => p.puts), name: "Puts", line: { color: "#e5534b", width: 1.2, dash: "dot" } }, priceTr("y2")],
        LAY("Cumulative option volume: calls vs puts", { shapes: [hline(0, "#8a8f98", "solid")], yaxis2: { overlaying: "y", side: "right", showgrid: false, title: "Price" } }));
    } else $("s4").innerHTML = '<p class="dim">Nothing stored yet for this day.</p>';
  },

  // ---- before the open ----------------------------------------------------------------------------------------------------
  async preopen() {
    const j = await api("/charts/preopen", { underlying: S.u, convention: $("conv").value }), m = j.meta, G = j.gamma_curve;
    $("view").innerHTML = panel(`Before the open, ${S.u}`, m, `
      <h3>5. Gamma curve: dealer exposure if price moved</h3><div id="p1" class="chart"></div><p class="hint">${esc(j.notes.gamma_curve)} The 0DTE curve (cyan, right axis) is today's expiry alone.</p>
      <h3>6. What changed overnight</h3><div id="p2" class="chart"></div><div id="p3" class="chart"></div><p class="hint">${esc(j.notes.gex_change)} Open interest change compares the last two stored sessions.</p>
      <h3>7. Volatility and skew across sessions</h3><div id="p4" class="chart"></div><div id="p5" class="chart"></div><p class="hint">${esc(j.notes.vol_days)}</p>`);
    if (G.all.length) plot("p1", [{ type: "scatter", mode: "lines", x: G.all.map(g => g.price), y: G.all.map(g => g.total_gex), name: "All expiries", line: { color: "#5b7bff", width: 2.5 }, fill: "tozeroy", fillcolor: "rgba(91,123,255,0.10)" },
      ...(G.zero && G.zero.length ? [{ type: "scatter", mode: "lines", x: G.zero.map(g => g.price), y: G.zero.map(g => g.total_gex), name: "0DTE only", line: { color: "#22d3ee", width: 1.8 }, yaxis: "y2" }] : [])],
      LAY("Total dealer gamma at hypothetical prices", { shapes: [vline(G.spot, "#fff"), hline(0, "#e5534b", "solid")].concat(G.flip ? [vline(G.flip, "#e6b422", "dash")] : []).concat(G.zero_flip ? [vline(G.zero_flip, "#ffd166", "dot")] : []),
        xaxis: { title: "Price", gridcolor: "#262c34" }, yaxis2: { overlaying: "y", side: "right", showgrid: false, title: "0DTE" } }));
    else $("p1").innerHTML = '<p class="dim">The gamma curve needs open interest and implied volatility.</p>';
    const gc = j.gex_change;
    if (gc && gc.rows.length) plot("p2", [{ type: "bar", x: gc.rows.map(r => r.strike), y: gc.rows.map(r => r.change), name: "Change in net GEX", marker: { color: gc.rows.map(r => r.change >= 0 ? "#3fb6ff" : "#a35bff") } }],
      LAY("Net GEX by strike: now minus the previous session's close", { shapes: [vline(m.spot, "#fff")], xaxis: { title: "Strike", gridcolor: "#262c34" } }));
    else $("p2").innerHTML = '<p class="dim">Needs a stored GEX profile from the previous session (the app must have run then).</p>';
    const oc = j.oi_change;
    if (oc && oc.available) plot("p3", [{ type: "bar", x: oc.change_by_strike.map(r => r.strike), y: oc.change_by_strike.map(r => r.call), name: "Calls added / removed", marker: { color: "#3fb96a" } },
      { type: "bar", x: oc.change_by_strike.map(r => r.strike), y: oc.change_by_strike.map(r => r.put), name: "Puts added / removed", marker: { color: "#e5534b" } }],
      LAY("Open interest change by strike since the previous session", { barmode: "group", shapes: [vline(m.spot, "#fff")], xaxis: { title: "Strike", gridcolor: "#262c34" } }));
    else $("p3").innerHTML = `<p class="dim">${esc((oc && oc.reason) || "Needs two sessions of stored data.")}</p>`;
    const V = j.vol_days, ln = (k, n, c, ax, mul = 100) => V[k] && V[k].length ? [{ type: "scatter", mode: "lines+markers", x: V[k].map(p => p.day), y: V[k].map(p => p.value * mul), name: n, line: { color: c, width: 2 }, yaxis: ax }] : [];
    const tr = ln("atm_iv_front", "Front ATM IV %", "#ff7a2e", "y").concat(ln("iv_mid", "3-week ATM IV %", "#5b7bff", "y"), ln("skew_25d", "25-delta skew (pts)", "#e5534b", "y2", 1));
    if (tr.length) plot("p4", tr, LAY("Implied volatility and skew, one point per session", { xaxis: { type: "category", gridcolor: "#262c34" }, yaxis: { title: "IV %", gridcolor: "#262c34" }, yaxis2: { overlaying: "y", side: "right", showgrid: false, title: "Skew" } }));
    else $("p4").innerHTML = '<p class="dim">Builds up one point per session.</p>';
    const ts = j.term_structure;
    if (ts.length) plot("p5", [{ type: "scatter", mode: "lines+markers", x: ts.map(t => t.expiry), y: ts.map(t => t.iv * 100), name: "ATM IV %", line: { color: "#a35bff", width: 2 } }],
      LAY("Today's term structure: ATM IV by expiry (front above back = stress)", { yaxis: { title: "IV %", gridcolor: "#262c34" } }));
  },

  // ---- scorecard ----------------------------------------------------------------------------------------------------------
  async scorecard() {
    const j = await api("/charts/scorecard", { underlying: S.u, days: 30 }), L = j.levels, D = j.regime_days;
    const rows = L.map(r => `<tr><td>${esc(r.kind)}</td><td class="num">${r.touches}</td><td class="num">${pct(r.held_pct_15)}</td><td class="num">${pct(r.held_pct_30)}</td>
      <td class="num">${r.avg_points_30 == null ? "-" : (r.avg_points_30 > 0 ? "+" : "") + fmt(r.avg_points_30, 1)}</td><td class="num">${r.avg_best_bounce == null ? "-" : fmt(r.avg_best_bounce, 1)}</td>
      <td>${r.enough_data ? "" : '<span class="dim">small sample</span>'}</td></tr>`).join("");
    $("view").innerHTML = panel(`Scorecard, ${S.u}`, null, `
      <h3>8. Which levels held</h3>${L.length ? `<div id="k1" class="chart"></div><div class="scroll"><table><tr><th>Level type</th><th>Touches</th><th>Held after 15 min</th><th>Held after 30 min</th><th>Avg points after 30 min</th><th>Avg best bounce</th><th></th></tr>${rows}</table></div>` : note("No touches recorded yet. The app records them as price meets each session's levels.")}
      <p class="hint">${esc(j.method)} ${esc(j.note)}</p>
      <h3>9. Regime call vs the day's real range</h3>${D.length ? '<div id="k2" class="chart"></div>' : note("Needs sessions where the app ran between 9:35 and 10:30 ET (it stores the opening regime then).")}
      <p class="hint">Each bar is a day's 9:30-16:00 range divided by that morning's expected move. "Pinned" or calm days should sit low; "trending" days high.</p>`);
    if (L.length) plot("k1", [{ type: "bar", x: L.map(r => r.kind), y: L.map(r => r.held_pct_15 == null ? null : r.held_pct_15 * 100), name: "Held after 15 min %", marker: { color: "#5b7bff" } },
      { type: "bar", x: L.map(r => r.kind), y: L.map(r => r.held_pct_30 == null ? null : r.held_pct_30 * 100), name: "Held after 30 min %", marker: { color: "#a35bff" } }],
      LAY("How often price held each level type after a touch", { barmode: "group", yaxis: { title: "%", range: [0, 100], gridcolor: "#262c34" }, shapes: [hline(50, "#8a8f98", "dot")] }));
    if (D.length) plot("k2", [{ type: "bar", x: D.map(d => d.date), y: D.map(d => d.range_vs_move), text: D.map(d => d.label), marker: { color: D.map(d => regCol(d.label || "")) },
        hovertemplate: "%{x}<br>%{text}<br>range = %{y:.2f} x expected move<extra></extra>", name: "Range / expected move" }],
      LAY("Day's range as a multiple of the expected move, colored by the opening regime", { shapes: [hline(1, "#8a8f98", "dot")], yaxis: { title: "x expected move", gridcolor: "#262c34" } }));
  },

  // ---- journal ------------------------------------------------------------------------------------------------------------
  async journal() {
    const j = await api("/journal"), T = j.trades, st = j.stats;
    const pts = t => t.points == null ? '<span class="dim">open</span>' : `<b style="color:${t.points > 0 ? "#3fb96a" : t.points < 0 ? "#e5534b" : "#ddd"}">${t.points > 0 ? "+" : ""}${fmt(t.points * (t.qty || 1), 2)}</b>`;
    const rows = T.map(t => { const c = t.context || {};
      return `<tr><td>${etStamp(t.opened_at) || "-"}</td><td>${esc(t.instrument)} <b style="color:${t.side === "long" ? "#3fb96a" : "#e5534b"}">${t.side}</b> x${fmt(t.qty, 0)}</td>
        <td class="num">${fmt(t.entry, 2)}</td><td class="num">${t.exit == null ? `<input data-exit="${t.id}" size="8" placeholder="exit"> <button data-close="${t.id}">Close</button>` : fmt(t.exit, 2)}</td><td class="num">${pts(t)}</td>
        <td>${esc(c.nearest_level || "-")}${c.distance != null ? ` <span class="dim">(${fmt(c.distance, 1)} away)</span>` : ""}</td><td>${esc(c.regime || "-")}</td><td>${esc(c.with_bias || "-")}</td><td>${esc(t.setup || "")}${t.note ? ` <span class="dim">${esc(t.note)}</span>` : ""}</td>
        <td><button data-deltrade="${t.id}" title="Delete this trade">x</button></td></tr>`; }).join("");
    const grp = (name) => { const g = st.groups[name] || []; return g.length ? `<div class="card" style="min-width:260px"><span>${esc(name)}</span><table>${g.map(r => `<tr><td>${esc(r.key)}</td><td class="num">${r.trades}</td><td class="num">${pct(r.win_rate)}</td><td class="num" style="color:${r.avg_points >= 0 ? "#3fb96a" : "#e5534b"}">${r.avg_points > 0 ? "+" : ""}${fmt(r.avg_points, 1)}</td></tr>`).join("")}</table></div>` : ""; };
    $("view").innerHTML = panel("Trade journal", null, `
      <div class="row journal-form">
        <label>Instrument${sel("tj_inst", [["NQ", "NQ"], ["MNQ", "MNQ"], ["ES", "ES"], ["MES", "MES"]], S.tjInst || "NQ")}</label>
        <label>Side${sel("tj_side", [["long", "Long"], ["short", "Short"]], "long")}</label>
        <label>Qty<input id="tj_qty" size="3" value="1"></label><label>Entry<input id="tj_entry" size="9" placeholder="price"></label>
        <label>Stop<input id="tj_stop" size="9"></label><label>Target<input id="tj_target" size="9"></label><label>Exit (if closed)<input id="tj_exit" size="9"></label>
        <label>Setup<input id="tj_setup" size="14" placeholder="e.g. Wall bounce" list="tj_setups"></label><label>Note<input id="tj_note" size="22"></label>
        <button class="go" id="tj_add">Log trade</button></div>
      <datalist id="tj_setups">${[...new Set(T.map(t => t.setup).filter(Boolean))].map(s => `<option value="${esc(s)}">`).join("")}</datalist>
      <p class="hint">The app saves which level was nearest your entry, the regime, the bias and which side of the gamma flip price was on, at the moment you log the trade. Prices are in the units you trade (with a saved basis they match the mapped levels).</p>
      <div class="grid">${card("Closed trades", st.closed, `${st.open} open`)}${card("Win rate", pct(st.win_rate))}${card("Total points", st.total_points ? (st.total_points > 0 ? "+" : "") + fmt(st.total_points, 1) : "0")}${card("Average per trade", st.avg_points == null ? "-" : fmt(st.avg_points, 2))}</div>
      ${st.closed ? `<h3>Where your results come from</h3><p class="dim">Each row: trades, win rate, average points.</p><div class="grid wide">${["Nearest level", "Regime", "With or against the bias", "Gamma side", "Time of day", "Setup"].map(grp).join("")}</div>` : ""}
      <h3>Trades</h3><div class="scroll"><table><tr><th>Opened (ET)</th><th>Trade</th><th>Entry</th><th>Exit</th><th>Points</th><th>Nearest level</th><th>Regime</th><th>Bias</th><th>Setup / note</th><th></th></tr>${rows || '<tr><td colspan="10" class="dim">No trades yet.</td></tr>'}</table></div>`);
    const num = id => { const v = parseFloat($(id).value); return isNaN(v) ? null : v; };
    $("tj_add").onclick = async () => {
      const body = { instrument: $("tj_inst").value, side: $("tj_side").value, qty: num("tj_qty") || 1, entry: num("tj_entry"), stop: num("tj_stop"), target: num("tj_target"), exit: num("tj_exit"), setup: $("tj_setup").value, note: $("tj_note").value };
      if (!body.entry) return alert("Enter the entry price.");
      S.tjInst = body.instrument;
      const r = await fetch("/api/journal" + (S.src ? "?source=" + S.src : ""), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!r.ok) { const e = await r.json().catch(() => ({})); return alert("Could not save: " + (e.detail || r.status)); }
      render();
    };
    document.querySelectorAll("[data-close]").forEach(b => b.onclick = async () => {
      const v = parseFloat(document.querySelector(`[data-exit="${b.dataset.close}"]`).value); if (isNaN(v)) return alert("Type the exit price first.");
      await fetch(`/api/journal/${b.dataset.close}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ exit: v }) }); render(); });
    document.querySelectorAll("[data-deltrade]").forEach(b => b.onclick = async () => { if (!confirm("Delete this trade?")) return; await fetch(`/api/journal/${b.dataset.deltrade}`, { method: "DELETE" }); render(); });
  },

  // ---- phone access -------------------------------------------------------------------------------------------------------
  async phone() {
    const j = await api("/phone"), dsk = await fetch("/api/desktop/info").then(r => r.ok ? r.json() : null).catch(() => null);
    const urls = j.lan_urls.concat(j.tailscale_urls);
    $("view").innerHTML = panel("Phone access", null, `
      <div class="msg" style="border-color:${j.enabled ? "#3fb96a" : "#8a8f98"}"><b>${j.enabled ? "On" : "Off"}</b> <span class="dim">${j.enabled ? "Other devices can open the dashboard with your password." : "Only this PC can open the dashboard."}</span></div>
      ${j.enabled ? `<div class="grid" style="align-items:flex-start"><div class="card" style="min-width:300px">On the same Wi-Fi, open<b style="font-size:1.1em">${j.lan_urls.map(esc).join("<br>") || "no network address found"}</b>
          ${j.tailscale_urls.length ? `From anywhere (Tailscale)<b style="font-size:1.1em">${j.tailscale_urls.map(esc).join("<br>")}</b>` : ""}</div>
        ${j.qr ? `<div class="card" style="background:#fff;padding:10px;width:180px">${j.qr}<span style="color:#333">Scan with your phone's camera</span></div>` : ""}</div>` : ""}
      <h3>${j.enabled ? "Change the password or turn it off" : "Turn it on"}</h3>
      <div class="row"><label>Password (8+ characters)<input id="ph_pw" type="password" size="18" placeholder="${j.password_set ? "leave empty to keep the current one" : ""}"></label>
        <button class="go" id="ph_on">${j.enabled ? "Save" : "Turn on phone access"}</button>${j.enabled ? '<button id="ph_off">Turn off</button>' : ""}<span id="ph_msg" class="dim"></span></div>
      <h3>From anywhere, safely: Tailscale</h3>
      <ol><li>Install <b>Tailscale</b> (free) on this PC and on your phone, and sign in to both with the same account.</li>
        <li>Turn phone access on above. The "From anywhere" address (it starts with 100.) appears here after the restart.</li>
        <li>Open that address on your phone, from any network. Tailscale encrypts the connection and nothing is opened to the internet.</li></ol>
      <p class="hint">On Wi-Fi the connection is plain http inside your home network, so use a password you don't use elsewhere. Windows or macOS may ask once to let Q DATA accept connections: allow it (on Windows, for private networks).
        Settings are stored in ${esc(j.env_file)}.</p>`);
    const save = async (enabled) => {
      const r = await fetch("/api/phone", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled, password: ($("ph_pw") || {}).value || "" }) });
      const e = await r.json().catch(() => ({}));
      if (!r.ok) { $("ph_msg").textContent = e.detail || "Could not save."; return; }
      if (dsk && dsk.desktop) { $("ph_msg").textContent = "Saved. Restarting the app..."; await fetch("/api/desktop/restart", { method: "POST" }).catch(() => null); }
      else $("ph_msg").textContent = "Saved. Close the black window (or run stop.bat) and start the app again for this to take effect.";
    };
    $("ph_on").onclick = () => save(true);
    if ($("ph_off")) $("ph_off").onclick = () => save(false);
  },
});

// ---- Daily bias: add the written case above the scorecard ------------------------------------------------------------------
const _biasBase = R.bias;
R.bias = async function () {
  await _biasBase();
  let j; try { j = await api("/analytics/bias-case", { underlying: S.u, convention: $("conv").value }); } catch (e) { return; }
  const c = j.case, col = c.lean.includes("ull") ? "#3fb96a" : c.lean.includes("ear") ? "#e5534b" : "#8a8f98";
  const li = p => `<li><b>${esc(p.title)}</b>${p.weight > 1 ? ' <span class="badge">strong</span>' : ""}<br><span class="dim">${esc(p.detail)}</span></li>`;
  const tg = xs => xs.length ? xs.map(x => fmt(x, 0)).join(" → ") : "none found";
  const box = document.createElement("div");
  box.className = "case";
  box.innerHTML = `<h3>The case for today: <span style="color:${col}">${esc(c.lean)}</span></h3><p>${esc(c.summary)}</p>
    <div class="cols2"><div class="side bull"><h4>Why it may go up <span class="dim">(weight ${c.bull_weight})</span></h4><ul>${c.bull.map(li).join("") || '<li class="dim">Nothing points up right now.</li>'}</ul></div>
      <div class="side bear"><h4>Why it may go down <span class="dim">(weight ${c.bear_weight})</span></h4><ul>${c.bear.map(li).join("") || '<li class="dim">Nothing points down right now.</li>'}</ul></div></div>
    ${c.neutral.length ? `<h4>Context</h4><ul>${c.neutral.map(li).join("")}</ul>` : ""}
    <div class="cols2"><div class="side bull"><h4>Bullish plan</h4><p>Trigger: <b>${esc(c.plan.bull.trigger)}</b><br>Targets: <b>${tg(c.plan.bull.targets)}</b><br><span class="dim">Wrong if: ${esc(c.plan.bull.invalidation)}</span></p></div>
      <div class="side bear"><h4>Bearish plan</h4><p>Trigger: <b>${esc(c.plan.bear.trigger)}</b><br>Targets: <b>${tg(c.plan.bear.targets)}</b><br><span class="dim">Wrong if: ${esc(c.plan.bear.invalidation)}</span></p></div></div>
    <p class="hint">${esc(c.note)} Prices are in ${esc(S.u)} units; the Levels tab converts them to futures points.</p>`;
  const p = $("view").querySelector(".panel"), after = p && p.querySelector(".grid");
  if (after) after.after(box); else if (p) p.appendChild(box);
};

// ---- Home: the lean, the regime, and a ladder of the key levels around price ------------------------------------------------
function ladderSVG(all, price, units) {
  const W = 360, H = 600, padT = 18, padB = 18, axis = 104;
  if (!all.length || price == null) return '<p class="dim">No levels yet.</p>';
  const up = all.filter(l => l.v >= price).sort((a, b) => a.v - b.v), dn = all.filter(l => l.v < price).sort((a, b) => b.v - a.v);
  const levels = up.slice(0, 6).concat(dn.slice(0, 6)), hidden = all.length - levels.length;
  // square-root spacing around price: nearby levels get room, far ones stay on the ladder (their point distance is printed beside them)
  const far = Math.max(...levels.map(l => Math.abs(l.v - price)), 1) * 1.08, mid = (H - padT - padB) / 2 + padT, half = (H - padT - padB) / 2;
  const y = v => mid - Math.sign(v - price) * Math.sqrt(Math.min(Math.abs(v - price), far) / far) * half;
  // keep labels from overlapping: walk down the ladder and push each label at least 17px below the previous one
  const py0 = y(price);
  const rows = levels.map(l => ({ ...l, y: y(l.v) })).concat([{ price: true, y: py0 }]).sort((a, b) => a.y - b.y);
  let last = -1e9; rows.forEach(r => { r.ly = Math.max(r.y, last + (r.price || (rows[rows.indexOf(r) - 1] || {}).price ? 22 : 17)); last = r.ly; });
  const over = last - (H - padB); if (over > 0) { rows.forEach(r => r.ly -= over); }
  const py = rows.find(r => r.price).ly, col = c => (CATCOL[c] || "#8B95AD");
  const trunc = t => t.length > 26 ? t.slice(0, 25) + "…" : t;
  const parts = [`<line x1="${axis}" x2="${axis}" y1="${padT}" y2="${H - padB}" stroke="#2A3554" stroke-width="1.5"/>`];
  rows.filter(r => !r.price).forEach(r => {
    const c = col(r.cat);
    if (r.lo != null && r.hi != null) parts.push(`<rect x="${axis - 7}" width="14" y="${y(r.hi)}" height="${Math.max(2, y(r.lo) - y(r.hi))}" rx="3" fill="${c}" fill-opacity=".28" stroke="${c}" stroke-opacity=".6"/>`);
    parts.push(`<line x1="${axis - 10}" x2="${axis + 10}" y1="${r.y}" y2="${r.y}" stroke="${c}" stroke-width="2.5"/>`);
    if (Math.abs(r.ly - r.y) > 1) parts.push(`<path d="M${axis + 10} ${r.y} L${axis + 18} ${r.ly}" stroke="${c}" stroke-opacity=".5" fill="none"/>`);
    const d = r.v - price;
    parts.push(`<text x="${axis - 16}" y="${r.ly + 4}" text-anchor="end" font-size="11.5" fill="${d > 0 ? "#3FB96A" : "#E5534B"}">${d > 0 ? "+" : ""}${fmt(d, 0)}</text>`);
    parts.push(`<text x="${axis + 22}" y="${r.ly + 4}" font-size="12" fill="#E7ECF5">${esc(trunc(r.label))}</text>`);
    parts.push(`<text x="${W - 4}" y="${r.ly + 4}" text-anchor="end" font-size="12" font-weight="700" fill="${c}">${fmt(r.v, 0)}</text>`);
  });
  parts.push(`<line x1="${axis}" x2="${W}" y1="${py}" y2="${py}" stroke="#E7ECF5" stroke-opacity=".55" stroke-width="1" stroke-dasharray="3 4"/>`,
    `<rect x="2" y="${py - 11}" width="${axis - 6}" height="22" rx="11" fill="url(#qg)"/>`,
    `<text x="${(axis - 4) / 2 + 2}" y="${py + 4.5}" text-anchor="middle" font-size="12.5" font-weight="800" fill="#fff">${fmt(price, 2)}</text>`,
    `<circle cx="${axis}" cy="${py}" r="4" fill="#fff"/>`);
  if (hidden > 0) parts.push(`<text x="${W - 4}" y="${H - 2}" text-anchor="end" font-size="11" fill="#5D6884">${hidden} farther level${hidden > 1 ? "s" : ""} on Key levels</text>`);
  return `<svg class="ladder" viewBox="0 0 ${W} ${H}" role="img" aria-label="Key levels above and below price, in ${esc(units)}">
    <defs><linearGradient id="qg" x1="0" x2="1"><stop offset="0" stop-color="#3D8BFF"/><stop offset="1" stop-color="#8B5CF6"/></linearGradient></defs>${parts.join("")}</svg>`;
}

R.home = async function () {
  const conv = $("conv").value;
  const [lv, cs, rg, zd, ss] = await Promise.all([
    api("/analytics/levels", { underlying: S.u, convention: conv, method: $("method").value, top: S.lvtop, by_expiry: S.lvexp, mid: S.lvmid, moves: S.lvmov, ...(S.lvq ? { quota: quotaFor() } : { key: Math.max(S.lvkey || 0, 12) }) }),
    api("/analytics/bias-case", { underlying: S.u, convention: conv }).catch(() => null),
    api("/analytics/regime", { underlying: S.u, convention: conv }).catch(() => null),
    api("/analytics/zerodte", { underlying: S.u, convention: conv }).catch(() => null),
    api("/charts/session", { underlying: S.u }).catch(() => null)]);
  const m = lv.meta, zones = lv.zones.length ? lv.zones : lv.levels;
  const mapped = zones.filter(z => z.mapped && z.mapped.mapped != null && z.mapped.status !== "invalid");
  const useF = mapped.length > 0, root = lv.mapping.futures_root;
  const offs = mapped.map(z => z.mapped.mapped - z.value).sort((a, b) => a - b), off = useF ? offs[Math.floor(offs.length / 2)] : 0;
  const L = zones.map(z => ({ label: z.label, cat: z.category, v: useF && z.mapped && z.mapped.mapped != null ? z.mapped.mapped : z.value,
    lo: z.low == null ? null : (useF && z.mapped_low != null ? z.mapped_low : z.low), hi: z.high == null ? null : (useF && z.mapped_high != null ? z.mapped_high : z.high) }));
  const price = m.spot + off, units = useF ? `${root} points (estimated)` : `${S.u} units`;
  const c = cs && cs.case, lean = c ? c.lean : "No read yet", lc = lean.includes("ull") ? "var(--ok)" : lean.includes("ear") ? "var(--bad)" : "var(--dim)";
  const r = rg && rg.data, z = zd && zd.data, em = cs && null;
  const above = L.filter(l => l.v > price).sort((a, b) => a.v - b.v)[0], below = L.filter(l => l.v < price).sort((a, b) => b.v - a.v)[0];
  const top = (arr) => arr.slice().sort((a, b) => b.weight - a.weight).slice(0, 3).map(p => `<li><b>${esc(p.title)}</b><br><span class="dim">${esc(p.detail)}</span></li>`).join("");
  $("view").innerHTML = `<div class="panel pagehead"><h2>${esc(uName(S.u))} today</h2>${metaBar(m)}</div>
    <div class="home">
      <div class="panel"><h3 style="margin-top:0">Level ladder</h3><p class="hint" style="margin:-4px 0 8px">${esc(units)}. ${useF ? "" : "Save a basis on Key levels to see NQ / ES points."}</p>
        ${ladderSVG(L, price, units)}
        <p class="hint">Nearest above: <b>${above ? esc(above.label) + " " + fmt(above.v, 0) : "none"}</b>${above ? ` (${fmt(above.v - price, 0)} pts)` : ""}. Nearest below: <b>${below ? esc(below.label) + " " + fmt(below.v, 0) : "none"}</b>${below ? ` (${fmt(price - below.v, 0)} pts)` : ""}.</p></div>
      <div>
        <div class="panel"><div class="verdict"><b style="color:${lc}">${esc(lean)}</b>${r ? `<span class="reg" style="color:${regCol(r.label)}">${esc(r.label)}</span>` : ""}</div>
          <p style="max-width:80ch;margin:0 0 4px">${c ? esc(c.summary) : "The written read appears once options data has loaded."}</p>
          ${useF && c ? `<p class="hint" style="margin:0 0 10px">The written read uses ${esc(uName(S.u))} index prices; the figures below and the ladder are in ${esc(root)} points.</p>` : ""}
          <dl class="kv"><dt>Price</dt><dd>${fmt(price, 2)} <span class="dim">${esc(useF ? root : uName(S.u))}</span></dd>
            ${r && r.gamma ? `<dt>Gamma flip</dt><dd>${fmt(r.gamma.flip + off, 0)} <span class="dim">price is ${r.gamma.above ? "above: dealers dampen moves" : "below: dealers add to moves"}</span></dd>` : ""}
            ${z && z.available ? `<dt>${z.is_today ? "0DTE" : "Front-expiry"} walls</dt><dd>${z.put_wall != null ? fmt(z.put_wall + off, 0) : "-"} put, ${z.call_wall != null ? fmt(z.call_wall + off, 0) : "-"} call</dd>` : ""}
            ${ss && ss.day_move ? `<dt>Expected move today</dt><dd>${fmt(ss.day_move.points, 0)} points <span class="dim">${esc(ss.day_move.method || "")}</span></dd>` : ""}
            ${r ? `<dt>What it means</dt><dd style="font-weight:400">${esc(r.meaning)}</dd>` : ""}</dl>
          <button class="go" data-goto="bias">Read the full case and plan</button> <button data-goto="levels">All key levels</button></div>
        ${c ? `<div class="home-cols" style="margin-top:16px"><div class="panel side bull"><h3 style="margin-top:0">Pointing up</h3><ul class="reasons">${top(c.bull) || '<li class="dim">Nothing right now.</li>'}</ul></div>
          <div class="panel side bear"><h3 style="margin-top:0">Pointing down</h3><ul class="reasons">${top(c.bear) || '<li class="dim">Nothing right now.</li>'}</ul></div></div>` : ""}
        <div class="panel" style="margin-top:16px"><h3 style="margin-top:0">Price against today's expected move</h3><div id="hc" class="chart"></div></div>
      </div></div>`;
  document.querySelectorAll("[data-goto]").forEach(b => b.onclick = () => { S.tab = b.dataset.goto; $("tabs").querySelectorAll("[data-t]").forEach(x => x.classList.toggle("on", x.dataset.t === S.tab)); render(); });
  if (ss && ss.cone.length) {
    const C = ss.cone, x = C.map(q => etx(q.t));
    plot("hc", [{ type: "scatter", mode: "lines", x, y: C.map(q => q.up1 + off), line: { width: 0 }, hoverinfo: "skip", showlegend: false },
      { type: "scatter", mode: "lines", x, y: C.map(q => q.dn1 + off), fill: "tonexty", fillcolor: "rgba(61,139,255,0.16)", line: { width: 0 }, name: "Expected move" },
      { type: "scatter", mode: "lines", x: ss.price.map(p => etx(p.t)), y: ss.price.map(p => p.price + off), name: "Price", line: { color: "#E7ECF5", width: 2 } }],
      LAY("", { margin: { l: 56, r: 12, t: 10, b: 50 }, showlegend: false }));
  } else $("hc").innerHTML = '<p class="dim">Fills in after 9:30 ET once the app has a price near the open.</p>';
};
