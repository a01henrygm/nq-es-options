"use strict";
// Strat QS tab (1.31.0): everything for the Q DATA Gamma Strategy, a TradingView Pine strategy that trades only from Q DATA's levels.
// The strategy has two paste boxes: box 1 = the GEX copy (gamma flip, walls, GEX strikes), box 2 = the Levels copy (projected HOD / LOD,
// Monte Carlo, stack zones). Copies made here ignore the TradingView tab's hidden kinds, so the strategy always gets every level it needs.
// Needs tv.js (tvFetch, TV2, tv2Save) and app.js (api, copyText, showText, download).

const SQ_RULES = [
  ["S1 Fade", "Positive gamma (price held above the gamma flip)", "Touch of a GEX level or wall that rejects (a red candle at resistance, green at support). Not at levels Q DATA marks BREAK or CHOP.", "The next GEX level at least 1.5x the risk away, else the gamma flip", "Beyond the level by 0.75 x ATR", "Dealers are long gamma: they sell rallies and buy dips, so pushes into a level stall and come back."],
  ["S1 Break", "Negative gamma (price held below the gamma flip)", "A close through a GEX level (or the retest of it, if you pick Retest). Not at levels Q DATA marks HOLD.", "The next GEX level in the direction of the break; the put wall is the last one down", "Back on the other side of the level by 0.75 x ATR", "Dealers are short gamma: they buy as price rises and sell as it falls, so their hedging adds to the move."],
  ["S2 HOD / LOD fade", "Positive gamma, or the level sits on a wall", "Rejection at the projected HOD (short) or LOD (long). Once per side per day. Optional: High / Low already in 60%+.", "The nearest Monte Carlo target at least 1.5x the risk away, else a GEX level or the flip", "Past the next projected band", "Most days stay inside the move options priced in, so the projected edge means most of the move is used up."],
  ["S3 Stack zone", "Any regime", "HOLD zone: rejection at its edge. BREAK zone: a close through it. CHOP zones are skipped.", "The next GEX level at least 1.5x the risk away", "Beyond the far side of the zone by 0.75 x ATR", "Several kinds of level stacked in one area: more hedging and orders sit there, so price reacts."],
  ["S4 Pin", "Positive gamma, 2:00 to 3:50 pm ET only", "Price at least 1 ATR from the biggest 0DTE gamma strike: a pullback, then a candle back toward it.", "The strike itself", "1.5 x ATR the other way", "Near expiry, 0DTE re-hedging (charm) pulls price toward the strike with the most gamma. Closed by 3:50 pm, when the pull fades."]];

// The levels the strategy will use, read from the pasted text (current levels only)
function sqParse(text) {
  const kinds = [], out = { flip: null, flip0: null, call: null, put: null, magnets: [], hod: [], lod: [], mc: [], stacks: [] };
  String(text || "").split("\n").forEach(row => {
    const a = row.trim().split("|");
    if (a[0] === "K" && a.length >= 8) kinds.push(a[1].toLowerCase());
    else if (a[0] === "L" && a.length >= 10) {
      const p = +a[1], k = kinds[+a[4]] || "", end = +a[6];
      if (!(p > 0) || end > 0) return;
      const lv = { price: p, low: +a[2], high: +a[3], read: a[7], label: a[9] };
      if (k.includes("stacked areas")) out.stacks.push(lv);
      else if (k.includes("projected hod")) out.hod.push(lv);
      else if (k.includes("projected lod")) out.lod.push(lv);
      else if (k.includes("monte carlo")) out.mc.push(lv);
      else if (k.includes("flip")) { if (k.includes("0dte")) out.flip0 = out.flip0 ?? p; else out.flip = out.flip ?? p; }
      else if (k.includes("call wall") && !k.includes("zone")) { if (k.includes("0dte")) out.call0 = out.call0 ?? p; else out.call = out.call ?? p; }
      else if (k.includes("put wall") && !k.includes("zone")) { if (k.includes("0dte")) out.put0 = out.put0 ?? p; else out.put = out.put ?? p; }
      else if (k.includes("biggest gex") || k.includes("top + 0dte")) out.magnets.push(lv);
    }
  });
  out.call = out.call ?? out.call0 ?? null;                 // the strategy falls back to the 0DTE walls the same way
  out.put = out.put ?? out.put0 ?? null;
  return out;
}
const sqKey = ind => S.u + ":sq:" + ind;
async function sqCopy(ind, btn, day) {
  try {
    const r = await tvFetch("/tv/levels", { underlying: S.u, ind, day: day || "" }, { prefs: { kinds: {} } });
    const what = ind === "gex" ? "GEX levels" : "Levels";
    try { await copyText(r.text); btn.textContent = `Copied ${what}${day ? " for " + day : ""} (${fmt(r.levels + (r.history || 0))})`; }
    catch (e) { showText(`${what} for the strategy${day ? ", " + day : ""}`, r.text); }
    if (!day) { TV2.copied[sqKey(ind)] = Date.now(); tv2Save(); }
  } catch (e) {
    alert(e.status === 404 ? `Q DATA has no stored ${ind === "gex" ? "GEX levels" : "Levels"} for ${day}. Older days only kept GEX levels, so strategies 2 and 3 can't be tested on them.` : "Could not build the levels: " + (e.msg || e.message));
  }
}
async function sqScript(btn, dl) {
  try {
    const r = await tvFetch("/tv/strat/script", {});
    if (dl) { download(r.filename, r.code); btn.textContent = "Downloaded"; return; }
    try { await copyText(r.code); btn.textContent = "Copied the strategy"; } catch (e) { showText(r.title, r.code); }
  } catch (e) { alert("Could not get the strategy: " + (e.msg || e.message)); }
}

R.stratqs = async function () {
  if (!S.u) { $("view").innerHTML = note("Pick a symbol first."); return; }
  const none = { prefs: { kinds: {} } };
  const [g, l, hl, log, dd] = await Promise.all([
    tvFetch("/tv/levels", { underlying: S.u, ind: "gex" }, none), tvFetch("/tv/levels", { underlying: S.u, ind: "lv" }, none),
    api("/analytics/hodlod", { underlying: S.u, convention: "standard" }).catch(() => null), tvFetch("/tv/log", { underlying: S.u }).catch(() => ({ events: [] })),
    tvFetch("/tv/days", { underlying: S.u, ind: "gex" }).catch(() => ({ days: [] }))]);
  const gx = sqParse(g.text), lx = sqParse(l.text);
  const flip = gx.flip ?? gx.flip0, px = hl && hl.mapped ? hl.spot_futures : null;
  const state = hl && hl.playbook ? hl.playbook.state : null;
  const pos = px != null && flip != null ? px > flip : state === "long" ? true : state === "short" ? false : null;
  const regime = pos === true ? ["Positive gamma: fade levels", "#16a34a", "S1 Fade, S2 and S4 are live. Breaks are skipped."] : pos === false ? ["Negative gamma: trade breaks", "#dc2626", "S1 Break is live. Fades and the afternoon pin are skipped (S2 only at a wall)."] : ["Not clear yet", "#64748b", "Waiting for the gamma flip."];
  const ai = hl && hl.already_in, pc = v => v == null ? "-" : Math.round(v * 100) + "%";
  const near = (arr, dir) => px == null ? arr[0] : arr.filter(x => (x.price - px) * dir > 0).sort((a, b) => Math.abs(a.price - px) - Math.abs(b.price - px))[0];
  const mag = px == null ? gx.magnets[0] : [...gx.magnets].sort((a, b) => Math.abs(a.price - px) - Math.abs(b.price - px))[0];
  const P = v => v == null ? "-" : fmt(v, 2);
  const stackRows = [...lx.stacks].sort((a, b) => px == null ? 0 : Math.abs(a.price - px) - Math.abs(b.price - px)).slice(0, 4)
    .map(s => `<tr><td>${s.low > 0 ? P(s.low) + " - " + P(s.high) : P(s.price)}</td><td><b style="color:${s.read === "H" ? "#16a34a" : s.read === "B" ? "#dc2626" : "#ca8a04"}">${s.read === "H" ? "HOLD: fade it" : s.read === "B" ? "BREAK: trade the break" : "CHOP: skipped"}</b></td></tr>`).join("");
  const lastChange = ind => (log.events || []).find(e => e.ind === ind && e.action !== "session");
  const copiedAt = ind => { const c = TV2.copied[sqKey(ind)]; return c ? new Date(c).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }) : "not yet"; };
  const stale = ind => { const c = TV2.copied[sqKey(ind)], e = lastChange(ind); return c && e && new Date(e.ts).getTime() > c; };
  const anyStale = stale("gex") || stale("lv");
  const asOf = g.data_as_of ? new Date(g.data_as_of).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false }) + " ET" : "-";
  const days = dd.days || [];

  $("view").innerHTML = `<div class="panel pagehead"><h2>Strat QS</h2>
      <p style="max-width:92ch">Everything for the <b>Q DATA Gamma Strategy</b>, a TradingView strategy that trades only from Q DATA's own levels: the gamma flip decides whether it fades levels or trades breaks, and it adds projected HOD / LOD fades, stack zones and the afternoon pin. Copy the two level sets below into its two paste boxes; it marks every setup, draws each trade as a green / red position box and sends an alert on every entry and exit.</p></div>
    ${anyStale ? `<div class="msg bad"><b>Levels changed since you last copied them here.</b> Copy both again, paste them into the strategy, then delete and re-create your TradingView alert (an alert keeps the levels it was created with).</div>` : ""}
    ${g.mapped ? "" : `<div class="msg bad">No futures price or basis saved, so these levels are in index units. Save a basis on the Key levels tab first, or use the strategy's "Shift every level" setting.</div>`}
    <div class="tvgrid">
      <div class="panel"><h2>Right now</h2>
        <div class="row" style="align-items:center;gap:10px;margin-bottom:8px"><span class="badge" style="background:${regime[1]};color:#fff;font-size:1.05em;padding:6px 12px">${regime[0]}</span><span class="dim">${regime[2]}</span></div>
        <table>
          <tr><td>Price${hl && hl.futures_root ? " (" + esc(hl.futures_root) + ")" : ""}</td><td class="num">${P(px)}</td></tr>
          <tr><td>Gamma flip</td><td class="num"><b style="color:#d97706">${P(flip)}</b>${gx.flip == null && gx.flip0 != null ? ' <span class="dim">(0DTE flip)</span>' : ""}</td></tr>
          <tr><td>Call wall / put wall</td><td class="num"><b style="color:#059669">${P(gx.call)}</b> / <b style="color:#dc2626">${P(gx.put)}</b></td></tr>
          <tr><td>Biggest 0DTE strike (S4 pin)</td><td class="num">${P(mag && mag.price)}</td></tr>
          <tr><td>Projected HOD / LOD (nearest)</td><td class="num">${P((near(lx.hod, 1) || {}).price)} / ${P((near(lx.lod, -1) || {}).price)}</td></tr>
          <tr><td>High already in / Low already in</td><td class="num"><b>${pc(ai && ai.high)}</b> / <b>${pc(ai && ai.low)}</b></td></tr>
        </table>
        <p class="hint">Optional: type the two "already in" numbers into the strategy's <i>High already in %</i> and <i>Low %</i> settings; S2 then only fades a side at 60%+. They change through the day.</p>
        ${stackRows ? `<h3 style="margin:10px 0 4px">Stack zones near price (S3)</h3><table><tr><th>Zone</th><th>What the strategy does</th></tr>${stackRows}</table>` : `<p class="hint">No stack zones right now, so S3 has nothing to trade.</p>`}
        <p class="hint">Data as of ${esc(asOf)} (about 15 min delayed). The strategy waits the same 15 minutes before it uses a new level.</p></div>

      <div class="panel"><h2>Copy into the strategy</h2>
        <div class="actions"><button class="go big" data-sq="gex">1. Copy GEX levels</button>${stale("gex") ? `<span class="badge stale">changed since your last copy</span>` : ""}</div>
        <p class="hint">Paste into the strategy's first box, <b>Q DATA GEX levels</b>. ${fmt(g.levels)} levels now. You copied: ${copiedAt("gex")}.</p>
        <div class="actions"><button class="go big" data-sq="lv">2. Copy Levels</button>${stale("lv") ? `<span class="badge stale">changed since your last copy</span>` : ""}</div>
        <p class="hint">Paste into the second box, <b>Q DATA Levels</b>. ${fmt(l.levels)} levels now. You copied: ${copiedAt("lv")}.</p>
        <p class="hint">In TradingView: the strategy's settings &gt; click in the box &gt; select all &gt; paste &gt; OK. These copies always include every kind of level, even ones you hid on the TradingView tab, because the strategy needs the flip and the walls.</p>
        <h3 style="margin:12px 0 4px">Backtest a past day</h3>
        ${days.length ? `<div class="actions"><select id="sqday">${days.map(x => `<option value="${esc(x.day)}">${esc(x.weekday)} ${esc(x.day)}${x.exact ? "" : " (GEX only)"}</option>`).join("")}</select>
          <button id="sqdg">Copy GEX for this day</button><button id="sqdl">Copy Levels for this day</button></div>
          <p class="hint">Paste both, keep <i>Trade only the pasted day</i> on, scroll back to that day and open the Strategy Tester. Days marked "GEX only" are from before Q DATA saved the other levels: only S1 and S4 can trade them. Copy today's levels again when you're done.</p>`
        : `<p class="hint">No earlier days stored yet. Q DATA keeps each day's levels while it runs, so past days build up from today on.</p>`}</div>
    </div>

    <div class="panel"><h2>Set it up</h2>
      <ol style="line-height:1.7;max-width:95ch">
        <li><b>Once:</b> <button data-sqs="copy">Copy the strategy</button> <button data-sqs="dl">Download .pine</button> then in TradingView: Pine Editor &gt; new script &gt; select all &gt; paste &gt; Save &gt; Add to chart. Use NQ or MNQ (the levels are NQ points).</li>
        <li><b>Each session:</b> copy <b>1. GEX levels</b> and <b>2. Levels</b> above into the strategy's two boxes.</li>
        <li><b>Alerts:</b> TradingView &gt; Create alert &gt; Condition: Q DATA Gamma Strategy &gt; <i>alert() function calls only</i>. You get an alert on every entry (with target and stop), every exit (target, stop, regime switch or session end) and every setup it skips.</li>
        <li><b>After every new paste:</b> delete that alert and create it again. TradingView alerts keep the levels from when they were made; the chart always shows the newest.</li>
        <li><b>Before real size:</b> paper trade or one micro contract for at least two weeks, and backtest a few stored days with the picker above.</li>
      </ol></div>

    <div class="panel"><h2>The rules</h2>
      <div class="scroll"><table><tr><th>Setup</th><th>When</th><th>Entry</th><th>Target</th><th>Stop</th><th>Why it works</th></tr>
      ${SQ_RULES.map(r => `<tr><td><b>${esc(r[0])}</b></td><td>${esc(r[1])}</td><td>${esc(r[2])}</td><td>${esc(r[3])}</td><td>${esc(r[4])}</td><td class="dim">${esc(r[5])}</td></tr>`).join("")}</table></div>
      <p class="hint">The regime only switches after price holds 15 minutes on the other side of the flip, and a switch closes the open trade. At most 4 trades a day, entries 9:30 to 3:50 pm ET, flat by 3:55 pm. Every number here is a setting in the strategy. Delayed options data: context, not a promise.</p></div>`;

  const v = $("view");
  v.querySelectorAll("[data-sq]").forEach(b => b.onclick = () => sqCopy(b.dataset.sq, b));
  v.querySelectorAll("[data-sqs]").forEach(b => b.onclick = () => sqScript(b, b.dataset.sqs === "dl"));
  const dg = $("sqdg"), dl = $("sqdl"), sel = $("sqday");
  if (dg) dg.onclick = () => sqCopy("gex", dg, sel.value);
  if (dl) dl.onclick = () => sqCopy("lv", dl, sel.value);
  if (sel) sel.onchange = () => { S.touch = Date.now(); dg.textContent = "Copy GEX for this day"; dl.textContent = "Copy Levels for this day"; };
};
