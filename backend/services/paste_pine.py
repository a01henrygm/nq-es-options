"""Q DATA All Tabs as a PASTE-IN TradingView indicator, like the Key levels one ("Options levels").

You add the script to TradingView once. Each session you copy the levels text from Q DATA and paste it into the indicator's
"Levels from Q DATA" setting. The script never changes, so every setting you make in TradingView stays where it is (TradingView
remembers settings by their position in the script, and in this script the positions never move).

The levels text (one record per line, fields split by |, lines that start with anything else are ignored):
  Q|1|<made, text>|<day yyyy-mm-dd>|<symbol>|<units>        header
  K|<name>|#rrggbb|S, D or O|<width>|<short meaning>         a kind of level; levels refer to kinds by their order (0, 1, 2...)
  L|<price>|<low>|<high>|<tab key>|<kind>|<key 1/0>|<boost>|<label>|<hover text>
  R|<tab key or *>|<name>|<value>                            an info table row
  C|<open>|<move>|<y>|<m>|<d>                                the Session tab's expected-move cone
The look of each kind (color, style, width, shown or not, key or not) is chosen in Q DATA and travels in the text.

Decluttering: in the default "Clean" view the shaded stack zones summarise every level, and only KEY levels (flips, walls,
high and low of day, projected HOD/LOD 80%, top setup entries, stacked areas; Q DATA's TradingView indicator tab lets you choose)
are drawn as lines. Levels at the same price from different tabs share one line and one label.
Written as conservative Pine v6; it has not been compiled by TradingView from here.
"""
from __future__ import annotations
import re

from .tab_pine import BG_MODES, INK_FUNCS, POS_EXPR, POSITIONS, TAB_COLORS, _arr, _hex, _set_arr, q

MAX_CHARS = 30000          # keep the pasted text well under Pine's string limit (40,960 characters)
TIP_CHARS = 110
STY = {"Solid": "S", "Dashed": "D", "Dotted": "O", "solid": "S", "dashed": "D", "dotted": "O"}
# kinds drawn as lines in the Clean view unless you choose otherwise in Q DATA (matched as parts of the kind's name)
KEY_KINDS = ("gamma flip", "0dte flip", "call wall", "put wall", "of day so far", "top setups: long entries", "top setups: short entries", "stacked areas",
             "projected hod", "projected lod")
DISPLAYS = ["Clean: zones + key lines", "Zones + every line", "Every line, no zones"]


def is_key_kind(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in KEY_KINDS) and "zones" not in n


def f(text, n=None) -> str:
    """A field in the levels text: no | and no line breaks."""
    t = re.sub(r"\s+", " ", str(text if text is not None else "").replace("|", "/")).strip()
    return t[:n] if n else t


def build_levels_text(sections, head_rows, made, day, symbol, units, cone=None, spot=None, prefs=None) -> dict:
    """The text to paste. sections: [{tab, name, groups, levels, table}] (only the tabs you included).
    Returns {text, levels, kinds, chars, tips_dropped, cut}."""
    prefs = prefs or {}
    kp = prefs.get("kinds") or {}
    kinds, kidx, lv = [], {}, []
    for sec in sections:
        for x in sec["levels"]:
            gi = int(x.get("group", 0))
            if x.get("price") is None or x["price"] <= 0 or gi >= len(sec["groups"]):
                continue
            g = sec["groups"][gi]
            g = {"name": g} if isinstance(g, str) else g
            name = g.get("name") or "Levels"
            p = kp.get(name) or {}
            if p.get("on") is False or g.get("on") is False and p.get("on") is not True:
                continue
            if name not in kidx:
                width = p.get("width") if isinstance(p.get("width"), int) else int(g.get("width") or 1)
                kidx[name] = len(kinds)
                kinds.append({"name": name, "color": _hex(p.get("color"), _hex(g.get("color"))), "style": STY.get(p.get("style") or g.get("style") or "solid", "S"),
                              "width": max(1, min(6, width)), "short": g.get("short") or "",
                              "key": p["key"] if isinstance(p.get("key"), bool) else is_key_kind(name)})
            k = kinds[kidx[name]]
            key = k["key"]
            if key and name.lower().startswith("projected") and "80%" not in str(x.get("label")):
                key = False                                          # of the projected HOD/LOD, only the 80% line is a key line
            lo, hi = x.get("low"), x.get("high")
            band = lo is not None and hi is not None and hi > lo
            lv.append({"price": float(x["price"]), "low": float(lo) if band else 0.0, "high": float(hi) if band else 0.0, "tab": sec["tab"],
                       "kind": kidx[name], "key": key, "boost": max(0, min(3, int(x.get("boost") or 0))), "label": x.get("label") or name,
                       "tip": x.get("tip") or x.get("label") or ""})
    lv.sort(key=lambda x: -x["price"])

    def render(with_tips, levels):
        o = [f"Q|1|{f(made, 40)}|{f(day, 10)}|{f(symbol, 40)}|{f(units, 120)}"]
        o += [f"K|{f(k['name'], 50)}|{k['color']}|{k['style']}|{k['width']}|{f(k['short'], 30)}" for k in kinds]
        o += [f"L|{x['price']:.2f}|{x['low']:.2f}|{x['high']:.2f}|{x['tab']}|{x['kind']}|{1 if x['key'] else 0}|{x['boost']}|{f(x['label'], 40)}|"
              + (f(x["tip"], TIP_CHARS) if with_tips else "") for x in levels]
        for sec in sections:
            o += [f"R|{sec['tab']}|{f(k, 40)}|{f(v, 70)}" for k, v in (sec.get("table") or []) if v not in (None, "")]
        o += [f"R|*|{f(k, 40)}|{f(v, 70)}" for k, v in head_rows if v]
        if cone:
            o.append(f"C|{cone['open']:.2f}|{cone['move']:.2f}|{int(cone['y'])}|{int(cone['m'])}|{int(cone['d'])}")
        return "\n".join(o) + "\n"

    text, tips_dropped, cut = render(True, lv), False, 0
    if len(text) > MAX_CHARS:
        text, tips_dropped = render(False, lv), True
    if len(text) > MAX_CHARS:                                       # still too long: keep key levels and the ones nearest price
        ref = spot if spot else (lv[len(lv) // 2]["price"] if lv else 0)
        order = sorted(lv, key=lambda x: (not x["key"], abs(x["price"] - ref)))
        keep = len(order)
        while keep > 1 and len(text) > MAX_CHARS:
            keep = int(keep * 0.9)
            chosen = sorted(order[:keep], key=lambda x: -x["price"])
            text = render(False, chosen)
        cut = len(lv) - keep
    return {"text": text, "levels": len(lv) - cut, "kinds": kinds, "chars": len(text), "tips_dropped": tips_dropped, "cut": cut}


def build_paste_script(tabs: list, session_tab: str = "session", default_on: tuple = ()) -> str:
    """The script itself. tabs: [(key, name)] in a fixed order; it only changes when Q DATA adds a tab."""
    nt = len(tabs)
    sess = next((i for i, (k, _) in enumerate(tabs) if k == session_tab), -1)
    pos = ", ".join(q(p) for p in POSITIONS)
    o = ['//@version=6',
         'indicator("Q DATA All Tabs", shorttitle = "QD All", overlay = true, max_lines_count = 500, max_labels_count = 500, max_boxes_count = 500, max_bars_back = 5000)',
         '',
         '// ---- Q DATA All Tabs (paste-in): add this script once, then paste the levels from Q DATA into its settings each session ----',
         '// In Q DATA: TradingView indicator tab > Copy levels. In TradingView: this indicator\'s settings > "Levels from Q DATA" > paste > OK.',
         '// The script never changes, so your settings stay put. Colors, styles and widths of each kind of level come with the pasted levels.',
         '// CLEAN view (default): shaded stack zones show where levels pile up; only key levels are lines. Hover labels for why.',
         '// Levels are estimates from delayed options data. Context, not signals.', '']
    o += _arr("tKey", "string", [q(k) for k, _ in tabs])
    o += _arr("tName", "string", [q(n, 40) for _, n in tabs])
    o += ['',
          '// ---- settings ----',
          'grpD = "Levels from Q DATA"',
          'dataTxt = input.text_area("", "Paste the levels from Q DATA here", group = grpD, tooltip = "In Q DATA open the TradingView indicator tab and click Copy levels, then paste here and press OK. Do it once per session. Nothing else in these settings changes when you paste.")',
          'grpQ = "Quick setup"',
          f'viewMode = input.string({q(DISPLAYS[0])}, "Show", options = [{", ".join(q(x) for x in DISPLAYS)}], group = grpQ, tooltip = "Clean: shaded stack zones where levels pile up, and only the key levels as lines (flips, walls, high and low of day, projected HOD/LOD 80%, top setups, stacked areas; choose which kinds are key in Q DATA). Zones + every line: zones plus every level. Every line, no zones: the old busy view.")',
          'showLabels = input.bool(true, "Labels", group = grpQ, inline = "q1")',
          'showTable  = input.bool(true, "Info table", group = grpQ, inline = "q1")',
          'showLegend = input.bool(false, "Legend", group = grpQ, inline = "q1")',
          'colorMode  = input.string("Kind of level", "Color levels by", options = ["Kind of level", "Tab", "Above / below price"], group = grpQ, tooltip = "Kind of level: the colors chosen in Q DATA. Tab: each tab\'s color (below). Above / below price: the two colors on the next row.")',
          'colUp = input.color(#e5534b, "Above price", group = grpQ, inline = "qc")',
          'colDn = input.color(#3fb96a, "Below price", group = grpQ, inline = "qc")',
          'nearestN   = input.int(0, "Only the nearest N lines on each side (0 = all)", minval = 0, maxval = 100, group = grpQ)',
          'maxDistPct = input.float(2.5, "Hide levels farther than this % from price", minval = 0.1, step = 0.5, group = grpQ)',
          'emphNear   = input.bool(true, "Thicker line for the nearest line above and below price", group = grpQ)',
          'offsetPts  = input.float(0.0, "Add to every level (points)", step = 0.25, group = grpQ, tooltip = "Use this if your chart is a different contract or month, or Q DATA had no NQ/ES price or basis saved.")',
          'hideKinds  = input.string("", "Hide kinds whose name contains", group = grpQ, tooltip = "Comma list, part of a name is enough, for example: midpoints, by expiry, vanna")',
          'warnOld    = input.bool(true, "Warn when the pasted levels are from an earlier day", group = grpQ)',
          f'bgMode     = input.string("Auto", "Chart background", options = [{", ".join(q(x) for x in BG_MODES)}], group = grpQ, tooltip = "Auto reads your chart background. On a light (white) chart, light colors are drawn darker in the same hue so every line, zone and label is easy to see.")',
          'grpTb = "Tabs"']
    for i, (k, n) in enumerate(tabs):
        o.append(f't{i} = input.bool(true, {q(n, 40)}, group = grpTb, inline = "t{i}", tooltip = "Only tabs you included in Q DATA have levels in the pasted text. Switch a tab off here to hide it without copying again.")'
                 if i == 0 else f't{i} = input.bool(true, {q(n, 40)}, group = grpTb, inline = "t{i}")')
        o.append(f'tc{i} = input.color({TAB_COLORS[i % len(TAB_COLORS)]}, "", group = grpTb, inline = "t{i}")')
    if sess >= 0:
        o += ['showCone = input.bool(true, "Session: expected-move cone from the 9:30 open", group = grpTb, inline = "cone")',
              'coneC1 = input.color(#7db7ff, "", group = grpTb, inline = "cone")', 'coneC2 = input.color(#8e9bff, "", group = grpTb, inline = "cone")']
    o += ['grpZ = "Stack zones"',
          'zCount  = input.string("Different kinds", "Count", options = ["Different kinds", "Different tabs", "Every level"], group = grpZ, tooltip = "Different kinds (default): two open-interest strikes count once, so a zone needs different reasons. Different tabs: each tab counts once. Every level: every line counts.")',
          'zMin    = input.int(2, "Minimum to make a zone", minval = 2, maxval = 30, group = grpZ, inline = "zn")',
          'zHeavy  = input.int(4, "Heavy at", minval = 2, maxval = 30, group = grpZ, inline = "zn", tooltip = "A zone needs at least the minimum count. At the heavy count it gets the heavy color and a thicker border. Raise the minimum for fewer, stronger zones.")',
          'zDistMode = input.string("Auto", "Join levels within", options = ["Auto", "Points", "% of price"], group = grpZ, inline = "zd")',
          'zDist   = input.float(12.0, "", minval = 0.01, step = 0.25, group = grpZ, inline = "zd", tooltip = "Levels this close together join one zone. Auto: 0.05% of price (about 12 to 13 NQ points, 3 ES points). Bigger = fewer, wider zones.")',
          'zMaxW   = input.float(0.0, "Widest zone in points (0 = auto, 4x the join distance)", minval = 0.0, step = 1.0, group = grpZ)',
          'zPad    = input.float(0.0, "Pad each side in points (0 = auto)", minval = 0.0, step = 0.25, group = grpZ)',
          'zColorMode = input.string("Strength", "Color zones by", options = ["Strength", "Above / below price"], group = grpZ)',
          'zCol    = input.color(#2f8bf5, "Stacked", group = grpZ, inline = "zc1")',
          'zColH   = input.color(#ff7a2e, "Heavy", group = grpZ, inline = "zc1")',
          'zColUp  = input.color(#e5534b, "Above price", group = grpZ, inline = "zc2")',
          'zColDn  = input.color(#3fb96a, "Below price", group = grpZ, inline = "zc2")',
          'zTransp = input.int(82, "Zone transparency", minval = 0, maxval = 100, group = grpZ)',
          'zBorder = input.bool(true, "Zone border", group = grpZ, inline = "zl")',
          'zLabel  = input.bool(true, "Zone label", group = grpZ, inline = "zl")',
          'zLabelSide = input.string("Right", "", options = ["Right", "Left"], group = grpZ, inline = "zl")',
          'grpL = "Labels and lines"',
          'labelsFor  = input.string("Key lines and zones", "Labels on", options = ["Key lines and zones", "Every line"], group = grpL)',
          'labelText  = input.string("Name + price", "Label shows", options = ["Name", "Name + price", "Name + meaning", "Name + meaning + price", "Meaning + price"], group = grpL, tooltip = "Meaning = a few plain words on what the level is. Hover any label for the full reason.")',
          'labelSize  = input.string("Small", "Label size", options = ["Tiny", "Small", "Normal", "Large"], group = grpL)',
          'labelTxtC  = input.color(color.white, "Label text", group = grpL, inline = "lc")',
          'labelTransp = input.int(25, "Label background transparency", minval = 0, maxval = 100, group = grpL, inline = "lc")',
          'labelSide  = input.string("Right", "Labels on the", options = ["Right", "Left"], group = grpL)',
          'priceDec   = input.int(2, "Price decimals", minval = 0, maxval = 4, group = grpL)',
          'mergePts   = input.float(0.0, "One line and label for levels within (points, 0 = auto)", minval = 0.0, step = 0.25, group = grpL, tooltip = "Levels this close from different tabs (the same flip or wall from several tabs) share one line and one label listing every name. Auto: a third of the zone join distance.")',
          'startMode  = input.string("Session open 9:30 ET", "Lines start at", options = ["Session open 9:30 ET", "Start of chart data", "Last N bars"], group = grpL, inline = "st")',
          'startBars  = input.int(50, "", minval = 1, maxval = 4000, group = grpL, inline = "st")',
          'extBars    = input.int(8, "Lines run this many bars past the last candle", minval = 0, maxval = 500, group = grpL)',
          'zoneTransp = input.int(85, "Level band transparency (GEX and walls)", minval = 0, maxval = 100, group = grpL)',
          'grpT = "Tables"',
          f'tablePos   = input.string("Top right", "Info table at", options = [{pos}], group = grpT)',
          f'legendPos  = input.string("Bottom right", "Legend at", options = [{pos}], group = grpT)',
          'tableSize  = input.string("Small", "Table text size", options = ["Tiny", "Small", "Normal"], group = grpT)',
          'tableBg    = input.color(#0f1626, "Table background", group = grpT, inline = "tbc")',
          'tableTxt   = input.color(color.white, "Text", group = grpT, inline = "tbc")',
          '']
    o += _set_arr("tOn", "bool", [f"t{i}" for i in range(nt)])
    o += _set_arr("tCol", "color", [f"tc{i}" for i in range(nt)])
    o += ['',
          '// ---- what was pasted (filled on the last bar) ----',
          'var float[]  lvP   = array.new<float>()', 'var float[]  lvLo  = array.new<float>()', 'var float[]  lvHi  = array.new<float>()',
          'var int[]    lvT   = array.new<int>()', 'var int[]    lvG   = array.new<int>()', 'var bool[]   lvK   = array.new<bool>()',
          'var int[]    lvB   = array.new<int>()', 'var string[] lvN   = array.new<string>()', 'var string[] lvTip = array.new<string>()',
          'var string[] kName = array.new<string>()', 'var string[] kShort = array.new<string>()', 'var color[]  kCol  = array.new<color>()',
          'var string[] kSty  = array.new<string>()', 'var int[]    kW    = array.new<int>()', 'var bool[]   kHide = array.new<bool>()',
          'var string[] tbT   = array.new<string>()', 'var string[] tbK   = array.new<string>()', 'var string[] tbV   = array.new<string>()',
          'var string[] meta  = array.from("", "", "", "")',
          '',
          '// ---- reading the pasted text ----',
          'fld(string[] a, int i) =>', '    i < array.size(a) ? str.trim(array.get(a, i)) : ""', '',
          'num(string[] a, int i) =>', '    v = str.tonumber(fld(a, i))', '    na(v) ? 0.0 : v', '',
          'hexNib(string ch) =>', '    k = str.pos("0123456789abcdef", str.lower(ch))', '    na(k) ? 0 : k', '',
          'hexColor(string h) =>',
          '    hx = str.replace_all(h, "#", "")',
          '    str.length(hx) >= 6 ? color.rgb(hexNib(str.substring(hx, 0, 1)) * 16 + hexNib(str.substring(hx, 1, 2)), hexNib(str.substring(hx, 2, 3)) * 16 + hexNib(str.substring(hx, 3, 4)), hexNib(str.substring(hx, 4, 5)) * 16 + hexNib(str.substring(hx, 5, 6))) : color.gray', '',
          'hiddenName(string nm) =>',
          '    hid = false',
          '    if str.length(str.trim(hideKinds)) > 0',
          '        lowNm = str.lower(nm)',
          '        for part in str.split(hideKinds, ",")',
          '            w = str.lower(str.trim(part))',
          '            if str.length(w) > 0 and str.contains(lowNm, w)',
          '                hid := true',
          '    hid', '',
          'qdKinds(string txt) =>',
          '    nm = array.new<string>()', '    sh = array.new<string>()', '    cl = array.new<color>()', '    st = array.new<string>()', '    wd = array.new<int>()', '    hd = array.new<bool>()',
          '    for row in str.split(txt, "\\n")',
          '        a = str.split(str.trim(row), "|")',
          '        if fld(a, 0) == "K" and array.size(a) >= 5',
          '            array.push(nm, fld(a, 1))',
          '            array.push(sh, fld(a, 5))',
          '            array.push(cl, hexColor(fld(a, 2)))',
          '            sy = fld(a, 3)',
          '            array.push(st, sy == "D" ? "Dashed" : sy == "O" ? "Dotted" : "Solid")',
          '            array.push(wd, int(math.max(1, math.min(6, num(a, 4)))))',
          '            array.push(hd, hiddenName(fld(a, 1)))',
          '    [nm, sh, cl, st, wd, hd]', '',
          'qdLevelsIn(string txt) =>',
          '    ps = array.new<float>()', '    los = array.new<float>()', '    his = array.new<float>()', '    ts = array.new<int>()', '    gs = array.new<int>()',
          '    ks = array.new<bool>()', '    bs = array.new<int>()', '    ns = array.new<string>()', '    tips = array.new<string>()',
          '    for row in str.split(txt, "\\n")',
          '        a = str.split(str.trim(row), "|")',
          '        if fld(a, 0) == "L" and array.size(a) >= 9',
          '            p = num(a, 1)',
          '            if p > 0',
          '                array.push(ps, p)', '                array.push(los, num(a, 2))', '                array.push(his, num(a, 3))',
          '                ti = array.indexof(tKey, fld(a, 4))',
          '                array.push(ts, ti < 0 ? -2 : ti)',
          '                array.push(gs, int(num(a, 5)))',
          '                array.push(ks, fld(a, 6) == "1")',
          '                array.push(bs, int(num(a, 7)))',
          '                array.push(ns, fld(a, 8))',
          '                array.push(tips, fld(a, 9))',
          '    [ps, los, his, ts, gs, ks, bs, ns, tips]', '',
          'qdRows(string txt) =>',
          '    rt = array.new<string>()', '    rk = array.new<string>()', '    rv = array.new<string>()', '    mt = array.from("", "", "", "")',
          '    for row in str.split(txt, "\\n")',
          '        a = str.split(str.trim(row), "|")',
          '        tag = fld(a, 0)',
          '        if tag == "R" and array.size(a) >= 4',
          '            array.push(rt, fld(a, 1))', '            array.push(rk, fld(a, 2))', '            array.push(rv, fld(a, 3))',
          '        if tag == "Q" and array.size(a) >= 6',
          '            array.set(mt, 0, fld(a, 2))', '            array.set(mt, 1, fld(a, 3))', '            array.set(mt, 2, fld(a, 4))', '            array.set(mt, 3, fld(a, 5))',
          '    [rt, rk, rv, mt]', '',
          'qdCone(string txt) =>',
          '    float co = na', '    float cm = na', '    int cy = na', '    int cmo = na', '    int cd = na',
          '    for row in str.split(txt, "\\n")',
          '        a = str.split(str.trim(row), "|")',
          '        if fld(a, 0) == "C" and array.size(a) >= 6',
          '            co := num(a, 1)', '            cm := num(a, 2)', '            cy := int(num(a, 3))', '            cmo := int(num(a, 4))', '            cd := int(num(a, 5))',
          '    [co, cm, cy, cmo, cd]', '',
          '// ---- helpers ----'] + INK_FUNCS + [
          'tabOn(int t) =>', '    t >= 0 and t < array.size(tOn) ? array.get(tOn, t) : false', '',
          'tabColor(int t) =>', '    ink(t >= 0 and t < array.size(tCol) ? array.get(tCol, t) : color.gray)', '',
          'kindColor(int g) =>', '    ink(g >= 0 and g < array.size(kCol) ? array.get(kCol, g) : color.gray)', '',
          'kindHidden(int g) =>', '    g >= 0 and g < array.size(kHide) ? array.get(kHide, g) : false', '',
          'kindStyle(int g) =>', '    sn = g >= 0 and g < array.size(kSty) ? array.get(kSty, g) : "Solid"', '    sn == "Dashed" ? line.style_dashed : sn == "Dotted" ? line.style_dotted : line.style_solid', '',
          'kindWidth(int g) =>', '    g >= 0 and g < array.size(kW) ? array.get(kW, g) : 1', '',
          'kindText(string[] a, int g) =>', '    g >= 0 and g < array.size(a) ? array.get(a, g) : ""', '',
          'levelColor(int g, int t, float p) =>',
          '    colorMode == "Tab" ? tabColor(t) : colorMode == "Above / below price" ? ink(p > close ? colUp : colDn) : kindColor(g)', '',
          'sizeOf(string nm) =>', '    nm == "Tiny" ? size.tiny : nm == "Normal" ? size.normal : nm == "Large" ? size.large : size.small', '',
          'fmtP(float p) =>', '    str.tostring(p, priceDec == 0 ? "#,###" : "#,###." + str.repeat("0", priceDec))', '',
          'joinDist() =>', '    zDistMode == "Auto" ? close * 0.0005 : zDistMode == "Points" ? zDist : close * zDist / 100', '',
          'mergeDist() =>', '    mergePts > 0 ? mergePts : joinDist() / 3', '',
          'var line[]  lns = array.new<line>()', 'var label[] lbs = array.new<label>()', 'var box[]   bxs = array.new<box>()',
          'var table   tb  = na', 'var table   lg  = na',
          'var int firstBarT = time',
          'tN = bar_index >= startBars ? time[startBars] : firstBarT', '',
          '// 1) which levels pass the switches and filters',
          'qdVisible(int n) =>',
          '    vis = array.new<bool>(n, false)',
          '    for i = 0 to n - 1',
          '        p = array.get(lvP, i) + offsetPts',
          '        g = array.get(lvG, i)',
          '        array.set(vis, i, tabOn(array.get(lvT, i)) and not kindHidden(g) and math.abs(p - close) / close * 100 <= maxDistPct)',
          '    vis', '',
          '// 2) stack zones: sort the visible levels by price, chain the close ones, count the reasons in each chain',
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
          '        joinD = joinDist()',
          '        maxW = zMaxW > 0 ? zMaxW : joinD * 4',
          '        pad = zPad > 0 ? zPad : joinD * 0.2',
          '        for k = 0 to m - 1',
          '            p = array.get(vp, array.get(ord, k))',
          '            if k == 0',
          '                firstP := p',
          '            else if p - lastP > joinD or p - firstP > maxW',
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
          '                    nmz = array.get(lvN, i)',
          '                    if array.size(names) < 12 and not array.includes(names, nmz)',
          '                        array.push(names, nmz)',
          '            if cnt >= zMin',
          '                for k = 0 to m - 1',
          '                    if array.get(cid, k) == z',
          '                        array.set(inZone, array.get(vi, array.get(ord, k)), true)',
          '                zl = lo + offsetPts - pad', '                zh = hi + offsetPts + pad',
          '                heavy = cnt >= zHeavy',
          '                above = (zl + zh) / 2 > close',
          '                zc = ink(zColorMode == "Strength" ? (heavy ? zColH : zCol) : (above ? zColUp : zColDn))',
          '                array.push(bxs, box.new(startX, zh, endX, zl, xloc = xloc.bar_time, border_color = zBorder ? color.new(zc, 30) : color.new(zc, 100), border_width = heavy ? 2 : 1, bgcolor = color.new(zc, zTransp)))',
          '                array.push(zLos, zl)', '                array.push(zHis, zh)', '                array.push(zNs, cnt)',
          '                if zLabel and showLabels',
          '                    unit = zCount == "Different tabs" ? " tabs" : zCount == "Different kinds" ? " kinds" : " levels"',
          '                    what = (heavy ? "HEAVY ZONE " : "ZONE ") + str.tostring(cnt) + unit + (above ? " - resistance?" : " - support?")',
          '                    ztip = "Stack zone " + fmtP(zl) + " to " + fmtP(zh) + ": " + str.tostring(cnt) + unit + " (" + str.tostring(tot) + " levels). Inside: " + array.join(names, ", ") + ". More separate reasons at one price = more likely price reacts here (" + (above ? "above price, so a likely ceiling" : "below price, so a likely floor") + "). A clean break through it often runs to the next zone. An estimate, not a signal."',
          '                    zx = zLabelSide == "Left" ? startX : endX',
          '                    array.push(lbs, label.new(zx, zh, what, xloc = xloc.bar_time, style = zLabelSide == "Left" ? label.style_label_lower_right : label.style_label_lower_left, color = color.new(zc, 15), textcolor = labelTxtC, size = sz, tooltip = ztip))',
          '    m', '',
          '// 3) the lines: in the Clean view only key levels; levels at the same price share one line and one label',
          'qdLines(bool[] vis, int n, int startX, int endX) =>',
          '    sz = sizeOf(labelSize)',
          '    clean = viewMode == "Clean: zones + key lines"',
          '    labX = labelSide == "Left" ? startX : endX',
          '    labStyle = labelSide == "Left" ? label.style_label_right : label.style_label_left',
          '    md = mergeDist()',
          '    draw = array.new<bool>(n, false)',
          '    for i = 0 to n - 1',
          '        array.set(draw, i, array.get(vis, i) and (not clean or array.get(lvK, i)))',
          '    if nearestN > 0',
          '        keep = array.new<bool>(n, false)',
          '        for i = 0 to n - 1',
          '            if array.get(draw, i)',
          '                pi = array.get(lvP, i)',
          '                closer = 0',
          '                for j = 0 to n - 1',
          '                    if j != i and array.get(draw, j)',
          '                        pj = array.get(lvP, j)',
          '                        if (pj + offsetPts > close) == (pi + offsetPts > close) and math.abs(pj + offsetPts - close) < math.abs(pi + offsetPts - close)',
          '                            closer += 1',
          '                array.set(keep, i, closer < nearestN)',
          '        for i = 0 to n - 1',
          '            array.set(draw, i, array.get(keep, i))',
          '    nearUp = -1', '    nearDn = -1',
          '    if emphNear',
          '        for i = 0 to n - 1',
          '            if array.get(draw, i)',
          '                pe = array.get(lvP, i) + offsetPts',
          '                if pe > close and (nearUp < 0 or pe < array.get(lvP, math.max(nearUp, 0)) + offsetPts)',
          '                    nearUp := i',
          '                if pe <= close and (nearDn < 0 or pe > array.get(lvP, math.max(nearDn, 0)) + offsetPts)',
          '                    nearDn := i',
          '    drawnP = array.new<float>()', '    drawnLab = array.new<int>()', '    drawnTip = array.new<string>()',
          '    cnt = 0',
          '    for i = 0 to n - 1',
          '        if array.get(draw, i)',
          '            g = array.get(lvG, i)',
          '            p = array.get(lvP, i) + offsetPts',
          '            nm = array.get(lvN, i)',
          '            tipI = nm + " " + fmtP(p) + (array.get(lvTip, i) != "" ? ": " + array.get(lvTip, i) : "")',
          '            twin = -1',
          '            if array.size(drawnP) > 0',
          '                for k = 0 to array.size(drawnP) - 1',
          '                    if twin < 0 and math.abs(array.get(drawnP, k) - p) <= md',
          '                        twin := k',
          '            if twin >= 0',
          '                li = array.get(drawnLab, twin)',
          '                joined = array.get(drawnTip, twin) + " | " + tipI',
          '                array.set(drawnTip, twin, joined)',
          '                if li >= 0',
          '                    lb = array.get(lbs, li)',
          '                    label.set_text(lb, label.get_text(lb) + " / " + nm)',
          '                    label.set_tooltip(lb, joined)',
          '            else',
          '                c = levelColor(g, array.get(lvT, i), p)',
          '                lo = array.get(lvLo, i)', '                hi = array.get(lvHi, i)',
          '                if hi > lo and lo > 0',
          '                    array.push(bxs, box.new(startX, hi + offsetPts, endX, lo + offsetPts, xloc = xloc.bar_time, border_color = color.new(c, 50), border_width = 1, bgcolor = color.new(c, zoneTransp)))',
          '                extra = (i == nearUp or i == nearDn) ? 1 : 0',
          '                array.push(lns, line.new(startX, p, endX, p, xloc = xloc.bar_time, color = c, width = kindWidth(g) + array.get(lvB, i) + extra, style = kindStyle(g)))',
          '                cnt += 1',
          '                li = -1',
          '                if showLabels and (labelsFor == "Every line" or array.get(lvK, i))',
          '                    mean = kindText(kShort, g)',
          '                    withMean = nm + (mean != "" ? " (" + mean + ")" : "")',
          '                    txt = labelText == "Name" ? nm : labelText == "Name + price" ? nm + " " + fmtP(p) : labelText == "Name + meaning" ? withMean : labelText == "Meaning + price" ? (mean != "" ? mean : nm) + " " + fmtP(p) : withMean + " " + fmtP(p)',
          '                    array.push(lbs, label.new(labX, p, txt, xloc = xloc.bar_time, style = labStyle, color = color.new(c, labelTransp), textcolor = labelTxtC, size = sz, tooltip = tipI))',
          '                    li := array.size(lbs) - 1',
          '                array.push(drawnP, p)', '                array.push(drawnLab, li)', '                array.push(drawnTip, tipI)',
          '    cnt', '',
          '// 4) the info table',
          'qdInfoTable(float[] zLos, float[] zHis, int[] zNs, int nLines) =>',
          '    table out = na',
          '    if showTable',
          '        tsz = sizeOf(tableSize)',
          '        today = str.format_time(time, "yyyy-MM-dd", "America/New_York")',
          '        old = array.get(meta, 1) != "" and array.get(meta, 1) != today',
          '        upI = -1', '        dnI = -1',
          '        if array.size(zNs) > 0',
          '            for k = 0 to array.size(zNs) - 1',
          '                mid = (array.get(zLos, k) + array.get(zHis, k)) / 2',
          '                if mid > close and (upI < 0 or mid < (array.get(zLos, math.max(upI, 0)) + array.get(zHis, math.max(upI, 0))) / 2)',
          '                    upI := k',
          '                if mid <= close and (dnI < 0 or mid > (array.get(zLos, math.max(dnI, 0)) + array.get(zHis, math.max(dnI, 0))) / 2)',
          '                    dnI := k',
          '        rowsOn = 0',
          '        if array.size(tbT) > 0',
          '            for r = 0 to array.size(tbT) - 1',
          '                rk = array.get(tbT, r)',
          '                if rk == "*" or tabOn(array.indexof(tKey, rk))',
          '                    rowsOn += 1',
          f'        out := table.new({POS_EXPR.format(v="tablePos")}, 2, rowsOn + 5, bgcolor = color.new(tableBg, 10), border_color = color.new(#2a3554, 0), border_width = 1)',
          '        table.cell(out, 0, 0, "Q DATA All Tabs", text_color = tableTxt, text_size = tsz, bgcolor = color.new(#162036, 0))',
          '        table.cell(out, 1, 0, array.size(lvP) == 0 ? "no levels pasted" : str.tostring(array.size(lvP)) + " levels, " + str.tostring(nLines) + " lines", text_color = color.new(#aeb7cc, 0), text_size = tsz, bgcolor = color.new(#162036, 0))',
          '        warnC = warnOld and old ? color.new(#e6b422, 0) : tableTxt',
          '        table.cell(out, 0, 1, "Levels from", text_color = color.new(#aeb7cc, 0), text_size = tsz, text_halign = text.align_left)',
          '        table.cell(out, 1, 1, array.size(lvP) == 0 ? "Paste them in the settings (Levels from Q DATA)" : array.get(meta, 0) + (warnOld and old ? "  OLD: copy new levels from Q DATA" : ""), text_color = warnC, text_size = tsz, text_halign = text.align_left)',
          '        row = 2',
          '        if array.size(tbT) > 0',
          '            for r = 0 to array.size(tbT) - 1',
          '                rk = array.get(tbT, r)',
          '                if rk == "*" or tabOn(array.indexof(tKey, rk))',
          '                    table.cell(out, 0, row, array.get(tbK, r), text_color = color.new(#aeb7cc, 0), text_size = tsz, text_halign = text.align_left)',
          '                    table.cell(out, 1, row, array.get(tbV, r), text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '                    row += 1',
          '        noZ = viewMode == "Every line, no zones"',
          '        zU = noZ ? "zones off" : "none in range"',
          '        zD = noZ ? "zones off" : "none in range"',
          '        if upI >= 0',
          '            zU := fmtP(array.get(zLos, upI)) + " - " + fmtP(array.get(zHis, upI)) + " (" + str.tostring(array.get(zNs, upI)) + ")"',
          '        if dnI >= 0',
          '            zD := fmtP(array.get(zLos, dnI)) + " - " + fmtP(array.get(zHis, dnI)) + " (" + str.tostring(array.get(zNs, dnI)) + ")"',
          '        table.cell(out, 0, row, "Nearest zone above", text_color = color.new(#aeb7cc, 0), text_size = tsz, text_halign = text.align_left)',
          '        table.cell(out, 1, row, zU, text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '        table.cell(out, 0, row + 1, "Nearest zone below", text_color = color.new(#aeb7cc, 0), text_size = tsz, text_halign = text.align_left)',
          '        table.cell(out, 1, row + 1, zD, text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '    out', '',
          '// 5) the legend: what each color means, following "Color levels by"',
          'qdLegend(bool[] vis, int n) =>',
          '    table out = na',
          '    if showLegend and n > 0',
          '        tsz = sizeOf(tableSize)',
          '        byTab = colorMode == "Tab"',
          '        bySide = colorMode == "Above / below price"',
          '        used = array.new<int>()',
          '        for i = 0 to n - 1',
          '            key = byTab ? array.get(lvT, i) : array.get(lvG, i)',
          '            if array.get(vis, i) and key >= 0 and not array.includes(used, key)',
          '                array.push(used, key)',
          '        array.sort(used)',
          '        rowsN = bySide ? 2 : math.min(array.size(used), 30)',
          f'        out := table.new({POS_EXPR.format(v="legendPos")}, 2, rowsN + 2, bgcolor = color.new(tableBg, 10), border_color = color.new(#2a3554, 0), border_width = 1)',
          '        table.cell(out, 0, 0, "", bgcolor = color.new(#162036, 0))',
          '        table.cell(out, 1, 0, "What the colors mean", text_color = tableTxt, text_size = tsz, bgcolor = color.new(#162036, 0), text_halign = text.align_left)',
          '        if bySide',
          '            table.cell(out, 0, 1, "  ", bgcolor = ink(colUp), text_size = tsz)',
          '            table.cell(out, 1, 1, "Level above price", text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '            table.cell(out, 0, 2, "  ", bgcolor = ink(colDn), text_size = tsz)',
          '            table.cell(out, 1, 2, "Level below price", text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '        else if rowsN > 0',
          '            for k = 0 to rowsN - 1',
          '                key = array.get(used, k)',
          '                mean = byTab ? "" : kindText(kShort, key)',
          '                table.cell(out, 0, k + 1, "  ", bgcolor = byTab ? tabColor(key) : kindColor(key), text_size = tsz)',
          '                table.cell(out, 1, k + 1, (byTab ? array.get(tName, key) : kindText(kName, key)) + (mean != "" ? ": " + mean : ""), text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '        zc0 = ink(zColorMode == "Strength" ? zCol : zColUp)',
          '        table.cell(out, 0, rowsN + 1, "  ", bgcolor = color.new(zc0, 40), text_size = tsz)',
          '        table.cell(out, 1, rowsN + 1, "Shaded: stack zone (where several levels pile up)", text_color = tableTxt, text_size = tsz, text_halign = text.align_left)',
          '    out', '',
          '// ---- the Session cone needs its numbers on every bar, so they are read once on the first bar ----',
          'var float coneOpen = na', 'var float coneMove = na', 'var int coneY = na', 'var int coneM = na', 'var int coneD = na',
          'if barstate.isfirst',
          '    [a1, a2, a3, a4, a5] = qdCone(dataTxt)',
          '    coneOpen := a1', '    coneMove := a2', '    coneY := a3', '    coneM := a4', '    coneD := a5',
          '',
          '// ---- read the pasted levels and draw everything, on the last bar ----',
          'if barstate.islast',
          '    for l in lns', '        line.delete(l)', '    for b in lbs', '        label.delete(b)', '    for x in bxs', '        box.delete(x)',
          '    array.clear(lns)', '    array.clear(lbs)', '    array.clear(bxs)',
          '    [k1, k2, k3, k4, k5, k6] = qdKinds(dataTxt)',
          '    kName := k1', '    kShort := k2', '    kCol := k3', '    kSty := k4', '    kW := k5', '    kHide := k6',
          '    [l1, l2, l3, l4, l5, l6, l7, l8, l9] = qdLevelsIn(dataTxt)',
          '    lvP := l1', '    lvLo := l2', '    lvHi := l3', '    lvT := l4', '    lvG := l5', '    lvK := l6', '    lvB := l7', '    lvN := l8', '    lvTip := l9',
          '    [r1, r2, r3, r4] = qdRows(dataTxt)',
          '    tbT := r1', '    tbK := r2', '    tbV := r3', '    meta := r4',
          '    sessionOpen = timestamp("America/New_York", year(time, "America/New_York"), month(time, "America/New_York"), dayofmonth(time, "America/New_York"), 9, 30, 0)',
          '    startX = startMode == "Start of chart data" ? firstBarT : startMode == "Last N bars" ? tN : math.min(sessionOpen, time)',
          '    endX = time + extBars * timeframe.in_seconds() * 1000',
          '    n = array.size(lvP)',
          '    nLines = 0',
          '    zLos = array.new<float>()', '    zHis = array.new<float>()', '    zNs = array.new<int>()',
          '    vis = array.new<bool>()',
          '    if n == 0',
          '        array.push(lbs, label.new(time, close, "Q DATA All Tabs: open this indicator\'s settings and paste the levels from Q DATA (TradingView indicator tab > Copy levels)", xloc = xloc.bar_time, style = label.style_label_down, color = color.new(color.gray, 60), textcolor = color.white, size = size.small))',
          '    else',
          '        vis := qdVisible(n)',
          '        inZone = array.new<bool>(n, false)',
          '        if viewMode != "Every line, no zones"',
          '            qdZones(vis, n, startX, endX, inZone, zLos, zHis, zNs)',
          '        nLines := qdLines(vis, n, startX, endX)',
          '    if not na(tb)', '        table.delete(tb)',
          '    tb := qdInfoTable(zLos, zHis, zNs, nLines)',
          '    if not na(lg)', '        table.delete(lg)',
          '    lg := qdLegend(vis, array.size(vis))']
    if sess >= 0:
        o += ['',
              '// ---- Session tab: the expected-move cone from the 9:30 open (only on the day the levels were made) ----',
              'hasCone = not na(coneOpen) and coneMove > 0 and not na(coneY)',
              'cOpenT  = hasCone ? timestamp("America/New_York", coneY, coneM, coneD, 9, 30, 0) : 0',
              'cCloseT = hasCone ? timestamp("America/New_York", coneY, coneM, coneD, 16, 0, 0) : 1',
              f'inCone = hasCone and t{sess} and showCone and time >= cOpenT and time <= cCloseT',
              'coneFrac = math.max(0.0, math.min(1.0, float(time - cOpenT) / float(cCloseT - cOpenT)))',
              'coneW = hasCone ? coneMove * math.sqrt(coneFrac) : 0.0',
              'plot(inCone ? coneOpen + offsetPts + coneW : na, "Cone +1", color = ink(coneC1), style = plot.style_linebr)',
              'plot(inCone ? coneOpen + offsetPts - coneW : na, "Cone -1", color = ink(coneC1), style = plot.style_linebr)',
              'plot(inCone ? coneOpen + offsetPts + 2 * coneW : na, "Cone +2", color = color.new(ink(coneC2), 40), style = plot.style_linebr)',
              'plot(inCone ? coneOpen + offsetPts - 2 * coneW : na, "Cone -2", color = color.new(ink(coneC2), 40), style = plot.style_linebr)']
    return "\n".join(o) + "\n"
