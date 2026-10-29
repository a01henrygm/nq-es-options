"""Q DATA All Tabs, back as a third paste-in indicator next to Q DATA GEX and Q DATA Levels (1.24.4).

1.24.0 replaced it with the two new indicators; some levels people were used to (every tab's own lines, the info table, the
expected-move cone) were no longer on the chart. This brings the classic one back unchanged, with EVERY tab's levels in the text
by default. Each tab can still be switched off in the indicator's settings ("Tabs"), and the Clean view keeps the chart readable.

  GET  /api/tv/alltabs/script   the script (add to TradingView once; it never changes, so its settings stay put)
  POST /api/tv/alltabs/levels   the levels text to paste. body: {"prefs": {"kinds": {...}, "tabs_on": [...]}} (both optional)
"""
from __future__ import annotations

from fastapi import Body, HTTPException

from .services import analytics as an
from .services.paste_pine import build_levels_text, build_paste_script
from .timeutil import to_et


def register(app, h, q, tab_parts, TABS):
    tab_names = [(k, v[0].replace("Q DATA ", "")) for k, v in TABS.items()]

    @app.get("/api/tv/alltabs/script")
    def alltabs_script():
        return {"code": build_paste_script(tab_names), "title": "Q DATA All Tabs", "filename": "qdata_all_tabs_paste_in.pine",
                "note": "Add this to TradingView once (Pine Editor > paste > Save > Add to chart). Then paste the levels from Q DATA into its settings."}

    @app.post("/api/tv/alltabs/levels")
    def alltabs_levels(underlying: str, convention: str = "standard", body: dict = Body(default={})):
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c = q.context(u, convention)
        prefs = (body or {}).get("prefs") if isinstance((body or {}).get("prefs"), dict) else {}
        kinds = prefs.get("kinds") if isinstance(prefs.get("kinds"), dict) else {}
        clean = {"kinds": {n: {kk: k[kk] for kk in ("on", "color", "style", "width", "key") if kk in k}
                           for n, k in list(kinds.items())[:500] if isinstance(n, str) and isinstance(k, dict)}}
        want = [x for x in prefs.get("tabs_on") or [] if x in TABS] or list(TABS)        # default: every tab
        sections, skipped, cone, included = [], [], None, []
        for tab, (title, _short, _f) in TABS.items():
            if tab not in want:
                continue
            name = title.replace("Q DATA ", "")
            try:
                groups, levels, table, cone_, _about = tab_parts(tab, u, convention, c)
            except HTTPException as e:
                skipped.append({"tab": tab, "name": name, "reason": str(e.detail)})
                continue
            cone = cone or cone_
            included.append({"tab": tab, "name": name, "levels": len(levels)})
            sections.append({"tab": tab, "name": name, "groups": groups, "levels": levels, "table": table})
        m = c["m"]
        mapped = c["spot_f"] is not None
        root = c["root"]
        units = (f"Prices are ESTIMATED {root} points (converted from {m['underlying']})." if mapped
                 else f"Prices are in {m['underlying']} units (no {root or 'futures'} price or basis saved). Use the offset setting.")
        head_rows = [("Symbol", f"{m['underlying']} -> {root} (est.)" if mapped else m["underlying"]),
                     ("Data", f"{m['calculated_at_et']} ({m['data_status']})")]
        now = to_et(c["now"])
        out = build_levels_text(sections, head_rows, now.strftime("%b %d %H:%M ET"), now.strftime("%Y-%m-%d"), m["underlying"], units, cone,
                                c["spot_f"] or c["snap"].spot, clean)
        return {"text": out["text"], "levels": out["levels"], "chars": out["chars"], "cut": out["cut"], "tabs": included, "skipped": skipped,
                "mapped": mapped, "data_as_of": m.get("calculated_at"),
                "note": "Paste into the Q DATA All Tabs indicator's settings (Levels from Q DATA)."}
