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
  - (the 1.36.0 time cycle slabs were taken out again in 1.38.0.)
  - GEX by strike (1.37.0, every indicator with GEX): EVERY strike's net GEX as a bar on the left of the chart, length by size,
    blue positive / purple negative, the biggest labeled; 1.39.0: pinned to the last candle (no longer slides when you scroll), whole chain. Drawn with two filled polylines, so it never eats the line / box budget.
Written as conservative Pine v6 (ASCII only); it has not been compiled by TradingView from here.
"""
from __future__ import annotations

from .tv_levels import GEX_SECTIONS, LV_SECTIONS, HEAT_SECTION, KL_SECTIONS, KL_YOURS, KL_IV

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
// added in 1.32.0 (last, so earlier settings keep their place)
grpB = "Best zones filter"
zoneFilter = input.string(__ZF_DEFAULT__, "Show", options = ["Best zones only", "Best zones + break levels", "Everything"], group = grpB, tooltip = "Best zones only: the kinds that held best in the Reactions tab - biggest GEX strikes, positive and negative GEX zones, GEX call and put wall zones, call open interest and dealer long delta - plus your own levels. Best zones + break levels: also gamma flips, expected move and call volume, drawn dashed because price tends to push THROUGH them (continuation, not a fade). Everything: the old view, every kind.")
showStackN = input.bool(true, "Count stacked levels (x2, x3...)", group = grpB, tooltip = "When several kinds of level sit at the same price, one label shows them all with a count in front. Bigger stacks held best in the Reactions tab.")
// added in 1.33.0 (last)
symTagIn = input.string("Auto", "Label tag", options = ["Auto", "Always", "Never"], group = grpB, tooltip = "Puts the symbol the levels came from in front of every label (for example QQQ), so NDX and QQQ levels pasted into two copies of this indicator on one chart are easy to tell apart. Auto: only for levels that did not come from the index itself (QQQ, SPY).")
__COMBO_INPUT__
__GP_INPUT__

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
var int[]    kCls = array.new<int>()
var bool[]   kProt = array.new<bool>()
var float[]  gzP = array.new<float>()
var float[]  hmP = array.new<float>()
var float[]  hmLo = array.new<float>()
var float[]  hmHi = array.new<float>()
var float[]  hmV = array.new<float>()
var float[]  gpP = array.new<float>()
var float[]  gpV = array.new<float>()
var string[] gpTx = array.new<string>()
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

// 0 = best zone, 1 = break level, 2 = other, 3 = your own levels (always shown)
kindClass(string nm) =>
    n = str.lower(nm)
    int c = 2
    if str.contains(n, "your level")
        c := 3
    else if str.contains(n, "biggest gex") or str.contains(n, "positive gex") or str.contains(n, "negative gex") or str.contains(n, "call wall zone") or str.contains(n, "put wall zone") or str.contains(n, "call open interest") or str.contains(n, "dealer delta: long")
        c := 0
    else if str.contains(n, "iv wall")
        c := 2
    else if str.contains(n, "flip") or str.contains(n, "expected move") or str.contains(n, "call volume")
        c := 1
    c

// 1.42.0: kinds that are never hidden by distance, Look or the zones filter: expected move / straddle / sd and HOD / LOD
protName(string nm) =>
    n = str.lower(nm)
    str.contains(n, "expected move") or str.contains(n, "straddle") or str.contains(n, " sd") or str.startswith(n, "1 sd") or str.startswith(n, "2 sd") or str.contains(n, "of day") or str.contains(n, "hod") or str.contains(n, "lod") or str.contains(n, "typical day") or str.contains(n, "monte carlo")

clsOf(int g) =>
    g >= 0 and g < array.size(kCls) ? array.get(kCls, g) : 2

classOk(int g) =>
    c = clsOf(g)
    zoneFilter == "Everything" or c == 0 or c == 3 or (c == 1 and zoneFilter == "Best zones + break levels")

breakStyle(int g) =>
    zoneFilter != "Everything" and clsOf(g) == 1

secOn(int s) =>
    s >= 0 and s < array.size(secs) ? array.get(secs, s) : false

kindOf(int g, int what) =>
    // what: 0 = section, 1 = width
    ok = g >= 0 and g < array.size(kSec)
    what == 0 ? (ok ? array.get(kSec, g) : -1) : (ok ? array.get(kW, g) : 1)

// GEX levels (flips, walls, GEX strikes, GEX zones) and the kinds above: always shown wherever they are (1.42.0)
protKind(int g) =>
    s = kindOf(g, 0)
    pr = g >= 0 and g < array.size(kProt) ? array.get(kProt, g) : false
    pr or (s >= 0 and s <= __GEXMAX__)

kindKey(int g) =>
    g >= 0 and g < array.size(kKey) ? array.get(kKey, g) : false

kindHidden(int g) =>
    g >= 0 and g < array.size(kHide) ? array.get(kHide, g) : true

kindColor(int g) =>
    g >= 0 and g < array.size(kCol) ? array.get(kCol, g) : color.gray

kindStyle(int g) =>
    sn = g >= 0 and g < array.size(kSty) ? array.get(kSty, g) : "S"
    sn == "D" ? line.style_dashed : sn == "O" ? line.style_dotted : line.style_solid

// the symbol the pasted levels came from ("QQQ -> NQ" gives "QQQ"), shown in front of labels per "Label tag"
symTag() =>
    sym = array.get(meta, 3)
    first = str.length(sym) > 0 ? array.get(str.split(str.trim(sym), " "), 0) : ""
    show = symTagIn == "Always" or (symTagIn == "Auto" and first != "" and first != "NDX" and first != "SPX")
    show and first != "" ? first + " " : ""

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

// how far right of the last candle the zones run (1.42.0): room for the labels inside them
runBars() =>
    math.max(extBars, math.max(zoneRun, labOff + 25))

// distance zones (combined indicators, 1.34.0): super close levels get a small, tight zone
superDist() =>
    superNear > 0 ? superNear : refClose() * 0.001

smallHalf() =>
    (smallH > 0 ? smallH : refClose() * 0.00012) / 2

// the symbol the pasted levels came from: "QQQ -> NQ" gives "QQQ"
symFirst() =>
    sym = array.get(meta, 3)
    str.length(sym) > 0 ? array.get(str.split(str.trim(sym), " "), 0) : ""

// combined indicators only take their own ticker's levels
wrongSym() =>
    wantSym != "" and symFirst() != "" and symFirst() != wantSym

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
    array.clear(kCls)
    array.clear(kProt)
    array.clear(hmP)
    array.clear(hmLo)
    array.clear(hmHi)
    array.clear(hmV)
    array.clear(gpP)
    array.clear(gpV)
    array.clear(gpTx)
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
            array.push(kCls, kindClass(fld(a, 1)))
            array.push(kProt, protName(fld(a, 1)))
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
        else if tag == "G" and array.size(a) >= 4
            gp = num(a, 1)
            if gp > 0
                array.push(gpP, gp)
                array.push(gpV, num(a, 2))
                array.push(gpTx, fld(a, 3))
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
    pk = protKind(g)
    array.get(lvE, i) == 0 and secOn(kindOf(g, 0)) and not kindHidden(g) and (classOk(g) or pk) and (showAll or pk or math.abs(p - refClose()) / refClose() * 100 <= maxPct)

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
            if showAll or protKind(g) or look == "Everything nearby" or k
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

qdDraw(int n, bool[] pick, int endX, int labX) =>
    white = theme == "White chart"
    sz = sizeOf()
    nd = nearDist()
    hh = halfH()
    labP = array.new<float>()
    labI = array.new<int>()
    labTip = array.new<string>()
    labCnt = array.new<int>()
    labBase = array.new<string>()
    array.clear(gzP)
    drawn = 0
    // faded history first, so current levels sit on top
    if showHist and dataStart()
        for i = 0 to n - 1
            e = array.get(lvE, i)
            g = array.get(lvG, i)
            p = array.get(lvP, i) + offsetPts
            if e > 0 and secOn(kindOf(g, 0)) and not kindHidden(g) and (classOk(g) or protKind(g)) and (showAll or protKind(g) or math.abs(p - refClose()) / refClose() * 100 <= maxPct) and array.size(lns) < 480
                c = kindColor(g)
                array.push(lns, line.new(clampT(array.get(lvS, i)), p, clampT(e), p, xloc = xloc.bar_time, color = color.new(c, histT), width = 1, style = line.style_dotted))
    // nearest to price first (1.42.0), so with every level on, the ones that matter most never run out of drawings
    dists = array.new<float>(n, 0.0)
    for i = 0 to n - 1
        array.set(dists, i, math.abs(array.get(lvP, i) + offsetPts - refClose()))
    ix = array.sort_indices(dists, order.ascending)
    for i in ix
        if array.get(pick, i) and array.size(lbs) < 480
            g = array.get(lvG, i)
            c = kindColor(g)
            p = array.get(lvP, i) + offsetPts
            x1 = startX(array.get(lvS, i))
            lo = array.get(lvLo, i)
            hi = array.get(lvHi, i)
            band = hi > lo and lo > 0
            gexZ = gexZones == "Every GEX level" and kindOf(g, 0) >= 0 and kindOf(g, 0) <= __GEXMAX__
            brk = breakStyle(g)
            dist = math.abs(p - refClose())
            // distance zones: every non-GEX level (expected move, OI, HOD / LOD...) is a zone when decently close, a small tight zone when super close
            tiered = distZones and not gexZ
            near = allZones or (tiered ? dist <= nd : (dist <= nd or gexZ) and not brk)
            small = tiered and dist <= superDist()
            if brk and not near
                array.push(lns, line.new(x1, p, endX, p, xloc = xloc.bar_time, color = color.new(c, white ? 10 : 20), width = 1, style = line.style_dashed))
            else if near and array.size(bxs) < 480
                sh = smallHalf()
                gH = gexH > 0 and kindOf(g, 0) >= 0 and kindOf(g, 0) <= __GEXMAX__
                zt = small ? p + sh : gH ? p + gexH / 2 : band ? hi + offsetPts : p + hh
                zb = small ? p - sh : gH ? p - gexH / 2 : band ? lo + offsetPts : p - hh
                array.push(bxs, box.new(x1, zt, endX, zb, xloc = xloc.bar_time, border_color = color.new(c, 15), border_width = 1, border_style = brk ? line.style_dashed : line.style_solid, bgcolor = color.new(c, small ? math.max(zoneT - 12, 0) : zoneT)))
                if kindOf(g, 0) >= 0 and kindOf(g, 0) <= __GEXMAX__
                    array.push(gzP, p)
                if band and not small and midLine
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
                cnt = array.get(labCnt, twin) + 1
                array.set(labCnt, twin, cnt)
                base = nm + " / " + array.get(labBase, twin)
                array.set(labBase, twin, base)
                label.set_text(lb, (showStackN ? "x" + str.tostring(cnt) + "  " : "") + base)
                jt = tip + " || " + array.get(labTip, twin)
                array.set(labTip, twin, jt)
                label.set_tooltip(lb, jt)
            else
                txt = symTag() + nm + " " + fmtP(p) + (brk ? "  BREAK LEVEL" : rd != "" ? "  " + rd : "")
                // 1.42.0: the label sits INSIDE its zone, a few bars right of the last candle, so it stays readable when price is in the zone
                array.push(lbs, label.new(labX, p, txt, xloc = xloc.bar_time, style = labX >= endX ? label.style_label_right : label.style_label_left, color = white ? color.new(c, 80) : color.new(c, 35), textcolor = white ? c : color.white, size = sz, tooltip = tip))
                array.push(labP, p)
                array.push(labI, array.size(lbs) - 1)
                array.push(labTip, tip)
                array.push(labCnt, 1)
                array.push(labBase, txt)
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
        wr = n > 0 and wrongSym()
        table.cell(out, 0, rows + 3, wr ? "Wrong ticker" : old ? "Old levels" : btEnd > 0 ? "Backtest" : "", text_color = color.new(#dc2626, 0), text_size = size.tiny, text_halign = text.align_left)
        table.cell(out, 1, rows + 3, wr ? "Pasted " + symFirst() + " levels: this indicator is for " + wantSym : old ? "These are from " + array.get(meta, 2) + ": copy today's from Q DATA" : btEnd > 0 ? "Levels of " + array.get(meta, 2) + ", drawn to that day's 5 pm ET close" : "", text_color = color.new(#dc2626, 0), text_size = size.tiny, text_halign = text.align_left)
    out

// ---- GEX by strike (1.37.0): every strike's net GEX as a bar on the left of the chart ----
var polyline[] gpPl = array.new<polyline>()
var label[]    gpLb = array.new<label>()

// GEX by strike placement and range (1.39.0)
gpIn(float p) =>
    gpRange <= 0 or math.abs(p - refClose()) / refClose() * 100 <= gpRange

// where the bars start: fixed at the last candle (growing back over the candles), right of price, or the left edge of the screen
gpX0(int barMs) =>
    gpWhere == "Left edge of the screen" ? chart.left_visible_bar_time : gpWhere == "Right of price" ? time + (runBars() + gpOff) * barMs : time

gpDir() =>
    gpWhere == "Behind the candles (fixed)" ? -1 : 1

gpDraw() =>
    for pl in gpPl
        polyline.delete(pl)
    array.clear(gpPl)
    for l in gpLb
        label.delete(l)
    array.clear(gpLb)
    nG = array.size(gpP)
    int shown = 0
    if gpOn and gpAs == "Bars" and nG > 0 and not wrongSym()
        white = theme == "White chart"
        barMs = timeframe.in_seconds() * 1000
        x0 = gpX0(barMs)
        dr = gpDir()
        ok = array.new<bool>(nG, false)
        float mx = 0.0
        for i = 0 to nG - 1
            p = array.get(gpP, i) + offsetPts
            v = math.abs(array.get(gpV, i))
            if gpIn(p) and v >= gpMin
                array.set(ok, i, true)
                mx := math.max(mx, v)
        if mx > 0
            ptsP = array.new<chart.point>()
            ptsN = array.new<chart.point>()
            for i = 0 to nG - 1
                if array.get(ok, i)
                    p = array.get(gpP, i) + offsetPts
                    v = array.get(gpV, i)
                    gUp = i < nG - 1 ? array.get(gpP, i + 1) - array.get(gpP, i) : 0.0
                    gDn = i > 0 ? array.get(gpP, i) - array.get(gpP, i - 1) : 0.0
                    gap = gUp > 0 and gDn > 0 ? math.min(gUp, gDn) : math.max(gUp, gDn)
                    hh = gap > 0 ? gap * 0.4 : refClose() * 0.0002
                    x1 = x0 + dr * int(math.max(1.0, math.abs(v) / mx * gpLen) * barMs)
                    pts = v > 0 ? ptsP : ptsN
                    array.push(pts, chart.point.from_time(x0, p - hh))
                    array.push(pts, chart.point.from_time(x1, p - hh))
                    array.push(pts, chart.point.from_time(x1, p + hh))
                    array.push(pts, chart.point.from_time(x0, p + hh))
                    shown += 1
            if array.size(ptsP) >= 4
                array.push(gpPl, polyline.new(ptsP, curved = false, closed = true, xloc = xloc.bar_time, line_color = color.new(gpPosC, white ? 10 : 20), fill_color = color.new(gpPosC, gpT), line_width = 1))
            if array.size(ptsN) >= 4
                array.push(gpPl, polyline.new(ptsN, curved = false, closed = true, xloc = xloc.bar_time, line_color = color.new(gpNegC, white ? 10 : 20), fill_color = color.new(gpNegC, gpT), line_width = 1))
            // labels on the biggest strikes in view
            used = array.new<bool>(nG, false)
            nLab = math.min(gpLab, 495 - array.size(lbs))
            for k = 1 to math.max(nLab, 1)
                if k <= nLab
                    best = -1
                    for i = 0 to nG - 1
                        if array.get(ok, i) and not array.get(used, i) and (best < 0 or math.abs(array.get(gpV, i)) > math.abs(array.get(gpV, best)))
                            best := i
                    if best >= 0
                        array.set(used, best, true)
                        p = array.get(gpP, best) + offsetPts
                        v = array.get(gpV, best)
                        c = v > 0 ? gpPosC : gpNegC
                        x1 = x0 + dr * int(math.max(1.0, math.abs(v) / mx * gpLen) * barMs)
                        array.push(gpLb, label.new(x1, p, fmtP(p) + "  " + array.get(gpTx, best), xloc = xloc.bar_time, style = dr < 0 ? label.style_label_right : label.style_label_left, color = color.new(c, 100), textcolor = c, size = size.tiny, tooltip = "GEX at " + fmtP(p) + ": " + array.get(gpTx, best) + " (" + str.tostring(math.round(math.abs(v))) + "% of the biggest strike). " + (v > 0 ? "Positive GEX: dealers dampen moves here." : "Negative GEX: dealers speed moves up here.")))
    shown

// ---- GEX by strike as zones (1.42.0): every strike Q DATA sent, a see-through zone at its price, labeled inside ----
// Drawn with 8 filled polylines (4 strength steps x positive / negative), so even hundreds of strikes cost no boxes.
openX() =>
    op = timestamp("America/New_York", year(time, "America/New_York"), month(time, "America/New_York"), dayofmonth(time, "America/New_York"), 9, 30, 0)
    clampT(float(op > time ? op - 86400000 : op))

gpHalf(int i) =>
    nG = array.size(gpP)
    gUp = i < nG - 1 ? array.get(gpP, i + 1) - array.get(gpP, i) : 0.0
    gDn = i > 0 ? array.get(gpP, i) - array.get(gpP, i - 1) : 0.0
    gap = gUp > 0 and gDn > 0 ? math.min(gUp, gDn) : math.max(gUp, gDn)
    base = gap > 0 ? gap * 0.4 : refClose() * 0.0002
    gexH > 0 ? (gap > 0 ? math.min(gexH / 2, gap * 0.5) : gexH / 2) : base

// a GEX level from the levels is already a zone at this strike
gpCovered(float p, float hh) =>
    bool cov = false
    if array.size(gzP) > 0
        for q in gzP
            if math.abs(q - p) <= hh
                cov := true
    cov

gpZones(int endX, int labX) =>
    nG = array.size(gpP)
    int shown = 0
    if gpAs == "Zones" and nG > 0 and not wrongSym()
        x0 = openX()
        float mx = 0.0
        for i = 0 to nG - 1
            mx := math.max(mx, math.abs(array.get(gpV, i)))
        if mx > 0
            for b = 0 to 7
                pos = b < 4
                stp = b % 4
                pts = array.new<chart.point>()
                for i = 0 to nG - 1
                    v = array.get(gpV, i)
                    r = math.abs(v) / mx
                    st = r >= 0.6 ? 3 : r >= 0.3 ? 2 : r >= 0.1 ? 1 : 0
                    p = array.get(gpP, i) + offsetPts
                    hh = gpHalf(i)
                    if v != 0 and (v > 0) == pos and st == stp and math.abs(v) >= gpMin and not gpCovered(p, hh)
                        array.push(pts, chart.point.from_time(x0, p - hh))
                        array.push(pts, chart.point.from_time(endX, p - hh))
                        array.push(pts, chart.point.from_time(endX, p + hh))
                        array.push(pts, chart.point.from_time(x0, p + hh))
                        shown += 1
                if array.size(pts) >= 4
                    c = pos ? gpPosC : gpNegC
                    array.push(gpPl, polyline.new(pts, curved = false, closed = true, xloc = xloc.bar_time, line_color = color.new(c, 100), fill_color = color.new(c, int(math.max(0, math.min(100, gpZT - stp * 8)))), line_width = 1))
            // labels inside the biggest strike zones
            white = theme == "White chart"
            used = array.new<bool>(nG, false)
            nLab = math.min(gpLab, 495 - array.size(lbs) - array.size(gpLb))
            for k = 1 to math.max(nLab, 1)
                if k <= nLab
                    best = -1
                    for i = 0 to nG - 1
                        if not array.get(used, i) and math.abs(array.get(gpV, i)) >= gpMin and (best < 0 or math.abs(array.get(gpV, i)) > math.abs(array.get(gpV, best)))
                            best := i
                    if best >= 0
                        array.set(used, best, true)
                        p = array.get(gpP, best) + offsetPts
                        v = array.get(gpV, best)
                        if not gpCovered(p, gpHalf(best))
                            c = v > 0 ? gpPosC : gpNegC
                            array.push(gpLb, label.new(labX, p, "GEX " + fmtP(p) + "  " + array.get(gpTx, best), xloc = xloc.bar_time, style = labX >= endX ? label.style_label_right : label.style_label_left, color = white ? color.new(c, 85) : color.new(c, 40), textcolor = white ? c : color.white, size = size.tiny, tooltip = "GEX at " + fmtP(p) + ": " + array.get(gpTx, best) + " (" + str.tostring(math.round(math.abs(v))) + "% of the biggest strike). " + (v > 0 ? "Positive GEX: dealers dampen moves here." : "Negative GEX: dealers speed moves up here.")))
    shown

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
    barMs = timeframe.in_seconds() * 1000
    endX = btEnd > 0 ? int(math.min(btEnd, float(time))) : time + runBars() * barMs
    labX = btEnd > 0 ? endX : time + labOff * barMs
    pick = array.new<bool>()
    if n == 0
        array.push(lbs, label.new(time, close, __NAME__ + ": open the settings and paste the levels from Q DATA (TradingView tab > __COPYBTN__)", xloc = xloc.bar_time, style = label.style_label_down, color = color.new(#64748b, 70), textcolor = color.new(#0f172a, 0), size = size.small))
    else if wrongSym()
        array.push(lbs, label.new(time, close, __NAME__ + ": these are " + symFirst() + " levels. Paste them into Q DATA " + symFirst() + ", and copy " + wantSym + " levels for this one.", xloc = xloc.bar_time, style = label.style_label_down, color = color.new(#dc2626, 80), textcolor = color.new(#991b1b, 0), size = size.small))
    else
__HEAT_CALL__
        pick := qdPick(n)
        qdDraw(n, pick, endX, labX)
    gpDraw()
    gpZones(endX, labX)
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
# Combined per-ticker indicators (1.34.0): All Tabs + Key levels in one, named for the ticker (Q DATA NDX, Q DATA QQQ, Q DATA SPX).
# Key levels sections 0-9 are the same sections as All Tabs 0-9; then "Your levels", then "IV walls" (1.35.0, last so nothing moved).
ALL_IV = ALL_LV_OFFSET + LV_SECTIONS.index("IV walls")
COMBO_SECTIONS = [s for i, s in enumerate(ALL_SECTIONS) if i != ALL_IV] + ["Your levels", "IV walls"]
COMBO_YOURS, COMBO_IV = len(COMBO_SECTIONS) - 2, len(COMBO_SECTIONS) - 1
# 1.40.0: the Activity heatmap's All measures (combined) hot spots as stacked zones. Last section; its switch is the last setting.
COMBO_SECTIONS = COMBO_SECTIONS + ["Activity stack"]
COMBO_ACT = len(COMBO_SECTIONS) - 1
ACT_INPUT = ('// added in 1.40.0 (last, so earlier settings keep their place)\n'
             f'sec{COMBO_ACT} = input.bool(true, "Activity stack", group = grpS, tooltip = "The Activity heatmap with All measures (combined): '
             'zones where new positions, volume, open interest, GEX, charm, vanna and dealer delta pile up on the same strikes. '
             'xN in the label = how many of those measures have their own hot spot there.")')
assert ALL_IV == len(ALL_SECTIONS) - 1


def combo_sec_all(sec: int) -> int:
    """All Tabs section -> combined indicator section."""
    return COMBO_IV if sec == ALL_IV else sec


def combo_sec_kl(sec: int) -> int:
    """Key levels section -> combined indicator section."""
    return COMBO_YOURS if sec == KL_YOURS else COMBO_IV if sec == KL_IV else sec
COMBO_TICKERS = {"NDX": "_NDX", "QQQ": "QQQ", "SPX": "_SPX"}
INFO = {"gex": ("Q DATA GEX", "QD GEX", "Copy GEX levels", "gamma flips and call / put walls"),
        "lv": ("Q DATA Levels", "QD Levels", "Copy Levels", "high and low of day, projected HOD / LOD, stacked areas and top setup entries"),
        "kl": ("Q DATA Key Levels", "QD Key", "Copy Key levels", "gamma flips, call / put walls and your own levels"),
        "all": ("Q DATA All Tabs", "QD All", "Copy All Tabs levels", "gamma flips, call / put walls, high and low of day, projected HOD / LOD, stacked areas and top setup entries")}
GEXZ_INPUT = ('grpZ = "GEX levels as zones"\n'
              'gexZones = input.string("Every GEX level", "GEX levels are drawn as", options = ["Every GEX level", "Only near price"], group = grpZ, '
              'tooltip = "Every GEX level (default): gamma flips, call / put walls, GEX strikes and GEX zones are see-through zones wherever they are. '
              'Only near price: like the other levels, zones only close to price and thin lines farther away.")')
GEXH_INPUT = ('// added in 1.41.0 (last, so earlier settings keep their place)\n'
              'grpGH = "GEX zone size"\n'
              'gexH = input.float(0.0, "GEX zone height (points, 0 = Q DATA size)", minval = 0.0, step = 1.0, group = grpGH, '
              'tooltip = "Every GEX zone (flips, walls, GEX strikes, GEX zones) is drawn this many points tall, centered on its level. '
              '0 = the size Q DATA works out from the GEX by strike profile (at least about 16 NQ points).")')
COMBO_INPUT = ('// added in 1.34.0 (last)\n'
               'grpC = "Distance zones"\n'
               'distZones = input.bool(true, "Zones by distance for every non-GEX level", group = grpC, tooltip = "Expected move, open interest, volume, HOD / LOD, charm / vanna and the rest: a see-through zone only when decently close (Quick setup > Zones within), a thin line when farther. Super close ones get a small, tight zone. GEX levels follow GEX levels as zones.")\n'
               'superNear = input.float(0.0, "Small zone when within (points, 0 = auto)", minval = 0.0, step = 1.0, group = grpC, tooltip = "Auto: 0.1% of price (about 20 NQ points, 6 ES points).")\n'
               'smallH = input.float(0.0, "Small zone height (points, 0 = auto)", minval = 0.0, step = 0.25, group = grpC, tooltip = "Auto: 0.012% of price (about 2.5 NQ points, 0.8 ES points).")\n'
               'wantSym = __WANT__')
NO_COMBO = 'distZones = false\nsuperNear = 0.0\nsmallH = 0.0\nwantSym = ""'
GP_INPUT = ('// added in 1.37.0 (last, so earlier settings keep their place)\n'
            'grpG = "GEX by strike (every strike)"\n'
            'gpOn   = input.bool(true, "Show every strike\'s GEX as bars", group = grpG, tooltip = "Every strike with GEX, not just the biggest few: one bar per strike on the left of the chart, longer = more GEX. Blue: positive GEX (dealers dampen moves, price tends to stick or reject). Purple: negative GEX (dealers speed moves up). Uses the same distance limit as the levels (Hide levels farther than).")\n'
            'gpLen  = input.int(40, "Length of the biggest bar (candles)", minval = 5, maxval = 400, group = grpG)\n'
            'gpLab  = input.int(10, "Label the biggest strikes (how many)", minval = 0, maxval = 25, group = grpG)\n'
            'gpMin  = input.float(0.0, "Hide strikes smaller than (% of the biggest)", minval = 0.0, maxval = 90.0, step = 1.0, group = grpG, tooltip = "0 = show every strike.")\n'
            'gpT    = input.int(45, "Bar transparency", minval = 0, maxval = 100, group = grpG)\n'
            'gpPosC = input.color(#2563eb, "Positive GEX color", group = grpG)\n'
            'gpNegC = input.color(#7c3aed, "Negative GEX color", group = grpG)\n'
            + '// added in 1.39.0 (last, so earlier settings keep their place)\ngrpG2 = "GEX by strike: placement"\ngpWhere = input.string("Right of price", "Bars sit", options = ["Behind the candles (fixed)", "Right of price", "Left edge of the screen"], group = grpG2, tooltip = "Behind the candles (fixed): the bars start at the last candle and grow back to the left over the candles, so they stay put when you scroll. Right of price (default): they start past the level labels (Run past the last candle + this gap) and grow to the right, away from the candles. Left edge of the screen: the old way, they follow the screen as you scroll.")\ngpOff   = input.int(40, "Gap from the last candle (bars, Right of price)", minval = 0, maxval = 500, group = grpG2)\ngpRange = input.float(0.0, "Show strikes within (% of price, 0 = every strike)", minval = 0.0, step = 0.5, group = grpG2, tooltip = "0 shows every strike Q DATA sent, from the lowest to the highest. The other levels still follow Hide levels farther than.")')
V_INPUT = ('// added in 1.42.0 (last, so earlier settings keep their place)\n'
           'grpV = "Show everything, labels inside zones"\n'
           'showAll  = input.bool(true, "Show every level (no distance or per-side limit)", group = grpV, tooltip = "On: every level of every section you have on is drawn, however far from price (Look, Levels on each side and Hide levels farther than are ignored). Off: those settings apply again. GEX levels, GEX strikes, expected move / straddle / sd and HOD / LOD are never hidden by distance either way.")\n'
           'allZones = input.bool(true, "Draw every level as a zone (no plain lines)", group = grpV, tooltip = "Every level is a see-through zone with its label inside it. Off: far levels go back to thin lines.")\n'
           'midLine  = input.bool(false, "Line at the exact level inside each zone", group = grpV, tooltip = "Off: just the zone. On: a dotted line at the exact strike / level in the middle of each banded zone.")\n'
           'labOff   = input.int(3, "Label offset past the last candle (bars)", minval = 0, maxval = 200, group = grpV, tooltip = "Labels sit inside their zone, this many bars right of the last candle, so you can still read them when price is in the zone.")\n'
           'zoneRun  = input.int(60, "Zones run past the last candle (bars)", minval = 0, maxval = 500, group = grpV, tooltip = "Room for the labels inside the zones. The longer of this and Run past the last candle is used.")')
GPZ_INPUT = ('\ngpAs = input.string("Zones", "GEX by strike drawn as", options = ["Zones", "Bars", "Off"], group = grpV, tooltip = "Zones: every strike Q DATA sent is a see-through zone at its own price (blue positive, purple negative, stronger color = more GEX), the biggest labeled inside (Label the biggest strikes). Bars: the old bars to the side. Off: neither.")\n'
             'gpZT = input.int(88, "GEX strike zone transparency (smallest strikes)", minval = 0, maxval = 100, group = grpV, tooltip = "Bigger strikes are drawn up to 24 less see-through than this.")')
NO_GPZ = '\ngpAs = "Off"\ngpZT = 88'
NO_GP = 'gpOn = false\ngpLen = 40\ngpLab = 0\ngpMin = 0.0\ngpT = 45\ngpPosC = #2563eb\ngpNegC = #7c3aed\ngpWhere = "Right of price"\ngpOff = 40\ngpRange = 0.0'


def build_script(ind: str, ticker: str | None = None) -> str:
    """ind gex, lv, kl, all, or combo (with ticker NDX, QQQ or SPX)."""
    combo = ind == "combo"
    if combo and ticker not in COMBO_TICKERS:
        raise ValueError("ticker must be NDX, QQQ or SPX")
    gex, has_heat = ind == "gex", ind in ("lv", "all", "combo")
    secs = (GEX_SECTIONS if gex else LV_SECTIONS if ind == "lv" else KL_SECTIONS if ind == "kl" else COMBO_SECTIONS if combo else ALL_SECTIONS)
    heat_sec = HEAT_SECTION + (ALL_LV_OFFSET if ind in ("all", "combo") else 0)
    off = {heat_sec} if has_heat else set()
    si = []
    for i, nm in enumerate(secs):
        if combo and i == COMBO_ACT:
            continue                                          # declared last (ACT_INPUT), after every older setting
        tip = ', tooltip = "Off until you switch it on: shaded strike bands where the most options activity sits (volume, open interest, GEX)."' if (has_heat and i == heat_sec) else ""
        si.append(f'sec{i} = input.bool({"false" if i in off else "true"}, {_q(nm)}, group = grpS{tip})')
    sa = f'secs = array.from({", ".join(f"sec{i}" for i in range(len(secs)))})'
    if combo:
        name, short, btn = f"Q DATA {ticker}", f"QD {ticker}", f"Copy {ticker} combined"
        keys = "gamma flips, call / put walls, high and low of day, projected HOD / LOD, stacked areas, top setup entries and your own levels"
    else:
        name, short, btn, keys = INFO[ind]
    code = TEMPLATE
    code = code.replace("__HEAT_FUNC__", HEAT_FUNC.replace("__HEATSEC__", str(heat_sec)) if has_heat else "")
    code = code.replace("__HEAT_CALL__\n", "        qdHeat(endX)\n" if has_heat else "")
    code = code.replace("__GEXZ_INPUT__", GEXZ_INPUT if ind != "lv" else 'gexZones = "Only near price"')
    code = code.replace("__ZF_DEFAULT__", _q("Best zones only") if ind in ("gex", "kl") else _q("Everything"))
    code = code.replace("__GEXMAX__", str(len(GEX_SECTIONS) - 1) if ind != "lv" else "-1")
    code = code.replace("__COMBO_INPUT__", COMBO_INPUT.replace("__WANT__", _q(ticker)) if combo else NO_COMBO)
    code = code.replace("__GP_INPUT__", (GP_INPUT if ind != "lv" else NO_GP) + ("\n" + ACT_INPUT if combo else "") + "\n" + (GEXH_INPUT if ind != "lv" else "gexH = 0.0")
                                          + "\n" + V_INPUT + (GPZ_INPUT if ind != "lv" else NO_GPZ))
    rep = {"__TITLE__": _q(name), "__SHORT__": _q(short), "__NAME__": name, "__COPYBTN__": btn, "__KEYS__": keys,
           "__POSITIONS__": ", ".join(_q(p) for p in POSITIONS), "__SECTION_INPUTS__": "\n".join(si), "__SECTION_ARRAY__": sa, "__POS__": POS}
    # __NAME__ appears both in comments (bare) and as a Pine string; handle the string uses first
    code = code.replace("table.cell(out, 0, 0, __NAME__", f"table.cell(out, 0, 0, {_q(name)}")
    code = code.replace("label.new(time, close, __NAME__ + ", f"label.new(time, close, {_q(name)} + ")
    for k, v in rep.items():
        code = code.replace(k, v)
    return code
