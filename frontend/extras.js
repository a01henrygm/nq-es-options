"use strict";
// Tabs added in 1.15: Volatility (VIX family), Earnings (mega-cap reports in NQ points), Replay (watch a stored session move).
// Uses the helpers in app.js and more.js (api, panel, plot, LAY, note, fmt, esc, card, etx, sel, S, R).

const TONE = { good: "#3fb96a", warn: "#e6b422", bad: "#e5534b", neutral: "#8a8f98" };
const signed = (v, d = 2) => v == null ? "-" : (v > 0 ? "+" : "") + fmt(v, d);
const pctTxt = (v, d = 1) => v == null ? "-" : fmt(v * 100, d) + "%";
const ord = p => { if (p == null) return "-"; const n = Math.round(p * 100), s = n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th"; return n + s; };
const ago = iso => { if (!iso) return "never"; const m = Math.round((Date.now() - new Date(iso)) / 60000); return m < 1 ? "just now" : m < 90 ? m + " min ago" : Math.round(m / 60) + " h ago"; };
const feedStatus = st => !st ? "" : `<details class="adv" data-k="feed-status"><summary>Data feed status</summary><div class="body"><table><tr><th>Feed</th><th>Last success</th><th>Problem</th></tr>
  ${Object.entries(st.jobs).map(([k, v]) => `<tr><td>${esc({ vol: "VIX family quotes", history: "Daily VIX history", members: "Nasdaq-100 members", reports: "Earnings dates", chains: "Option chains of reporting companies" }[k] || k)}</td>
  <td>${esc(ago(v.last_ok))}</td><td class="dim">${v.last_error ? esc(v.last_error.message) : ""}</td></tr>`).join("")}</table></div></details>`;

const hexA = (h, a) => { const n = parseInt(h.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
Object.assign(R, {
  // ---- Volatility -----------------------------------------------------------------------------------------------------------
  async vix() {
    const j = await api("/volatility");
    if (!j.available) { $("view").innerHTML = `<div class="panel"><h2>Volatility backdrop</h2>${note(j.reason, true)}${feedStatus(j.status)}</div>`; return; }
    const g = j.regime, c = TONE[g.color] || TONE.neutral, nm = j.moves.nq_today || j.moves.nq_day, es = j.moves.es_day, ctx = j.context;
    const rows = j.rows.filter(r => r.value != null);
    const tile = r => {
      const up = r.change > 0, col = r.change == null ? "#8a8f98" : up ? "#e5534b" : "#3fb96a";           // volatility up = fear up = red
      return `<div class="card" title="${esc(r.meaning)}">${esc(r.name)}<b>${fmt(r.value, 2)}</b>
        <span style="color:${col}">${r.change == null ? "no change data" : signed(r.change) + (r.change_pct != null ? ` (${signed(r.change_pct * 100, 1)}%)` : "")}</span>
        ${r.pct_1y != null ? `<br><span class="dim">${ord(r.pct_1y)} percentile of the last year</span>` : ""}</div>`;
    };
    $("view").innerHTML = `<div class="panel"><h2>Volatility backdrop</h2>
      <div class="msg" style="border-color:${c};background:#0f1318"><b style="font-size:1.7em;color:${c}">${esc(g.label)}</b>
        <span class="dim"> VIX/VIX3M ${fmt(j.ratios.vix_vix3m, 3)}${j.curve.shape ? ", curve " + esc(j.curve.shape) : ""}</span><p style="margin:6px 0 0">${esc(g.meaning)}</p></div>
      <div class="grid">${rows.map(tile).join("")}</div>
      <h3>What it means for today</h3>
      <div class="grid">
        ${card("Typical NQ day", nm && nm.futures_points ? fmt(nm.futures_points, 0) + " pts" : nm && nm.index_points ? fmt(nm.index_points, 0) + " NDX pts" : "-", nm ? esc(nm.from) : "")}
        ${card("Typical ES day", es && es.futures_points ? fmt(es.futures_points, 1) + " pts" : es && es.index_points ? fmt(es.index_points, 1) + " SPX pts" : "-", es && es.available ? esc(es.from) : "needs the SPX option data (_SPX in CBOE_UNDERLYINGS)")}
        ${card("Today vs the month", j.ratios.vix1d_vix == null ? "-" : fmt(j.ratios.vix1d_vix, 2) + "x", "VIX1D / VIX: above 1 = an event day, below 0.7 = priced quiet")}
        ${card("Next 9 days vs the month", j.ratios.vix9d_vix == null ? "-" : fmt(j.ratios.vix9d_vix, 2) + "x", "VIX9D / VIX: above 1 = trouble expected soon")}
        ${card("Vol of vol", j.ratios.vvix == null ? "-" : fmt(j.ratios.vvix, 0), "VVIX: above 110 = VIX can spike fast")}
        ${card("Nasdaq premium", j.ratios.vxn_vix_spread == null ? "-" : signed(j.ratios.vxn_vix_spread, 1) + " pts", "VXN minus VIX")}</div>
      <ul>${j.summary.slice(1).map(s => `<li>${esc(s)}</li>`).join("")}${j.flags.map(f => `<li style="color:${TONE[f.tone] || "inherit"}">${esc(f.text)}</li>`).join("")}</ul>
      ${!ctx.ndx ? note("Typical-day points need the NDX option data (add _NDX to CBOE_UNDERLYINGS). With a saved basis on Key levels they show as NQ points.") : !ctx.nq_ratio ? note("Points are shown in NDX units. Save an NQ basis on the Key levels tab to see NQ points.") : ""}
      <div id="vx1" class="chart"></div><div id="vx2" class="chart"></div><div id="vx3" class="chart"></div>
      <p class="dim">${esc(j.rules)} ${esc(j.note)}</p>${feedStatus(j.status)}</div>`;
    const tc = j.curve, lbl = tc.today.map(p => `${p.name} (${p.days}d)`);
    plot("vx1", [{ type: "scatter", mode: "lines+markers", x: lbl, y: tc.today.map(p => p.value), name: "Now", line: { color: "#3fb6ff", width: 3 } }]
      .concat(tc.prev.length ? [{ type: "scatter", mode: "lines+markers", x: tc.prev.map(p => `${p.name} (${p.days}d)`), y: tc.prev.map(p => p.value), name: "Previous close", line: { color: "#8a8f98", dash: "dot" } }] : []),
      LAY("Term structure: S&P volatility priced for each horizon (upward = calm, downward = stress)", { yaxis: { title: "Volatility (annualized %)", gridcolor: "#1E2840" } }));
    const H = j.history, line = (n, col, ax) => H[n] && H[n].length ? [{ type: "scatter", mode: "lines", x: H[n].map(p => p.d), y: H[n].map(p => p.v), name: n, yaxis: ax, line: { color: col, width: n === "VXN" ? 2.2 : 1.6 } }] : [];
    const hs = line("VXN", "#ff7a2e").concat(line("VIX", "#3fb6ff"), line("VVIX", "#a371f7", "y2"));
    if (hs.length) plot("vx2", hs, LAY("The last year: VIX and VXN (left), VVIX (right)", { yaxis: { title: "VIX / VXN", gridcolor: "#1E2840" }, yaxis2: { title: "VVIX", overlaying: "y", side: "right", showgrid: false }, margin: { l: 60, r: 64, t: 44, b: 80 } }), { gate: true });
    else { $("vx2").className = ""; $("vx2").innerHTML = '<p class="dim">The one-year chart appears once Cboe\'s daily history file has downloaded.</p>'; }
    const I = j.intraday, il = (n, col) => I[n] && I[n].length ? [{ type: "scatter", mode: "lines", x: I[n].map(p => etx(p.t)), y: I[n].map(p => p.v), name: n, line: { color: col, width: 2, shape: "hv" } }] : [];
    const is = il("VIX1D", "#ffd166").concat(il("VIX", "#3fb6ff"), il("VXN", "#ff7a2e"));
    if (is.length) plot("vx3", is, LAY("Today (ET), as the app collected it", { xaxis: { gridcolor: "#1E2840" } }));
    else { $("vx3").className = ""; $("vx3").innerHTML = '<p class="dim">The through-the-day chart fills in while the market is open.</p>'; }
  },

  // ---- Earnings ---------------------------------------------------------------------------------------------------------------
  async earnings() {
    const j = await api("/earnings");
    if (!j.available) { $("view").innerHTML = `<div class="panel"><h2>Mega-cap earnings in NQ points</h2>${note(j.reason, true)}${feedStatus(j.status)}</div>`; return; }
    const P = j.price_label || "NQ", when = { before_open: "before the open", after_close: "after the close", unknown: "time not announced" };
    const dayTxt = r => r.days_away === 0 ? "today" : r.days_away === 1 ? "tomorrow" : `in ${r.days_away} days`;
    const row = r => {
      const m = r.move || {}, ok = m.available;
      return `<tr><td><b>${esc(r.report_date)}</b><br><span class="dim">${dayTxt(r)}${r.estimated ? ', <span title="Nasdaq estimates this date from past reports; the company has not confirmed it">estimated</span>' : ""}</span></td>
        <td>${esc(when[r.timing] || r.timing)}<br><span class="dim">NQ reacts ${esc(r.reaction_day || "-")}</span></td>
        <td><b>${esc(r.symbol)}</b><br><span class="dim">${esc(r.name)}</span></td>
        <td class="num"><input class="wt" data-w="${esc(r.symbol)}" size="5" value="${r.weight_source === "yours" ? fmt(r.weight * 100, 2) : ""}" placeholder="${fmt((r.weight || 0) * 100, 2)}"><br><span class="dim">${r.weight_source === "yours" ? "your weight" : "approx."}</span></td>
        <td class="num">${ok ? `<b>&plusmn;${pctTxt(r.move_pct)}</b><br><span class="dim">${m.event_expected_pct ? "event only &plusmn;" + pctTxt(m.event_expected_pct) : ""}</span>` : `<span class="dim">${esc(m.reason || "")}</span>`}</td>
        <td class="num">${r.nq_points ? `<b style="font-size:1.15em">&plusmn;${fmt(r.nq_points, 0)}</b>` : "-"}</td>
        <td class="dim">${ok ? `expiry ${esc(m.expiry)}${m.straddle_price ? `, straddle $${fmt(m.straddle_price, 2)} at ${fmt(m.atm_strike, 1)}` : ""}${m.as_of ? `<br>prices ${esc(ago(m.as_of))}` : ""}` : ""}</td></tr>`;
    };
    const up = j.upcoming, next = up[0];
    $("view").innerHTML = `<div class="panel"><h2>Mega-cap earnings in ${esc(P)} points</h2>
      ${next ? `<div class="msg"><b>Next: ${esc(next.symbol)} reports ${esc(next.report_date)} ${esc(when[next.timing] || "")}</b>${next.nq_points ? `. Its options price about &plusmn;${pctTxt(next.move_pct)}, which by itself moves ${esc(P)} about <b>&plusmn;${fmt(next.nq_points, 0)} points</b>.` : "."}</div>` : note("None of the followed companies reports in the next 45 days.")}
      ${j.clusters.map(c => `<div class="msg" style="border-color:#e6b422"><b>${esc(c.symbols.join(" + "))} all trade on ${esc(c.reaction_day)}</b>: ${pctTxt(c.weight)} of the index. Together about &plusmn;${fmt(c.nq_points, 0)} ${esc(P)} points if their moves are unrelated, up to &plusmn;${fmt(c.nq_points_if_same_way, 0)} if they all go the same way.</div>`).join("")}
      <div id="ea1" class="chart"></div>
      <div class="scroll"><table><tr><th>Reports</th><th>When</th><th>Company</th><th>Index weight %</th><th>Implied move</th><th>${esc(P)} points</th><th>From</th></tr>${up.map(row).join("") || "<tr><td colspan=7 class='dim'>Nothing in the window</td></tr>"}</table></div>
      <div class="row"><button class="go" id="wsave">Save my weights</button><span class="dim">Type a weight (in %) to replace the approximate one; clear the box to go back to it.</span></div>
      ${j.later.length ? `<h3>Later</h3><p>${j.later.map(r => `${esc(r.symbol)} ${esc(r.report_date || "date not known")}${r.estimated ? " (est.)" : ""}`).join(", ")}</p>` : ""}
      ${!j.price_label ? note("Points need the NDX option data (add _NDX to CBOE_UNDERLYINGS) and, for NQ points, a saved basis on Key levels.") : j.price_label === "NDX" ? note("Shown in NDX points. Save an NQ basis on the Key levels tab to see NQ points.") : ""}
      <details class="adv" data-k="ea-how"><summary>How this is worked out</summary><div class="body"><p class="dim">The implied move is the at-the-money straddle of the first expiry that trades the news, divided by the stock price: the market's own price for the move. "Event only" removes an ordinary day's worth of movement (using the expiry before the report), leaving the jump options expect from the report itself. ${esc(P)} points = index weight x implied move x ${esc(P)}. ${esc(j.note)}</p>
        <table><tr><th>Biggest members</th><th>Approx. weight</th><th>Raw market-cap share</th></tr>${j.weights_top.slice(0, 12).map(w => `<tr><td>${esc(w.symbol)} <span class="dim">${esc(w.name)}</span></td><td class="num">${pctTxt(w.weight, 2)}</td><td class="num dim">${pctTxt(w.raw_weight, 2)}</td></tr>`).join("")}</table></div></details>
      ${feedStatus(j.status)}</div>`;
    const withPts = up.filter(r => r.nq_points);
    if (withPts.length) plot("ea1", [{ type: "bar", x: withPts.map(r => `${r.symbol} ${r.reaction_day.slice(5)}`), y: withPts.map(r => r.nq_points), marker: { color: withPts.map(r => r.days_away <= 7 ? "#ff7a2e" : "#3fb6ff") },
      text: withPts.map(r => "±" + fmt(r.nq_points, 0)), textposition: "outside", hovertext: withPts.map(r => `${r.name}: ±${pctTxt(r.move_pct)} stock move, weight ${pctTxt(r.weight, 2)}`), hoverinfo: "text" }],
      LAY(`${P} points each report moves the index by itself (orange = within a week)`, { yaxis: { title: `${P} points`, gridcolor: "#1E2840" }, margin: { l: 60, r: 20, t: 44, b: 60 } }));
    else { $("ea1").className = ""; $("ea1").innerHTML = ""; }
    $("wsave").onclick = async () => {
      const w = {}; document.querySelectorAll("[data-w]").forEach(i => { w[i.dataset.w] = i.value.trim(); });
      const r = await fetch("/api/earnings/weights", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ weights: w }) });
      if (!r.ok) { const d = (await r.json()).detail; return alert(typeof d === "string" ? d : "Could not save the weights"); }
      render();
    };
  },

  // ---- Interval map (1.30.0): time x strike heatmap of GEX, dealer delta, charm, vanna, volume or open interest ----------------
  async imap() {
    const ms = S.imM || "gex", sc = S.imS || "all", iv = S.imI || "1";
    const j = await api("/charts/intervalmap", { underlying: S.u, day: S.imD || "", measure: ms, scope: sc, interval: iv });
    const M = [["gex", "GEX"], ["dex", "Delta exposure (DEX)"], ["charm", "Charm"], ["vanna", "Vanna"], ["volume", "Volume"], ["oi", "Open interest"]];
    const head = `<div class="row">${M.map(([k, n]) => `<button class="${k === ms ? "go" : ""}" data-imm="${k}">${n}</button>`).join("")}</div>
      <div class="row"><label>Day${sel("im_day", (j.days || []).map(d => [d, d]), j.day || (j.days || [])[0])}</label>
      <label>Expiries${sel("im_scope", [["all", "All expiries"], ["0dte", "0DTE only"]], sc)}</label>
      <label>Interval${sel("im_int", [["0", "Every snapshot"], ["1", "1 min"], ["5", "5 min"], ["10", "10 min"], ["15", "15 min"], ["30", "30 min"]], iv)}</label>
      <label>Strikes${sel("im_n", [["20", "20 strikes"], ["30", "30 strikes"], ["50", "50 strikes"], ["0", "All"]], S.imN || "30")}</label>
      <label>Style${sel("im_style", [["dots", "Dots"], ["heat", "Heatmap"]], S.imStyle || "dots")}</label>
      <label><span><input type="checkbox" id="im_lines" ${S.imL === false ? "" : "checked"}> Gamma flip</span></label></div>`;
    const hook = () => {
      document.querySelectorAll("[data-imm]").forEach(b => b.onclick = () => { S.imM = b.dataset.imm; render(); });
      if ($("im_day")) $("im_day").onchange = () => { S.imD = $("im_day").value; render(); };
      $("im_scope").onchange = () => { S.imS = $("im_scope").value; render(); };
      $("im_int").onchange = () => { S.imI = $("im_int").value; render(); };
      $("im_lines").onchange = () => { S.imL = $("im_lines").checked; render(); };
      $("im_n").onchange = () => { S.imN = $("im_n").value; render(); };
      $("im_style").onchange = () => { S.imStyle = $("im_style").value; render(); };
    };
    if (!j.available) { $("view").innerHTML = `<div class="panel"><h2>Interval map, ${esc(uName(S.u))}</h2>${head}${note(j.reason, true)}</div>`; hook(); return; }
    const k = j.futures_ratio, root = j.futures_root || "", px = v => k ? v * k : v, unit = k ? root : uName(S.u);
    const money = v => { if (v == null) return "-"; const a = Math.abs(v), s = v < 0 ? "-" : ""; return ms === "volume" || ms === "oi" ? fmt(v) : s + (a >= 1e9 ? (a / 1e9).toFixed(2) + " B" : a >= 1e6 ? (a / 1e6).toFixed(2) + " M" : a >= 1e3 ? (a / 1e3).toFixed(1) + " K" : fmt(a)); };
    // which strikes: the N nearest the day's price
    const P = j.price.map(p => [etx(p.t), p.price]), mid = P.length ? P.map(p => p[1]).sort((a, b) => a - b)[Math.floor(P.length / 2)] : j.strikes[Math.floor(j.strikes.length / 2)];
    const nK = +(S.imN || 30), idx = j.strikes.map((s, i) => i).sort((a, b) => Math.abs(j.strikes[a] - mid) - Math.abs(j.strikes[b] - mid)).slice(0, nK || j.strikes.length).sort((a, b) => a - b);
    const X = j.times.map(etx), cap = Math.max(...idx.flatMap(i => j.z[i].map(v => Math.abs(v || 0)))) || 1;
    // the heavy strikes: biggest at any moment of the day, top 3 on each side (top 4 for unsigned measures)
    const peak = i => j.z[i].reduce((m, v) => (v != null && Math.abs(v) > Math.abs(m) ? v : m), 0);
    const pos = idx.filter(i => peak(i) > 0).sort((a, b) => peak(b) - peak(a)).slice(0, j.signed ? 3 : 4), neg = j.signed ? idx.filter(i => peak(i) < 0).sort((a, b) => peak(a) - peak(b)).slice(0, 3) : [];
    const heavy = new Set([...pos, ...neg]);
    const GREEN = "#22e36b", RED = "#ff3d5a", GOLD = "#ffc94d";
    const tr = [];
    if (S.imStyle === "heat") {
      const sh = idx.map(i => j.z[i].map(v => v == null ? null : Math.max(-cap, Math.min(cap, v))));
      tr.push({ type: "heatmap", x: X, y: idx.map(i => px(j.strikes[i])), z: sh, customdata: idx.map(i => j.z[i]), colorscale: j.signed ? [[0, RED], [0.5, "rgba(0,0,0,0)"], [1, GREEN]] : RCS,
        zmid: j.signed ? 0 : undefined, zmin: j.signed ? -cap : 0, zmax: cap, hoverongaps: false, ygap: 1, showscale: false, hovertemplate: `%{x}<br>${esc(unit)} %{y:,.0f}<br>${esc(j.title)}: %{customdata:,.0f}<extra></extra>` });
    } else {
      // the dot grid: every strike at every moment; faint specks where nothing sits, dots growing and brightening with size
      const xs = [], ys = [], sz = [], col = [], cd = [], hx = [], hy = [], hs = [], hc = [];
      for (const i of idx) for (let c = 0; c < X.length; c++) {
        const v = j.z[i][c], r = v ? Math.sqrt(Math.abs(v) / cap) : 0, y = px(j.strikes[i]);
        xs.push(X[c]); ys.push(y); sz.push(r < 0.04 ? 3 : 5 + r * 19);
        const base = !j.signed ? GOLD : v >= 0 ? GREEN : RED, op = r < 0.04 ? 0.22 : Math.min(1, 0.35 + r * 0.9);
        col.push(hexA(base, op));
        cd.push([money(v), j.zc ? money(j.zc[i][c]) : "", j.zp ? money(j.zp[i][c]) : "", fmt(y, 0), j.times[c]]);
        if (heavy.has(i) && r >= 0.04) { hx.push(X[c]); hy.push(y); hs.push(12 + r * 30); hc.push(hexA(base, 0.16)); }
      }
      const tip = j.zc ? `<b>%{x|%I:%M %p on %b %d, %Y}</b><br>${esc(unit)}  <b>%{customdata[3]}</b><br>Call GEX  %{customdata[1]}<br>Put GEX  %{customdata[2]}<br><b>Net GEX  %{customdata[0]}</b><extra></extra>`
        : `<b>%{x|%I:%M %p on %b %d, %Y}</b><br>${esc(unit)}  <b>%{customdata[3]}</b><br><b>${esc(j.title)}  %{customdata[0]}</b><extra></extra>`;
      tr.push({ type: "scatter", mode: "markers", x: hx, y: hy, hoverinfo: "skip", showlegend: false, marker: { size: hs, color: hc, line: { width: 0 } } });   // glow under the heavy rows
      tr.push({ type: "scatter", mode: "markers", x: xs, y: ys, customdata: cd, showlegend: false, hovertemplate: tip,
        marker: { size: sz, color: col, line: { width: 0 } } });
    }
    if (P.length) tr.push({ type: "scatter", mode: "lines", x: P.map(p => p[0]), y: P.map(p => px(p[1])), name: uName(S.u), line: { color: "#3d8bff", width: 2.6, shape: "spline", smoothing: 0.6 }, hovertemplate: `${esc(uName(S.u))} %{y:,.2f}<extra></extra>` });
    if (S.imL !== false) [["gamma_flip", "Gamma flip", GOLD]].forEach(([key, nm, cl]) => {
      const L = (j.lines[key] || []).filter(r => r.value != null);
      if (L.length) tr.push({ type: "scatter", mode: "lines", line: { shape: "hv", color: hexA(cl, 0.8), width: 1.4, dash: "dash" }, name: nm, x: L.map(r => etx(r.t)), y: L.map(r => px(r.value)), hovertemplate: `${nm} %{y:,.0f}<extra></extra>` });
    });
    // price tags on the left for the heavy strikes, and what they are on the right; biggest first, none overlapping
    const ann = [], shapes = [];
    const name = (i, v) => ms === "gex" ? (v > 0 ? "Call wall" : "Put wall") : ms === "dex" ? (v > 0 ? "+DEX" : "-DEX") : ms === "charm" ? (v > 0 ? "+Charm" : "-Charm") : ms === "vanna" ? (v > 0 ? "+Vanna" : "-Vanna") : ms === "volume" ? "Hot strike" : "Big OI";
    const ysAll = idx.map(i => px(j.strikes[i])), gap = (Math.max(...ysAll) - Math.min(...ysAll)) * 0.045;
    const lastP = P.length ? px(P[P.length - 1][1]) : null, placed = [];
    const free = y => placed.every(q => Math.abs(q - y) >= gap);
    [...pos, ...neg].sort((a, b) => Math.abs(peak(b)) - Math.abs(peak(a))).forEach((i, n) => {
      const v = peak(i), y = px(j.strikes[i]), cl = !j.signed ? GOLD : v > 0 ? GREEN : RED, top = n < 2;
      shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color: hexA(cl, top ? 0.4 : 0.2), width: top ? 2 : 1 }, layer: "below" });
      if (!free(y)) return;
      placed.push(y);
      ann.push({ xref: "paper", x: 0, xanchor: "right", y, yanchor: "middle", text: `<b>${fmt(y, 0)}</b>`, showarrow: false, font: { color: "#06121f", size: 12 }, bgcolor: cl, borderpad: 4 });
      ann.push({ xref: "paper", x: 1, xanchor: "left", y, yanchor: "middle", text: `${top ? "<b>" : ""}${name(i, v)} ${money(v)}${top ? "</b>" : ""}`, showarrow: false, font: { color: cl, size: 11 }, bgcolor: "rgba(8,18,40,0.9)", bordercolor: hexA(cl, 0.7), borderpad: 3 });
    });
    const near = placed.find(q => Math.abs(q - lastP) < gap);        // price tag steps aside for a wall tag at the same height
    if (lastP) ann.push({ xref: "paper", x: 1, xanchor: "left", y: lastP, yanchor: "middle", yshift: near == null ? 0 : lastP >= near ? 18 : -18, text: `<b>${fmt(lastP, 2)}</b>`, showarrow: false, font: { color: "#ffffff", size: 11 }, bgcolor: "#3d8bff", borderpad: 3 });
    const ys = idx.map(i => px(j.strikes[i])), yr = [Math.min(...ys) - (ys[1] - ys[0] || 5), Math.max(...ys) + (ys[1] - ys[0] || 5)];
    const L0 = { paper_bgcolor: "#081228", plot_bgcolor: "#081228", font: { color: "#c9d6ee", family: "Manrope, Segoe UI, sans-serif", size: 12 },
      title: { text: `<b>${esc(uName(S.u))} · ${esc(j.title)} by strike through the session</b>${lastP ? `<br><span style="font-size:12px;color:#8fb4ff">● ${esc(unit)} ${fmt(lastP, 2)}</span>` : ""}`, x: 0.5, xanchor: "center", font: { size: 16, color: "#ffffff" } },
      margin: { l: 92, r: 150, t: 70, b: 50 }, showlegend: false, hovermode: "closest", annotations: ann, shapes,
      hoverlabel: { bgcolor: "#163a8a", bordercolor: "#3d8bff", font: { color: "#ffffff", family: "Manrope, Segoe UI, sans-serif", size: 13 }, align: "left" },
      xaxis: { showgrid: false, zeroline: false, tickformat: "%I:%M %p", color: "#c9d6ee", showspikes: true, spikemode: "across", spikedash: "dot", spikecolor: "#8fb4ff", spikethickness: 1 },
      yaxis: { showgrid: false, zeroline: false, tickformat: ",d", color: "#c9d6ee", range: yr } };
    const meaning = { gex: "Green: positive gamma (dealers dampen moves, price tends to pin or reject). Red: negative gamma (dealers chase, moves speed up).",
      dex: "Modeled dealer delta by strike (the same sign scenario as the Delta exposure tab). Bigger, brighter blocks are strikes carrying more of the delta dealers hedge; where the blocks shift as price moves is where hedging flows are concentrated.",
      charm: "How much dealer delta changes each day from time decay alone. Big blocks near price drive the drift into the close, strongest on 0DTE.",
      vanna: "How much dealer delta changes when implied volatility moves. A vol crush with big vanna near price usually pushes price up through it, a vol spike down.",
      volume: "Where contracts traded today, building through the session. Hot strikes are where the day's action is.",
      oi: "Open interest by strike (updates once a day, so it mostly shows the starting map; changes appear when the data refreshes)." }[ms];
    $("view").innerHTML = `<div class="panel"><h2>Interval map, ${esc(uName(S.u))} ${esc(j.day)}: ${esc(j.title)}${sc === "0dte" ? " (0DTE)" : ""}</h2>${head}
      <p class="dim" style="margin:4px 0 8px">${esc(meaning)}</p>
      <div id="im1" class="chart imchart" style="height:680px"></div>
      <p class="dim">${esc(j.note)}Prices are ${k ? esc(root) + " (" + esc(j.ratio_from) + ")" : esc(uName(S.u)) + " units (save a basis on Key levels for futures prices)"}. Dot size and brightness follow the size at that strike and moment; the heaviest strikes of the day are tagged on the left and named on the right.</p></div>`;
    hook();
    plot("im1", tr, L0, { gate: true });
  },

  // ---- Replay -----------------------------------------------------------------------------------------------------------------
  async replay() {
    const j = await api("/charts/replay", { underlying: S.u, day: S.rpDay || "", scope: S.rpScope || "all" });
    const head = days => `<div class="row"><label>Day${sel("rp_day", (days || []).map(d => [d, d]), S.rpDay || (days || [])[0])}</label>
      <label>Gamma from${sel("rp_scope", [["all", "All expiries"], ["0dte", "0DTE only"]], S.rpScope || "all")}</label></div>`;
    const hook = () => {
      $("rp_day").onchange = () => { S.rpDay = $("rp_day").value; S.rpI = null; render(); };
      $("rp_scope").onchange = () => { S.rpScope = $("rp_scope").value; S.rpI = null; render(); };
    };
    if (!j.available) { $("view").innerHTML = `<div class="panel"><h2>Session replay, ${esc(uName(S.u))}</h2>${j.days ? head(j.days) : ""}${note(j.reason, true)}</div>`; if (j.days) hook(); return; }
    const F = j.frames, k = j.futures_ratio, root = j.futures_root || "futures", fx = v => v == null || !k ? "" : ` <span class="dim">${esc(root)} ${fmt(v * k, 0)}</span>`;
    const live = j.day === j.days[0];
    if (S.rpDayShown !== j.day) S.rpI = live ? F.length - 1 : 0;               // a new day: today opens at the latest snapshot, past days at the start
    else if (S.rpI == null || S.rpI >= F.length) S.rpI = F.length - 1;
    if (S.rpFollow && live && !S.rpPlay) S.rpI = F.length - 1;                  // parked on the newest snapshot today: keep following it
    S.rpDayShown = j.day; S.rpData = j;
    $("view").innerHTML = `<div class="panel"><h2>Session replay, ${esc(uName(S.u))} ${esc(j.day)}</h2>${head(j.days)}
      <div class="row rpbar"><button id="rp_prev" title="Previous snapshot">&#9664;</button><button class="go" id="rp_play">${S.rpPlay ? "Pause" : "Play"}</button><button id="rp_next" title="Next snapshot">&#9654;</button>
        <label>Speed${sel("rp_speed", [["1", "1x"], ["2", "2x"], ["4", "4x"], ["8", "8x"]], S.rpSpeed || "2")}</label>
        <input id="rp_slider" type="range" min="0" max="${F.length - 1}" value="${S.rpI}" style="flex:1;min-width:180px">
        <b id="rp_time"></b></div>
      <div class="grid" id="rp_cards"></div>
      <div id="rp_now" class="msg" style="min-height:1.6em"></div>
      <div id="rp1" class="chart"></div><div id="rp2" class="chart"></div>
      <h3>What changed during the day</h3><div class="scroll" style="max-height:320px"><table id="rp_events"><tr><th>Time (ET)</th><th>What happened</th></tr>
      ${j.events.map(e => `<tr data-go="${e.i}" style="cursor:pointer"><td>${esc(etx(e.t).slice(11, 16))}</td><td>${esc(e.text)}</td></tr>`).join("") || "<tr><td colspan=2 class='dim'>No wall moves, flip crossings or touches were recorded.</td></tr>"}</table></div>
      <p class="dim">${esc(j.note)} Click a row to jump there. Arrow keys step one snapshot.</p></div>`;
    hook();
    const pts = j.price, X = pts.map(p => etx(p.t)), Y = pts.map(p => p.price), strikes = j.strikes;
    const lo = Math.min(...Y, ...F.map(f => f.put_wall || Infinity)), hi = Math.max(...Y, ...F.map(f => f.call_wall || -Infinity)), pad = (hi - lo) * 0.08 || 10;
    const step = (i, user) => {
      S.rpI = Math.max(0, Math.min(F.length - 1, i)); if (user) S.touch = Date.now();
      S.rpFollow = live && S.rpI === F.length - 1;
      const f = F[S.rpI], tx = etx(f.t);
      $("rp_slider").value = S.rpI; $("rp_time").textContent = tx.slice(11, 16) + " ET  (" + (S.rpI + 1) + " / " + F.length + ")";
      const g = f.gamma_at_spot;
      $("rp_cards").innerHTML = card("Price", fmt(f.price, 2) + fx(f.price)) + card("Gamma flip", fmt(f.gamma_flip, 0) + fx(f.gamma_flip), f.price && f.gamma_flip ? `price ${f.price > f.gamma_flip ? "above" : "below"}` : "")
        + card("Call wall", fmt(f.call_wall, 0) + fx(f.call_wall), f.price && f.call_wall ? `${signed(f.call_wall - f.price, 0)} pts` : "") + card("Put wall", fmt(f.put_wall, 0) + fx(f.put_wall), f.price && f.put_wall ? `${signed(f.put_wall - f.price, 0)} pts` : "")
        + card("Dealer gamma at price", g == null ? "-" : `<span style="color:${g >= 0 ? "#3fb96a" : "#e5534b"}">${g >= 0 ? "Long" : "Short"}</span>`, g == null ? "" : g >= 0 ? "moves get absorbed" : "moves can extend")
        + card("Net GEX near price", big(f.net_total));
      const ch = f.biggest_changes.map(c => `${fmt(c.strike, 0)} ${c.change > 0 ? "+" : "-"}${big(Math.abs(c.change))}`).join(", ");
      $("rp_now").innerHTML = f.events.length ? f.events.map(e => `<b>${esc(e.text)}</b>`).join("<br>") + (ch ? `<br><span class="dim">Biggest GEX changes: ${esc(ch)}</span>` : "")
        : ch ? `<span class="dim">Biggest GEX changes since the last snapshot: ${esc(ch)}</span>` : '<span class="dim">Start of the day.</span>';
      document.querySelectorAll("#rp_events tr[data-go]").forEach(r => r.classList.toggle("on", +r.dataset.go === S.rpI));
      const cut = X.findIndex(x => x > tx), n = cut < 0 ? X.length : cut;
      const hl = (v, col, dash, name) => v == null ? [] : [{ type: "scatter", mode: "lines", x: [X[0], X[X.length - 1]], y: [v, v], name, line: { color: col, dash, width: 1.6 }, hoverinfo: "name+y" }];
      plot("rp1", [{ type: "scatter", mode: "lines", x: X, y: Y, name: "Whole day", line: { color: "#3a4256", width: 1.5 }, hoverinfo: "skip" },
        { type: "scatter", mode: "lines", x: X.slice(0, n), y: Y.slice(0, n), name: "Price so far", line: { color: "#fff", width: 2.4 } }]
        .concat(hl(f.call_wall, "#22d3ee", "solid", "Call wall"), hl(f.put_wall, "#ff4d8d", "solid", "Put wall"), hl(f.gamma_flip, "#ffd166", "dash", "Gamma flip"),
          hl(f.em_high, "#7db7ff", "dot", "Expected move high"), hl(f.em_low, "#7db7ff", "dot", "Expected move low")),
        LAY("Price against the levels as they stood at this moment", { yaxis: { range: [lo - pad, hi + pad], gridcolor: "#1E2840" }, shapes: [vline(tx, "#ffffff55", "dot")], showlegend: true }));
      const P = f.profile, K = P.map(r => r[0]);
      const vl = (v, col, dash) => v == null ? [] : [vline(v, col, dash)];
      plot("rp2", [{ type: "bar", x: K, y: P.map(r => r[1]), name: "Net GEX", marker: { color: P.map(r => r[1] >= 0 ? "#3fb6ff" : "#7b3fe4") }, hovertemplate: "%{x}: %{y:.3s}<extra></extra>" }],
        LAY(`${S.rpScope === "0dte" ? "0DTE" : "All-expiry"} net GEX by strike at ${tx.slice(11, 16)} ET (white = price, yellow = flip)`,
          { xaxis: { title: "Strike", range: strikes.length ? [strikes[0], strikes[strikes.length - 1]] : undefined, gridcolor: "#1E2840" }, yaxis: { gridcolor: "#1E2840" },
            shapes: vl(f.price, "#fff", "solid").concat(vl(f.gamma_flip, "#ffd166", "dash")), showlegend: false }));
    };
    const tick = () => { if (S.tab !== "replay" || !$("rp_slider")) { clearInterval(window.__rpT); return; }
      if (S.rpI >= F.length - 1) { S.rpPlay = false; clearInterval(window.__rpT); $("rp_play").textContent = "Play"; return; } step(S.rpI + 1, true); };
    const playing = on => { S.rpPlay = on; clearInterval(window.__rpT); $("rp_play").textContent = on ? "Pause" : "Play"; if (on) { if (S.rpI >= F.length - 1) step(0, true); window.__rpT = setInterval(tick, 1600 / (+(S.rpSpeed || 2))); } };
    $("rp_play").onclick = () => playing(!S.rpPlay);
    $("rp_prev").onclick = () => { playing(false); step(S.rpI - 1, true); };
    $("rp_next").onclick = () => { playing(false); step(S.rpI + 1, true); };
    $("rp_slider").oninput = e => { playing(false); step(+e.target.value, true); };
    $("rp_speed").onchange = () => { S.rpSpeed = $("rp_speed").value; if (S.rpPlay) playing(true); };
    document.querySelectorAll("#rp_events tr[data-go]").forEach(r => r.onclick = () => { playing(false); step(+r.dataset.go, true); });
    if (!window.__rpKeys) {
      window.__rpKeys = true;
      document.addEventListener("keydown", e => { if (S.tab !== "replay" || !$("rp_slider") || /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
        if (e.key === "ArrowRight") $("rp_next").click(); else if (e.key === "ArrowLeft") $("rp_prev").click(); else if (e.key === " ") { e.preventDefault(); $("rp_play").click(); } });
    }
    step(S.rpI);
    if (S.rpPlay) playing(true); else clearInterval(window.__rpT);
  },
});
