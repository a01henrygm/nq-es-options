"""Q DATA Day Map (1.38.0): one clean paste-in TradingView indicator for the day.

It reads the SAME text as Q DATA NDX / QQQ / SPX (Copy NDX combined), so no new copy button is needed, and draws only:
  - GEX by strike: EVERY strike's net GEX as a bar (blue positive, purple negative), biggest labeled; 1.39.0: pinned to the last
    candle so it no longer slides when you scroll, the whole chain from the lowest to the highest strike;
  - the key levels of the day: the kinds Q DATA marks as key (gamma flips, call / put walls, 0DTE flip / walls, high / low of day
    so far, projected HOD / LOD, stacked areas, top setup entries, your own levels), GEX ones as zones, with a HOLD / BREAK / CHOP read;
    optionally the best GEX zones too;
  - the straddle: price at the data time +/- the at-the-money straddle of the nearest expiry, shaded, with a meter in the info box
    (move from the 9:30 open as a % of the straddle, room left to each edge).
Written as conservative Pine v6 (ASCII only); it has not been compiled by TradingView from here.
"""
from __future__ import annotations

from .tv_pine import POSITIONS, POS, _q

NAME = "Q DATA Day Map"
FILE = "qdata_day_map_paste_in.pine"

SCRIPT = r'''//@version=6
indicator("Q DATA Day Map", shorttitle = "QD Day Map", overlay = true, max_lines_count = 500, max_labels_count = 500, max_boxes_count = 500, max_bars_back = 5000)

// ---- Q DATA Day Map (paste-in) ----
// Add this script once. Each session: in Q DATA open the TradingView tab, click Copy NDX combined (or QQQ / SPX), then open these
// settings, click into "Levels", select all, paste, OK. The same copy also works in Q DATA NDX, so one copy feeds both.
// Draws only three things: every strike's GEX as bars, the key levels of the day, and the straddle (expected move).
// Levels are estimates from delayed options data. Context, not signals.

// ---- settings (new settings only ever go at the end) ----
grpD = "Paste the levels from Q DATA"
dataTxt = input.text_area("", "Levels", group = grpD, tooltip = "Q DATA > TradingView tab > Copy NDX combined (or QQQ / SPX), then paste here and press OK. The same text works in Q DATA NDX / QQQ / SPX.")
grpQ = "Quick setup"
theme     = input.string("White chart", "Chart", options = ["White chart", "Dark chart"], group = grpQ)
maxPct    = input.float(2.0, "Hide anything farther than (% of price)", minval = 0.1, step = 0.25, group = grpQ)
offsetPts = input.float(0.0, "Shift everything (points)", step = 0.25, group = grpQ, tooltip = "Use this if your chart is a different contract month, or Q DATA had no futures price or basis saved.")
showTable = input.bool(true, "Info box", group = grpQ, inline = "tb")
tablePos  = input.string("Top right", "", options = [__POSITIONS__], group = grpQ, inline = "tb")
labelSize = input.string("Small", "Label size", options = ["Tiny", "Small", "Normal"], group = grpQ)
warnOld   = input.bool(true, "Warn when the pasted levels are from an earlier day", group = grpQ)
grpK = "Key levels of the day"
keyOn     = input.bool(true, "Show the key levels", group = grpK, tooltip = "The kinds Q DATA marks as key: gamma flips, call / put walls (and the 0DTE ones), high / low of day so far, projected HOD / LOD, stacked areas, top setup entries and your own levels.")
keyBest   = input.bool(false, "Also the best GEX zones", group = grpK, tooltip = "Adds the kinds that held best in the Reactions tab: biggest GEX strikes, positive / negative GEX zones, call / put wall zones, call open interest and dealer long delta.")
showRead  = input.bool(true, "What price should do at each level", group = grpK, tooltip = "HOLD: should reject (down from above, up from below). BREAK: likely pushes through. CHOP: two-way trade around it. Hover a label for why.")
zoneNear  = input.float(0.0, "Zones within (points, 0 = auto)", minval = 0.0, step = 1.0, group = grpK, tooltip = "GEX levels are always zones. Other key levels are zones this close to price and thin lines farther away. Auto: 0.35% of price (about 75 NQ points).")
zoneT     = input.int(82, "Zone fill transparency", minval = 0, maxval = 100, group = grpK)
startMode = input.string("When the data first showed it", "Levels start at", options = ["When the data first showed it", "9:30 open"], group = grpK)
extBars   = input.int(10, "Run past the last candle (bars)", minval = 0, maxval = 300, group = grpK)
grpG = "GEX by strike (every strike)"
gpOn   = input.bool(true, "Show every strike's GEX as bars", group = grpG, tooltip = "One bar per strike on the left of the chart, longer = more GEX. Blue: positive GEX (dealers dampen moves, price tends to stick or reject). Purple: negative GEX (dealers speed moves up).")
gpLen  = input.int(40, "Length of the biggest bar (candles)", minval = 5, maxval = 400, group = grpG)
gpLab  = input.int(10, "Label the biggest strikes (how many)", minval = 0, maxval = 25, group = grpG)
gpMin  = input.float(0.0, "Hide strikes smaller than (% of the biggest)", minval = 0.0, maxval = 90.0, step = 1.0, group = grpG, tooltip = "0 = show every strike.")
gpT    = input.int(45, "Bar transparency", minval = 0, maxval = 100, group = grpG)
gpPosC = input.color(#2563eb, "Positive GEX color", group = grpG)
gpNegC = input.color(#7c3aed, "Negative GEX color", group = grpG)
grpX = "Straddle (expected move)"
stOn   = input.bool(true, "Show the straddle", group = grpX, tooltip = "Price at the data time +/- the at-the-money straddle of the nearest expiry: the move options are priced for by that expiry. The info box shows how much of it the move from the 9:30 open has used.")
stFill = input.bool(true, "Shade between the straddle edges", group = grpX)
stT    = input.int(93, "Shade transparency", minval = 0, maxval = 100, group = grpX)
stSd   = input.bool(false, "Also the 1 sd move (nearest expiry)", group = grpX)
stCol  = input.color(#2563eb, "Straddle color", group = grpX)
// added in 1.39.0 (last, so earlier settings keep their place)
grpG2 = "GEX by strike: placement"
gpWhere = input.string("Right of price", "Bars sit", options = ["Behind the candles (fixed)", "Right of price", "Left edge of the screen"], group = grpG2, tooltip = "Behind the candles (fixed): the bars start at the last candle and grow back to the left over the candles, so they stay put when you scroll. Right of price (default): they start past the level labels (Run past the last candle + this gap) and grow to the right, away from the candles. Left edge of the screen: the old way, they follow the screen as you scroll.")
gpOff   = input.int(40, "Gap from the last candle (bars, Right of price)", minval = 0, maxval = 500, group = grpG2)
gpRange = input.float(0.0, "Show strikes within (% of price, 0 = every strike)", minval = 0.0, step = 0.5, group = grpG2, tooltip = "0 shows every strike Q DATA sent, from the lowest to the highest. The other levels still follow Hide levels farther than.")
// added in 1.41.0 (last, so earlier settings keep their place)
grpGH = "GEX zone size"
gexH = input.float(0.0, "GEX zone height (points, 0 = Q DATA size)", minval = 0.0, step = 1.0, group = grpGH, tooltip = "Every GEX zone is drawn this many points tall, centered on its level. 0 = the size Q DATA works out from the GEX by strike profile (at least about 16 NQ points).")
// added in 1.42.0 (last, so earlier settings keep their place)
grpV = "Show everything, labels inside zones"
showAll  = input.bool(true, "Show every level, not just the key ones", group = grpV, tooltip = "On: every level in the paste is drawn (not only the key kinds), however far from price, and the 1 sd move too (Hide anything farther than is ignored). Off: key levels only, within the distance. GEX levels, GEX strikes, expected move / straddle / sd and HOD / LOD are never hidden by distance either way.")
allZones = input.bool(true, "Draw every level as a zone (no plain lines)", group = grpV, tooltip = "Every level is a see-through zone with its label inside it. Off: far levels go back to thin lines.")
midLine  = input.bool(false, "Line at the exact level inside each zone", group = grpV, tooltip = "Off: just the zone. On: a dotted line at the exact strike / level in the middle of each zone.")
labOff   = input.int(3, "Label offset past the last candle (bars)", minval = 0, maxval = 200, group = grpV, tooltip = "Labels sit inside their zone, this many bars right of the last candle, so you can still read them when price is in the zone.")
zoneRun  = input.int(60, "Zones run past the last candle (bars)", minval = 0, maxval = 500, group = grpV, tooltip = "Room for the labels inside the zones. The longer of this and Run past the last candle is used.")
gpAs = input.string("Zones", "GEX by strike drawn as", options = ["Zones", "Bars", "Off"], group = grpV, tooltip = "Zones: every strike Q DATA sent is a see-through zone at its own price (blue positive, purple negative, stronger color = more GEX), the biggest labeled inside (Label the biggest strikes). Bars: the old bars to the side. Off: neither.")
gpZT = input.int(88, "GEX strike zone transparency (smallest strikes)", minval = 0, maxval = 100, group = grpV, tooltip = "Bigger strikes are drawn up to 24 less see-through than this.")

// ---- backtest: levels copied for an earlier day carry that day's session end ----
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
refClose() =>
    btEnd > 0 and not na(btPx) ? btPx : close

// ---- the regular session so far (for the straddle meter) ----
inRth = not na(time(timeframe.period, "0930-1600", "America/New_York")) and timeframe.in_seconds() < 86400
var float rthOpen = na
var float rthHi = na
var float rthLo = na
if inRth and not inRth[1]
    rthOpen := open
    rthHi := high
    rthLo := low
else if inRth and not na(rthOpen)
    rthHi := math.max(rthHi, high)
    rthLo := math.min(rthLo, low)

// ---- what was pasted ----
var float[]  lvP = array.new<float>()
var float[]  lvLo = array.new<float>()
var float[]  lvHi = array.new<float>()
var int[]    lvG = array.new<int>()
var float[]  lvS = array.new<float>()
var float[]  lvE = array.new<float>()
var string[] lvR = array.new<string>()
var string[] lvN = array.new<string>()
var string[] lvTip = array.new<string>()
var string[] kName = array.new<string>()
var color[]  kCol = array.new<color>()
var int[]    kSec = array.new<int>()
var bool[]   kKey = array.new<bool>()
var int[]    kCls = array.new<int>()
var bool[]   kProt = array.new<bool>()
var float[]  gzP = array.new<float>()
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

// 0 = best zone, 2 = other, 3 = your own levels
kindClass(string nm) =>
    n = str.lower(nm)
    int c = 2
    if str.contains(n, "your level")
        c := 3
    else if str.contains(n, "biggest gex") or str.contains(n, "positive gex") or str.contains(n, "negative gex") or str.contains(n, "call wall zone") or str.contains(n, "put wall zone") or str.contains(n, "call open interest") or str.contains(n, "dealer delta: long")
        c := 0
    c

// 1.42.0: kinds that are never hidden by distance: expected move / straddle / sd and HOD / LOD
protName(string nm) =>
    n = str.lower(nm)
    str.contains(n, "expected move") or str.contains(n, "straddle") or str.contains(n, " sd") or str.startswith(n, "1 sd") or str.startswith(n, "2 sd") or str.contains(n, "of day") or str.contains(n, "hod") or str.contains(n, "lod") or str.contains(n, "typical day") or str.contains(n, "monte carlo")

kNm(int g) =>
    g >= 0 and g < array.size(kName) ? str.lower(array.get(kName, g)) : ""

kindColor(int g) =>
    g >= 0 and g < array.size(kCol) ? array.get(kCol, g) : color.gray

// straddle kinds: 1 = straddle (nearest expiry), 2 = 1 sd (nearest expiry), 0 = not one
strKind(int g) =>
    n = kNm(g)
    str.contains(n, "nearest") ? (str.contains(n, "straddle") ? 1 : str.contains(n, "1 sd") ? 2 : 0) : 0

// GEX sections are 0-3 in every Q DATA paste-in that has GEX (not in Q DATA Levels)
isGex(int g) =>
    s = g >= 0 and g < array.size(kSec) ? array.get(kSec, g) : -1
    array.get(meta, 0) != "lv" and s >= 0 and s <= 3

// GEX levels and the kinds above (1.42.0)
protKind(int g) =>
    pr = g >= 0 and g < array.size(kProt) ? array.get(kProt, g) : false
    pr or isGex(g)

keyOk(int g) =>
    k = g >= 0 and g < array.size(kKey) ? array.get(kKey, g) : false
    c = g >= 0 and g < array.size(kCls) ? array.get(kCls, g) : 2
    pk = g >= 0 and g < array.size(kProt) ? array.get(kProt, g) : false
    strKind(g) == 0 and (showAll or k or pk or c == 3 or (keyBest and c == 0))

sizeOf() =>
    labelSize == "Tiny" ? size.tiny : labelSize == "Normal" ? size.normal : size.small

fmtP(float p) =>
    str.tostring(p, "#,###.##")

fmtS(float v) =>
    (v >= 0 ? "+" : "") + str.tostring(v, "#,###")

readText(string r, float p) =>
    above = p > refClose()
    r == "H" ? (above ? "HOLD: rejects down" : "HOLD: bounces up") : r == "B" ? (above ? "BREAK: pushes up through" : "BREAK: pushes down through") : r == "C" ? "CHOP: two-way" : ""

nearDist() =>
    zoneNear > 0 ? zoneNear : refClose() * 0.0035

halfH() =>
    refClose() * 0.00015

rowVal(string k) =>
    string out = ""
    if array.size(tbK) > 0
        for i = 0 to array.size(tbK) - 1
            if array.get(tbK, i) == k
                out := array.get(tbV, i)
    out

// ---- reading the pasted text ----
qdParse(string txt) =>
    array.clear(lvP)
    array.clear(lvLo)
    array.clear(lvHi)
    array.clear(lvG)
    array.clear(lvS)
    array.clear(lvE)
    array.clear(lvR)
    array.clear(lvN)
    array.clear(lvTip)
    array.clear(kName)
    array.clear(kCol)
    array.clear(kSec)
    array.clear(kKey)
    array.clear(kCls)
    array.clear(kProt)
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
            array.push(kSec, int(num(a, 6)))
            array.push(kKey, fld(a, 7) == "1")
            array.push(kCls, kindClass(fld(a, 1)))
            array.push(kProt, protName(fld(a, 1)))
        else if tag == "L" and array.size(a) >= 10
            p = num(a, 1)
            if p > 0 and num(a, 6) == 0
                array.push(lvP, p)
                array.push(lvLo, num(a, 2))
                array.push(lvHi, num(a, 3))
                array.push(lvG, int(num(a, 4)))
                array.push(lvS, num(a, 5))
                array.push(lvE, num(a, 6))
                array.push(lvR, fld(a, 7))
                array.push(lvN, fld(a, 9))
                array.push(lvTip, fld(a, 10))
        else if tag == "G" and array.size(a) >= 4
            gp = num(a, 1)
            if gp > 0
                array.push(gpP, gp)
                array.push(gpV, num(a, 2))
                array.push(gpTx, fld(a, 3))
        else if tag == "R" and array.size(a) >= 3
            array.push(tbK, fld(a, 1))
            array.push(tbV, fld(a, 2))
    array.size(lvP) + array.size(gpP)

var line[]     lns = array.new<line>()
var label[]    lbs = array.new<label>()
var box[]      bxs = array.new<box>()
var polyline[] pls = array.new<polyline>()
var table      tb  = na
var int firstT = time

clampT(float t) =>
    int(math.max(float(firstT), math.min(t, float(time))))

startX(float levelStart) =>
    int out = 0
    if startMode == "9:30 open"
        op = timestamp("America/New_York", year(time, "America/New_York"), month(time, "America/New_York"), dayofmonth(time, "America/New_York"), 9, 30, 0)
        out := clampT(float(op > time ? op - 86400000 : op))
    else
        out := clampT(levelStart)
    out

inRange(float p) =>
    showAll or math.abs(p - refClose()) / refClose() * 100 <= maxPct

// a level passes the distance limit (GEX, expected move / sd and HOD / LOD always do, 1.42.0)
inRangeG(int g, float p) =>
    protKind(g) or inRange(p)

// how far right of the last candle the zones run (1.42.0): room for the labels inside them
runBars() =>
    math.max(extBars, math.max(zoneRun, labOff + 25))

// ---- the key levels of the day ----
keyDraw(int endX, int labX) =>
    white = theme == "White chart"
    sz = sizeOf()
    nd = nearDist()
    hh = halfH()
    labP = array.new<float>()
    labI = array.new<int>()
    labCnt = array.new<int>()
    labBase = array.new<string>()
    labTip = array.new<string>()
    array.clear(gzP)
    n = array.size(lvP)
    if keyOn and n > 0
        // nearest to price first (1.42.0), so with every level on, the ones that matter most never run out of drawings
        dists = array.new<float>(n, 0.0)
        for i = 0 to n - 1
            array.set(dists, i, math.abs(array.get(lvP, i) + offsetPts - refClose()))
        ix = array.sort_indices(dists, order.ascending)
        for i in ix
            g = array.get(lvG, i)
            p = array.get(lvP, i) + offsetPts
            if keyOk(g) and inRangeG(g, p) and array.size(lbs) < 470 and array.size(bxs) < 470
                c = kindColor(g)
                x1 = startX(array.get(lvS, i))
                lo = array.get(lvLo, i)
                hi = array.get(lvHi, i)
                band = hi > lo and lo > 0
                zone = allZones or isGex(g) or math.abs(p - refClose()) <= nd
                if zone
                    gH = gexH > 0 and isGex(g)
                    zt = gH ? p + gexH / 2 : band ? hi + offsetPts : p + hh * 2
                    zb = gH ? p - gexH / 2 : band ? lo + offsetPts : p - hh * 2
                    array.push(bxs, box.new(x1, zt, endX, zb, xloc = xloc.bar_time, border_color = color.new(c, 15), border_width = 1, bgcolor = color.new(c, zoneT)))
                    if isGex(g)
                        array.push(gzP, p)
                    if midLine
                        array.push(lns, line.new(x1, p, endX, p, xloc = xloc.bar_time, color = color.new(c, 30), width = 1, style = line.style_dotted))
                else
                    array.push(lns, line.new(x1, p, endX, p, xloc = xloc.bar_time, color = color.new(c, white ? 5 : 15), width = 2, style = line.style_solid))
                nm = array.get(lvN, i)
                rd = showRead ? readText(array.get(lvR, i), p) : ""
                tip = nm + " " + fmtP(p) + ": " + array.get(lvTip, i) + " | since " + str.format_time(int(array.get(lvS, i)), "HH:mm", "America/New_York") + " ET (data time)"
                twin = -1
                if array.size(labP) > 0
                    for k = 0 to array.size(labP) - 1
                        if twin < 0 and math.abs(array.get(labP, k) - p) <= hh * 2
                            twin := k
                if twin >= 0
                    lb = array.get(lbs, array.get(labI, twin))
                    cnt = array.get(labCnt, twin) + 1
                    array.set(labCnt, twin, cnt)
                    base = nm + " / " + array.get(labBase, twin)
                    array.set(labBase, twin, base)
                    label.set_text(lb, "x" + str.tostring(cnt) + "  " + base)
                    jt = tip + " || " + array.get(labTip, twin)
                    array.set(labTip, twin, jt)
                    label.set_tooltip(lb, jt)
                else
                    txt = nm + " " + fmtP(p) + (rd != "" ? "  " + rd : "")
                    // 1.42.0: the label sits INSIDE its zone, a few bars right of the last candle, readable when price is in the zone
                    array.push(lbs, label.new(labX, p, txt, xloc = xloc.bar_time, style = labX >= endX ? label.style_label_right : label.style_label_left, color = white ? color.new(c, 80) : color.new(c, 35), textcolor = white ? c : color.white, size = sz, tooltip = tip))
                    array.push(labP, p)
                    array.push(labI, array.size(lbs) - 1)
                    array.push(labCnt, 1)
                    array.push(labBase, txt)
                    array.push(labTip, tip)
    0

// the nearest drawn key level above (dir 1) or below (dir -1) price
nextKey(int dir) =>
    string s = "-"
    float best = na
    n = array.size(lvP)
    if keyOn and n > 0
        for i = 0 to n - 1
            g = array.get(lvG, i)
            p = array.get(lvP, i) + offsetPts
            if keyOk(g) and inRangeG(g, p) and (dir > 0 ? p > refClose() : p <= refClose())
                if na(best) or math.abs(p - refClose()) < math.abs(best - refClose())
                    best := p
                    s := array.get(lvN, i) + " " + fmtP(p) + (showRead ? "  " + readText(array.get(lvR, i), p) : "")
    s

// ---- GEX by strike: every strike's net GEX as a bar on the left of the chart ----
// GEX by strike placement and range (1.39.0)
gpIn(float p) =>
    gpRange <= 0 or math.abs(p - refClose()) / refClose() * 100 <= gpRange

// where the bars start: fixed at the last candle (growing back over the candles), right of price, or the left edge of the screen
gpX0(int barMs) =>
    gpWhere == "Left edge of the screen" ? chart.left_visible_bar_time : gpWhere == "Right of price" ? time + (runBars() + gpOff) * barMs : time

gpDir() =>
    gpWhere == "Behind the candles (fixed)" ? -1 : 1

gpDraw() =>
    nG = array.size(gpP)
    int shown = 0
    if gpOn and gpAs == "Bars" and nG > 0
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
                array.push(pls, polyline.new(ptsP, curved = false, closed = true, xloc = xloc.bar_time, line_color = color.new(gpPosC, white ? 10 : 20), fill_color = color.new(gpPosC, gpT), line_width = 1))
            if array.size(ptsN) >= 4
                array.push(pls, polyline.new(ptsN, curved = false, closed = true, xloc = xloc.bar_time, line_color = color.new(gpNegC, white ? 10 : 20), fill_color = color.new(gpNegC, gpT), line_width = 1))
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
                        array.push(lbs, label.new(x1, p, fmtP(p) + "  " + array.get(gpTx, best), xloc = xloc.bar_time, style = dr < 0 ? label.style_label_right : label.style_label_left, color = color.new(c, 100), textcolor = c, size = size.tiny, tooltip = "GEX at " + fmtP(p) + ": " + array.get(gpTx, best) + " (" + str.tostring(math.round(math.abs(v))) + "% of the biggest strike). " + (v > 0 ? "Positive GEX: dealers dampen moves here." : "Negative GEX: dealers speed moves up here.")))
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

// a GEX level from the key levels is already a zone at this strike
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
    if gpAs == "Zones" and nG > 0
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
                    if v != 0 and (v > 0) == pos and st == stp and math.abs(v) >= gpMin and gpIn(p) and not gpCovered(p, hh)
                        array.push(pts, chart.point.from_time(x0, p - hh))
                        array.push(pts, chart.point.from_time(endX, p - hh))
                        array.push(pts, chart.point.from_time(endX, p + hh))
                        array.push(pts, chart.point.from_time(x0, p + hh))
                        shown += 1
                if array.size(pts) >= 4
                    c = pos ? gpPosC : gpNegC
                    array.push(pls, polyline.new(pts, curved = false, closed = true, xloc = xloc.bar_time, line_color = color.new(c, 100), fill_color = color.new(c, int(math.max(0, math.min(100, gpZT - stp * 8)))), line_width = 1))
            // labels inside the biggest strike zones
            white = theme == "White chart"
            used = array.new<bool>(nG, false)
            nLab = math.min(gpLab, 495 - array.size(lbs))
            for k = 1 to math.max(nLab, 1)
                if k <= nLab
                    best = -1
                    for i = 0 to nG - 1
                        if not array.get(used, i) and math.abs(array.get(gpV, i)) >= gpMin and gpIn(array.get(gpP, i) + offsetPts) and (best < 0 or math.abs(array.get(gpV, i)) > math.abs(array.get(gpV, best)))
                            best := i
                    if best >= 0
                        array.set(used, best, true)
                        p = array.get(gpP, best) + offsetPts
                        v = array.get(gpV, best)
                        if not gpCovered(p, gpHalf(best))
                            c = v > 0 ? gpPosC : gpNegC
                            array.push(lbs, label.new(labX, p, "GEX " + fmtP(p) + "  " + array.get(gpTx, best), xloc = xloc.bar_time, style = labX >= endX ? label.style_label_right : label.style_label_left, color = white ? color.new(c, 85) : color.new(c, 40), textcolor = white ? c : color.white, size = size.tiny, tooltip = "GEX at " + fmtP(p) + ": " + array.get(gpTx, best) + " (" + str.tostring(math.round(math.abs(v))) + "% of the biggest strike). " + (v > 0 ? "Positive GEX: dealers dampen moves here." : "Negative GEX: dealers speed moves up here.")))
    shown

// the biggest positive (dir 1) or negative (dir -1) GEX strike in range
bigGex(int dir) =>
    string s = "-"
    int best = -1
    nG = array.size(gpP)
    if nG > 0
        for i = 0 to nG - 1
            v = array.get(gpV, i)
            if gpIn(array.get(gpP, i) + offsetPts) and (dir > 0 ? v > 0 : v < 0)
                if best < 0 or math.abs(v) > math.abs(array.get(gpV, best))
                    best := i
    if best >= 0
        s := fmtP(array.get(gpP, best) + offsetPts) + "  " + array.get(gpTx, best)
    s

// ---- draw everything on the last bar ----
if barstate.islast
    for l in lns
        line.delete(l)
    for b in lbs
        label.delete(b)
    for x in bxs
        box.delete(x)
    for pl in pls
        polyline.delete(pl)
    array.clear(lns)
    array.clear(lbs)
    array.clear(bxs)
    array.clear(pls)
    n = qdParse(dataTxt)
    white = theme == "White chart"
    barMs = timeframe.in_seconds() * 1000
    endX = btEnd > 0 ? int(math.min(btEnd, float(time))) : time + runBars() * barMs
    labX = btEnd > 0 ? endX : time + labOff * barMs
    stSty = labX >= endX ? label.style_label_right : label.style_label_left
    // the straddle (and 1 sd) of the nearest expiry: the highest and lowest current level of each
    float stUp = na
    float stDn = na
    float sdUp = na
    float sdDn = na
    float stS = na
    if array.size(lvP) > 0
        for i = 0 to array.size(lvP) - 1
            sk = strKind(array.get(lvG, i))
            p = array.get(lvP, i) + offsetPts
            if sk == 1
                stUp := na(stUp) ? p : math.max(stUp, p)
                stDn := na(stDn) ? p : math.min(stDn, p)
                stS := na(stS) ? array.get(lvS, i) : math.min(stS, array.get(lvS, i))
            else if sk == 2
                sdUp := na(sdUp) ? p : math.max(sdUp, p)
                sdDn := na(sdDn) ? p : math.min(sdDn, p)
    hasSt = not na(stUp) and not na(stDn) and stUp > stDn
    stMid = hasSt ? (stUp + stDn) / 2 : na
    stHalf = hasSt ? (stUp - stDn) / 2 : na
    if n == 0
        array.push(lbs, label.new(time, close, "Q DATA Day Map: open the settings and paste the levels from Q DATA (TradingView tab > Copy NDX combined)", xloc = xloc.bar_time, style = label.style_label_down, color = color.new(#64748b, 70), textcolor = color.new(#0f172a, 0), size = size.small))
    else
        if stOn and hasSt
            x1 = startX(stS)
            if stFill
                array.push(bxs, box.new(x1, stUp, endX, stDn, xloc = xloc.bar_time, border_width = 0, bgcolor = color.new(stCol, stT)))
            array.push(lns, line.new(x1, stUp, endX, stUp, xloc = xloc.bar_time, color = color.new(stCol, white ? 0 : 10), width = 2, style = line.style_solid))
            array.push(lns, line.new(x1, stDn, endX, stDn, xloc = xloc.bar_time, color = color.new(stCol, white ? 0 : 10), width = 2, style = line.style_solid))
            if midLine
                array.push(lns, line.new(x1, stMid, endX, stMid, xloc = xloc.bar_time, color = color.new(stCol, 50), width = 1, style = line.style_dotted))
            stTip = "Price at the data time +/- the at-the-money straddle of the nearest expiry (" + fmtP(stHalf) + " points): the move options are priced for by that expiry. Outside it, the move is bigger than options expected."
            array.push(lbs, label.new(labX, stUp, "Straddle high " + fmtP(stUp) + "  (+" + fmtP(stHalf) + ")", xloc = xloc.bar_time, style = stSty, color = white ? color.new(stCol, 86) : color.new(stCol, 25), textcolor = white ? stCol : color.white, size = sizeOf(), tooltip = stTip))
            array.push(lbs, label.new(labX, stDn, "Straddle low " + fmtP(stDn) + "  (-" + fmtP(stHalf) + ")", xloc = xloc.bar_time, style = stSty, color = white ? color.new(stCol, 86) : color.new(stCol, 25), textcolor = white ? stCol : color.white, size = sizeOf(), tooltip = stTip))
            if (stSd or showAll) and not na(sdUp) and not na(sdDn) and sdUp > sdDn
                array.push(lns, line.new(x1, sdUp, endX, sdUp, xloc = xloc.bar_time, color = color.new(stCol, 35), width = 1, style = line.style_dashed))
                array.push(lns, line.new(x1, sdDn, endX, sdDn, xloc = xloc.bar_time, color = color.new(stCol, 35), width = 1, style = line.style_dashed))
                array.push(lbs, label.new(labX, sdUp, "1 sd " + fmtP(sdUp), xloc = xloc.bar_time, style = stSty, color = color.new(stCol, 100), textcolor = color.new(stCol, 20), size = size.tiny))
                array.push(lbs, label.new(labX, sdDn, "1 sd " + fmtP(sdDn), xloc = xloc.bar_time, style = stSty, color = color.new(stCol, 100), textcolor = color.new(stCol, 20), size = size.tiny))
        keyDraw(endX, labX)
    gpDraw()
    gpZones(endX, labX)
    // ---- info box ----
    if not na(tb)
        table.delete(tb)
    if showTable
        bg = white ? color.new(#ffffff, 0) : color.new(#111827, 0)
        tx = white ? color.new(#0f172a, 0) : color.new(#f1f5f9, 0)
        dim = white ? color.new(#64748b, 0) : color.new(#94a3b8, 0)
        tb := table.new(__POS__, 2, 12, bgcolor = bg, border_color = white ? color.new(#e2e8f0, 0) : color.new(#334155, 0), border_width = 1, frame_color = white ? color.new(#cbd5e1, 0) : color.new(#334155, 0), frame_width = 1)
        table.cell(tb, 0, 0, "Q DATA Day Map", text_color = tx, text_size = size.small, text_halign = text.align_left)
        table.cell(tb, 1, 0, n == 0 ? "paste levels from Q DATA" : array.get(meta, 3), text_color = dim, text_size = size.small, text_halign = text.align_left)
        table.cell(tb, 0, 1, "Data as of", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 1, rowVal("Data as of"), text_color = tx, text_size = size.tiny, text_halign = text.align_left)
        // straddle meter
        stTxt = hasSt ? "+/- " + fmtP(stHalf) + " pts  (" + fmtP(stDn) + " to " + fmtP(stUp) + ")" : "not in the paste (switch on Expected move in Q DATA)"
        table.cell(tb, 0, 2, "Straddle", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 2, stTxt, text_color = hasSt ? stCol : tx, text_size = size.tiny, text_halign = text.align_left)
        mv = refClose() - rthOpen
        used = hasSt and not na(rthOpen) and stHalf > 0 ? math.abs(mv) / stHalf * 100 : na
        rng = not na(rthHi) and not na(rthLo) ? rthHi - rthLo : na
        mvTxt = na(used) ? "-" : fmtS(mv) + " pts = " + str.tostring(math.round(used)) + "% of the straddle" + (used >= 100 ? "  (past it)" : "")
        table.cell(tb, 0, 3, "From the 9:30 open", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 3, mvTxt, text_color = na(used) ? tx : used >= 100 ? color.new(#dc2626, 0) : used >= 70 ? color.new(#d97706, 0) : color.new(#16a34a, 0), text_size = size.tiny, text_halign = text.align_left)
        rgTxt = na(rng) ? "-" : fmtP(rng) + " pts" + (hasSt and stHalf > 0 ? " = " + str.tostring(math.round(rng / stHalf * 100)) + "% of the straddle" : "")
        table.cell(tb, 0, 4, "Range today", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 4, rgTxt, text_color = tx, text_size = size.tiny, text_halign = text.align_left)
        rmTxt = hasSt ? fmtP(math.max(stUp - refClose(), 0)) + " up / " + fmtP(math.max(refClose() - stDn, 0)) + " down" : "-"
        table.cell(tb, 0, 5, "Room to the edges", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 5, rmTxt, text_color = tx, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 0, 6, "Biggest +GEX", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 6, bigGex(1), text_color = gpPosC, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 0, 7, "Biggest -GEX", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 7, bigGex(-1), text_color = gpNegC, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 0, 8, "Next key above", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 8, nextKey(1), text_color = tx, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 0, 9, "Next key below", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 9, nextKey(-1), text_color = tx, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 0, 11, "GEX strikes", text_color = dim, text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 11, array.size(gpP) > 0 ? str.tostring(array.size(gpP)) + " strikes, lowest " + fmtP(array.get(gpP, 0) + offsetPts) + ", highest " + fmtP(array.get(gpP, array.size(gpP) - 1) + offsetPts) : "-", text_color = tx, text_size = size.tiny, text_halign = text.align_left)
        today = str.format_time(time, "yyyy-MM-dd", "America/New_York")
        old = warnOld and btEnd == 0 and n > 0 and array.get(meta, 2) != "" and array.get(meta, 2) != today
        table.cell(tb, 0, 10, old ? "Old levels" : btEnd > 0 ? "Backtest" : "", text_color = color.new(#dc2626, 0), text_size = size.tiny, text_halign = text.align_left)
        table.cell(tb, 1, 10, old ? "These are from " + array.get(meta, 2) + ": copy today's from Q DATA" : btEnd > 0 ? "Levels of " + array.get(meta, 2) : "", text_color = color.new(#dc2626, 0), text_size = size.tiny, text_halign = text.align_left)
'''


def build_daymap_script() -> str:
    return SCRIPT.replace("__POSITIONS__", ", ".join(_q(p) for p in POSITIONS)).replace("__POS__", POS)
