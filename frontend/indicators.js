"use strict";
// All indicators tab: every TradingView indicator Q DATA makes, in one place, each with Copy and Download buttons.
// Paste-in indicators (Key Levels, All Tabs) are added to TradingView once; only their levels text is copied each session.
// The baked-in ones (HOD / LOD, Activity heatmap, one per tab) hold today's levels inside the script, so they are re-copied each session.
const IND_SAFE = s => String(s || "").replace(/^_/, "");
function indKeyLevelsText() {
  return api("/analytics/levels", { underlying: S.u, convention: $("conv").value, method: $("method").value, top: S.lvtop, expiration: exps(), by_expiry: S.lvexp, mid: S.lvmid, moves: S.lvmov, ...selParams() })
    .then(lv => indicatorText(lv, lv.meta, lv.mapping.futures_root));
}
function indList() {
  const conv = () => $("conv") ? $("conv").value : "standard", meth = () => $("method") ? $("method").value : "auto";
  const pasteIn = [
    { id: "keylv", name: "Q DATA Key Levels (paste-in)", what: "The Key levels tab's levels. Every level is a see-through zone (or only the ones near price, your choice in its Zones settings). Uses what is shown on the Key levels tab.",
      script: () => api("/export/levels-script", {}), levels: () => indKeyLevelsText().then(it => ({ text: it.text, n: it.count })), where: "Levels (paste from the app)", tab: "levels" },
    { id: "alltabs", name: "Q DATA All Tabs (paste-in)", what: "Every tab's levels in one indicator, with stack zones and the key and GEX levels near price drawn as zones. Pick which tabs and kinds go in on the TradingView indicator tab.",
      script: () => tvScript(), levels: () => tvLevels().then(r => ({ text: r.text, n: r.levels })), where: "Levels from Q DATA", tab: "tvind" }];
  const baked = [
    { id: "hodlod", name: "Q DATA HOD / LOD", what: "Projected high and low of day, the open +/- sd ladder and the gamma playbook, computed live on the chart.", get: () => api("/export/hodlod-pine", { underlying: S.u, convention: conv() }), file: () => `qdata_hodlod_${IND_SAFE(S.u)}.pine`, tab: "hodlod" },
    { id: "heat", name: "Q DATA Activity Heatmap", what: "The Activity heatmap drawn as a real heatmap on the chart: hot spots and activity centers for every measure.", get: () => api("/export/heatmap-pine", { underlying: S.u, convention: conv(), method: meth() }), file: () => `qdata_heatmap_${IND_SAFE(S.u)}.pine`, tab: "heatmap" }];
  const nameOf = Object.fromEntries(TABS);
  Object.entries(TAB_PINE).forEach(([tab, name]) => baked.push({ id: "tab_" + tab, name, what: `Every level from the ${nameOf[tab] || tab} tab, with stack zones and near-price key / GEX zones.`,
    get: () => tvPost("/export/tab-pine", { tab, underlying: S.u, convention: conv() }), file: r => r.filename, tab }));
  return { pasteIn, baked };
}
R.indicators = async function () {
  if (!S.u) { $("view").innerHTML = note("Pick a symbol first."); return; }
  const { pasteIn, baked } = indList();
  const goBtn = (tab, txt) => `<button data-go="${tab}">${esc(txt)}</button>`;
  const nameOf = Object.fromEntries(TABS);
  $("view").innerHTML = `<div class="panel pagehead"><h2>All indicators</h2>
      <p style="max-width:85ch">Every TradingView indicator Q DATA makes, in one place. Zones and fills are bright but see-through, and the key and GEX levels near price are drawn as zones, so what matters right now stands out without hiding the candles.</p></div>
    <div class="panel"><h2>Paste-in indicators</h2><p class="hint" style="margin:0 0 8px"><b>Once:</b> copy the indicator, then in TradingView Pine Editor &gt; new script &gt; select all &gt; paste &gt; Save &gt; Add to chart. <b>Each session:</b> copy the levels and paste them into the indicator's settings. Your TradingView settings stay put because the script never changes.</p>
      <div class="scroll"><table><tr><th>Indicator</th><th>What it shows</th><th>Once: the indicator</th><th>Each session: the levels</th></tr>
      ${pasteIn.map(x => `<tr><td><b>${esc(x.name)}</b><br>${goBtn(x.tab, "Open " + (nameOf[x.tab] || x.tab) + " tab")}</td><td class="dim" style="max-width:46ch">${esc(x.what)}</td>
        <td><span class="actions"><button data-is="${x.id}">Copy</button><button data-isd="${x.id}">Download .pine</button></span></td>
        <td><span class="actions"><button class="go" data-il="${x.id}">Copy levels</button><button data-ild="${x.id}">Download .txt</button></span><br><span class="hint">Paste into: ${esc(x.where)}</span></td></tr>`).join("")}</table></div></div>
    <div class="panel"><h2>Indicators with today's levels inside</h2><p class="hint" style="margin:0 0 8px">These hold today's levels in the script: copy again each session and paste over the old script (Pine Editor &gt; select all &gt; paste &gt; Save).</p>
      <div class="actions" style="margin-bottom:8px"><button id="inddlall">Download every one (.pine files)</button><span class="hint" id="inddlnote"></span></div>
      <div class="scroll"><table><tr><th>Indicator</th><th>What it shows</th><th></th></tr>
      ${baked.map(x => `<tr><td><b>${esc(x.name)}</b><br>${goBtn(x.tab, "Open " + (nameOf[x.tab] || x.tab) + " tab")}</td><td class="dim" style="max-width:56ch">${esc(x.what)}</td>
        <td><span class="actions"><button class="go" data-ib="${x.id}">Copy</button><button data-ibd="${x.id}">Download .pine</button></span></td></tr>`).join("")}</table></div></div>
    <div class="panel"><h2>Zones and colors in TradingView</h2><ul style="max-width:85ch;margin:4px 0 0;padding-left:1.2em">
      <li><b>Key and GEX levels as zones</b> (last group in the All Tabs and tab indicators' settings): <b>Near price</b> (default), <b>All of them</b> or <b>Off</b>, how near counts as near, the zone height, and the fill transparency.</li>
      <li>Key Levels: <b>Zones (each level) &gt; Draw each level as</b> has Zones, Zones near price (lines farther), or Lines.</li>
      <li>Fills default to about 65 to 72% transparent: lower the transparency number for bolder zones, raise it to see more of the candles. Borders stay bright.</li>
      <li>On a white chart, only very light colors (yellow, light cyan) are darkened a little so they stay readable; everything else keeps its full color.</li></ul></div>`;
  const all = [...pasteIn, ...baked], byId = Object.fromEntries(all.map(x => [x.id, x]));
  const v = $("view"), fail = (x, e) => alert(`Could not build ${x.name}: ` + (e.msg || e.message));
  v.querySelectorAll("[data-go]").forEach(b => b.onclick = () => { S.tab = b.dataset.go; $("tabs").querySelectorAll("[data-t]").forEach(t => t.classList.toggle("on", t.dataset.t === S.tab)); render(); });
  v.querySelectorAll("[data-is]").forEach(b => b.onclick = async () => { const x = byId[b.dataset.is]; try { const r = await x.script(); try { await copyText(r.code); b.textContent = "Copied"; } catch (e) { showText(x.name, r.code); } } catch (e) { fail(x, e); } });
  v.querySelectorAll("[data-isd]").forEach(b => b.onclick = async () => { const x = byId[b.dataset.isd]; try { const r = await x.script(); download(r.filename, r.code); b.textContent = "Downloaded"; } catch (e) { fail(x, e); } });
  v.querySelectorAll("[data-il]").forEach(b => b.onclick = async () => { const x = byId[b.dataset.il]; try { const r = await x.levels(); try { await copyText(r.text); b.textContent = `Copied ${r.n} levels`; } catch (e) { showText("Levels for " + x.name, r.text); } } catch (e) { fail(x, e); } });
  v.querySelectorAll("[data-ild]").forEach(b => b.onclick = async () => { const x = byId[b.dataset.ild]; try { const r = await x.levels(); download(`${x.id === "keylv" ? "qdata_key_levels" : "qdata_all_tabs_levels"}_${IND_SAFE(S.u)}.txt`, r.text); b.textContent = "Downloaded"; } catch (e) { fail(x, e); } });
  v.querySelectorAll("[data-ib]").forEach(b => b.onclick = async () => { const x = byId[b.dataset.ib]; try { const r = await x.get(); try { await copyText(r.code); b.textContent = r.levels != null ? `Copied (${r.levels} levels)` : "Copied"; } catch (e) { showText(x.name + " (Pine)", r.code); } } catch (e) { fail(x, e); } });
  v.querySelectorAll("[data-ibd]").forEach(b => b.onclick = async () => { const x = byId[b.dataset.ibd]; try { const r = await x.get(); download(x.file(r), r.code); b.textContent = "Downloaded"; } catch (e) { fail(x, e); } });
  $("inddlall").onclick = async ev => {
    const b = ev.currentTarget, nt = $("inddlnote"); b.disabled = true; let ok = 0; const bad = [];
    for (const x of baked) { nt.textContent = `Building ${x.name}...`; try { const r = await x.get(); await download(x.file(r), r.code); ok += 1; } catch (e) { bad.push(x.name.replace("Q DATA ", "")); } }
    b.disabled = false; nt.textContent = `Saved ${ok} indicator${ok === 1 ? "" : "s"}${bad.length ? `; not available right now: ${bad.join(", ")}` : ""}.`;
  };
};
