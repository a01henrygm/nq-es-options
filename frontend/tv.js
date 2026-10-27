"use strict";
// TradingView indicator tab: Q DATA All Tabs is a PASTE-IN indicator, like the Key levels one. Add the script to TradingView once,
// then each session copy the levels here and paste them into the indicator's "Levels from Q DATA" setting.
// What goes into the levels (which tabs, and each kind's show / key / color / style / width) is chosen here and saved in this
// browser (localStorage "nqes.tv"). Everything else (view, zones, labels, tables) is set in TradingView and stays put there,
// because the script never changes. The same look is also sent with the per-tab indicators from the bar at the top of each tab.
const TV = (() => { try { return Object.assign({ set: {}, tab_colors: {}, kinds: {} }, JSON.parse(localStorage.getItem("nqes.tv") || "{}")); } catch (e) { return { set: {}, tab_colors: {}, kinds: {} }; } })();
const TVLAST = { j: null, filter: "" };
function tvSave() { try { localStorage.setItem("nqes.tv", JSON.stringify(TV)); } catch (e) { /* private window: the choices last this visit */ } }
function tvPrefs() { return JSON.parse(JSON.stringify(TV)); }
async function tvPost(path, params) {
  const qs = new URLSearchParams(Object.entries(Object.assign({}, params, S.src ? { source: S.src } : {})).filter(([, v]) => v != null && v !== "")).toString();
  const r = await fetch("/api" + path + "?" + qs, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prefs: tvPrefs() }) });
  const j = await r.json().catch(() => null);
  if (!r.ok) { const d = j && j.detail; throw { status: r.status, msg: (d && d.reason) || (typeof d === "string" ? d : "Request failed") }; }
  return j;
}
const tvConv = () => $("conv") ? $("conv").value : "standard";
const tvLevels = () => tvPost("/export/all-levels", { underlying: S.u, convention: tvConv() });
const tvScript = () => api("/export/all-script", {});
const TVSTY = ["solid", "dashed", "dotted"];
R.tvind = async function () {
  if (!S.u) { $("view").innerHTML = note("Pick a symbol first."); return; }
  const j = await tvLevels(); TVLAST.j = j;
  const inc = j.tabs.filter(t => t.on);
  const kinds = j.kinds.filter(k => !TVLAST.filter || (k.name + " " + k.tabs.join(" ")).toLowerCase().includes(TVLAST.filter.toLowerCase()));
  $("view").innerHTML = `<div class="panel pagehead"><h2>TradingView indicator</h2>${metaBar(j.meta)}
      <p style="max-width:85ch"><b>Q DATA All Tabs</b> works like the Key levels indicator: add the script to TradingView once, then each session copy the levels here and paste them into its settings. The script never changes, so every setting you make in TradingView stays put.</p></div>
    <div class="panel"><h2>Each session: copy the levels</h2>
      <div class="actions"><button class="go" id="tvcopy">Copy levels</button><button id="tvlvdl">Download levels .txt</button></div>
      <p class="hint" style="margin:0 0 8px">${fmt(j.levels)} levels from ${inc.length} tab${inc.length === 1 ? "" : "s"} (${inc.map(t => esc(t.name)).join(", ") || "none"}). In the default Clean view about ${fmt(j.key_lines)} of them are drawn as lines; the rest go into the shaded zones. ${fmt(j.chars)} characters${j.tips_dropped ? ", hover text left out to fit" : ""}${j.cut ? `, ${fmt(j.cut)} far-away levels left out to fit` : ""}. ${j.mapped ? "Prices are in futures points (estimated)." : "No futures price or basis saved: levels are in index units (use the offset in the indicator's Quick setup)."}</p>
      <textarea id="tvtext" readonly spellcheck="false" style="width:100%;height:150px;font:calc(12px*var(--z)) ui-monospace,Menlo,Consolas,monospace">${esc(j.text)}</textarea>
      <p class="hint">In TradingView: open the Q DATA All Tabs settings, click into <b>Levels from Q DATA</b>, select all, paste, OK.</p></div>
    <div class="panel"><h2>Once: add the indicator to TradingView</h2>
      <div class="actions"><button id="tvscript">Copy the indicator</button><button id="tvscriptdl">Download .pine</button></div>
      <p class="hint" style="margin:0">Pine Editor &gt; new script &gt; select all &gt; paste &gt; Save &gt; Add to chart. Only needed again if a Q DATA update says the indicator changed. If you had the old all-tabs indicator on your chart, remove it.</p></div>
    <div class="panel"><h2>Less clutter</h2><ul style="max-width:85ch;margin:4px 0 0;padding-left:1.2em">
      <li>The indicator opens in the <b>Clean</b> view: shaded zones where levels pile up, and only the <b>key</b> levels as lines. Choose which kinds are key below.</li>
      <li>Fewer tabs in the levels means fewer zones and lines; Stack map, Game plan, Session and HOD / LOD is a good start.</li>
      <li>In TradingView: <b>Stack zones &gt; Minimum to make a zone</b> higher for fewer, stronger zones; <b>Join levels within</b> bigger for fewer, wider zones; <b>Hide kinds whose name contains</b> for a quick filter; <b>Only the nearest N lines</b> to cap the lines.</li></ul></div>
    <div class="panel"><h2>Tabs in the levels</h2><p class="hint" style="margin:0">Only these tabs go into the levels you copy. You can still switch any of them off in TradingView without copying again.</p>
      <div class="scroll"><table><tr><th>Include</th><th>Tab</th><th>Levels now</th><th>Kinds</th></tr>
      ${j.tabs.map(t => `<tr><td><input type="checkbox" data-tvt="${t.tab}" ${t.on ? "checked" : ""}></td><td>${esc(t.name)}${t.reason ? `<br><span class="hint">${esc(t.reason)}</span>` : ""}</td><td class="num">${fmt(t.levels)}</td><td class="num">${fmt(t.kinds)}</td></tr>`).join("")}</table></div>
      <div class="actions"><button id="tvall">All</button><button id="tvnone">None</button><button id="tvdef">Default (Stack map, Game plan, Session, HOD / LOD)</button></div></div>
    <div class="panel"><h2>Kinds of level</h2><p class="hint" style="margin:0"><b>Show</b> = in the levels at all. <b>Key</b> = drawn as a line in the Clean view (the others only shape the zones). Color, style and width travel with the levels, so they change as soon as you paste.</p>
      <div class="row"><label>Find<input id="tvfind" value="${esc(TVLAST.filter)}" placeholder="GEX, wall, Game plan..."></label><button id="tvkon">Show all kinds</button><button id="tvkdef">Back to defaults</button></div>
      <div class="scroll"><table><tr><th>Show</th><th>Key</th><th>Color</th><th>Style</th><th>Width</th><th>Kind</th><th>Means</th><th>On tabs</th></tr>
      ${kinds.map(k => { const n = esc(k.name); return `<tr><td><input type="checkbox" data-tvk="${n}" data-f="on" ${k.on ? "checked" : ""}></td><td><input type="checkbox" data-tvk="${n}" data-f="key" ${k.key ? "checked" : ""}></td>
        <td><input type="color" data-tvk="${n}" data-f="color" value="${esc(k.color)}"></td>
        <td><select data-tvk="${n}" data-f="style">${TVSTY.map(s => `<option value="${s}" ${s === k.style ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}</select></td>
        <td><select data-tvk="${n}" data-f="width">${[1, 2, 3, 4, 5, 6].map(w => `<option ${w === k.width ? "selected" : ""}>${w}</option>`).join("")}</select></td>
        <td title="${esc(k.help)}"><b style="color:${esc(k.color)}">${n}</b></td><td class="dim">${esc(k.short)}</td><td class="dim">${esc(k.tabs.join(", "))}</td></tr>`; }).join("") || `<tr><td colspan="8" class="dim">No kind matches.</td></tr>`}</table></div></div>`;
  const busy = () => { S.touch = Date.now(); };
  const v = $("view");
  const tabsOn = () => TV.tabs_on || j.tabs.filter(t => t.on).map(t => t.tab);
  v.querySelectorAll("[data-tvt]").forEach(el => el.onchange = () => { busy(); const on = new Set(tabsOn()); el.checked ? on.add(el.dataset.tvt) : on.delete(el.dataset.tvt); TV.tabs_on = j.tabs.map(t => t.tab).filter(t => on.has(t)); tvSave(); render(); });
  v.querySelectorAll("[data-tvk]").forEach(el => el.onchange = () => {
    busy(); const k = TV.kinds[el.dataset.tvk] = TV.kinds[el.dataset.tvk] || {}, f = el.dataset.f;
    k[f] = f === "on" || f === "key" ? el.checked : f === "width" ? parseInt(el.value, 10) : el.value;
    tvSave(); render();
  });
  const setTabs = list => { if (list) TV.tabs_on = list; else delete TV.tabs_on; tvSave(); render(); };
  $("tvall").onclick = () => setTabs(j.tabs.map(t => t.tab));
  $("tvnone").onclick = () => setTabs([]);
  $("tvdef").onclick = () => setTabs(null);
  $("tvkon").onclick = () => { j.kinds.forEach(k => { TV.kinds[k.name] = Object.assign(TV.kinds[k.name] || {}, { on: true }); }); tvSave(); render(); };
  $("tvkdef").onclick = () => { if (!confirm("Put every kind back to Q DATA's default show, key, color, style and width?")) return; TV.kinds = {}; tvSave(); render(); };
  $("tvfind").oninput = e => { TVLAST.filter = e.target.value; clearTimeout(TVLAST.ft); TVLAST.ft = setTimeout(() => { render().then(() => { const f = $("tvfind"); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }); }, 350); };
  $("tvtext").onclick = () => $("tvtext").select();
  const fail = e => alert("Could not build the levels: " + (e.msg || e.message));
  $("tvcopy").onclick = async ev => { const b = ev.currentTarget; try { const r = await tvLevels(); try { await copyText(r.text); b.textContent = `Copied ${r.levels} levels`; } catch (e) { showText("Levels for Q DATA All Tabs", r.text); } } catch (e) { fail(e); } };
  $("tvlvdl").onclick = async ev => { const b = ev.currentTarget; try { const r = await tvLevels(); download(`qdata_all_tabs_levels_${S.u.replace(/^_/, "")}.txt`, r.text); b.textContent = "Downloaded"; } catch (e) { fail(e); } };
  const failS = e => alert("Could not build the indicator: " + (e.msg || e.message));
  $("tvscript").onclick = async ev => { const b = ev.currentTarget; try { const r = await tvScript(); try { await copyText(r.code); b.textContent = "Copied the indicator"; } catch (e) { showText("Q DATA All Tabs (Pine)", r.code); } } catch (e) { failS(e); } };
  $("tvscriptdl").onclick = async ev => { const b = ev.currentTarget; try { const r = await tvScript(); download(r.filename, r.code); b.textContent = "Downloaded"; } catch (e) { failS(e); } };
};
