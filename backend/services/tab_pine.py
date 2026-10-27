"""One TradingView Pine Script v6 indicator per Q DATA tab that has levels, named after that tab ("Q DATA Stack Map", ...).

TradingView cannot read the app, so each tab's levels are baked in as arrays when you copy or download the indicator.
Re-copy each session. Every level belongs to a group (one show/hide box per group in the indicator's settings), and
carries its own color, line style, label and a hover tooltip with the tab's reasoning (the call, the plan, the chance).
Only GEX and the call/put walls are drawn as zones (boxes); everything else is a single line.
Written as conservative Pine v6; it has not been compiled by TradingView from here.
"""
from __future__ import annotations
import re

STYLES = {"solid": 0, "dashed": 1, "dotted": 2}
CALL_COLOR = {"RESPECT": "#3fb96a", "CHOP": "#e6b422", "DISRESPECT": "#e5534b"}
CALL_WORD = {"RESPECT": "HOLD", "CHOP": "CHOP", "DISRESPECT": "BREAK"}
POSITIONS = ["Top right", "Top left", "Bottom right", "Bottom left", "Middle right"]


def s(text, n=None) -> str:
    """Make text safe inside a Pine string literal or comment."""
    t = re.sub(r"\s+", " ", re.sub(r'["\\]', "", str(text if text is not None else ""))).strip()
    return t[:n] if n else t


def _hex(c) -> str:
    c = str(c or "").strip()
    return c if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else "#9aa4b8"


def _num(v) -> str:
    return f"{float(v):.2f}"


def build_tab_pine(title: str, short: str, groups: list, levels: list, table: list | None = None, source: str = "", units: str = "",
                   made_at: str = "", cone: dict | None = None, max_dist_pct: float = 4.0, about: str = "") -> str:
    """groups: show/hide box names, in order. levels: dicts with price, group (index into groups), label, and optionally
    low/high (zone edges, only used for zones), tip (hover text), color '#rrggbb', style solid/dashed/dotted, width 1-4.
    table: (name, value) rows for the info table. cone: {open, move, y, m, d} draws +/-1 and +/-2 x move from the 9:30 open,
    widening with the square root of time through the session (live on the chart)."""
    lv = [x for x in levels if x.get("price") is not None and x["price"] > 0]
    lv.sort(key=lambda x: -x["price"])
    if not lv:     # array.from() needs at least one element: a placeholder in group -1, which is never drawn
        lv = [{"price": 1.0, "group": -1, "label": "none"}]
    a = lambda f: ", ".join(f(x) for x in lv)
    prices = a(lambda x: _num(x["price"]))
    lows = a(lambda x: _num(x["low"]) if x.get("low") and x.get("high") and x["high"] > x["low"] else "0.0")
    highs = a(lambda x: _num(x["high"]) if x.get("low") and x.get("high") and x["high"] > x["low"] else "0.0")
    grp = a(lambda x: str(int(x.get("group", 0))))
    names = a(lambda x: f'"{s(x.get("label"), 60)}"')
    tips = a(lambda x: f'"{s(x.get("tip") or x.get("label"), 700)}"')
    cols = a(lambda x: _hex(x.get("color")))
    sty = a(lambda x: str(STYLES.get(x.get("style") or "solid", 0)))
    wid = a(lambda x: str(max(1, min(4, int(x.get("width") or 1)))))
    rows = [(s(k, 40), s(v, 90)) for k, v in (table or []) if v not in (None, "")] or [("Levels", str(len(levels)))]
    gname = [s(g, 60) for g in groups] or ["Levels"]

    out = [f'//@version=6',
           f'indicator("{s(title, 60)}", shorttitle = "{s(short, 20)}", overlay = true, max_lines_count = 500, max_labels_count = 500, max_boxes_count = 200)',
           '',
           f'// ---- {s(title)} - made by Q DATA from the "{s(title.replace("Q DATA ", ""))}" tab ----',
           f'// {s(source)}', f'// {s(units)}', f'// Made {s(made_at)}. Re-copy it from Q DATA each session: the levels are baked in.']
    if about:
        out.append(f'// {s(about)}')
    out += ['// Hover a label for why that level is there. Levels are estimates from delayed options data: context, not signals.', '',
            f'var float[]  lvP   = array.from({prices})',
            f'var float[]  lvLo  = array.from({lows})        // zone bottom (0 = single line)',
            f'var float[]  lvHi  = array.from({highs})        // zone top',
            f'var int[]    lvG   = array.from({grp})          // which show/hide box',
            f'var string[] lvN   = array.from({names})',
            f'var string[] lvTip = array.from({tips})',
            f'var color[]  lvC   = array.from({cols})',
            f'var int[]    lvS   = array.from({sty})          // 0 solid, 1 dashed, 2 dotted',
            f'var int[]    lvW   = array.from({wid})',
            f'var string[] tbK   = array.from({", ".join(chr(34) + k + chr(34) for k, _ in rows)})',
            f'var string[] tbV   = array.from({", ".join(chr(34) + v + chr(34) for _, v in rows)})',
            '', 'grpShow = "Show"']
    for i, g in enumerate(gname):
        out.append(f'g{i} = input.bool(true, "{g}", group = grpShow)')
    if cone:
        out.append('showCone = input.bool(true, "Expected-move cone from the 9:30 open (+/-1 and 2)", group = grpShow)')
    out += ['grpLook = "Look"',
            'offsetPts  = input.float(0.0, "Add to every level (points)", group = grpLook, tooltip = "Use this if your chart is a different contract or Q DATA had no NQ price or basis saved.")',
            f'maxDistPct = input.float({max_dist_pct:.1f}, "Hide levels farther than this % from price", minval = 0.1, step = 0.5, group = grpLook)',
            'startMode  = input.string("Session open 9:30 ET", "Lines start at", options = ["Session open 9:30 ET", "Start of chart data", "Last 20 bars"], group = grpLook)',
            'extBars    = input.int(8, "Lines run this many bars past the last candle", minval = 0, group = grpLook)',
            'showLabels = input.bool(true, "Labels", group = grpLook)',
            'showPrices = input.bool(true, "Price in the label", group = grpLook)',
            'labelSize  = input.string("Small", "Label size", options = ["Tiny", "Small", "Normal"], group = grpLook)',
            'zoneTransp = input.int(82, "Zone transparency", minval = 0, maxval = 100, group = grpLook)',
            'showTable  = input.bool(true, "Info table", group = grpLook)',
            f'tablePos   = input.string("Top right", "Table position", options = [{", ".join(chr(34) + p + chr(34) for p in POSITIONS)}], group = grpLook)',
            '', 'groupOn(int g) =>', '    switch g']
    for i in range(len(gname)):
        out.append(f'        {i} => g{i}')
    out += ['        => false', '',
            'styleOf(int k) =>', '    k == 1 ? line.style_dashed : k == 2 ? line.style_dotted : line.style_solid', '',
            'var line[]  lns = array.new<line>()', 'var label[] lbs = array.new<label>()', 'var box[]   bxs = array.new<box>()', 'var table   tb  = na', 'var int firstBarT = time', 't20 = bar_index >= 20 ? time[20] : firstBarT', '',
            'if barstate.islast',
            '    for l in lns', '        line.delete(l)', '    for b in lbs', '        label.delete(b)', '    for x in bxs', '        box.delete(x)',
            '    array.clear(lns)', '    array.clear(lbs)', '    array.clear(bxs)',
            '    sessionOpen = timestamp("America/New_York", year(time, "America/New_York"), month(time, "America/New_York"), dayofmonth(time, "America/New_York"), 9, 30, 0)',
            '    startX = startMode == "Start of chart data" ? firstBarT : startMode == "Last 20 bars" ? t20 : math.min(sessionOpen, time)',
            '    endX = time + extBars * timeframe.in_seconds() * 1000',
            '    sz = labelSize == "Tiny" ? size.tiny : labelSize == "Normal" ? size.normal : size.small',
            '    for i = 0 to array.size(lvP) - 1',
            '        p = array.get(lvP, i) + offsetPts',
            '        if groupOn(array.get(lvG, i)) and math.abs(p - close) / close * 100 <= maxDistPct',
            '            c = array.get(lvC, i)',
            '            lo = array.get(lvLo, i)',
            '            hi = array.get(lvHi, i)',
            '            if hi > lo and lo > 0',
            '                array.push(bxs, box.new(startX, hi + offsetPts, endX, lo + offsetPts, xloc = xloc.bar_time, border_color = color.new(c, 40), border_width = 1, bgcolor = color.new(c, zoneTransp)))',
            '            array.push(lns, line.new(startX, p, endX, p, xloc = xloc.bar_time, color = c, width = array.get(lvW, i), style = styleOf(array.get(lvS, i))))',
            '            if showLabels',
            '                txt = array.get(lvN, i) + (showPrices ? " " + str.tostring(p, "#,###.##") : "")',
            '                array.push(lbs, label.new(endX, p, txt, xloc = xloc.bar_time, style = label.style_label_left, color = color.new(c, 25), textcolor = color.white, size = sz, tooltip = array.get(lvTip, i)))',
            '    if not na(tb)', '        table.delete(tb)',
            '    if showTable',
            '        pos = tablePos == "Top left" ? position.top_left : tablePos == "Bottom right" ? position.bottom_right : tablePos == "Bottom left" ? position.bottom_left : tablePos == "Middle right" ? position.middle_right : position.top_right',
            '        tb := table.new(pos, 2, array.size(tbK) + 1, bgcolor = color.new(#0f1626, 10), border_color = color.new(#2a3554, 0), border_width = 1)',
            f'        table.cell(tb, 0, 0, "{s(title, 40)}", text_color = color.white, text_size = size.small, bgcolor = color.new(#162036, 0))',
            '        table.cell(tb, 1, 0, "", bgcolor = color.new(#162036, 0))',
            '        for r = 0 to array.size(tbK) - 1',
            '            table.cell(tb, 0, r + 1, array.get(tbK, r), text_color = color.new(#aeb7cc, 0), text_size = size.small, text_halign = text.align_left)',
            '            table.cell(tb, 1, r + 1, array.get(tbV, r), text_color = color.white, text_size = size.small, text_halign = text.align_left)']
    if cone:
        out += ['', '// The cone: +/-1 and +/-2 x the day\'s expected move from the 9:30 open, widening with the square root of time (only on the day it was made).',
                f'coneOpen = {_num(cone["open"])}', f'coneMove = {_num(cone["move"])}',
                f'cOpenT  = timestamp("America/New_York", {int(cone["y"])}, {int(cone["m"])}, {int(cone["d"])}, 9, 30, 0)',
                f'cCloseT = timestamp("America/New_York", {int(cone["y"])}, {int(cone["m"])}, {int(cone["d"])}, 16, 0, 0)',
                'inCone = showCone and time >= cOpenT and time <= cCloseT',
                'coneFrac = math.max(0.0, math.min(1.0, float(time - cOpenT) / float(cCloseT - cOpenT)))',
                'coneW = coneMove * math.sqrt(coneFrac)',
                'plot(inCone ? coneOpen + offsetPts + coneW : na, "Cone +1", color = color.new(#7db7ff, 0), style = plot.style_linebr)',
                'plot(inCone ? coneOpen + offsetPts - coneW : na, "Cone -1", color = color.new(#7db7ff, 0), style = plot.style_linebr)',
                'plot(inCone ? coneOpen + offsetPts + 2 * coneW : na, "Cone +2", color = color.new(#8e9bff, 40), style = plot.style_linebr)',
                'plot(inCone ? coneOpen + offsetPts - 2 * coneW : na, "Cone -2", color = color.new(#8e9bff, 40), style = plot.style_linebr)']
    return "\n".join(out) + "\n"


def build_all_pine(sections: list, head_rows: list, source: str, units: str, made_at: str, cone: dict | None = None, max_dist_pct: float = 4.0) -> str:
    """Every tab in one indicator, "Q DATA All Tabs". sections: [{tab, name, on, groups, levels, table}] (levels use group indexes
    into their own section's groups). Settings: per tab, an on/off switch and a box per kind of level, under a heading with the tab's name.
    Levels at the same price from different tabs share one label (both names), unless that is switched off."""
    gnames, lv, rows = [], [], []                     # global group list as (section index, name)
    for si, sec in enumerate(sections):
        base = len(gnames)
        gnames += [(si, g) for g in sec["groups"]]
        for x in sec["levels"]:
            if x.get("price") is not None and x["price"] > 0:
                lv.append({**x, "group": base + int(x.get("group", 0)), "tab": si})
        rows += [(si, f"{sec['name']}: {k}", v) for k, v in (sec.get("table") or []) if v not in (None, "")]
    rows = [(-1, k, v) for k, v in head_rows if v] + rows
    lv.sort(key=lambda x: -x["price"])
    if not lv:
        lv = [{"price": 1.0, "group": -1, "tab": -1, "label": "none"}]
    a = lambda f: ", ".join(f(x) for x in lv)
    zone = lambda x: x.get("low") and x.get("high") and x["high"] > x["low"]
    sess = next((i for i, sec in enumerate(sections) if sec["tab"] == "session"), None)

    out = ['//@version=6',
           'indicator("Q DATA All Tabs", shorttitle = "QD All", overlay = true, max_lines_count = 500, max_labels_count = 500, max_boxes_count = 200)',
           '', '// ---- Q DATA All Tabs: every Q DATA tab that has levels, in one indicator ----',
           f'// {s(source)}', f'// {s(units)}', f'// Made {s(made_at)}. Re-copy it from Q DATA each session: the levels are baked in.',
           '// Settings: each tab has an on/off switch and, under it, a box for each kind of level. Hover a label for why it is there.', '',
           f'var float[]  lvP   = array.from({a(lambda x: _num(x["price"]))})',
           f'var float[]  lvLo  = array.from({a(lambda x: _num(x["low"]) if zone(x) else "0.0")})',
           f'var float[]  lvHi  = array.from({a(lambda x: _num(x["high"]) if zone(x) else "0.0")})',
           f'var int[]    lvT   = array.from({a(lambda x: str(int(x["tab"])))})          // which tab',
           f'var int[]    lvG   = array.from({a(lambda x: str(int(x["group"])))})          // which kind of level',
           f'var string[] lvN   = array.from({a(lambda x: chr(34) + s(x.get("label"), 60) + chr(34))})',
           f'var string[] lvTip = array.from({a(lambda x: chr(34) + s(x.get("tip") or x.get("label"), 500) + chr(34))})',
           f'var color[]  lvC   = array.from({a(lambda x: _hex(x.get("color")))})',
           f'var int[]    lvS   = array.from({a(lambda x: str(STYLES.get(x.get("style") or "solid", 0)))})',
           f'var int[]    lvW   = array.from({a(lambda x: str(max(1, min(4, int(x.get("width") or 1)))))})',
           f'var int[]    tbT   = array.from({", ".join(str(t) for t, _, _ in rows)})',
           f'var string[] tbK   = array.from({", ".join(chr(34) + s(k, 50) + chr(34) for _, k, _ in rows)})',
           f'var string[] tbV   = array.from({", ".join(chr(34) + s(v, 80) + chr(34) for _, _, v in rows)})', '']
    for si, sec in enumerate(sections):
        grp = s(sec["name"], 40)
        out.append(f'grp{si} = "{grp}"')
        out.append(f't{si} = input.bool({"true" if sec["on"] else "false"}, "Show {grp}", group = grp{si})')
        for gi_, (sj, g) in enumerate(gnames):
            if sj == si:
                out.append(f'g{gi_} = input.bool(true, "{s(g, 60)}", group = grp{si})')
        if cone and si == sess:
            out.append(f'showCone = input.bool(true, "Expected-move cone from the 9:30 open (+/-1 and 2)", group = grp{si})')
    out += ['grpLook = "Look"',
            'offsetPts  = input.float(0.0, "Add to every level (points)", group = grpLook)',
            f'maxDistPct = input.float({max_dist_pct:.1f}, "Hide levels farther than this % from price", minval = 0.1, step = 0.5, group = grpLook)',
            'mergeSame  = input.bool(true, "One label for levels at the same price", group = grpLook, tooltip = "When two tabs have a level at the same price, show one label with both names.")',
            'mergePts   = input.float(1.0, "Same price means within (points)", minval = 0.0, step = 0.25, group = grpLook)',
            'startMode  = input.string("Session open 9:30 ET", "Lines start at", options = ["Session open 9:30 ET", "Start of chart data", "Last 20 bars"], group = grpLook)',
            'extBars    = input.int(8, "Lines run this many bars past the last candle", minval = 0, group = grpLook)',
            'showLabels = input.bool(true, "Labels", group = grpLook)',
            'showPrices = input.bool(true, "Price in the label", group = grpLook)',
            'labelSize  = input.string("Small", "Label size", options = ["Tiny", "Small", "Normal"], group = grpLook)',
            'zoneTransp = input.int(82, "Zone transparency", minval = 0, maxval = 100, group = grpLook)',
            'showTable  = input.bool(true, "Info table (tabs that are on)", group = grpLook)',
            f'tablePos   = input.string("Top right", "Table position", options = [{", ".join(chr(34) + p + chr(34) for p in POSITIONS)}], group = grpLook)',
            '', 'tabOn(int t) =>', '    switch t', '        -1 => true']
    out += [f'        {i} => t{i}' for i in range(len(sections))]
    out += ['        => false', '', 'groupOn(int g) =>', '    switch g']
    out += [f'        {i} => g{i}' for i in range(len(gnames))]
    out += ['        => false', '',
            'styleOf(int k) =>', '    k == 1 ? line.style_dashed : k == 2 ? line.style_dotted : line.style_solid', '',
            'var line[]  lns = array.new<line>()', 'var label[] lbs = array.new<label>()', 'var box[]   bxs = array.new<box>()', 'var table   tb  = na',
            'var int firstBarT = time', 't20 = bar_index >= 20 ? time[20] : firstBarT', '',
            'if barstate.islast',
            '    for l in lns', '        line.delete(l)', '    for b in lbs', '        label.delete(b)', '    for x in bxs', '        box.delete(x)',
            '    array.clear(lns)', '    array.clear(lbs)', '    array.clear(bxs)',
            '    labP = array.new<float>()',
            '    labTip = array.new<string>()',
            '    sessionOpen = timestamp("America/New_York", year(time, "America/New_York"), month(time, "America/New_York"), dayofmonth(time, "America/New_York"), 9, 30, 0)',
            '    startX = startMode == "Start of chart data" ? firstBarT : startMode == "Last 20 bars" ? t20 : math.min(sessionOpen, time)',
            '    endX = time + extBars * timeframe.in_seconds() * 1000',
            '    sz = labelSize == "Tiny" ? size.tiny : labelSize == "Normal" ? size.normal : size.small',
            '    for i = 0 to array.size(lvP) - 1',
            '        p = array.get(lvP, i) + offsetPts',
            '        if tabOn(array.get(lvT, i)) and groupOn(array.get(lvG, i)) and math.abs(p - close) / close * 100 <= maxDistPct',
            '            c = array.get(lvC, i)',
            '            lo = array.get(lvLo, i)',
            '            hi = array.get(lvHi, i)',
            '            if hi > lo and lo > 0',
            '                array.push(bxs, box.new(startX, hi + offsetPts, endX, lo + offsetPts, xloc = xloc.bar_time, border_color = color.new(c, 40), border_width = 1, bgcolor = color.new(c, zoneTransp)))',
            '            array.push(lns, line.new(startX, p, endX, p, xloc = xloc.bar_time, color = c, width = array.get(lvW, i), style = styleOf(array.get(lvS, i))))',
            '            if showLabels',
            '                twin = -1',
            '                if mergeSame and array.size(labP) > 0',
            '                    for k = 0 to array.size(labP) - 1',
            '                        if twin < 0 and math.abs(array.get(labP, k) - p) <= mergePts',
            '                            twin := k',
            '                if twin >= 0',
            '                    lb = array.get(lbs, twin)',
            '                    label.set_text(lb, array.get(lvN, i) + " / " + label.get_text(lb))',
            '                    tip2 = array.get(lvTip, i) + " | " + array.get(labTip, twin)',
            '                    array.set(labTip, twin, tip2)',
            '                    label.set_tooltip(lb, tip2)',
            '                else',
            '                    txt = array.get(lvN, i) + (showPrices ? " " + str.tostring(p, "#,###.##") : "")',
            '                    array.push(lbs, label.new(endX, p, txt, xloc = xloc.bar_time, style = label.style_label_left, color = color.new(c, 25), textcolor = color.white, size = sz, tooltip = array.get(lvTip, i)))',
            '                    array.push(labP, p)',
            '                    array.push(labTip, array.get(lvTip, i))',
            '    if not na(tb)', '        table.delete(tb)',
            '    if showTable',
            '        n = 0',
            '        for r = 0 to array.size(tbT) - 1',
            '            if tabOn(array.get(tbT, r))',
            '                n += 1',
            '        pos = tablePos == "Top left" ? position.top_left : tablePos == "Bottom right" ? position.bottom_right : tablePos == "Bottom left" ? position.bottom_left : tablePos == "Middle right" ? position.middle_right : position.top_right',
            '        tb := table.new(pos, 2, n + 1, bgcolor = color.new(#0f1626, 10), border_color = color.new(#2a3554, 0), border_width = 1)',
            '        table.cell(tb, 0, 0, "Q DATA All Tabs", text_color = color.white, text_size = size.small, bgcolor = color.new(#162036, 0))',
            '        table.cell(tb, 1, 0, "", bgcolor = color.new(#162036, 0))',
            '        row = 1',
            '        for r = 0 to array.size(tbT) - 1',
            '            if tabOn(array.get(tbT, r))',
            '                table.cell(tb, 0, row, array.get(tbK, r), text_color = color.new(#aeb7cc, 0), text_size = size.small, text_halign = text.align_left)',
            '                table.cell(tb, 1, row, array.get(tbV, r), text_color = color.white, text_size = size.small, text_halign = text.align_left)',
            '                row += 1']
    if cone and sess is not None:
        out += ['', '// Session tab: the expected-move cone from the 9:30 open, widening with the square root of time (only on the day it was made).',
                f'coneOpen = {_num(cone["open"])}', f'coneMove = {_num(cone["move"])}',
                f'cOpenT  = timestamp("America/New_York", {int(cone["y"])}, {int(cone["m"])}, {int(cone["d"])}, 9, 30, 0)',
                f'cCloseT = timestamp("America/New_York", {int(cone["y"])}, {int(cone["m"])}, {int(cone["d"])}, 16, 0, 0)',
                f'inCone = t{sess} and showCone and time >= cOpenT and time <= cCloseT',
                'coneFrac = math.max(0.0, math.min(1.0, float(time - cOpenT) / float(cCloseT - cOpenT)))',
                'coneW = coneMove * math.sqrt(coneFrac)',
                'plot(inCone ? coneOpen + offsetPts + coneW : na, "Cone +1", color = color.new(#7db7ff, 0), style = plot.style_linebr)',
                'plot(inCone ? coneOpen + offsetPts - coneW : na, "Cone -1", color = color.new(#7db7ff, 0), style = plot.style_linebr)',
                'plot(inCone ? coneOpen + offsetPts + 2 * coneW : na, "Cone +2", color = color.new(#8e9bff, 40), style = plot.style_linebr)',
                'plot(inCone ? coneOpen + offsetPts - 2 * coneW : na, "Cone -2", color = color.new(#8e9bff, 40), style = plot.style_linebr)']
    return "\n".join(out) + "\n"
