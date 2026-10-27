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
