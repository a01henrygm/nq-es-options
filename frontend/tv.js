"use strict";
// TradingView tab and level-change alerts.
// Two paste-in indicators: Q DATA GEX (gamma levels) and Q DATA Levels (everything else), plus the classic Q DATA All Tabs (1.24.4). Add each script to TradingView once;
// when levels change, Q DATA alerts (banner here, plus a desktop notification and sound from the desktop app), then copy and paste.
// Per-kind show / color choices are saved in this browser (localStorage "nqes.tv2") and travel with the copied levels.
const TV2 = (() => { try { return Object.assign({ kinds: {}, copied: {} }, JSON.parse(localStorage.getItem("nqes.tv2") || "{}")); } catch (e) { return { kinds: {}, copied: {} }; } })();
const TVW = { last: 0, desktop: null, started: false };
function tv2Save() { try { localStorage.setItem("nqes.tv2", JSON.stringify(TV2)); } catch (e) { /* private window */ } }
const TVNAME = { gex: "Q DATA GEX", lv: "Q DATA Levels" }, TVBTN = { gex: "Copy GEX levels", lv: "Copy Levels" };
async function tvFetch(path, params, body) {
  const qs = new URLSearchParams(Object.entries(Object.assign({}, params, S.src ? { source: S.src } : {})).filter(([, v]) => v != null && v !== "")).toString();
  const r = await fetch("/api" + path + "?" + qs, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => null);
  if (!r.ok) { const d = j && j.detail; throw { status: r.status, msg: (d && d.reason) || (typeof d === "string" ? d : "Request failed") }; }
  return j;
}
const tvLevels = ind => tvFetch("/tv/levels", { underlying: S.u, ind }, { prefs: { kinds: TV2.kinds } });
async function tvCopy(ind, btn) {
  try {
    const r = await tvLevels(ind);
    try { await copyText(r.text); if (btn) btn.textContent = `Copied ${r.levels} levels`; }
    catch (e) { showText(`Levels for ${TVNAME[ind]}`, r.text); }
    TV2.copied[S.u + ":" + ind] = Date.now(); tv2Save();
    return r;
  } catch (e) { alert(`Could not build the ${TVNAME[ind]} levels: ` + (e.msg || e.message)); }
}
async function tvScriptCopy(ind, btn, dl) {
  try {
    const r = await tvFetch("/tv/script", { ind });
    if (dl) { download(r.filename, r.code); btn.textContent = "Downloaded"; return; }
    try { await copyText(r.code); btn.textContent = "Copied the indicator"; } catch (e) { showText(r.title, r.code); }
  } catch (e) { alert("Could not get the indicator: " + (e.msg || e.message)); }
}

// ---- Q DATA All Tabs (classic): every tab's levels in one paste-in indicator ----
async function allCopy(btn) {
  try {
    const r = await tvFetch("/tv/alltabs/levels", { underlying: S.u }, { prefs: { kinds: TV2.kinds } });
    try { await copyText(r.text); if (btn) btn.textContent = `Copied ${r.levels} levels`; }
    catch (e) { showText("Levels for Q DATA All Tabs", r.text); }
    TV2.copied[S.u + ":all"] = Date.now(); tv2Save();
  } catch (e) { alert("Could not build the All Tabs levels: " + (e.msg || e.message)); }
}
async function allScript(btn, dl) {
  try {
    const r = await tvFetch("/tv/alltabs/script", {});
    if (dl) { download(r.filename, r.code); btn.textContent = "Downloaded"; return; }
    try { await copyText(r.code); btn.textContent = "Copied the indicator"; } catch (e) { showText(r.title, r.code); }
  } catch (e) { alert("Could not get the indicator: " + (e.msg || e.message)); }
}

// ---- alerts: a banner on every page, with its own sound per kind of change ----
function tvSound(tier) {
  try {
    const c = new (window.AudioContext || window.webkitAudioContext)();
    const notes = tier === 2 ? [[660, 0], [990, 0.16], [1320, 0.32]] : tier === 1 ? [[880, 0], [880, 0.2]] : [[520, 0]];
    notes.forEach(([f, at]) => { const o = c.createOscillator(), g = c.createGain(); o.type = tier === 2 ? "triangle" : "sine"; o.frequency.value = f; o.connect(g); g.connect(c.destination);
      g.gain.setValueAtTime(0.0001, c.currentTime + at); g.gain.exponentialRampToValueAtTime(0.18, c.currentTime + at + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + at + 0.22);
      o.start(c.currentTime + at); o.stop(c.currentTime + at + 0.25); });
  } catch (e) { /* no audio */ }
}
function tvBanner(evs) {
  const gex = evs.filter(e => e.ind === "gex"), other = evs.filter(e => e.ind !== "gex");
  const tm = e => { try { return new Date(e.data_ts).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false }); } catch (x) { return ""; } };
  const list = evs.slice(0, 6).map(e => `<li><b class="${e.ind === "gex" ? "tvgex" : ""}">${e.ind === "gex" ? "GEX" : "Levels"}</b> ${esc(e.text)} <span class="dim">${tm(e)} ET data</span></li>`).join("");
  const d = document.createElement("div"); d.className = "toastmsg tvalert";
  d.innerHTML = `<button data-x>Close</button><b>${gex.length ? "GEX levels changed" : "Levels changed"} (${evs.length}) ${esc(String(evs[0].underlying || "").replace(/^_/, ""))}</b><ul style="margin:4px 0;padding-left:1.1em">${list}</ul>${evs.length > 6 ? `<span class="dim">+${evs.length - 6} more in the Level log</span><br>` : ""}
    <span class="actions">${gex.length ? `<button class="go" data-c="gex">Copy GEX levels</button>` : ""}${other.length ? `<button class="${gex.length ? "" : "go"}" data-c="lv">Copy Levels</button>` : ""}</span>
    <span class="hint">Then in TradingView: indicator settings &gt; Levels &gt; select all &gt; paste &gt; OK.</span>`;
  d.querySelector("[data-x]").onclick = () => d.remove();
  d.querySelectorAll("[data-c]").forEach(b => b.onclick = () => tvCopy(b.dataset.c, b));
  $("toast").appendChild(d); setTimeout(() => d.remove(), 15 * 60000);
}
async function tvWatchTick() {
  if (!S.u) return;
  if (TVW.desktop === null) { try { TVW.desktop = (await fetch("/api/desktop/info")).ok; } catch (e) { TVW.desktop = false; } }
  try {
    const j = await tvFetch("/tv/events", { since: TVW.last });
    if (TVW.last > 0 && j.events.length) {
      const evs = j.events.filter(e => e.underlying === S.u || !S.u);
      const a = TVW.alerts || {};
      const want = evs.filter(e => a.which === "gex" ? e.tier === 2 : a.which === "important" ? e.tier >= 1 : true);
      if (want.length && a.on !== false) {
        tvBanner(want);
        if (!TVW.desktop && a.sound !== false) tvSound(Math.max(...want.map(e => e.tier)));        // the desktop app plays its own sounds
      }
      if (S.tab === "tv" && !userBusy()) render();
    }
    TVW.last = Math.max(TVW.last, j.last);
  } catch (e) { /* the next tick tries again */ }
}
async function tvWatch() {
  if (TVW.started) return; TVW.started = true;
  try { TVW.alerts = await tvFetch("/tv/alerts", {}); } catch (e) { TVW.alerts = {}; }
  const wait = () => S.u ? tvWatchTick() : setTimeout(wait, 1000);
  wait(); setInterval(tvWatchTick, 20000);
}
setTimeout(tvWatch, 1500);

// ---- the TradingView tab ----
R.tv = async function () {
  if (!S.u) { $("view").innerHTML = note("Pick a symbol first."); return; }
  const [g, l, log, al] = await Promise.all([tvLevels("gex"), tvLevels("lv"), tvFetch("/tv/log", { underlying: S.u }), tvFetch("/tv/alerts", {})]);
  TVW.alerts = al;
  const lastChange = ind => log.events.find(e => e.ind === ind && e.action !== "session");
  const stale = ind => { const c = TV2.copied[S.u + ":" + ind], e = lastChange(ind); return c && e && new Date(e.ts).getTime() > c; };
  const copiedAt = ind => { const c = TV2.copied[S.u + ":" + ind]; return c ? new Date(c).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }) : "not yet"; };
  const card = (ind, r) => `<div class="panel tvcard"><h2>${TVNAME[ind]}</h2>
      <p class="dim" style="margin:0 0 6px">${ind === "gex" ? "Gamma flips, call / put walls, 0DTE walls, the biggest GEX strikes and GEX zones." : "Open interest, volume, expected move, charm / vanna, dealer delta, new positions, HOD / LOD, stack zones, Game plan setups, VIX day and Quant targets. Heatmap included, off until you switch it on in the indicator."}</p>
      <div class="actions"><button class="go big" data-copy="${ind}">${TVBTN[ind]}</button>${stale(ind) ? `<span class="badge stale">changed since your last copy</span>` : ""}</div>
      <p class="hint">${fmt(r.levels)} levels now${r.history ? `, ${fmt(r.history)} earlier positions (faded on the chart)` : ""}. Data as of ${esc(new Date(r.data_as_of).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false }))} ET (about 15 min delayed). You copied: ${copiedAt(ind)}.${r.mapped ? "" : " No futures price or basis saved, so prices are index units (Key levels tab > Convert)."}${r.cut ? ` ${r.cut} far-away levels left out to fit.` : ""}${r.catching_up ? ` <b>Still replaying today's stored data so every level gets its real start time: wait a minute or two, then copy.</b>` : ""}</p>
      <details class="adv"><summary>Once: add ${TVNAME[ind]} to TradingView</summary><div class="body"><div class="actions"><button data-scr="${ind}">Copy the indicator</button><button data-scrdl="${ind}">Download .pine</button></div>
        <p class="hint">Pine Editor &gt; new script &gt; select all &gt; paste &gt; Save &gt; Add to chart. Only again if a Q DATA update says this indicator changed.</p></div></details></div>`;
  const allCard = `<div class="panel tvcard"><h2>Q DATA All Tabs (classic)</h2>
      <p class="dim" style="margin:0 0 6px">The old all-in-one indicator: every tab's levels (Stack map, Level map, Game plan, Bias, Session, Regime, VIX, Quant, GEX, 0DTE, Flip, Charm / vanna, OI, Volume, Overnight, Expected move, Delta, HOD / LOD), the info table and the expected-move cone. Switch any tab off in its settings.</p>
      <div class="actions"><button class="go big" data-allcopy>Copy All Tabs levels</button></div>
      <p class="hint">You copied: ${copiedAt("all")}. Use it alongside the two above or on its own.</p>
      <details class="adv"><summary>Once: add Q DATA All Tabs to TradingView</summary><div class="body"><div class="actions"><button data-allscr>Copy the indicator</button><button data-allscrdl>Download .pine</button></div>
        <p class="hint">Pine Editor &gt; new script &gt; select all &gt; paste &gt; Save &gt; Add to chart. Then settings &gt; Levels from Q DATA &gt; paste &gt; OK.</p></div></details></div>`;
  const tm = t => t || "";
  const rows = log.events.slice(0, 120).map(e => `<tr><td class="num">${esc(tm(e.time_et))}</td><td><span class="badge ${e.ind === "gex" ? "tvgexb" : ""}">${e.ind === "gex" ? "GEX" : "Levels"}</span></td><td>${esc(e.text)}</td></tr>`).join("");
  const kinds = [...g.kinds, ...(g.hidden_kinds || [])].map(k => ({ ...k, ind: "GEX" })).concat([...l.kinds, ...(l.hidden_kinds || [])].map(k => ({ ...k, ind: "Levels" })));
  $("view").innerHTML = `<div class="panel pagehead"><h2>TradingView</h2>
      <p style="max-width:90ch">Two indicators, both paste-in: add each once, then paste new levels when Q DATA tells you they changed. Each level starts on the candle of the <b>options data time</b> it first appeared; when a level moves, the old spot stays faded with a step to the new price. Levels near price are see-through zones, farther ones thin lines, and every label says what price should do there. Colors are made for a white chart.</p></div>
    <div class="tvgrid">${card("gex", g)}${card("lv", l)}${allCard}</div>
    <div class="panel"><h2>Alerts when levels change</h2>
      <div class="row"><label><span><input type="checkbox" id="tval_on" ${al.on ? "checked" : ""}> Alerts on</span></label>
        <label><span><input type="checkbox" id="tval_snd" ${al.sound ? "checked" : ""}> Sound</span></label>
        <label><span><input type="checkbox" id="tval_pop" ${al.notify ? "checked" : ""}> Desktop notification</span></label>
        <label>Alert on<select id="tval_which"><option value="all">Any level change</option><option value="important">GEX and important levels</option><option value="gex">GEX only</option></select></label></div>
      <p class="hint">One alert per data update, saying what changed (for example "Call wall moved 21,400 -> 21,450"). Three sounds: GEX, other important levels (high / low of day, stack zones, top setups), everything else.
        <button data-test="2">Hear GEX sound</button> <button data-test="1">Important</button> <button data-test="0">Other</button></p></div>
    <div class="panel"><h2>Level log, ${esc(log.day)}</h2><p class="hint" style="margin:0 0 6px">${esc(log.note)}</p>
      <div class="scroll tall"><table><tr><th>Data time (ET)</th><th></th><th>What changed</th></tr>${rows || `<tr><td colspan="3" class="dim">No changes yet today.</td></tr>`}</table></div></div>
    <div class="panel"><details class="adv"><summary>Kinds of level: show or hide, colors</summary><div class="body">
      <p class="hint">Applies to what you copy next. Sections (Walls, Open interest, Heatmap...) can also be switched in each indicator's "What to show" settings.</p>
      <div class="scroll"><table><tr><th>Show</th><th>Color</th><th>Kind</th><th>Indicator</th></tr>
      ${kinds.map(k => `<tr><td><input type="checkbox" data-kon="${esc(k.name)}" ${(TV2.kinds[k.name] || {}).on === false ? "" : "checked"}></td><td><input type="color" data-kcol="${esc(k.name)}" value="${esc((TV2.kinds[k.name] || {}).color || k.color)}"></td><td><b style="color:${esc((TV2.kinds[k.name] || {}).color || k.color)}">${esc(k.name)}</b>${k.key ? ' <span class="dim">(key)</span>' : ""}</td><td class="dim">${k.ind}</td></tr>`).join("")}</table></div>
      <div class="actions"><button id="tvkdef">Back to Q DATA's colors</button></div></div></details></div>`;
  const v = $("view");
  v.querySelectorAll("[data-copy]").forEach(b => b.onclick = async () => { await tvCopy(b.dataset.copy, b); });
  v.querySelector("[data-allcopy]").onclick = e => allCopy(e.target);
  v.querySelector("[data-allscr]").onclick = e => allScript(e.target, false);
  v.querySelector("[data-allscrdl]").onclick = e => allScript(e.target, true);
  v.querySelectorAll("[data-scr]").forEach(b => b.onclick = () => tvScriptCopy(b.dataset.scr, b, false));
  v.querySelectorAll("[data-scrdl]").forEach(b => b.onclick = () => tvScriptCopy(b.dataset.scrdl, b, true));
  $("tval_which").value = al.which;
  const saveAl = async () => { S.touch = Date.now(); TVW.alerts = await tvFetch("/tv/alerts", {}, { on: $("tval_on").checked, sound: $("tval_snd").checked, notify: $("tval_pop").checked, which: $("tval_which").value }); };
  ["tval_on", "tval_snd", "tval_pop", "tval_which"].forEach(id => $(id).onchange = saveAl);
  v.querySelectorAll("[data-test]").forEach(b => b.onclick = async () => { const t = +b.dataset.test; const r = await tvFetch("/tv/alerts/test", { tier: t }, {}); if (!r.desktop) tvSound(t); });
  v.querySelectorAll("[data-kon]").forEach(el => el.onchange = () => { S.touch = Date.now(); TV2.kinds[el.dataset.kon] = Object.assign(TV2.kinds[el.dataset.kon] || {}, { on: el.checked }); tv2Save(); });
  v.querySelectorAll("[data-kcol]").forEach(el => el.onchange = () => { S.touch = Date.now(); TV2.kinds[el.dataset.kcol] = Object.assign(TV2.kinds[el.dataset.kcol] || {}, { color: el.value }); tv2Save(); render(); });
  $("tvkdef").onclick = () => { if (!confirm("Put every kind back to Q DATA's show and color?")) return; TV2.kinds = {}; tv2Save(); render(); };
};
