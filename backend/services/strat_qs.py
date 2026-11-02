"""Strat QS (1.31.0): the Q DATA Gamma Strategy, a TradingView Pine v6 strategy that trades only from Q DATA's own levels.

It reads the same paste-in text as the Q DATA GEX and Q DATA Levels indicators (see tv_levels.py for the format): the gamma flip,
walls and GEX strikes from the GEX copy, the projected HOD / LOD, Monte Carlo targets and stack zones from the Levels copy.
Rules (also on the Strat QS tab): S1 gamma regime (fade above the flip, trade breaks below it), S2 projected HOD / LOD fade,
S3 stack zones (HOLD fade, BREAK break, CHOP skip), S4 afternoon pin toward the biggest 0DTE strike.
Each level is only used after its options data time plus the data delay, so a backtest of a pasted past day never peeks ahead.
"""
NAME = "Q DATA Gamma Strategy"
FILE = "qdata_gamma_strategy.pine"

CODE = r'''//@version=6
strategy("Q DATA Gamma Strategy", shorttitle = "QD Strategy", overlay = true, initial_capital = 50000, default_qty_type = strategy.fixed, default_qty_value = 1, commission_type = strategy.commission.cash_per_contract, commission_value = 2.0, slippage = 1, max_labels_count = 500, max_boxes_count = 500, max_lines_count = 500, max_bars_back = 5000)

// ==========================================================================
// Q DATA Gamma Strategy
// Trades only from Q DATA's own options data, pasted in from the
// TradingView tab (same text the Q DATA GEX / Levels indicators use).
//   S1 Gamma regime: above the gamma flip fade levels, below it trade breaks
//   S2 Expected-move fade at the projected HOD / LOD
//   S3 Stack zones: HOLD = fade, BREAK = trade the break, CHOP = skip
//   S4 Afternoon pin toward the biggest 0DTE gamma strike
// Backtest a past day: copy that day's levels in Q DATA, paste them here,
// keep "Trade only the pasted day" on, and read the Strategy Tester.
// Each level only becomes usable after the time it first showed in the
// options data PLUS the data delay, so the backtest never peeks ahead.
// Comments are plain ASCII only.
// ==========================================================================

// ---------------- Inputs ----------------
string grpD = "Paste the levels from Q DATA"
gexTxt    = input.text_area("", "Q DATA GEX levels", group = grpD, tooltip = "Q DATA > TradingView tab > copy the GEX levels, paste here, OK. Needed: it holds the gamma flip, walls and GEX strikes.")
lvTxt     = input.text_area("", "Q DATA Levels (HOD/LOD, stacks, Monte Carlo)", group = grpD, tooltip = "Q DATA > TradingView tab > copy the Levels, paste here, OK. Needed for Strategies 2 and 3.")
offsetPts = input.float(0.0, "Shift every level (points)", step = 0.25, group = grpD, tooltip = "Use if your chart is a different contract month than Q DATA's levels.")
onlyDay   = input.bool(true, "Trade only the pasted day", group = grpD, tooltip = "Keeps trades on the day the levels are from. Turn off only to see the rules on other days (levels would be stale).")
delayMin  = input.int(15, "Data delay (minutes)", minval = 0, maxval = 60, group = grpD, tooltip = "Q DATA's options data reaches you about 15 minutes after its time. A level is only used this long after it first appeared.")
hiInPct   = input.float(0.0, "High already in % (0 = ignore)", minval = 0.0, maxval = 100.0, group = grpD, inline = "ai", tooltip = "Optional: type Q DATA's 'High already in' / 'Low already in' readout. Strategy 2 then needs 60%+ to fade that side.")
loInPct   = input.float(0.0, "Low %", minval = 0.0, maxval = 100.0, group = grpD, inline = "ai")

string grpS = "Strategies"
useFade   = input.bool(true, "S1: Fade levels in positive gamma", group = grpS)
useBreak  = input.bool(true, "S1: Trade breaks in negative gamma", group = grpS)
breakLong = input.bool(true, "S1: Allow long breaks in negative gamma", group = grpS, tooltip = "Negative gamma favors downside breaks. Turn off to take only short breaks.")
breakMode = input.string("Close through", "S1: Break entry", options = ["Close through", "Retest"], group = grpS, tooltip = "Close through: enter on the close past the level. Retest: wait for price to come back to the level and reject.")
useHL     = input.bool(true, "S2: Fade the projected HOD / LOD", group = grpS)
useStack  = input.bool(true, "S3: Trade stack zones", group = grpS)
usePin    = input.bool(true, "S4: Afternoon pin", group = grpS)

string grpR = "Risk and trade rules"
stopATR   = input.float(0.75, "Stop buffer beyond the level (x ATR)", minval = 0.1, step = 0.05, group = grpR)
atrLen    = input.int(14, "ATR length", minval = 2, group = grpR)
minRR     = input.float(1.5, "Min reward:risk to take a trade", minval = 0.5, step = 0.1, group = grpR, tooltip = "The target must be at least this many times the risk. The script looks past nearer levels to find one that is.")
fallbackR = input.float(2.0, "Target when no level qualifies (R, 0 = skip trade)", minval = 0.0, step = 0.25, group = grpR)
touchIn   = input.float(0.0, "Touch tolerance (points, 0 = auto)", minval = 0.0, step = 0.25, group = grpR, tooltip = "How close price must get to count as touching a level. Auto: 0.25 x ATR.")
maxTrades = input.int(4, "Max trades per day", minval = 1, maxval = 20, group = grpR)
coolBars  = input.int(5, "Bars between trades", minval = 0, group = grpR)
holdMin   = input.int(15, "Minutes past the flip to switch regime", minval = 1, maxval = 120, group = grpR, tooltip = "One wick across the flip does not change dealer positioning. Price must hold on the other side this long.")
flipClose = input.bool(true, "Close the trade when the regime switches", group = grpR)
retestMax = input.int(10, "Retest must come within (bars)", minval = 1, group = grpR)
pinMinATR = input.float(1.0, "S4: Min distance to the strike (x ATR)", minval = 0.0, step = 0.25, group = grpR)

string grpT = "Trading hours (New York time)"
sessStr   = input.session("0930-1550", "New entries", group = grpT)
pinSess   = input.session("1400-1550", "S4 pin window", group = grpT)
flatSess  = input.session("0930-1555", "Flat outside", group = grpT, tooltip = "Any open trade is closed when the bar falls outside this window.")

string grpV = "Display"
showLevels = input.bool(true, "Draw the levels and zones the strategy uses", group = grpV, tooltip = "Every pasted level the rules can trade from: gamma flip, walls, GEX strikes and zones, projected HOD / LOD, Monte Carlo targets and stack zones (green HOLD, red BREAK, amber CHOP). Lines start when the level became usable (data time + delay).")
drawPct   = input.float(3.0, "Only levels within (% of price)", minval = 0.2, step = 0.5, group = grpV)
showEnded = input.bool(false, "Also draw levels that ended earlier", group = grpV)
lvZoneT   = input.int(85, "Level zone transparency", minval = 0, maxval = 100, group = grpV)
showPos   = input.bool(true, "Position boxes (green to target, red to stop)", group = grpV, tooltip = "Like TradingView's long/short position tool: drawn from the entry until the trade closes, with an arrow at the entry and the result at the exit.")
showAll   = input.bool(true, "Show every setup", group = grpV, tooltip = "Marks every zone where the rules trigger, including setups the strategy skips because it is already in a trade or hit the daily limit. Each gets its own alert. The backtest still counts only the trades taken.")
posT      = input.int(82, "Position box transparency", minval = 0, maxval = 100, group = grpV)
cLong     = input.color(#16a34a, "Long / target color", group = grpV)
cShort    = input.color(#dc2626, "Short / stop color", group = grpV)
showLv    = input.bool(true, "Gamma flip, walls and trade target/stop", group = grpV)
showBg    = input.bool(true, "Tint the regime", group = grpV)
showTable = input.bool(true, "Results table", group = grpV)
tblPosIn  = input.string("Top right", "Table position", options = ["Top right", "Top left", "Bottom right", "Bottom left"], group = grpV)

string TZ = "America/New_York"

// ---------------- Pasted levels ----------------
// One array entry per level. lvC = category:
//   1 gamma flip, 2 0DTE flip, 3 call wall, 4 put wall, 5 other GEX level,
//   6 projected HOD, 7 projected LOD, 8 Monte Carlo high, 9 Monte Carlo low,
//   10 stack zone, 11 biggest GEX / top + 0DTE strike (pin magnets),
//   12 0DTE call wall, 13 0DTE put wall (used as the walls when no plain wall is pasted), 0 other
var float[]  lvP  = array.new<float>()
var float[]  lvLo = array.new<float>()
var float[]  lvHi = array.new<float>()
var float[]  lvS  = array.new<float>()
var float[]  lvE  = array.new<float>()
var string[] lvR  = array.new<string>()
var int[]    lvC  = array.new<int>()

f_fld(string[] a, int i) =>
    i < array.size(a) ? str.trim(array.get(a, i)) : ""

f_num(string[] a, int i) =>
    v = str.tonumber(f_fld(a, i))
    na(v) ? 0.0 : v

f_cat(string nm, int src) =>
    n = str.lower(nm)
    int c = 0
    if str.contains(n, "stacked areas")
        c := 10
    else if str.contains(n, "projected hod")
        c := 6
    else if str.contains(n, "projected lod")
        c := 7
    else if str.contains(n, "monte carlo high")
        c := 8
    else if str.contains(n, "monte carlo low")
        c := 9
    else if src == 0
        if str.contains(n, "flip")
            c := str.contains(n, "0dte") ? 2 : 1
        else if str.contains(n, "call wall") and not str.contains(n, "zone")
            c := str.contains(n, "0dte") ? 12 : 3
        else if str.contains(n, "put wall") and not str.contains(n, "zone")
            c := str.contains(n, "0dte") ? 13 : 4
        else if str.contains(n, "biggest gex") or str.contains(n, "top + 0dte")
            c := 11
        else
            c := 5
    c

// Reads one pasted text (src 0 = GEX, 1 = Levels). Returns the day it is from.
f_parse(string txt, int src) =>
    string[] kn = array.new<string>()
    string day = ""
    for row in str.split(txt, "\n")
        a = str.split(str.trim(row), "|")
        tag = f_fld(a, 0)
        if tag == "Q" and array.size(a) >= 8
            day := f_fld(a, 4)
        else if tag == "K" and array.size(a) >= 8
            kn.push(f_fld(a, 1))
        else if tag == "L" and array.size(a) >= 10
            p = f_num(a, 1)
            g = int(f_num(a, 4))
            if p > 0 and g >= 0 and g < kn.size()
                lvP.push(p)
                lvLo.push(f_num(a, 2))
                lvHi.push(f_num(a, 3))
                lvS.push(f_num(a, 5))
                lvE.push(f_num(a, 6))
                lvR.push(f_fld(a, 7))
                lvC.push(f_cat(kn.get(g), src))
    day

var string pDay   = ""
var bool   parsed = false
if not parsed
    d1 = f_parse(gexTxt, 0)
    d2 = f_parse(lvTxt, 1)
    pDay   := d1 != "" ? d1 : d2
    parsed := true

// A level is usable once its data time + delay has passed, and stays usable until the data that
// replaced it has also arrived (its end time + the same delay).
f_active(int i) =>
    s = lvS.get(i)
    e = lvE.get(i)
    (s <= 0 or s + delayMin * 60000 <= time_close) and (e <= 0 or e + delayMin * 60000 > time)

f_px(int i) =>
    lvP.get(i) + offsetPts

f_inMode(int i, int mode) =>
    c = lvC.get(i)
    mode == 0 ? (c == 1 or c == 3 or c == 4 or c == 5 or c == 11 or c == 12 or c == 13) : mode == 1 ? c == 6 : mode == 2 ? c == 7 : mode == 3 ? (c == 8 or c == 9) : mode == 4 ? c == 10 : mode == 5 ? c == 11 : false

// Nearest usable level of a group in one direction (dir 1 = above ref, -1 = below),
// farther than minDist. Groups: 0 GEX map (flip, walls, GEX strikes), 1 projected HOD,
// 2 projected LOD, 3 Monte Carlo, 4 stack zones, 5 pin magnets. Returns index or -1.
f_find(int mode, float ref, int dir, float minDist) =>
    int best = -1
    float bd = 1e12
    n = lvP.size()
    if n > 0
        for i = 0 to n - 1
            if f_inMode(i, mode) and f_active(i)
                d = (f_px(i) - ref) * dir
                if d > minDist and d < bd
                    bd := d
                    best := i
    best

// Usable level of one category nearest to price (na if none)
f_catPx(int c) =>
    float best = na
    float bd = 1e12
    n = lvP.size()
    if n > 0
        for i = 0 to n - 1
            if lvC.get(i) == c and f_active(i)
                d = math.abs(f_px(i) - close)
                if d < bd
                    bd := d
                    best := f_px(i)
    best

// ---------------- Per-bar context ----------------
float atr     = ta.atr(atrLen)
float tol     = touchIn > 0 ? touchIn : 0.25 * atr
string barDay = str.format_time(time, "yyyy-MM-dd", TZ)
bool newDay   = barDay != barDay[1]
bool dayOk    = lvP.size() > 0 and (not onlyDay or pDay == "" or barDay == pDay)
bool inSess   = not na(time(timeframe.period, sessStr, TZ))
bool inPin    = not na(time(timeframe.period, pinSess, TZ))
bool inFlat   = not na(time(timeframe.period, flatSess, TZ))
int holdBars  = math.max(1, int(math.round(holdMin * 60.0 / timeframe.in_seconds())))
float prevC   = close[1]
float prevO   = open[1]

float flip  = na
float callW = na
float putW  = na
if dayOk
    flip  := f_catPx(1)
    if na(flip)
        flip := f_catPx(2)
    callW := f_catPx(3)
    if na(callW)
        callW := f_catPx(12)
    putW  := f_catPx(4)
    if na(putW)
        putW := f_catPx(13)

// ---------------- Gamma regime with a hold time ----------------
var int regime = 0
var int upCnt  = 0
var int dnCnt  = 0
bool flipped = false
if newDay
    regime := 0
    upCnt  := 0
    dnCnt  := 0
if dayOk and not na(flip)
    upCnt := close > flip ? upCnt + 1 : 0
    dnCnt := close < flip ? dnCnt + 1 : 0
    if regime == 0
        regime := close > flip ? 1 : -1
    else if upCnt >= holdBars and regime != 1
        regime  := 1
        flipped := true
    else if dnCnt >= holdBars and regime != -1
        regime  := -1
        flipped := true

// ---------------- Day state ----------------
var int   tradesToday = 0
var int   lastEntry   = -100000
var bool  hodDone     = false
var bool  lodDone     = false
var float rtLvl       = na
var int   rtDir       = 0
var int   rtBar       = 0
var float posTgt      = na
var float posStp      = na
var string posName    = ""
if newDay
    tradesToday := 0
    hodDone     := false
    lodDone     := false
    rtLvl       := na
    rtDir       := 0

// Target: the nearest GEX level at least minRR x risk away, else the flip
// (when it lies that far in the trade's direction), else a fixed R.
f_target(int dir, float entry, float risk, float flipLv) =>
    ti = f_find(0, entry, dir, risk * minRR)
    float t = ti >= 0 ? f_px(ti) : na
    if na(t) and not na(flipLv) and (flipLv - entry) * dir >= risk * minRR
        t := flipLv
    if na(t) and fallbackR > 0
        t := entry + dir * risk * fallbackR
    t

// ---------------- Signals ----------------
int    sigDir  = 0
string sigName = ""
float  sigStop = na
float  sigTgt  = na
bool   canTrade = dayOk and inSess and strategy.position_size == 0 and tradesToday < maxTrades and bar_index - lastEntry >= coolBars and not na(flip) and not na(atr) and regime != 0
// Setups are found whenever the rules can apply; canTrade only decides whether one is taken
bool   canSee   = dayOk and inSess and not na(flip) and not na(atr) and regime != 0

// S1 positive gamma: fade a touch-and-reject at the nearest GEX level
if canSee and useFade and regime == 1 and sigDir == 0
    iS = f_find(0, close, 1, 0.0)
    if iS >= 0
        L = f_px(iS)
        r = lvR.get(iS)
        if high >= L - tol and close < open and r != "B" and r != "C"
            stp = math.max(high, L) + stopATR * atr
            tgt = f_target(-1, close, stp - close, flip)
            if not na(tgt)
                sigDir  := -1
                sigName := "S1 Fade S"
                sigStop := stp
                sigTgt  := tgt
    if sigDir == 0
        iL = f_find(0, close, -1, 0.0)
        if iL >= 0
            L = f_px(iL)
            r = lvR.get(iL)
            if low <= L + tol and close > open and r != "B" and r != "C"
                stp = math.min(low, L) - stopATR * atr
                tgt = f_target(1, close, close - stp, flip)
                if not na(tgt)
                    sigDir  := 1
                    sigName := "S1 Fade L"
                    sigStop := stp
                    sigTgt  := tgt

// S1 negative gamma: trade the break of a GEX level (close through or retest)
if canSee and useBreak and regime == -1 and sigDir == 0
    // a fresh close through a level
    iA = f_find(0, close, 1, 0.0)
    bool brokeDn = false
    float lvDn = na
    if iA >= 0
        L = f_px(iA)
        if prevC >= L and close < L and close < open and lvR.get(iA) != "H"
            brokeDn := true
            lvDn := L
    bool brokeUp = false
    float lvUp = na
    if breakLong
        iB = f_find(0, close, -1, 0.0)
        if iB >= 0
            L = f_px(iB)
            if prevC <= L and close > L and close > open and lvR.get(iB) != "H"
                brokeUp := true
                lvUp := L
    if breakMode == "Close through"
        if brokeDn
            stp = lvDn + stopATR * atr
            tgt = f_target(-1, close, stp - close, na)
            if not na(tgt)
                sigDir  := -1
                sigName := "S1 Break S"
                sigStop := stp
                sigTgt  := tgt
        else if brokeUp
            stp = lvUp - stopATR * atr
            tgt = f_target(1, close, close - stp, na)
            if not na(tgt)
                sigDir  := 1
                sigName := "S1 Break L"
                sigStop := stp
                sigTgt  := tgt
    else
        // Retest: remember the break, enter when price comes back and rejects
        if brokeDn
            rtLvl := lvDn
            rtDir := -1
            rtBar := bar_index
        else if brokeUp
            rtLvl := lvUp
            rtDir := 1
            rtBar := bar_index
        else if not na(rtLvl) and bar_index - rtBar <= retestMax
            if rtDir == -1 and high >= rtLvl - tol and close < rtLvl and close < open
                stp = math.max(high, rtLvl) + stopATR * atr
                tgt = f_target(-1, close, stp - close, na)
                if not na(tgt)
                    sigDir  := -1
                    sigName := "S1 Break S"
                    sigStop := stp
                    sigTgt  := tgt
                rtLvl := na
            else if rtDir == 1 and low <= rtLvl + tol and close > rtLvl and close > open
                stp = math.min(low, rtLvl) - stopATR * atr
                tgt = f_target(1, close, close - stp, na)
                if not na(tgt)
                    sigDir  := 1
                    sigName := "S1 Break L"
                    sigStop := stp
                    sigTgt  := tgt
                rtLvl := na
        else if not na(rtLvl) and bar_index - rtBar > retestMax
            rtLvl := na

// S2: fade the projected HOD / LOD (once per side per day)
if canSee and useHL and sigDir == 0
    iH = f_find(1, close, 1, 0.0)
    if iH >= 0 and not hodDone and (hiInPct == 0 or hiInPct >= 60)
        L = f_px(iH)
        wallHere = not na(callW) and math.abs(callW - L) <= 2 * tol
        if high >= L - tol and close < open and (regime == 1 or wallHere)
            iN = f_find(1, L, 1, tol)
            stp = math.max(iN >= 0 ? f_px(iN) + tol : L + stopATR * atr, high + tol)
            risk = stp - close
            iT = f_find(3, close, -1, risk * minRR)
            tgt = iT >= 0 ? f_px(iT) : f_target(-1, close, risk, flip)
            if not na(tgt)
                sigDir  := -1
                sigName := "S2 HOD fade"
                sigStop := stp
                sigTgt  := tgt
    if sigDir == 0
        iLo = f_find(2, close, -1, 0.0)
        if iLo >= 0 and not lodDone and (loInPct == 0 or loInPct >= 60)
            L = f_px(iLo)
            wallHere = not na(putW) and math.abs(putW - L) <= 2 * tol
            if low <= L + tol and close > open and (regime == 1 or wallHere)
                iN = f_find(2, L, -1, tol)
                stp = math.min(iN >= 0 ? f_px(iN) - tol : L - stopATR * atr, low - tol)
                risk = close - stp
                iT = f_find(3, close, 1, risk * minRR)
                tgt = iT >= 0 ? f_px(iT) : f_target(1, close, risk, flip)
                if not na(tgt)
                    sigDir  := 1
                    sigName := "S2 LOD fade"
                    sigStop := stp
                    sigTgt  := tgt

// S3: stack zones. HOLD = fade at the zone edge, BREAK = trade the close through, CHOP = skip
if canSee and useStack and sigDir == 0
    iU = f_find(4, close, 1, 0.0)
    if iU >= 0
        zr = lvR.get(iU)
        zlo = lvLo.get(iU) > 0 ? lvLo.get(iU) + offsetPts : f_px(iU) - tol
        zhi = lvHi.get(iU) > 0 ? lvHi.get(iU) + offsetPts : f_px(iU) + tol
        if zr == "H" and high >= zlo - tol and close < zlo and close < open
            stp = zhi + stopATR * atr
            tgt = f_target(-1, close, stp - close, flip)
            if not na(tgt)
                sigDir  := -1
                sigName := "S3 Stack hold S"
                sigStop := stp
                sigTgt  := tgt
        else if zr == "B" and prevC >= zlo and close < zlo and close < open
            stp = zhi + stopATR * atr
            tgt = f_target(-1, close, stp - close, na)
            if not na(tgt)
                sigDir  := -1
                sigName := "S3 Stack break S"
                sigStop := stp
                sigTgt  := tgt
    if sigDir == 0
        iD = f_find(4, close, -1, 0.0)
        if iD >= 0
            zr = lvR.get(iD)
            zlo = lvLo.get(iD) > 0 ? lvLo.get(iD) + offsetPts : f_px(iD) - tol
            zhi = lvHi.get(iD) > 0 ? lvHi.get(iD) + offsetPts : f_px(iD) + tol
            if zr == "H" and low <= zhi + tol and close > zhi and close > open
                stp = zlo - stopATR * atr
                tgt = f_target(1, close, close - stp, flip)
                if not na(tgt)
                    sigDir  := 1
                    sigName := "S3 Stack hold L"
                    sigStop := stp
                    sigTgt  := tgt
            else if zr == "B" and prevC <= zhi and close > zhi and close > open
                stp = zlo - stopATR * atr
                tgt = f_target(1, close, close - stp, na)
                if not na(tgt)
                    sigDir  := 1
                    sigName := "S3 Stack break L"
                    sigStop := stp
                    sigTgt  := tgt

// S4: afternoon pin toward the biggest 0DTE gamma strike (positive gamma only)
if canSee and usePin and inPin and regime == 1 and sigDir == 0
    strike = f_catPx(11)
    if not na(strike)
        dist = strike - close
        if math.abs(dist) >= pinMinATR * atr
            dir = dist > 0 ? 1 : -1
            // pullback then resume: last bar against the strike, this bar toward it
            pull = dir == 1 ? (prevC < prevO and close > open) : (prevC > prevO and close < open)
            if pull
                stp = close - dir * stopATR * atr * 2
                risk = math.abs(close - stp)
                if math.abs(dist) >= risk
                    sigDir  := dir
                    sigName := dir == 1 ? "S4 Pin L" : "S4 Pin S"
                    sigStop := stp
                    sigTgt  := strike

// ---------------- Orders ----------------
fmt(float p) =>
    str.tostring(p, format.mintick)

bool takeIt = sigDir != 0 and canTrade

// Position box state (one trade at a time)
var box   pfBox  = na
var box   lsBox  = na
var bool  boxOn  = false
var bool  boxFix = false
var int   boxDir = 0

if takeIt
    strategy.entry(sigName, sigDir == 1 ? strategy.long : strategy.short, comment = sigName)
    strategy.exit(sigName + " exit", from_entry = sigName, stop = sigStop, limit = sigTgt, comment_profit = "Target", comment_loss = "Stop")
    posTgt  := sigTgt
    posStp  := sigStop
    posName := sigName
    tradesToday += 1
    lastEntry := bar_index
    if sigName == "S2 HOD fade"
        hodDone := true
    if sigName == "S2 LOD fade"
        lodDone := true
    alert("Q DATA ENTRY " + sigName + (sigDir == 1 ? " LONG " : " SHORT ") + syminfo.ticker + " near " + fmt(close) + " | target " + fmt(sigTgt) + " | stop " + fmt(sigStop), alert.freq_once_per_bar_close)
    if showPos
        // green = entry to target, red = entry to stop; the entry edge snaps to the fill next bar
        pfBox := box.new(bar_index, math.max(close, sigTgt), bar_index + 1, math.min(close, sigTgt), border_color = color.new(cLong, 40), bgcolor = color.new(cLong, posT), text = "Target " + fmt(sigTgt), text_color = cLong, text_size = size.tiny, text_halign = text.align_right, text_valign = sigDir == 1 ? text.align_top : text.align_bottom)
        lsBox := box.new(bar_index, math.max(close, sigStop), bar_index + 1, math.min(close, sigStop), border_color = color.new(cShort, 40), bgcolor = color.new(cShort, posT), text = "Stop " + fmt(sigStop), text_color = cShort, text_size = size.tiny, text_halign = text.align_right, text_valign = sigDir == 1 ? text.align_bottom : text.align_top)
        boxOn  := true
        boxFix := false
        boxDir := sigDir
        label.new(bar_index, sigDir == 1 ? low : high, (sigDir == 1 ? "LONG  " : "SHORT  ") + sigName, style = sigDir == 1 ? label.style_label_up : label.style_label_down, color = sigDir == 1 ? cLong : cShort, textcolor = color.white, size = size.small)

// Every setup, including ones skipped (already in a trade, daily limit, cooldown)
var int    lastSetupBar  = -100000
var string lastSetupName = ""
if showAll and sigDir != 0 and not takeIt and not (sigName == lastSetupName and bar_index - lastSetupBar <= coolBars)
    string why = strategy.position_size != 0 ? "in a trade" : tradesToday >= maxTrades ? "daily limit" : "cooldown"
    label.new(bar_index, sigDir == 1 ? low : high, sigName + "\nT " + fmt(sigTgt) + "  S " + fmt(sigStop) + "\nskipped: " + why, style = sigDir == 1 ? label.style_label_up : label.style_label_down, color = color.new(sigDir == 1 ? cLong : cShort, 55), textcolor = color.white, size = size.tiny)
    alert("Q DATA SETUP " + sigName + (sigDir == 1 ? " LONG " : " SHORT ") + syminfo.ticker + " near " + fmt(close) + " | target " + fmt(sigTgt) + " | stop " + fmt(sigStop) + " | not taken: " + why, alert.freq_once_per_bar_close)
    lastSetupBar  := bar_index
    lastSetupName := sigName

// Keep the position boxes in step with the open trade
if boxOn
    if strategy.position_size != 0
        if not boxFix
            ep = strategy.position_avg_price
            box.set_top(pfBox, math.max(ep, posTgt))
            box.set_bottom(pfBox, math.min(ep, posTgt))
            box.set_top(lsBox, math.max(ep, posStp))
            box.set_bottom(lsBox, math.min(ep, posStp))
            boxFix := true
        box.set_right(pfBox, bar_index)
        box.set_right(lsBox, bar_index)
    else if boxFix
        box.set_right(pfBox, bar_index)
        box.set_right(lsBox, bar_index)
        boxOn := false

// Regime switch, pin window end and session end close the trade
if strategy.position_size != 0
    if flipped and flipClose
        strategy.close_all(comment = "Regime switch")
    else if str.startswith(posName, "S4") and not inPin
        strategy.close_all(comment = "Pin window over")
    else if not inFlat
        strategy.close_all(comment = "Session end")

// Exit alerts: one per closed trade, saying target, stop or why it closed
var int lastClosed = 0
if strategy.closedtrades > lastClosed
    k = strategy.closedtrades - 1
    why = strategy.closedtrades.exit_comment(k)
    alert("Q DATA EXIT " + strategy.closedtrades.entry_id(k) + " - " + (why == "" ? "closed" : why) + " at " + fmt(strategy.closedtrades.exit_price(k)) + " | P/L " + str.tostring(strategy.closedtrades.profit(k), "#.##"), alert.freq_once_per_bar_close)
    if showPos
        pl = strategy.closedtrades.profit(k)
        isLong = strategy.closedtrades.size(k) > 0
        label.new(bar_index, isLong ? high : low, (why == "" ? "Exit" : why) + "  " + (pl >= 0 ? "+" : "") + str.tostring(pl, "#,##0"), style = isLong ? label.style_label_down : label.style_label_up, color = color.new(pl >= 0 ? cLong : cShort, 15), textcolor = color.white, size = size.tiny)
    lastClosed := strategy.closedtrades
if strategy.position_size == 0
    posTgt := na
    posStp := na

// ---------------- Display ----------------
color cFlip = #d97706
color cCall = #059669
color cPut  = #dc2626
plot(showLv and dayOk ? flip : na, "Gamma flip", cFlip, 2, plot.style_linebr)
plot(showLv and dayOk ? callW : na, "Call wall", cCall, 2, plot.style_linebr)
plot(showLv and dayOk ? putW : na, "Put wall", cPut, 2, plot.style_linebr)
plot(showLv and strategy.position_size != 0 ? posTgt : na, "Trade target", #2563eb, 1, plot.style_linebr)
plot(showLv and strategy.position_size != 0 ? posStp : na, "Trade stop", #64748b, 1, plot.style_linebr)
bgcolor(showBg and dayOk and regime == 1 ? color.new(cCall, 95) : showBg and dayOk and regime == -1 ? color.new(cPut, 95) : na, title = "Regime tint")

// ---------------- The levels and zones the strategy uses ----------------
var int firstT = time
var line[]  drL = array.new<line>()
var box[]   drB = array.new<box>()
var label[] drT = array.new<label>()

f_lvName(int c, string r) =>
    c == 1 ? "Gamma flip" : c == 2 ? "0DTE flip" : c == 3 ? "Call wall" : c == 4 ? "Put wall" : c == 12 ? "0DTE call wall" : c == 13 ? "0DTE put wall" : c == 5 ? "GEX" : c == 11 ? "Big GEX" : c == 6 ? "Proj HOD" : c == 7 ? "Proj LOD" : c == 8 ? "MC high" : c == 9 ? "MC low" : c == 10 ? (r == "H" ? "Stack HOLD" : r == "B" ? "Stack BREAK" : "Stack CHOP") : ""

f_lvCol(int c, string r) =>
    c == 1 ? #d97706 : c == 2 ? #b45309 : (c == 3 or c == 12) ? #059669 : (c == 4 or c == 13) ? #dc2626 : c == 11 ? #1d4ed8 : c == 6 ? #0e7490 : c == 7 ? #be123c : (c == 8 or c == 9) ? #7c3aed : c == 10 ? (r == "H" ? #16a34a : r == "B" ? #dc2626 : #ca8a04) : #64748b

if barstate.islast
    for x in drL
        line.delete(x)
    for x in drB
        box.delete(x)
    for x in drT
        label.delete(x)
    drL.clear()
    drB.clear()
    drT.clear()
    n = lvP.size()
    if showLevels and n > 0
        int ext = time + int(timeframe.in_seconds() * 1000 * 8)
        for i = 0 to n - 1
            c = lvC.get(i)
            e = lvE.get(i)
            p = f_px(i)
            if c != 0 and (e <= 0 or showEnded) and math.abs(p - close) <= close * drawPct / 100
                r = lvR.get(i)
                s0 = lvS.get(i)
                int x1 = s0 > 0 ? int(math.min(math.max(s0 + delayMin * 60000, firstT), time)) : firstT
                int x2 = e > 0 ? int(e + delayMin * 60000) : ext
                col = f_lvCol(c, r)
                lo = lvLo.get(i)
                hi = lvHi.get(i)
                if lo > 0 and hi > lo
                    drB.push(box.new(x1, hi + offsetPts, x2, lo + offsetPts, xloc = xloc.bar_time, border_color = color.new(col, 45), bgcolor = color.new(col, lvZoneT)))
                else
                    st = (c == 1 or c == 3 or c == 4) ? line.style_solid : (c >= 6 and c <= 9) ? line.style_dotted : line.style_dashed
                    drL.push(line.new(x1, p, x2, p, xloc = xloc.bar_time, color = col, width = (c == 1 or c == 3 or c == 4) ? 2 : 1, style = st))
                drT.push(label.new(x2, p, f_lvName(c, r) + "  " + fmt(p), xloc = xloc.bar_time, style = label.style_label_left, color = color.new(color.white, 100), textcolor = col, size = size.tiny))

// ---------------- Results table ----------------
tblPos = tblPosIn == "Top left" ? position.top_left : tblPosIn == "Bottom right" ? position.bottom_right : tblPosIn == "Bottom left" ? position.bottom_left : position.top_right
var table tb = table.new(tblPos, 3, 12, bgcolor = color.white, border_color = #e2e8f0, border_width = 1, frame_color = #94a3b8, frame_width = 1)

f_cell(int c, int r, string t, color tc, color bg) =>
    table.cell(tb, c, r, t, text_color = tc, bgcolor = bg, text_size = size.small, text_halign = text.align_left)

if barstate.islast and showTable
    string[] names = array.from("S1 Fade", "S1 Break", "S2 HOD/LOD", "S3 Stack", "S4 Pin")
    string[] pref  = array.from("S1 Fade", "S1 Break", "S2", "S3", "S4")
    int[]   wins = array.new<int>(5, 0)
    int[]   loss = array.new<int>(5, 0)
    float[] pnl  = array.new<float>(5, 0.0)
    nC = strategy.closedtrades
    if nC > 0
        for i = 0 to nC - 1
            id = strategy.closedtrades.entry_id(i)
            pr = strategy.closedtrades.profit(i)
            for j = 0 to 4
                if str.startswith(id, pref.get(j))
                    if pr > 0
                        wins.set(j, wins.get(j) + 1)
                    else
                        loss.set(j, loss.get(j) + 1)
                    pnl.set(j, pnl.get(j) + pr)
    color hd = #0f172a
    color qt = #475569
    f_cell(0, 0, "Q DATA Strategy", color.white, #334155)
    f_cell(1, 0, lvP.size() > 0 ? pDay : "Paste levels", color.white, #334155)
    f_cell(2, 0, "", color.white, #334155)
    f_cell(0, 1, "Levels loaded", qt, color.white)
    f_cell(1, 1, str.tostring(lvP.size()), hd, color.white)
    f_cell(2, 1, "", hd, color.white)
    f_cell(0, 2, "Regime", qt, color.white)
    f_cell(1, 2, regime == 1 ? "Positive gamma: fade" : regime == -1 ? "Negative gamma: breaks" : "Waiting", color.white, regime == 1 ? cCall : regime == -1 ? cPut : #94a3b8)
    f_cell(2, 2, "", hd, color.white)
    f_cell(0, 3, "Gamma flip", qt, color.white)
    f_cell(1, 3, na(flip) ? "none pasted" : fmt(flip), hd, color.white)
    f_cell(2, 3, "", hd, color.white)
    f_cell(0, 4, "Walls (call / put)", qt, color.white)
    f_cell(1, 4, (na(callW) ? "-" : fmt(callW)) + " / " + (na(putW) ? "-" : fmt(putW)), hd, color.white)
    f_cell(2, 4, "", hd, color.white)
    f_cell(0, 5, "Strategy", qt, #f1f5f9)
    f_cell(1, 5, "Wins - losses", qt, #f1f5f9)
    f_cell(2, 5, "P/L", qt, #f1f5f9)
    for j = 0 to 4
        f_cell(0, 6 + j, names.get(j), hd, color.white)
        f_cell(1, 6 + j, str.tostring(wins.get(j)) + " - " + str.tostring(loss.get(j)), hd, color.white)
        f_cell(2, 6 + j, str.tostring(pnl.get(j), "#,##0"), pnl.get(j) > 0 ? cCall : pnl.get(j) < 0 ? cPut : qt, color.white)
    f_cell(0, 11, "Data delay used", qt, color.white)
    f_cell(1, 11, str.tostring(delayMin) + " min", hd, color.white)
    f_cell(2, 11, "", hd, color.white)
'''
