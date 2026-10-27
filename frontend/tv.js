"use strict";
// TradingView indicator tab: set the look of Q DATA's TradingView indicators here (which tabs are on when added, each tab's color,
// each kind of level's show/color/style/width, the quick setup, stack zones, labels and tables), then copy or download.
// The choices are saved in this browser (localStorage "nqes.tv") and sent with every indicator copy, including the per-tab
// indicators from the bar at the top of each tab, so they are the indicator's starting settings.
const TV = (() => { try { return Object.assign({ set: {}, tab_colors: {}, kinds: {} }, JSON.parse(localStorage.getItem("nqes.tv") || "{}")); } catch (e) { return { set: {}, tab_colors: {}, kinds: {} }; } })();
const TVLAST = { j: null, changed: false, filter: "" };
function tvSave() { try { localStorage.setItem("nqes.tv", JSON.stringify(TV)); } catch (e) { /* private window: the look lasts this visit */ } TVLAST.changed = true; tvStatus(); }
function tvPrefs() { return JSON.parse(JSON.stringify(TV)); }
async function tvPost(path, params) {
  const qs = new URLSearchParams(Object.entries(Object.assign({}, params, S.src ? { source: S.src } : {})).filter(([, v]) => v != null && v !== "")).toString();
  const r = await fetch("/api" + path + "?" + qs, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prefs: tvPrefs() }) });
  const j = await r.json().catch(() => null);
  if (!r.ok) { const d = j && j.detail; throw { status: r.status, msg: (d && d.reason) || (typeof d === "string" ? d : "Request failed") }; }
  return j;
}
const tvConv = () => $("conv") ? $("conv").value : "standard";
const tvGetAll = () => tvPost("/export/all-pine", { underlying: S.u, convention: tvConv() });
function tvStatus() {
  const el = $("tvstat"); if (!el) return;
  el.textContent = TVLAST.changed ? "Look changed: copy the indicator again, paste it over the old one in Pine Editor, then use Defaults > Reset settings in its settings window." : "";
}
function tvField(x) {
  const v = x.var, cur = TV.set[v], val = cur === undefined ? x.value : cur, id = "tvs_" + v;
  const title = x.title || ({ zDist: "Join distance", zLabelSide: "Zone label side", mergePts: "Same price within (points)", startBars: "N bars" })[v] || v;
  const tip = x.tip ? ` title="${esc(x.tip)}"` : "";
  if (x.type === "bool") return `<label class="chip"${tip}><input type="checkbox" data-tvs="${v}" ${val ? "checked" : ""}> ${esc(title)}</label>`;
  if (x.type === "string") return `<label${tip}>${esc(title)}<select data-tvs="${v}">${x.options.map(o => `<option ${o === val ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`;
  if (x.type === "color") return `<label${tip}>${esc(title)}<input type="color" data-tvs="${v}" value="${esc(val)}"></label>`;
  const auto = x.auto && cur === undefined;
  return `<label${tip}>${esc(title)}${x.auto ? ` <span class="hint">(auto ${fmt(x.default, 2)})</span>` : ""}<input class="wt" type="number" data-tvs="${v}" id="${id}" step="${x.step || 1}" ${x.min != null ? `min="${x.min}"` : ""} ${x.max != null ? `max="${x.max}"` : ""} value="${auto ? "" : esc(val)}" placeholder="${auto ? "auto" : ""}"></label>`;
}
function tvGroup(j, g) { return `<div class="row">${j.settings.filter(x => x.group === g).map(tvField).join("")}</div>`; }
const TVSTY = ["solid", "dashed", "dotted"];
R.tvind = async function () {
  if (!S.u) { $("view").innerHTML = note("Pick a symbol first."); return; }
  const j = await tvGetAll(); TVLAST.j = j;
  const onTabs = j.tabs.filter(t => t.on), withLv = j.tabs.filter(t => t.levels > 0);
  const kinds = j.kinds.filter(k => !TVLAST.filter || (k.name + " " + k.tabs.join(" ")).toLowerCase().includes(TVLAST.filter.toLowerCase()));
  $("view").innerHTML = `<div class="panel pagehead"><h2>TradingView indicator</h2>${metaBar(j.meta)}
      <p style="max-width:85ch">Set how <b>Q DATA All Tabs</b> looks on your chart, then copy it. Everything here becomes the indicator's starting settings, and the same look is used by the indicator buttons at the top of every tab. You can still change anything inside TradingView.</p>
      <div class="actions"><button class="go" id="tvcopy">Copy all-tabs indicator</button><button id="tvdl">Download .pine</button><button id="tvreset" title="Back to Q DATA's built-in look">Reset the look</button></div>
      <p class="hint" style="margin:0">${fmt(j.levels)} levels from ${withLv.length} of ${j.tabs.length} tabs right now. On when added: ${onTabs.map(t => esc(t.name)).join(", ") || "none"}. ${j.mapped ? "Prices are in futures points (estimated)." : "No futures price or basis saved: levels are in index units (use the offset in Quick setup)."}</p>
      <p class="hint" id="tvstat" style="color:var(--warn,#e6b422);margin:6px 0 0"></p></div>
    <div class="panel"><h2>How to use it</h2><ol style="max-width:85ch;margin:6px 0 0;padding-left:1.2em">
      <li>Copy the indicator, open Pine Editor in TradingView, select everything, paste over the old script and click <b>Save</b>, then <b>Add to chart</b> if it is not on yet.</li>
      <li>The levels are baked in, so do this once per session (or whenever Q DATA refreshes and you want the newest levels).</li>
      <li>After you change the look here, open the indicator's settings in TradingView and pick <b>Defaults &gt; Reset settings</b> so it takes Q DATA's look. Set the look here rather than in TradingView: TradingView remembers settings by their position in the script, and the kinds of level change from day to day, so changes made only in TradingView can slide onto the wrong row.</li></ol></div>
    <div class="panel"><h2>Quick setup</h2><p class="hint" style="margin:0">The first group in the indicator's settings: master switches and the most-used filters.</p>${tvGroup(j, "Quick setup")}</div>
    <div class="panel"><h2>Tabs</h2><p class="hint" style="margin:0">Which tabs are switched on when the indicator is first added, and each tab's color (used when "Color levels by" is Tab). Every tab is always in the indicator; tabs without levels right now are just empty.</p>
      <div class="scroll"><table><tr><th>On</th><th>Color</th><th>Tab</th><th>Levels now</th><th>Kinds</th></tr>
      ${j.tabs.map(t => `<tr><td><input type="checkbox" data-tvt="${t.tab}" ${t.on ? "checked" : ""}></td><td><input type="color" data-tvc="${t.tab}" value="${esc(t.color)}"></td>
        <td>${esc(t.name)}${(j.skipped.find(x => x.tab === t.tab) || {}).reason ? `<br><span class="hint">${esc(j.skipped.find(x => x.tab === t.tab).reason)}</span>` : ""}</td><td class="num">${fmt(t.levels)}</td><td class="num">${fmt(t.kinds)}</td></tr>`).join("")}</table></div>
      <div class="actions"><button id="tvall">All on</button><button id="tvnone">All off</button><button id="tvdef">Default (Stack map, Game plan, Session, HOD / LOD)</button></div></div>
    <div class="panel"><h2>Kinds of level</h2><p class="hint" style="margin:0">One row per kind. A change applies on every tab that has that kind. The width here is the base width; very stacked levels are drawn a little thicker.</p>
      <div class="row"><label>Find<input id="tvfind" value="${esc(TVLAST.filter)}" placeholder="GEX, wall, Game plan..."></label><button id="tvkon">Show all kinds</button><button id="tvkdef">Default colors and styles</button></div>
      <div class="scroll"><table><tr><th>Show</th><th>Color</th><th>Style</th><th>Width</th><th>Kind</th><th>Means</th><th>On tabs</th></tr>
      ${kinds.map(k => { const n = esc(k.name); return `<tr><td><input type="checkbox" data-tvk="${n}" data-f="on" ${k.on ? "checked" : ""}></td><td><input type="color" data-tvk="${n}" data-f="color" value="${esc(k.color)}"></td>
        <td><select data-tvk="${n}" data-f="style">${TVSTY.map(s => `<option value="${s}" ${s === k.style ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}</select></td>
        <td><select data-tvk="${n}" data-f="width">${[1, 2, 3, 4, 5, 6].map(w => `<option ${w === k.width ? "selected" : ""}>${w}</option>`).join("")}</select></td>
        <td title="${esc(k.help)}"><b style="color:${esc(k.color)}">${n}</b></td><td class="dim">${esc(k.short)}</td><td class="dim">${esc(k.tabs.join(", "))}</td></tr>`; }).join("") || `<tr><td colspan="7" class="dim">No kind matches.</td></tr>`}</table></div></div>
    <details class="adv" data-k="tv-zones"><summary>Stack zones</summary><div class="body"><p class="hint">Shaded areas drawn live on the chart where several of the levels you have on sit close together.</p>${tvGroup(j, "Stack zones (estimated)")}</div></details>
    <details class="adv" data-k="tv-labels"><summary>Labels and lines</summary><div class="body">${tvGroup(j, "Labels and lines")}</div></details>
    <details class="adv" data-k="tv-tables"><summary>Tables</summary><div class="body">${tvGroup(j, "Tables")}</div></details>`;
  tvStatus();
  const busy = () => { S.touch = Date.now(); };
  const v = $("view");
  v.querySelectorAll("[data-tvs]").forEach(el => el.onchange = () => {
    busy(); const x = j.settings.find(s => s.var === el.dataset.tvs);
    if (x.type === "bool") TV.set[x.var] = el.checked;
    else if (x.type === "int" || x.type === "float") { if (el.value === "") delete TV.set[x.var]; else { const n = x.type === "int" ? parseInt(el.value, 10) : parseFloat(el.value); if (isNaN(n)) delete TV.set[x.var]; else TV.set[x.var] = n; } }
    else TV.set[x.var] = el.value;
    tvSave();
  });
  const tabsOn = () => TV.tabs_on || j.tabs.filter(t => t.on).map(t => t.tab);
  v.querySelectorAll("[data-tvt]").forEach(el => el.onchange = () => { busy(); const on = new Set(tabsOn()); el.checked ? on.add(el.dataset.tvt) : on.delete(el.dataset.tvt); TV.tabs_on = j.tabs.map(t => t.tab).filter(t => on.has(t)); tvSave(); });
  v.querySelectorAll("[data-tvc]").forEach(el => el.onchange = () => { busy(); TV.tab_colors[el.dataset.tvc] = el.value; tvSave(); });
  v.querySelectorAll("[data-tvk]").forEach(el => el.onchange = () => {
    busy(); const k = TV.kinds[el.dataset.tvk] = TV.kinds[el.dataset.tvk] || {}, f = el.dataset.f;
    k[f] = f === "on" ? el.checked : f === "width" ? parseInt(el.value, 10) : el.value;
    tvSave(); if (f === "color") { const b = el.closest("tr").querySelector("b"); if (b) b.style.color = el.value; }
  });
  const setAllTabs = list => { TV.tabs_on = list; tvSave(); render(); };
  $("tvall").onclick = () => setAllTabs(j.tabs.map(t => t.tab));
  $("tvnone").onclick = () => setAllTabs([]);
  $("tvdef").onclick = () => { delete TV.tabs_on; tvSave(); render(); };
  $("tvkon").onclick = () => { j.kinds.forEach(k => { TV.kinds[k.name] = Object.assign(TV.kinds[k.name] || {}, { on: true }); }); tvSave(); render(); };
  $("tvkdef").onclick = () => { if (!confirm("Put every kind back to Q DATA's default color, style and width?")) return; Object.keys(TV.kinds).forEach(n => { const on = TV.kinds[n].on; TV.kinds[n] = on === undefined ? {} : { on }; }); tvSave(); render(); };
  $("tvfind").oninput = e => { TVLAST.filter = e.target.value; clearTimeout(TVLAST.ft); TVLAST.ft = setTimeout(() => { render().then(() => { const f = $("tvfind"); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }); }, 350); };
  $("tvreset").onclick = () => { if (!confirm("Reset the whole indicator look to Q DATA's built-in settings?")) return; TV.set = {}; TV.tab_colors = {}; TV.kinds = {}; delete TV.tabs_on; tvSave(); render(); };
  const fail = e => alert("Could not build Q DATA All Tabs: " + (e.msg || e.message));
  $("tvcopy").onclick = async ev => { const b = ev.currentTarget; try { const r = await tvGetAll(); try { await copyText(r.code); b.textContent = `Copied (${r.levels} levels)`; TVLAST.changed = false; tvStatus(); } catch (e) { showText("Q DATA All Tabs (Pine)", r.code); } } catch (e) { fail(e); } };
  $("tvdl").onclick = async ev => { const b = ev.currentTarget; try { const r = await tvGetAll(); download(r.filename, r.code); b.textContent = "Downloaded"; TVLAST.changed = false; tvStatus(); } catch (e) { fail(e); } };
};
