"""The scripts of the paste-in TradingView indicators: Q DATA GEX, Q DATA Levels, Q DATA All Tabs (both in one, 1.25.0) and
Q DATA Key Levels (the Key levels tab, 1.28.0: built like Q DATA GEX, with the Key levels tab's other kinds as extra sections).

Each is added to TradingView once and never changes; each session the levels text from Q DATA is pasted into its first setting.
Settings are remembered by TradingView by their position, so NEW SETTINGS MUST ONLY EVER BE ADDED AT THE END.

What it draws (made for a pure white chart, with a Dark chart option):
  - levels near price as see-through zones (their own band when they have one), farther ones as thin lines; every GEX level
    (flips, walls, GEX strikes, GEX zones) is a zone wherever it is, unless "GEX levels are drawn as" says only near price (1.25.0);
  - each level starts on the candle of the options data time it first appeared (from the pasted epoch-ms times), and when a level
    moved today the old piece stays as a faded dotted line with a dotted step to the new price;
  - a short read on each label: HOLD (rejects down / bounces up), BREAK (pushes through), CHOP, worked out live against price;
  - an info box: data time, copy time, the nearest level above and below with their reads;
  - Levels only: the Activity heatmap as shaded strike bands (off until switched on).
Written as conservative Pine v6 (ASCII only); it has not been compiled by TradingView from here.
"""
from __future__ import annotations

from .tv_levels import GEX_SECTIONS, LV_SECTIONS, HEAT_SECTION, KL_SECTIONS

POSITIONS = ["Top right", "Top left", "Bottom right", "Bottom left", "Middle right"]
POS = ('tablePos == "Top left" ? position.top_left : tablePos == "Bottom right" ? position.bottom_right : '
       'tablePos == "Bottom left" ? position.bottom_left : tablePos == "Middle right" ? position.middle_right : position.top_right')


def _q(s: str) -> str:
    return '"' + str(s).replace("\\", "/").replace('"', "'") + '"'


TEMPLATE = r'''//@version=6
indicator(__TITLE__, shorttitle = __SHORT__, overlay = true, max_lines_count = 500, max_labels_count = 500, max_boxes_count = 500, max_bars_back = 5000)

// ---- __NAME__ (paste-in) ----
// Add this script once. Each session (or when Q DATA alerts that levels changed): in Q DATA open the TradingView tab, click
// __COPYBTN__, then open these settings, click into "Levels", select all, paste, OK. The script never changes, so your settings stay put.
// Every level starts on the candle of the options data time it first appeared (the data reaches Q DATA about 15 minutes later).
// Levels are estimates from delayed options data. Context, not signals.

// ---- settings (new settings only ever go at the end) ----
grpD = "Paste the levels from Q DATA"
dataTxt = input.text_area("", "Levels", group = grpD, tooltip = "Q DATA > TradingView tab > __COPYBTN__, then paste here and press OK.")
grpQ = "Quick setup"
look      = input.string("Clean", "Look", options = ["Clean", "Everything nearby", "Key levels only"], group = grpQ, tooltip = "Clean: the key levels plus the nearest few on each side from every section. Everything nearby: every level within the distance below. Key levels only: __KEYS__.")
perSide   = input.int(3, "Levels on each side of price, per section (Clean)", minval = 1, maxval = 40, group = grpQ, tooltip = "Clean keeps the key levels plus this many of the nearest levels above and below price from EACH section you have on (charm, expected move, open interest...), so one busy section never crowds out the others.")
zoneNear  = input.float(0.0, "Zones within (points, 0 = auto)", minval = 0.0, step = 1.0, group = grpQ, tooltip = "Levels this close to price are drawn as see-through zones; farther ones are thin lines. Auto: 0.35% of price (about 75 NQ points, 20 ES points).")
maxPct    = input.float(2.0, "Hide levels farther than (% of price)", minval = 0.1, step = 0.25, group = grpQ)
showRead  = input.bool(true, "What price should do at each level", group = grpQ, tooltip = "HOLD: should reject (down from above, up from below). BREAK: likely pushes through. CHOP: two-way trade around it. From the gamma regime and dealer gamma at the level. Hover a label for why.")
showHist  = input.bool(true, "Where levels started and moved today", group = grpQ, tooltip = "Each level starts on the candle it first appeared. A level that moved leaves a faded dotted line where it was, with a dotted step to the new price.")
showTable = input.bool(true, "Info box", group = grpQ, inline = "tb")
tablePos  = input.string("Top right", "", options = [__POSITIONS__], group = grpQ, inline = "tb")
theme     = input.string("White chart", "Chart", options = ["White chart", "Dark chart"], group = grpQ)
offsetPts = input.float(0.0, "Shift every level (points)", step = 0.25, group = grpQ, tooltip = "Use this if your chart is a different contract month, or Q DATA had no futures price or basis saved.")
grpS = "What to show"
__SECTION_INPUTS__
grpF = "Fine tuning"
labelSize = input.string("Small", "Label size", options = ["Tiny", "Small", "Normal"], group = grpF)
zoneT     = input.int(82, "Zone fill transparency", minval = 0, maxval = 100, group = grpF, tooltip = "Higher = more see-through. The border stays crisp.")
zoneH     = input.float(0.0, "Zone height when a level has no band (points, 0 = auto)", minval = 0.0, step = 0.25, group = grpF, tooltip = "Auto: 0.03% of price (about 6 NQ points, 2 ES points). Levels with their own band (GEX zones, stacks) use it.")
histT     = input.int(60, "Faded history transparency", minval = 0, maxval = 100, group = grpF)
hideKinds = input.string("", "Hide kinds whose name contains", group = grpF, tooltip = "Comma list, part of a name is enough, for example: midpoints, 0DTE")
extBars   = input.int(10, "Run past the last candle (bars)", minval = 0, maxval = 300, group = grpF)
warnOld   = input.bool(true, "Warn when the pasted levels are from an earlier day", group = grpF)
// added in 1.24.3 (last, so earlier settings keep their place)
grpT = "Where levels start"
startMode = input.string("When the data first showed it", "Levels start at", options = ["When the data first showed it", "9:30 open", "Start of chart data", "Last N bars"], group = grpT, inline = "st", tooltip = "When the data first showed it: each level starts on the candle of the options data time it first appeared, and moves show as faded steps. 9:30 open: every level starts at today's open (the last session's open before 9:30). Start of chart data: from the left edge. Last N bars: the number on the right.")
startBars = input.int(100, "", minval = 1, maxval = 5000, group = grpT, inline = "st")
__GEXZ_INPUT__

// ---- backtest: levels copied for an earlier day carry that day's session end (added in 1.29.0) ----
qdBtEnd(string txt) =>
    float out = 0.0
    for row in str.split(txt, "\n")
        a = str.split(str.trim(row), "|")
        if array.size(a) >= 9
            if array.get(a, 0) == "Q"
                v = str.tonumber(array.get(a, 8))
                out := na(v) ? 0.0 : v
    out
var float btEnd = qdBtEnd(dataTxt)
var float btPx = na
if btEnd > 0 and time <= btEnd
    btPx := close
// the price levels are measured against: the close at the end of that day when backtesting, else the current close
refClose() =>
    btEnd > 0 and not na(btPx) ? btPx : close

__SECTION_ARRAY__

// ---- what was pasted ----
var float[]  lvP = array.new<float>()
var float[]  lvLo = array.new<float>()
var float[]  lvHi = array.new<float>()
var int[]    lvG = array.new<int>()
var float[]  lvS = array.new<float>()
var float[]  lvE = array.new<float>()
var string[] lvR = array.new<string>()
var float[]  lvPv = array.new<float>()
var string[] lvN = array.new<string>()
var string[] lvTip = array.new<string>()
var string[] kName = array.new<string>()
var color[]  kCol = array.new<color>()
var string[] kSty = array.new<string>()
var int[]    kW = array.new<int>()
var int[]    kSec = array.new<int>()
var bool[]   kKey = array.new<bool>()
var bool[]   kHide = array.new<bool>()
var float[]  hmP = array.new<float>()
var float[]  hmLo = array.new<float>()
var float[]  hmHi = array.new<float>()
var float[]  hmV = array.new<float>()
var string[] tbK = array.new<string>()
var string[] tbV = array.new<string>()
var string[] meta = array.from("", "", "", "", "", "0")

fld(string[] a, int i) =>
    i < array.size(a) ? str.trim(array.get(a, i)) : ""

num(string[] a, int i) =>
    v = str.tonumber(fld(a, i))
    na(v) ? 0.0 : v

hexNib(string ch) =>
    k = str.pos("0123456789abcdef", str.lower(ch))
    na(k) ? 0 : k

hexColor(string h) =>
    hx = str.replace_all(h, "#", "")
    str.length(hx) >= 6 ? color.rgb(hexNib(str.substring(hx, 0, 1)) * 16 + hexNib(str.substring(hx, 1, 2)), hexNib(str.substring(hx, 2, 3)) * 16 + hexNib(str.substring(hx, 3, 4)), hexNib(str.substring(hx, 4, 5)) * 16 + hexNib(str.substring(hx, 5, 6))) : color.gray

hiddenName(string nm) =>
    hid = false
    if str.length(str.trim(hideKinds)) > 0
        lowNm = str.lower(nm)
        for part in str.split(hideKinds, ",")
            w = str.lower(str.trim(part))
            if str.length(w) > 0 and str.contains(lowNm, w)
                hid := true
    hid

secOn(int s) =>
    s >= 0 and s < array.size(secs) ? array.get(secs, s) : false

kindOf(int g, int what) =>
    // what: 0 = section, 1 = width
    ok = g >= 0 and g < array.size(kSec)
    what == 0 ? (ok ? array.get(kSec, g) : -1) : (ok ? array.get(kW, g) : 1)

kindKey(int g) =>
    g >= 0 and g < array.size(kKey) ? array.get(kKey, g) : false

kindHidden(int g) =>
    g >= 0 and g < array.size(kHide) ? array.get(kHide, g) : true

kindColor(int g) =>
    g >= 0 and g < array.size(kCol) ? array.get(kCol, g) : color.gray

kindStyle(int g) =>
    sn = g >= 0 and g < array.size(kSty) ? array.get(kSty, g) : "S"
    sn == "D" ? line.style_dashed : sn == "O" ? line.style_dotted : line.style_solid

sizeOf() =>
    labelSize == "Tiny" ? size.tiny : labelSize == "Normal" ? size.normal : size.small

fmtP(float p) =>
    str.tostring(p, "#,###.##")

// what price should do at a level, worked out against the current price
readText(string r, float p) =>
    above = p > refClose()
    r == "H" ? (above ? "HOLD: rejects down" : "HOLD: bounces up") : r == "B" ? (above ? "BREAK: pushes up through" : "BREAK: pushes down through") : r == "C" ? "CHOP: two-way" : ""

nearDist() =>
    zoneNear > 0 ? zoneNear : refClose() * 0.0035

halfH() =>
    (zoneH > 0 ? zoneH : refClose() * 0.0003) / 2

// ---- reading the pasted text ----
qdParse(string txt) =>
    array.clear(lvP)
    array.clear(lvLo)
    array.clear(lvHi)
    array.clear(lvG)
    array.clear(lvS)
    array.clear(lvE)
    array.clear(lvR)
    array.clear(lvPv)
    array.clear(lvN)
    array.clear(lvTip)
    array.clear(kName)
    array.clear(kCol)
    array.clear(kSty)
    array.clear(kW)
    array.clear(kSec)
    array.clear(kKey)
    array.clear(kHide)
    array.clear(hmP)
    array.clear(hmLo)
    array.clear(hmHi)
    array.clear(hmV)
    array.clear(tbK)
    array.clear(tbV)
    for row in str.split(txt, "\n")
        a = str.split(str.trim(row), "|")
        tag = fld(a, 0)
        if tag == "Q" and array.size(a) >= 8
            for j = 0 to 5
                array.set(meta, j, fld(a, j + 2))
        else if tag == "K" and array.size(a) >= 8
            array.push(kName, fld(a, 1))
            array.push(kCol, hexColor(fld(a, 2)))
            array.push(kSty, fld(a, 3))
            array.push(kW, int(math.max(1, math.min(4, num(a, 4)))))
            array.push(kSec, int(num(a, 6)))
            array.push(kKey, fld(a, 7) == "1")
            array.push(kHide, hiddenName(fld(a, 1)))
        else if tag == "L" and array.size(a) >= 10
            p = num(a, 1)
            if p > 0
                array.push(lvP, p)
                array.push(lvLo, num(a, 2))
                array.push(lvHi, num(a, 3))
                array.push(lvG, int(num(a, 4)))
                array.push(lvS, num(a, 5))
                array.push(lvE, num(a, 6))
                array.push(lvR, fld(a, 7))
                array.push(lvPv, num(a, 8))
                array.push(lvN, fld(a, 9))
                array.push(lvTip, fld(a, 10))
        else if tag == "H" and array.size(a) >= 5
            array.push(hmP, num(a, 1))
            array.push(hmLo, num(a, 2))
            array.push(hmHi, num(a, 3))
            array.push(hmV, num(a, 4))
        else if tag == "R" and array.size(a) >= 3
            array.push(tbK, fld(a, 1))
            array.push(tbV, fld(a, 2))
    array.size(lvP)

var line[]  lns = array.new<line>()
var label[] lbs = array.new<label>()
var box[]   bxs = array.new<box>()
var table   tb  = na
var int firstT = time

clampT(float t) =>
    int(math.max(float(firstT), math.min(t, float(time))))

var int barsT = time
barsT := bar_index >= startBars ? time[startBars] : firstT

dataStart() =>
    startMode == "When the data first showed it"

// where a level's line or zone starts, following "Levels start at"
startX(float levelStart) =>
    int out = 0
    if startMode == "When the data first showed it"
        out := clampT(levelStart)
    else if startMode == "9:30 open"
        op = timestamp("America/New_York", year(time, "America/New_York"), month(time, "America/New_York"), dayofmonth(time, "America/New_York"), 9, 30, 0)
        out := clampT(float(op > time ? op - 86400000 : op))
    else if startMode == "Start of chart data"
        out := firstT
    else
        out := barsT
    out

// a current level passes the switches and the distance filter
visibleAt(int i) =>
    g = array.get(lvG, i)
    p = array.get(lvP, i) + offsetPts
    array.get(lvE, i) == 0 and secOn(kindOf(g, 0)) and not kindHidden(g) and math.abs(p - refClose()) / refClose() * 100 <= maxPct

// which current levels get drawn: Clean = key levels + the nearest perSide on each side
qdPick(int n) =>
    vis = array.new<bool>(n, false)
    pick = array.new<bool>(n, false)
    for i = 0 to n - 1
        array.set(vis, i, visibleAt(i))
    for i = 0 to n - 1
        if array.get(vis, i)
            g = array.get(lvG, i)
            k = kindKey(g)
            if look == "Everything nearby" or k
                array.set(pick, i, true)
            else if look == "Clean"
                pi = array.get(lvP, i) + offsetPts
                closer = 0
                si = kindOf(g, 0)
                for j = 0 to n - 1
                    if j != i and array.get(vis, j) and not kindKey(array.get(lvG, j)) and kindOf(array.get(lvG, j), 0) == si
                        pj = array.get(lvP, j) + offsetPts
                        if (pj > refClose()) == (pi > refClose()) and math.abs(pj - refClose()) < math.abs(pi - refClose())
                            closer += 1
                array.set(pick, i, closer < perSide)
    pick

qdDraw(int n, bool[] pick, int endX) =>
    white = theme == "White chart"
    sz = sizeOf()
    nd = nearDist()
    hh = halfH()
    labP = array.new<float>()
    labI = array.new<int>()
    labTip = array.new<string>()
    drawn = 0
    // faded history first, so current levels sit on top
    if showHist and dataStart()
        for i = 0 to n - 1
            e = array.get(lvE, i)
            g = array.get(lvG, i)
            p = array.get(lvP, i) + offsetPts
            if e > 0 and secOn(kindOf(g, 0)) and not kindHidden(g) and math.abs(p - refClose()) / refClose() * 100 <= maxPct and array.size(lns) < 480
                c = kindColor(g)
                array.push(lns, line.new(clampT(array.get(lvS, i)), p, clampT(e), p, xloc = xloc.bar_time, color = color.new(c, histT), width = 1, style = line.style_dotted))
    for i = 0 to n - 1
        if array.get(pick, i) and array.size(lbs) < 480
            g = array.get(lvG, i)
            c = kindColor(g)
            p = array.get(lvP, i) + offsetPts
            x1 = startX(array.get(lvS, i))
            lo = array.get(lvLo, i)
            hi = array.get(lvHi, i)
            band = hi > lo and lo > 0
            gexZ = gexZones == "Every GEX level" and kindOf(g, 0) >= 0 and kindOf(g, 0) <= __GEXMAX__
            near = math.abs(p - refClose()) <= nd or gexZ
            if near and array.size(bxs) < 480
                zt = band ? hi + offsetPts : p + hh
                zb = band ? lo + offsetPts : p - hh
                array.push(bxs, box.new(x1, zt, endX, zb, xloc = xloc.bar_time, border_color = color.new(c, 15), border_width = 1, bgcolor = color.new(c, zoneT)))
                if band
                    array.push(lns, line.new(x1, p, endX, p, xloc = xloc.bar_time, color = color.new(c, 35), width = 1, style = line.style_dotted))
            else
                array.push(lns, line.new(x1, p, endX, p, xloc = xloc.bar_time, color = color.new(c, white ? 5 : 15), width = kindOf(g, 1), style = kindStyle(g)))
            pv = array.get(lvPv, i)
            if showHist and dataStart() and pv > 0
                array.push(lns, line.new(x1, pv + offsetPts, x1, p, xloc = xloc.bar_time, color = color.new(c, histT), width = 1, style = line.style_dotted))
            drawn += 1
            nm = array.get(lvN, i)
            rd = showRead ? readText(array.get(lvR, i), p) : ""
            since = "since " + str.format_time(int(array.get(lvS, i)), "HH:mm", "America/New_York") + " ET (data time)"
            tip = nm + " " + fmtP(p) + ": " + array.get(lvTip, i) + " | " + since + (pv > 0 ? ", moved from " + fmtP(pv + offsetPts) : "")
            twin = -1
            if array.size(labP) > 0
                for k = 0 to array.size(labP) - 1
                    if twin < 0 and math.abs(array.get(labP, k) - p) <= hh
                        twin := k
            if twin >= 0
                lb = array.get(lbs, array.get(labI, twin))
                label.set_text(lb, nm + " / " + label.get_text(lb))
                jt = tip + " || " + array.get(labTip, twin)
                array.set(labTip, twin, jt)
                label.set_tooltip(lb, jt)
            else
                txt = nm + " " + fmtP(p) + (rd != "" ? "  " + rd : "")
                array.push(lbs, label.new(endX, p, txt, xloc = xloc.bar_time, style = label.style_label_left, color = white ? color.new(c, 86) : color.new(c, 25), textcolor = white ? c : color.white, size = sz, tooltip = tip))
                array.push(labP, p)
                array.push(labI, array.size(lbs) - 1)
                array.push(labTip, tip)
    drawn

__HEAT_FUNC__

gAt(int i) =>
    i >= 0 and i < array.size(lvG) ? array.get(lvG, i) : -1

nextText(int i) =>
    string s = "-"
    if i >= 0 and i < array.size(lvP)
        p = array.get(lvP, i) + offsetPts
        s := array.get(lvN, i) + " " + fmtP(p) + "  " + readText(array.get(lvR, i), p)
    s

qdTable(int n, bool[] pick) =>
    table out = na
    if showTable
        white = theme == "White chart"
        bg = white ? color.new(#ffffff, 0) : color.new(#111827, 0)
        tx = white ? color.new(#0f172a, 0) : color.new(#f1f5f9, 0)
        dim = white ? color.new(#64748b, 0) : color.new(#94a3b8, 0)
        rows = array.size(tbK)
        out := table.new(__POS__, 2, rows + 4, bgcolor = bg, border_color = white ? color.new(#e2e8f0, 0) : color.new(#334155, 0), border_width = 1, frame_color = white ? color.new(#cbd5e1, 0) : color.new(#334155, 0), frame_width = 1)
        table.cell(out, 0, 0, __NAME__, text_color = tx, text_size = size.small, text_halign = text.align_left)
        table.cell(out, 1, 0, n == 0 ? "paste levels from Q DATA" : array.get(meta, 3), text_color = dim, text_size = size.small, text_halign = text.align_left)
        if rows > 0
            for r = 0 to rows - 1
                table.cell(out, 0, r + 1, array.get(tbK, r), text_color = dim, text_size = size.tiny, text_halign = text.align_left)
                table.cell(out, 1, r + 1, array.get(tbV, r), text_color = tx, text_size = size.tiny, text_halign = text.align_left)
        up = -1
        dn = -1
        if n > 0 and array.size(pick) == n
            for i = 0 to n - 1
                if array.get(pick, i)
                    p = array.get(lvP, i) + offsetPts
                    if p > refClose() and (up < 0 or p < array.get(lvP, math.max(up, 0)) + offsetPts)
                        up := i
                    if p <= refClose() and (dn < 0 or p > array.get(lvP, math.max(dn, 0)) + offsetPts)
                        dn := i
        table.cell(out, 0, rows + 1, "Next above", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(out, 1, rows + 1, nextText(up), text_color = up < 0 ? tx : kindColor(gAt(up)), text_size = size.tiny, text_halign = text.align_left)
        table.cell(out, 0, rows + 2, "Next below", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(out, 1, rows + 2, nextText(dn), text_color = dn < 0 ? tx : kindColor(gAt(dn)), text_size = size.tiny, text_halign = text.align_left)
        today = str.format_time(time, "yyyy-MM-dd", "America/New_York")
        old = warnOld and btEnd == 0 and n > 0 and array.get(meta, 2) != "" and array.get(meta, 2) != today
        table.cell(out, 0, rows + 3, old ? "Old levels" : btEnd > 0 ? "Backtest" : "", text_color = color.new(#dc2626, 0), text_size = size.tiny, text_halign = text.align_left)
        table.cell(out, 1, rows + 3, old ? "These are from " + array.get(meta, 2) + ": copy today's from Q DATA" : btEnd > 0 ? "Levels of " + array.get(meta, 2) + ", drawn to that day's 5 pm ET close" : "", text_color = color.new(#dc2626, 0), text_size = size.tiny, text_halign = text.align_left)
    out

// ---- draw everything on the last bar ----
if barstate.islast
    for l in lns
        line.delete(l)
    for b in lbs
        label.delete(b)
    for x in bxs
        box.delete(x)
    array.clear(lns)
    array.clear(lbs)
    array.clear(bxs)
    n = qdParse(dataTxt)
    endX = btEnd > 0 ? int(math.min(btEnd, float(time))) : time + extBars * timeframe.in_seconds() * 1000
    pick = array.new<bool>()
    if n == 0
        array.push(lbs, label.new(time, close, __NAME__ + ": open the settings and paste the levels from Q DATA (TradingView tab > __COPYBTN__)", xloc = xloc.bar_time, style = label.style_label_down, color = color.new(#64748b, 70), textcolor = color.new(#0f172a, 0), size = size.small))
    else
__HEAT_CALL__
        pick := qdPick(n)
        qdDraw(n, pick, endX)
    if not na(tb)
        table.delete(tb)
    tb := qdTable(n, pick)
'''

HEAT_FUNC = r'''// the Activity heatmap: strike bands shaded by how much activity sits there (0-100), from the 9:30 open
qdHeat(int endX) =>
    if secOn(__HEATSEC__) and array.size(hmP) > 0
        x1 = clampT(float(timestamp("America/New_York", year(time, "America/New_York"), month(time, "America/New_York"), dayofmonth(time, "America/New_York"), 9, 30, 0)))
        for i = 0 to array.size(hmP) - 1
            p = array.get(hmP, i) + offsetPts
            v = array.get(hmV, i)
            if math.abs(p - close) / close * 100 <= maxPct and array.size(bxs) < 470
                c = color.from_gradient(v, 15, 100, #f59e0b, #dc2626)
                array.push(bxs, box.new(x1, array.get(hmHi, i) + offsetPts, endX, array.get(hmLo, i) + offsetPts, xloc = xloc.bar_time, border_width = 0, bgcolor = color.new(c, int(94 - v * 0.24))))
    0
'''


# Q DATA All Tabs = the GEX sections first, then the Levels sections (Levels section i is All Tabs section ALL_LV_OFFSET + i)
ALL_LV_OFFSET = len(GEX_SECTIONS)
ALL_SECTIONS = GEX_SECTIONS + LV_SECTIONS
INFO = {"gex": ("Q DATA GEX", "QD GEX", "Copy GEX levels", "gamma flips and call / put walls"),
        "lv": ("Q DATA Levels", "QD Levels", "Copy Levels", "high and low of day, projected HOD / LOD, stacked areas and top setup entries"),
        "kl": ("Q DATA Key Levels", "QD Key", "Copy Key levels", "gamma flips, call / put walls and your own levels"),
        "all": ("Q DATA All Tabs", "QD All", "Copy All Tabs levels", "gamma flips, call / put walls, high and low of day, projected HOD / LOD, stacked areas and top setup entries")}
GEXZ_INPUT = ('grpZ = "GEX levels as zones"\n'
              'gexZones = input.string("Every GEX level", "GEX levels are drawn as", options = ["Every GEX level", "Only near price"], group = grpZ, '
              'tooltip = "Every GEX level (default): gamma flips, call / put walls, GEX strikes and GEX zones are see-through zones wherever they are. '
              'Only near price: like the other levels, zones only close to price and thin lines farther away.")')


def build_script(ind: str) -> str:
    gex, has_heat = ind == "gex", ind in ("lv", "all")
    secs = GEX_SECTIONS if gex else LV_SECTIONS if ind == "lv" else KL_SECTIONS if ind == "kl" else ALL_SECTIONS
    heat_sec = HEAT_SECTION + (ALL_LV_OFFSET if ind == "all" else 0)
    off = {heat_sec} if has_heat else set()
    si = []
    for i, nm in enumerate(secs):
        tip = ', tooltip = "Off until you switch it on: shaded strike bands where the most options activity sits (volume, open interest, GEX)."' if (has_heat and i == heat_sec) else ""
        si.append(f'sec{i} = input.bool({"false" if i in off else "true"}, {_q(nm)}, group = grpS{tip})')
    sa = f'secs = array.from({", ".join(f"sec{i}" for i in range(len(secs)))})'
    name, short, btn, keys = INFO[ind]
    code = TEMPLATE
    code = code.replace("__HEAT_FUNC__", HEAT_FUNC.replace("__HEATSEC__", str(heat_sec)) if has_heat else "")
    code = code.replace("__HEAT_CALL__\n", "        qdHeat(endX)\n" if has_heat else "")
    code = code.replace("__GEXZ_INPUT__", GEXZ_INPUT if ind != "lv" else 'gexZones = "Only near price"')
    code = code.replace("__GEXMAX__", str(len(GEX_SECTIONS) - 1) if ind != "lv" else "-1")
    rep = {"__TITLE__": _q(name), "__SHORT__": _q(short), "__NAME__": name, "__COPYBTN__": btn, "__KEYS__": keys,
           "__POSITIONS__": ", ".join(_q(p) for p in POSITIONS), "__SECTION_INPUTS__": "\n".join(si), "__SECTION_ARRAY__": sa, "__POS__": POS}
    # __NAME__ appears both in comments (bare) and as a Pine string; handle the string uses first
    code = code.replace("table.cell(out, 0, 0, __NAME__", f"table.cell(out, 0, 0, {_q(name)}")
    code = code.replace("label.new(time, close, __NAME__ + ", f"label.new(time, close, {_q(name)} + ")
    for k, v in rep.items():
        code = code.replace(k, v)
    return code
