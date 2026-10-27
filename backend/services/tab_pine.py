"""Q DATA's tab indicators for TradingView (Pine Script v6): one per tab that has levels ("Q DATA Stack Map", ...) and one with
every tab ("Q DATA All Tabs"). Both come from build_pine() below, so they have the same settings.

TradingView cannot read the app, so the levels are baked in as arrays when you copy or download the indicator (re-copy each session).
Everything about HOW they are drawn is a setting in the indicator:
  - Quick setup at the top: master switches (lines, labels, zones, tables), color levels by kind / tab / side of price, how many
    levels to show, emphasis on the nearest level each side, and an offset for a different contract
  - per tab: a Show switch and a tab color; per kind of level: show/hide, color, line style and width on one row, with a tooltip
  - estimated stack zones: computed live on the chart from the levels you have switched on. Where enough levels (different kinds,
    different tabs, or simply levels) sit within a distance you choose, a zone is drawn, colored by strength or by side of price,
    and labeled with how many reasons are stacked there. Every number is a setting.
  - labels (name, plain-English meaning, price), a legend of what each color means, an info table with the nearest zones.

The starting value of every setting can be chosen in Q DATA (the "TradingView indicator" tab) and is passed in as `prefs`:
  {"set": {<setting var>: value}, "tabs_on": [tab keys], "tab_colors": {tab key: "#rrggbb"},
   "kinds": {<kind name>: {"on": bool, "color": "#rrggbb", "style": "solid|dashed|dotted", "width": 1-6}}}
Anything missing or invalid falls back to the built-in default. SETTINGS (below) is the list Q DATA's tab draws its form from.

TradingView limits how many outside values (inputs) one function may read, counting everything the functions it calls read too
(CE10116, 254 "external elements", int/float/bool count 2). So the per-tab and per-kind settings are gathered into arrays once, and
the drawing functions read the arrays (one element each) instead of hundreds of inputs.
Written as conservative Pine v6; it has not been compiled by TradingView from here.
"""
from __future__ import annotations
import re

STYLES = {"solid": "Solid", "dashed": "Dashed", "dotted": "Dotted"}
CALL_COLOR = {"RESPECT": "#3fb96a", "CHOP": "#e6b422", "DISRESPECT": "#e5534b"}
CALL_WORD = {"RESPECT": "HOLD", "CHOP": "CHOP", "DISRESPECT": "BREAK"}
POSITIONS = ["Top right", "Top left", "Top center", "Bottom right", "Bottom left", "Bottom center", "Middle right", "Middle left"]
POS_EXPR = ('{v} == "Top left" ? position.top_left : {v} == "Top center" ? position.top_center : {v} == "Bottom right" ? position.bottom_right : '
            '{v} == "Bottom left" ? position.bottom_left : {v} == "Bottom center" ? position.bottom_center : {v} == "Middle right" ? position.middle_right : '
            '{v} == "Middle left" ? position.middle_left : position.top_right')
# Default tab colors (used when "Color levels by" is set to Tab)
TAB_COLORS = ["#2f8bf5", "#ff7a2e", "#3fb96a", "#e6b422", "#7db7ff", "#a371f7", "#22d3ee", "#ff4d8d", "#c77dff", "#2ec4b6", "#e76f51",
              "#4cc9f0", "#f72585", "#b5e48c", "#ffb703", "#8e9bff", "#f06292", "#9aa4b8"]

GQ, GZ, GL, GT = "Quick setup", "Stack zones (estimated)", "Labels and lines", "Tables"
COLOR_MODES = ["Kind of level", "Tab", "Above / below price"]

# Every setting that is not per tab or per kind, in the order it appears in TradingView. default None = worked out from the data.
SETTINGS = [
    # ---- quick setup ----
    {"var": "showLines", "type": "bool", "default": True, "title": "Lines", "group": GQ, "inline": "q1"},
    {"var": "showLabels", "type": "bool", "default": True, "title": "Labels", "group": GQ, "inline": "q1"},
    {"var": "zOn", "type": "bool", "default": True, "title": "Stack zones", "group": GQ, "inline": "q1",
     "tip": "Lines, labels and the estimated stack zones (shaded areas where several levels pile up) can each be switched off here."},
    {"var": "showTable", "type": "bool", "default": True, "title": "Info table", "group": GQ, "inline": "q2"},
    {"var": "showLegend", "type": "bool", "default": True, "title": "Legend", "group": GQ, "inline": "q2"},
    {"var": "colorMode", "type": "string", "default": "Kind of level", "title": "Color levels by", "group": GQ, "options": COLOR_MODES,
     "tip": "Kind of level: each kind has its own color (set under each tab). Tab: every level from a tab gets that tab's color. "
            "Above / below price: one color above price, one below (the two colors on the next row)."},
    {"var": "colUp", "type": "color", "default": "#e5534b", "title": "Above price", "group": GQ, "inline": "qc"},
    {"var": "colDn", "type": "color", "default": "#3fb96a", "title": "Below price", "group": GQ, "inline": "qc"},
    {"var": "nearestN", "type": "int", "default": 0, "title": "Only the nearest N levels on each side (0 = all)", "group": GQ, "min": 0, "max": 100},
    {"var": "maxDistPct", "type": "float", "default": None, "title": "Hide levels farther than this % from price", "group": GQ, "min": 0.1, "step": 0.5},
    {"var": "emphNear", "type": "bool", "default": True, "title": "Thicker line for the nearest level above and below price", "group": GQ},
    {"var": "offsetPts", "type": "float", "default": 0.0, "title": "Add to every level (points)", "group": GQ, "step": 0.25,
     "tip": "Use this if your chart is a different contract or month, or Q DATA had no NQ/ES price or basis saved."},
    # ---- stack zones ----
    {"var": "zCount", "type": "string", "default": "Different kinds", "title": "Count", "group": GZ, "options": ["Different kinds", "Different tabs", "Every level"],
     "tip": "Different kinds (default): two open-interest strikes count once, so a zone needs different reasons. Different tabs: each tab counts once. Every level: every line counts."},
    {"var": "zMin", "type": "int", "default": 3, "title": "Minimum to make a zone", "group": GZ, "inline": "zn", "min": 2, "max": 30},
    {"var": "zHeavy", "type": "int", "default": 5, "title": "Heavy at", "group": GZ, "inline": "zn", "min": 2, "max": 30,
     "tip": "A zone needs at least the minimum count. At the heavy count it gets the heavy color and a thicker border."},
    {"var": "zDistMode", "type": "string", "default": "Points", "title": "Join levels within", "group": GZ, "inline": "zd", "options": ["Points", "% of price"]},
    {"var": "zDist", "type": "float", "default": None, "title": "", "group": GZ, "inline": "zd", "min": 0.01, "step": 0.25,
     "tip": "Levels this close to each other (in points, or % of price) join the same zone. NQ: 8 to 15 points is a good start. ES: 2 to 4."},
    {"var": "zMaxW", "type": "float", "default": None, "title": "Widest zone (points)", "group": GZ, "min": 1.0, "step": 1.0,
     "tip": "Stops a chain of close levels from turning into one huge zone."},
    {"var": "zPad", "type": "float", "default": 2.0, "title": "Pad each side (points)", "group": GZ, "min": 0.0, "step": 0.25},
    {"var": "zColorMode", "type": "string", "default": "Strength", "title": "Color zones by", "group": GZ, "options": ["Strength", "Above / below price"]},
    {"var": "zCol", "type": "color", "default": "#2f8bf5", "title": "Stacked", "group": GZ, "inline": "zc1"},
    {"var": "zColH", "type": "color", "default": "#ff7a2e", "title": "Heavy", "group": GZ, "inline": "zc1"},
    {"var": "zColUp", "type": "color", "default": "#e5534b", "title": "Above price", "group": GZ, "inline": "zc2"},
    {"var": "zColDn", "type": "color", "default": "#3fb96a", "title": "Below price", "group": GZ, "inline": "zc2"},
    {"var": "zTransp", "type": "int", "default": 80, "title": "Zone transparency", "group": GZ, "min": 0, "max": 100},
    {"var": "zBorder", "type": "bool", "default": True, "title": "Zone border", "group": GZ},
    {"var": "zLabel", "type": "bool", "default": True, "title": "Zone label", "group": GZ, "inline": "zl"},
    {"var": "zLabelSide", "type": "string", "default": "Right", "title": "", "group": GZ, "inline": "zl", "options": ["Right", "Left"]},
    {"var": "zOnly", "type": "bool", "default": False, "title": "Only zones (hide the single lines inside them)", "group": GZ},
    # ---- labels and lines ----
    {"var": "labelText", "type": "string", "default": "Name + meaning + price", "title": "Label shows", "group": GL,
     "options": ["Name", "Name + price", "Name + meaning", "Name + meaning + price", "Meaning + price"],
     "tip": "Meaning = a few plain words on what the level is (ceiling, floor, should hold...). Hover any label for the full reason."},
    {"var": "labelSize", "type": "string", "default": "Small", "title": "Label size", "group": GL, "options": ["Tiny", "Small", "Normal", "Large"]},
    {"var": "labelTxtC", "type": "color", "default": "#ffffff", "title": "Label text", "group": GL, "inline": "lc"},
    {"var": "labelTransp", "type": "int", "default": 25, "title": "Label background transparency", "group": GL, "inline": "lc", "min": 0, "max": 100},
    {"var": "labelSide", "type": "string", "default": "Right", "title": "Labels on the", "group": GL, "options": ["Right", "Left"]},
    {"var": "priceDec", "type": "int", "default": 2, "title": "Price decimals", "group": GL, "min": 0, "max": 4},
    {"var": "mergeSame", "type": "bool", "default": True, "title": "One label for levels at the same price", "group": GL, "inline": "mg",
     "tip": "Levels within this many points share one label listing every name."},
    {"var": "mergePts", "type": "float", "default": 1.0, "title": "", "group": GL, "inline": "mg", "min": 0.0, "step": 0.25},
    {"var": "startMode", "type": "string", "default": "Session open 9:30 ET", "title": "Lines start at", "group": GL, "inline": "st",
     "options": ["Session open 9:30 ET", "Start of chart data", "Last N bars"]},
    {"var": "startBars", "type": "int", "default": 50, "title": "", "group": GL, "inline": "st", "min": 1, "max": 4000},
    {"var": "extBars", "type": "int", "default": 8, "title": "Lines run this many bars past the last candle", "group": GL, "min": 0, "max": 500},
    {"var": "zoneTransp", "type": "int", "default": 82, "title": "Level zone transparency (GEX and walls)", "group": GL, "min": 0, "max": 100},
    # ---- tables ----
    {"var": "tablePos", "type": "string", "default": "Top right", "title": "Info table at", "group": GT, "options": POSITIONS},
    {"var": "legendPos", "type": "string", "default": "Bottom right", "title": "Legend at", "group": GT, "options": POSITIONS},
    {"var": "tableSize", "type": "string", "default": "Small", "title": "Table text size", "group": GT, "options": ["Tiny", "Small", "Normal"]},
    {"var": "tableBg", "type": "color", "default": "#0f1626", "title": "Table background", "group": GT, "inline": "tbc"},
    {"var": "tableTxt", "type": "color", "default": "#ffffff", "title": "Text", "group": GT, "inline": "tbc"},
]
SET_BY_VAR = {x["var"]: x for x in SETTINGS}


def s(text, n=None) -> str:
    """Make text safe inside a Pine string literal or comment."""
    t = re.sub(r"\s+", " ", re.sub(r'["\\]', "", str(text if text is not None else ""))).strip()
    return t[:n] if n else t


def q(text, n=None) -> str:
    return '"' + s(text, n) + '"'


def _hex(c, fallback="#9aa4b8") -> str:
    c = str(c or "").strip()
    return c if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else fallback


def _num(v) -> str:
    return f"{float(v):.2f}"


def _group(g) -> dict:
    """Accepts a group as a plain name or a dict {name, color, style, width, short, help}."""
    if isinstance(g, str):
        g = {"name": g}
    return {"name": g.get("name") or "Levels", "color": _hex(g.get("color")), "style": STYLES.get(g.get("style") or "solid", "Solid"),
            "width": max(1, min(4, int(g.get("width") or 1))), "short": g.get("short") or "", "help": g.get("help") or g.get("name") or "",
            "on": g.get("on") is not False}


def setting_value(spec: dict, prefs_set: dict | None, auto: dict | None = None):
    """The starting value of one setting: the user's choice from Q DATA if it is valid, else the default (or the data-based one)."""
    d = spec["default"] if spec["default"] is not None else (auto or {}).get(spec["var"])
    v = (prefs_set or {}).get(spec["var"])
    t = spec["type"]
    try:
        if v is None:
            return d
        if t == "bool":
            return v if isinstance(v, bool) else d
        if t == "string":
            return v if v in spec.get("options", []) else d
        if t == "color":
            return _hex(v, d)
        x = int(v) if t == "int" else float(v)
        if x != x:                                              # NaN
            return d
        if "min" in spec:
            x = max(spec["min"], x)
        if "max" in spec:
            x = min(spec["max"], x)
        return x
    except (TypeError, ValueError):
        return d


def _lit(t, v) -> str:
    if t == "bool":
        return "true" if v else "false"
    if t == "int":
        return str(int(v))
    if t == "float":
        return f"{float(v):.2f}"
    if t == "color":
        return _hex(v)
    return q(v)


def _input(spec: dict, value, group_var: str) -> str:
    t = spec["type"]
    parts = [_lit(t, value), q(spec["title"], 80)]
    if t == "string":
        parts.append("options = [" + ", ".join(q(o) for o in spec["options"]) + "]")
    for k, nm in (("min", "minval"), ("max", "maxval"), ("step", "step")):
        if k in spec and t in ("int", "float"):
            parts.append(f"{nm} = {_lit(t, spec[k])}")
    parts.append(f"group = {group_var}")
    if spec.get("inline"):
        parts.append(f'inline = "{spec["inline"]}"')
    if spec.get("tip"):
        parts.append(f"tooltip = {q(spec['tip'], 400)}")
    return f'{spec["var"]} = input.{t}({", ".join(parts)})'


CHUNK = 60          # items per array.from(): keeps every function small


def _arr(name: str, typ: str, items: list) -> list:
    """Pine lines declaring `var <typ>[] name`, filled by functions that each hold at most CHUNK items. TradingView limits how much
    code the main body (outside functions) may hold, so the long baked-in lists live in functions instead."""
    parts = [items[i:i + CHUNK] for i in range(0, len(items), CHUNK)] or [["na"]]
    o = []
    for k, part in enumerate(parts):
        o += [f'_{name}{k}() =>', f'    array.from({", ".join(part)})']
    if len(parts) == 1:
        o.append(f'var {typ}[] {name} = _{name}0()')
    else:
        o += [f'_{name}() =>', f'    a = _{name}0()']
        o += [f'    array.concat(a, _{name}{k}())' for k in range(1, len(parts))]
        o += ['    a', f'var {typ}[] {name} = _{name}()']
    return o


SET_CHUNK = 80      # settings per gathering function: 80 int/bool settings = 160 external elements, well under TradingView's 254


def _set_arr(name: str, typ: str, refs: list) -> list:
    """Gathers settings (input variables) into one array, `var <typ>[] name`. Each gathering function reads at most SET_CHUNK of
    them, and the extra parts are added on the first bar in the main script (not in a function), so no single function ever reads
    more than SET_CHUNK settings, however many tabs and kinds there are."""
    parts = [refs[i:i + SET_CHUNK] for i in range(0, len(refs), SET_CHUNK)]
    if not parts:
        return [f'var {typ}[] {name} = array.new<{typ}>()']
    o = []
    for k, part in enumerate(parts):
        o += [f'_{name}{k}() =>', f'    array.from({", ".join(part)})']
    o.append(f'var {typ}[] {name} = _{name}0()')
    if len(parts) > 1:
        o.append('if barstate.isfirst')
        o += [f'    array.concat({name}, _{name}{k}())' for k in range(1, len(parts))]
    return o


def build_tab_pine(title: str, short: str, groups: list, levels: list, table: list | None = None, source: str = "", units: str = "",
                   made_at: str = "", cone: dict | None = None, max_dist_pct: float = 4.0, about: str = "", zone_pts: float = 10.0,
                   prefs: dict | None = None, tab: str = "tab") -> str:
    """One tab's indicator. groups: names or dicts (see _group). levels: dicts with price, group (index), label, optional low/high
    (zone edges), tip (hover text) and boost (extra line width). table: (name, value) rows."""
    sec = {"tab": "session" if cone else tab, "name": title.replace("Q DATA ", ""), "on": True, "groups": groups, "levels": levels,
           "table": table or [], "about": about}
    return build_pine(title, short, [sec], [], source, units, made_at, cone, max_dist_pct, single=True, about=about, zone_pts=zone_pts, prefs=prefs)


def build_all_pine(sections: list, head_rows: list, source: str, units: str, made_at: str, cone: dict | None = None, max_dist_pct: float = 4.0,
                   zone_pts: float = 10.0, prefs: dict | None = None) -> str:
    """Every tab in one indicator, "Q DATA All Tabs". sections: [{tab, name, on, groups, levels, table}]."""
    return build_pine("Q DATA All Tabs", "QD All", sections, head_rows, source, units, made_at, cone, max_dist_pct, zone_pts=zone_pts, prefs=prefs)


def apply_kind_prefs(g: dict, prefs: dict | None) -> dict:
    """A kind of level with the user's look from Q DATA (matched by the kind's name, so it applies on every tab that has it)."""
    k = ((prefs or {}).get("kinds") or {}).get(g["name"]) or {}
    out = dict(g)
    if isinstance(k.get("on"), bool):
        out["on"] = k["on"]
    if k.get("color"):
        out["color"] = _hex(k["color"], g["color"])
    if k.get("style") in STYLES:
        out["style"] = STYLES[k["style"]]
    try:
        if k.get("width") is not None:
            out["width"] = max(1, min(6, int(k["width"])))
    except (TypeError, ValueError):
        pass
    return out


def build_pine(title, short, sections, head_rows, source, units, made_at, cone=None, max_dist_pct=4.0, single=False, about="", zone_pts=10.0,
               prefs=None) -> str:
    prefs = prefs or {}
    pset = prefs.get("set") or {}
    auto = {"maxDistPct": round(float(max_dist_pct), 1), "zDist": float(zone_pts), "zMaxW": float(zone_pts) * 4}
    tab_colors = prefs.get("tab_colors") or {}
    G, lv, rows = [], [], []                          # G: every kind of level, as (section index, group dict)
    for si, sec in enumerate(sections):
        base = len(G)
        G += [(si, apply_kind_prefs(_group(g), prefs)) for g in sec["groups"]]
        for x in sec["levels"]:
            if x.get("price") is not None and x["price"] > 0 and int(x.get("group", 0)) < len(sec["groups"]):
                lv.append({**x, "group": base + int(x.get("group", 0)), "tab": si})
        pre = "" if single else f"{sec['name']}: "
        rows += [(si, pre + str(k), v) for k, v in (sec.get("table") or []) if v not in (None, "")]
    rows = [(-1, k, v) for k, v in head_rows if v] + rows or [(-1, "Levels", str(len(lv)))]
    lv.sort(key=lambda x: -x["price"])
    if not lv:     # array.from() needs at least one element: a placeholder in tab -2, which is never drawn
        lv = [{"price": 1.0, "group": 0, "tab": -2, "label": "none"}]
    if not G:
        G = [(0, _group("Levels"))]
    zone = lambda x: x.get("low") and x.get("high") and x["high"] > x["low"]
    sess = next((i for i, sec in enumerate(sections) if sec["tab"] == "session"), None)

    o = ['//@version=6',
         f'indicator({q(title, 60)}, shorttitle = {q(short, 20)}, overlay = true, max_lines_count = 500, max_labels_count = 500, max_boxes_count = 500, max_bars_back = 5000)',
         '',
         f'// ---- {s(title)}: made by Q DATA ----',
         f'// {s(source)}', f'// {s(units)}',
         f'// Made {s(made_at)}. The levels are baked in: re-copy from Q DATA each session and paste over this script.',
         '// Set the look in Q DATA (TradingView indicator tab): those choices become the starting values here and stay right even when',
         '// the kinds of level change from day to day. To pull them in after pasting, use Defaults > Reset settings in the settings window.']
    if about:
        o.append(f'// {s(about)}')
    o += ['// HOW TO READ IT: every line is a level from Q DATA. Hover a label for why it is there. The shaded STACK ZONES are estimated',
          '// on your chart wherever several of the levels you have switched on sit close together: more different reasons in one place',
          '// means price is more likely to react there. Everything (what shows, colors, styles, widths, zone rules, labels, tables) is in Settings.',
          '// Levels are estimates from delayed options data. Context, not signals.', '',
          '// ---- the levels (baked in; each list is built by small functions so the main script stays short) ----']
    o += _arr("lvP", "float", [_num(x["price"]) for x in lv])
    o += _arr("lvLo", "float", [_num(x["low"]) if zone(x) else "0.0" for x in lv])        # zone bottom (0 = a single line)
    o += _arr("lvHi", "float", [_num(x["high"]) if zone(x) else "0.0" for x in lv])       # zone top
    o += _arr("lvT", "int", [str(int(x["tab"])) for x in lv])                             # which tab
    o += _arr("lvG", "int", [str(int(x["group"])) for x in lv])                           # which kind of level
    o += _arr("lvB", "int", [str(max(0, min(3, int(x.get("boost") or 0)))) for x in lv])  # extra width (e.g. very stacked)
    o += _arr("lvN", "string", [q(x.get("label"), 60) for x in lv])
    o += _arr("lvTip", "string", [q(x.get("tip") or x.get("label"), 600) for x in lv])
    o += _arr("gName", "string", [q(g["name"], 60) for _, g in G])
    o += _arr("gShort", "string", [q(g["short"], 40) for _, g in G])
    o += _arr("tName", "string", [q(sec["name"], 40) for sec in sections])
    o += _arr("tbT", "int", [str(t) for t, _, _ in rows])
    o += _arr("tbK", "string", [q(k, 50) for _, k, _ in rows])
    o += _arr("tbV", "string", [q(v, 90) for _, _, v in rows])

    # ---- settings, in the order they appear in TradingView ----
    def block(group_title, var):
        out = [f'{var} = {q(group_title)}']
        for spec in SETTINGS:
            if spec["group"] == group_title:
                out.append(_input(spec, setting_value(spec, pset, auto), var))
        return out

    o += ['', '// ---- 1) quick setup ----']
    o += block(GQ, "grpQ")
    o += ['', '// ---- 2) each tab: a Show switch and a tab color, then a row per kind of level (show, color, style, width) ----']
    tabs_on = prefs.get("tabs_on")
    for si, sec in enumerate(sections):
        nm = s(sec["name"], 40)
        on = sec["on"] if not isinstance(tabs_on, list) or single else sec["tab"] in tabs_on
        tcol = _hex(tab_colors.get(sec["tab"]), TAB_COLORS[si % len(TAB_COLORS)])
        o.append(f'grp{si} = {q(("Levels: " if single else "Tab: ") + nm)}')
        tip = s(sec.get("about") or f"Every level from Q DATA's {nm} tab.", 300)
        if not sec["levels"]:
            tip = s(f"No levels from this tab in this copy. {sec.get('about') or ''}", 300)
        o.append(f't{si} = input.bool({"true" if on else "false"}, {q("Show " + nm)}, group = grp{si}, inline = "tab{si}", tooltip = {q(tip)})')
        o.append(f'tc{si} = input.color({tcol}, "Tab color", group = grp{si}, inline = "tab{si}")')
        for gi, (sj, g) in enumerate(G):
            if sj != si:
                continue
            o += [f'g{gi} = input.bool({"true" if g["on"] else "false"}, {q(g["name"], 50)}, group = grp{si}, inline = "k{gi}")',
                  f'c{gi} = input.color({g["color"]}, "", group = grp{si}, inline = "k{gi}")',
                  f's{gi} = input.string({q(g["style"])}, "", options = ["Solid", "Dashed", "Dotted"], group = grp{si}, inline = "k{gi}")',
                  f'w{gi} = input.int({g["width"]}, "", minval = 1, maxval = 6, group = grp{si}, inline = "k{gi}", tooltip = {q(g["help"], 300)})']
        if cone and si == sess:
            o.append(f'showCone = input.bool(true, "Expected-move cone from the 9:30 open", group = grp{si}, inline = "cone", '
                     f'tooltip = "+/-1 and +/-2 times the day expected move from the 9:30 open, widening through the session. About 2 days in 3 stay inside +/-1.")')
            o.append(f'coneC1 = input.color(#7db7ff, "", group = grp{si}, inline = "cone")')
            o.append(f'coneC2 = input.color(#8e9bff, "", group = grp{si}, inline = "cone")')
    o += ['', '// ---- 3) stack zones ----'] + block(GZ, "grpZ")
    o += ['', '// ---- 4) labels and lines ----'] + block(GL, "grpL")
    o += ['', '// ---- 5) tables ----'] + block(GT, "grpT")

    nt, ng = len(sections), len(G)
    o += ['', '// ---- the per-tab and per-kind settings gathered into arrays, so the drawing functions read a few arrays, not hundreds of settings ----']
    o += _set_arr("tOn", "bool", [f"t{i}" for i in range(nt)])
    o += _set_arr("tCol", "color", [f"tc{i}" for i in range(nt)])
    o += _set_arr("kOn", "bool", [f"g{i}" for i in range(ng)])
    o += _set_arr("kCol", "color", [f"c{i}" for i in range(ng)])
    o += _set_arr("kSty", "string", [f"s{i}" for i in range(ng)])
    o += _set_arr("kW", "int", [f"w{i}" for i in range(ng)])
    o += ['',
          'tabOn(int t) =>', '    t == -1 ? true : t < 0 or t >= array.size(tOn) ? false : array.get(tOn, t)', '',
          'groupOn(int g) =>', '    g >= 0 and g < array.size(kOn) ? array.get(kOn, g) : false', '',
          'kindColor(int g) =>', '    g >= 0 and g < array.size(kCol) ? array.get(kCol, g) : color.gray', '',
          'tabColor(int t) =>', '    t >= 0 and t < array.size(tCol) ? array.get(tCol, t) : color.gray', '',
          '// the color a level is drawn in, following "Color levels by"',
          'levelColor(int g, int t, float p) =>',
          '    colorMode == "Tab" ? tabColor(t) : colorMode == "Above / below price" ? (p > close ? colUp : colDn) : kindColor(g)', '',
          'styleName(int g) =>', '    g >= 0 and g < array.size(kSty) ? array.get(kSty, g) : "Solid"', '',
          'widthOf(int g) =>', '    g >= 0 and g < array.size(kW) ? array.get(kW, g) : 1', '',
          'lineStyle(string nm) =>', '    nm == "Dashed" ? line.style_dashed : nm == "Dotted" ? line.style_dotted : line.style_solid', '',
          'sizeOf(string nm) =>', '    nm == "Tiny" ? size.tiny : nm == "Normal" ? size.normal : nm == "Large" ? size.large : size.small', '',
          'fmtP(float p) =>', '    str.tostring(p, priceDec == 0 ? "#,###" : "#,###." + str.repeat("0", priceDec))',
          '',
          'var line[]  lns = array.new<line>()', 'var label[] lbs = array.new<label>()', 'var box[]   bxs = array.new<box>()',
          'var table   tb  = na', 'var table   lg  = na',
          'var int firstBarT = time',
          'tN = bar_index >= startBars ? time[startBars] : firstBarT', '',
          '// 1) which levels pass the switches and filters',
          'qdVisible(int n) =>',
          '    vis = array.new<bool>(n, false)',
          '    for i = 0 to n - 1',
          '        p = array.get(lvP, i) + offsetPts',
          '        array.set(vis, i, tabOn(array.get(lvT, i)) and groupOn(array.get(lvG, i)) and math.abs(p - close) / close * 100 <= maxDistPct)',
          '    if nearestN > 0',
          '        keep = array.new<bool>(n, false)',
          '        for i = 0 to n - 1',
          '            if array.get(vis, i)',
          '                pi = array.get(lvP, i) + offsetPts',
          '                closer = 0',
          '                for j = 0 to n - 1',
          '                    if j != i and array.get(vis, j)',
          '                        pj = array.get(lvP, j) + offsetPts',
          '                        if (pj > close) == (pi > close) and math.abs(pj - close) < math.abs(pi - close)',
          '                            closer += 1',
          '                array.set(keep, i, closer < nearestN)',
          '        for i = 0 to n - 1',
          '            array.set(vis, i, array.get(keep, i))',
          '    vis', '',
          '// 2) estimated stack zones: sort the visible levels by price, chain the close ones, count the reasons in each chain',
          'qdZones(bool[] vis, int n, int startX, int endX, bool[] inZone, float[] zLos, float[] zHis, int[] zNs) =>',
          '    sz = sizeOf(labelSize)',
          '    vi = array.new<int>()', '    vp = array.new<float>()',
          '    for i = 0 to n - 1',
          '        if array.get(vis, i)',
          '            array.push(vi, i)',
          '            array.push(vp, array.get(lvP, i))',
          '    m = array.size(vi)',
          '    if m > 0',
          '        ord = array.sort_indices(vp, order.ascending)',
          '        cid = array.new<int>(m, 0)',
          '        nc = 0',
          '        lastP = 0.0', '        firstP = 0.0',
          '        joinD = zDistMode == "Points" ? zDist : close * zDist / 100',
          '        for k = 0 to m - 1',
          '            p = array.get(vp, array.get(ord, k))',
          '            if k == 0',
          '                firstP := p',
          '            else if p - lastP > joinD or p - firstP > zMaxW',
          '                nc += 1',
          '                firstP := p',
          '            array.set(cid, k, nc)',
          '            lastP := p',
          '        for z = 0 to nc',
          '            seen = array.new<int>()', '            names = array.new<string>()',
          '            lo = 1e12', '            hi = -1e12', '            cnt = 0', '            tot = 0',
          '            for k = 0 to m - 1',
          '                if array.get(cid, k) == z',
          '                    i = array.get(vi, array.get(ord, k))',
          '                    p = array.get(lvP, i)',
          '                    lo := math.min(lo, p)', '                    hi := math.max(hi, p)',
          '                    tot += 1',
          '                    key = zCount == "Different tabs" ? array.get(lvT, i) : zCount == "Different kinds" ? array.get(lvG, i) : tot',
          '                    if not array.includes(seen, key)',
          '                        array.push(seen, key)',
          '                        cnt += 1',
          '                    if array.size(names) < 12',
          '                        array.push(names, array.get(lvN, i))',
          '            if cnt >= zMin',
          '                for k = 0 to m - 1',
          '                    if array.get(cid, k) == z',
          '                        array.set(inZone, array.get(vi, array.get(ord, k)), true)',
          '                zl = lo + offsetPts - zPad', '                zh = hi + offsetPts + zPad',
          '                heavy = cnt >= zHeavy',
          '                above = (zl + zh) / 2 > close',
          '                zc = zColorMode == "Strength" ? (heavy ? zColH : zCol) : (above ? zColUp : zColDn)',
          '                array.push(bxs, box.new(startX, zh, endX, zl, xloc = xloc.bar_time, border_color = zBorder ? color.new(zc, 30) : color.new(zc, 100), border_width = heavy ? 2 : 1, bgcolor = color.new(zc, zTransp)))',
          '                array.push(zLos, zl)', '                array.push(zHis, zh)', '                array.push(zNs, cnt)',
          '                if zLabel',
          '                    unit = zCount == "Different tabs" ? " tabs" : zCount == "Different kinds" ? " kinds" : " levels"',
          '                    what = (heavy ? "HEAVY STACK " : "STACK ") + str.tostring(cnt) + unit + (above ? " - resistance?" : " - support?")',
          '                    ztip = "Estimated stack zone " + fmtP(zl) + " to " + fmtP(zh) + ": " + str.tostring(cnt) + unit + " (" + str.tostring(tot) + " levels) within " + fmtP(zh - zl) + " points. Inside: " + array.join(names, ", ") + ". More separate reasons at one price = more likely price reacts here (" + (above ? "above price, so a likely ceiling" : "below price, so a likely floor") + "). A clean break through it often runs to the next zone. An estimate, not a signal."',
          '                    zx = zLabelSide == "Left" ? startX : endX',
          '                    array.push(lbs, label.new(zx, zh, what, xloc = xloc.bar_time, style = zLabelSide == "Left" ? label.style_label_lower_right : label.style_label_lower_left, color = color.new(zc, 15), textcolor = labelTxtC, size = sz, tooltip = ztip))',
          '    m', '',
          '// 3) the levels themselves',
          'qdLevels(bool[] vis, bool[] inZone, int n, int startX, int endX) =>',
          '    sz = sizeOf(labelSize)',
          '    labX = labelSide == "Left" ? startX : endX',
          '    labStyle = labelSide == "Left" ? label.style_label_right : label.style_label_left',
          '    labP = array.new<float>()', '    labIdx = array.new<int>()', '    labTip = array.new<string>()',
          '    nearUp = -1', '    nearDn = -1',
          '    if emphNear',
          '        for i = 0 to n - 1',
          '            if array.get(vis, i)',
          '                pe = array.get(lvP, i) + offsetPts',
          '                if pe > close and (nearUp < 0 or pe < array.get(lvP, math.max(nearUp, 0)) + offsetPts)',
          '                    nearUp := i',
          '                if pe <= close and (nearDn < 0 or pe > array.get(lvP, math.max(nearDn, 0)) + offsetPts)',
          '                    nearDn := i',
          '    for i = 0 to n - 1',
          '        if array.get(vis, i) and not (zOnly and array.get(inZone, i))',
          '            g = array.get(lvG, i)',
          '            p = array.get(lvP, i) + offsetPts',
          '            c = levelColor(g, array.get(lvT, i), p)',
          '            lo = array.get(lvLo, i)', '            hi = array.get(lvHi, i)',
          '            if showLines',
          '                if hi > lo and lo > 0',
          '                    array.push(bxs, box.new(startX, hi + offsetPts, endX, lo + offsetPts, xloc = xloc.bar_time, border_color = color.new(c, 40), border_width = 1, bgcolor = color.new(c, zoneTransp)))',
          '                extra = (i == nearUp or i == nearDn) ? 1 : 0',
          '                array.push(lns, line.new(startX, p, endX, p, xloc = xloc.bar_time, color = c, width = widthOf(g) + array.get(lvB, i) + extra, style = lineStyle(styleName(g))))',
          '            if showLabels',
          '                nm = array.get(lvN, i)',
          '                mean = array.get(gShort, g)',
          '                withMean = nm + (mean != "" ? " (" + mean + ")" : "")',
          '                txt = labelText == "Name" ? nm : labelText == "Name + price" ? nm + " " + fmtP(p) : labelText == "Name + meaning" ? withMean : labelText == "Meaning + price" ? (mean != "" ? mean : nm) + " " + fmtP(p) : withMean + " " + fmtP(p)',
          '                tip = nm + " " + fmtP(p) + ": " + array.get(lvTip, i)',
          '                twin = -1',
          '                if mergeSame and array.size(labP) > 0',
          '                    for k = 0 to array.size(labP) - 1',
          '                        if twin < 0 and math.abs(array.get(labP, k) - p) <= mergePts',
          '                            twin := k',
          '                if twin >= 0',
          '                    lb = array.get(lbs, array.get(labIdx, twin))',
          '                    label.set_text(lb, nm + " / " + label.get_text(lb))',
          '                    joinedTip = tip + " | " + array.get(labTip, twin)',
          '                    array.set(labTip, twin, joinedTip)',
          '                    label.set_tooltip(lb, joinedTip)',
          '                else',
          '                    array.push(lbs, label.new(labX, p, txt, xloc = xloc.bar_time, style = labStyle, color = color.new(c, labelTransp), textcolor = labelTxtC, size = sz, tooltip = tip))',
          '                    array.push(labP, p)', '                    array.push(labIdx, array.size(lbs) - 1)', '                    array.push(labTip, tip)',
          '    n', '',
          '// 4) the info table: headline numbers of the tabs that are on, and the nearest zones',
          'qdInfoTable(float[] zLos, float[] zHis, int[] zNs) =>',
          '    table out = na',
          '    if showTable',
          '        tsz = sizeOf(tableSize)',
          '        upI = -1', '        dnI = -1',
          '        if array.size(zNs) > 0',
          '            for k = 0 to array.size(zNs) - 1',
          '                mid = (array.get(zLos, k) + array.get(zHis, k)) / 2',
          '                if mid > close and (upI < 0 or mid < (array.get(zLos, math.max(upI, 0)) + array.get(zHis, math.max(upI, 0))) / 2)',
          '                    upI := k',
          '                if mid <= close and (dnI < 0 or mid > (array.get(zLos, math.max(dnI, 0)) + array.get(zHis, math.max(dnI, 0))) / 2)',
          '                    dnI := k',
          '        nr = 2',
          '        for r = 0 to array.size(tbT) - 1',
          '            if tabOn(array.get(tbT, r))',
          '                nr += 1',
          f'        out := table.new({POS_EXPR.format(v="tablePos")}, 2, nr + 1, bgcolor = color.new(tableBg, 10), border_color = color.new(#2a3554, 0), border_width = 1)',
          f'        table.cell(out, 0, 0, {q(title, 40)}, text_color = tableTxt, text_size = tsz, bgcolor = color.new(#162036, 0))',
          '        table.cell(out, 1, 0, "hover labels for why", text_color = color.new(#aeb7cc, 0), text_size = tsz, bgcolor = color.new(#162036, 0))',
          '        row = 1',
          '        for r = 0 to array.size(tbT) - 1',
          '            if tabOn(array.get(tbT, r))',
          '                table.cell(out, 0, row, array.get(tbK, r), text_color = color.new(#aeb7cc, 0), text_size = tsz, text_halign = text.align_left)',
          '                table.cell(out, 1, row, array.get(tbV, r), text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '                row += 1',
          '        zU = zOn ? "none in range" : "zones off"',
          '        zD = zOn ? "none in range" : "zones off"',
          '        if upI >= 0',
          '            zU := fmtP(array.get(zLos, upI)) + " - " + fmtP(array.get(zHis, upI)) + " (" + str.tostring(array.get(zNs, upI)) + ")"',
          '        if dnI >= 0',
          '            zD := fmtP(array.get(zLos, dnI)) + " - " + fmtP(array.get(zHis, dnI)) + " (" + str.tostring(array.get(zNs, dnI)) + ")"',
          '        table.cell(out, 0, row, "Nearest stack zone above", text_color = color.new(#aeb7cc, 0), text_size = tsz, text_halign = text.align_left)',
          '        table.cell(out, 1, row, zU, text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '        table.cell(out, 0, row + 1, "Nearest stack zone below", text_color = color.new(#aeb7cc, 0), text_size = tsz, text_halign = text.align_left)',
          '        table.cell(out, 1, row + 1, zD, text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '    out', '',
          '// 5) the legend: what each color means, following "Color levels by" (kinds, tabs, or above / below price)',
          'qdLegend(bool[] vis, int n) =>',
          '    table out = na',
          '    if showLegend',
          '        tsz = sizeOf(tableSize)',
          '        byTab = colorMode == "Tab"',
          '        bySide = colorMode == "Above / below price"',
          '        used = array.new<int>()',
          '        for i = 0 to n - 1',
          '            key = byTab ? array.get(lvT, i) : array.get(lvG, i)',
          '            if array.get(vis, i) and key >= 0 and not array.includes(used, key)',
          '                array.push(used, key)',
          '        array.sort(used)',
          '        rowsN = bySide ? 2 : array.size(used)',
          f'        out := table.new({POS_EXPR.format(v="legendPos")}, 2, rowsN + 2, bgcolor = color.new(tableBg, 10), border_color = color.new(#2a3554, 0), border_width = 1)',
          '        table.cell(out, 0, 0, "", bgcolor = color.new(#162036, 0))',
          '        table.cell(out, 1, 0, "What the colors mean", text_color = tableTxt, text_size = tsz, bgcolor = color.new(#162036, 0), text_halign = text.align_left)',
          '        if bySide',
          '            table.cell(out, 0, 1, "  ", bgcolor = colUp, text_size = tsz)',
          '            table.cell(out, 1, 1, "Level above price", text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '            table.cell(out, 0, 2, "  ", bgcolor = colDn, text_size = tsz)',
          '            table.cell(out, 1, 2, "Level below price", text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '        else if array.size(used) > 0',
          '            for k = 0 to array.size(used) - 1',
          '                key = array.get(used, k)',
          '                mean = byTab ? "" : array.get(gShort, key)',
          '                table.cell(out, 0, k + 1, "  ", bgcolor = byTab ? tabColor(key) : kindColor(key), text_size = tsz)',
          '                table.cell(out, 1, k + 1, (byTab ? array.get(tName, key) : array.get(gName, key)) + (mean != "" ? ": " + mean : ""), text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '        zc0 = zColorMode == "Strength" ? zCol : zColUp',
          '        table.cell(out, 0, rowsN + 1, "  ", bgcolor = color.new(zc0, 40), text_size = tsz)',
          '        table.cell(out, 1, rowsN + 1, zColorMode == "Strength" ? "Shaded: estimated stack zone (heavy color = heavily stacked)" : "Shaded: stack zone (above price / below price colors)", text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '    out', '',
          '// ---- draw everything once, on the last bar ----',
          'if barstate.islast',
          '    for l in lns', '        line.delete(l)', '    for b in lbs', '        label.delete(b)', '    for x in bxs', '        box.delete(x)',
          '    array.clear(lns)', '    array.clear(lbs)', '    array.clear(bxs)',
          '    sessionOpen = timestamp("America/New_York", year(time, "America/New_York"), month(time, "America/New_York"), dayofmonth(time, "America/New_York"), 9, 30, 0)',
          '    startX = startMode == "Start of chart data" ? firstBarT : startMode == "Last N bars" ? tN : math.min(sessionOpen, time)',
          '    endX = time + extBars * timeframe.in_seconds() * 1000',
          '    n = array.size(lvP)',
          '    vis = qdVisible(n)',
          '    inZone = array.new<bool>(n, false)',
          '    zLos = array.new<float>()', '    zHis = array.new<float>()', '    zNs = array.new<int>()',
          '    if zOn',
          '        qdZones(vis, n, startX, endX, inZone, zLos, zHis, zNs)',
          '    qdLevels(vis, inZone, n, startX, endX)',
          '    if not na(tb)', '        table.delete(tb)',
          '    tb := qdInfoTable(zLos, zHis, zNs)',
          '    if not na(lg)', '        table.delete(lg)',
          '    lg := qdLegend(vis, n)']
    if cone and sess is not None:
        o += ['', '// ---- Session tab: the expected-move cone from the 9:30 open, widening with the square root of time (only on the day it was made) ----',
              f'coneOpen = {_num(cone["open"])}', f'coneMove = {_num(cone["move"])}',
              f'cOpenT  = timestamp("America/New_York", {int(cone["y"])}, {int(cone["m"])}, {int(cone["d"])}, 9, 30, 0)',
              f'cCloseT = timestamp("America/New_York", {int(cone["y"])}, {int(cone["m"])}, {int(cone["d"])}, 16, 0, 0)',
              f'inCone = t{sess} and showCone and time >= cOpenT and time <= cCloseT',
              'coneFrac = math.max(0.0, math.min(1.0, float(time - cOpenT) / float(cCloseT - cOpenT)))',
              'coneW = coneMove * math.sqrt(coneFrac)',
              'plot(inCone ? coneOpen + offsetPts + coneW : na, "Cone +1", color = coneC1, style = plot.style_linebr)',
              'plot(inCone ? coneOpen + offsetPts - coneW : na, "Cone -1", color = coneC1, style = plot.style_linebr)',
              'plot(inCone ? coneOpen + offsetPts + 2 * coneW : na, "Cone +2", color = color.new(coneC2, 40), style = plot.style_linebr)',
              'plot(inCone ? coneOpen + offsetPts - 2 * coneW : na, "Cone -2", color = color.new(coneC2, 40), style = plot.style_linebr)']
    return "\n".join(o) + "\n"
