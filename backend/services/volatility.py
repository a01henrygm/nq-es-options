"""The volatility backdrop: Cboe's VIX family (free, delayed) turned into a plain-English read for NQ and ES.

Sources (checked against the live files, Oct 2026):
  quotes   https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json   (one small file per index)
  history  https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv  (one row per day)

Quirks handled here:
  * After the close Cboe already writes today's close into "prev_day_close", so the day's change comes from "price_change".
  * VXN's file reports price_change 0; its change comes from the daily history instead.
  * VIX's own file carries "iv30" = the 30-day IV of VIX options (the same idea as VVIX).

Pure functions, no network access.
"""
from __future__ import annotations
import csv
import io
import math
from datetime import date, datetime

from ..timeutil import parse_et, to_et

# key, label, horizon in calendar days (None = not a point on the curve), what it measures
INDICES = [
    ("_VIX1D", "VIX1D", 1, "S&P 500 volatility expected for today (or the next session)"),
    ("_VIX9D", "VIX9D", 9, "S&P 500 volatility over the next 9 days"),
    ("_VIX", "VIX", 30, "S&P 500 volatility over the next 30 days, the headline fear gauge"),
    ("_VIX3M", "VIX3M", 93, "S&P 500 volatility over the next 3 months"),
    ("_VIX6M", "VIX6M", 183, "S&P 500 volatility over the next 6 months"),
    ("_VXN", "VXN", None, "Nasdaq-100 volatility over the next 30 days, the NQ version of VIX"),
    ("_VVIX", "VVIX", None, "Volatility of VIX itself: how violently VIX is expected to move"),
]
LABEL = {k: n for k, n, _, _ in INDICES}
HISTORY_NAMES = ("VIX", "VXN", "VVIX", "VIX3M", "VIX9D")      # Cboe publishes a daily history file for each of these
CURVE = [(k, n, d) for k, n, d, _ in INDICES if d]
TRADING_DAYS = 252


def _num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def parse_quote(j: dict) -> dict | None:
    """One Cboe quote file -> {value, change, prev, open, high, low, time}. None when there is no usable price."""
    d = (j or {}).get("data") or {}
    v = _num(d.get("current_price")) or _num(d.get("close"))
    if not v or v <= 0:
        return None
    chg, pdc = _num(d.get("price_change")), _num(d.get("prev_day_close"))
    prev = None
    if pdc and abs(pdc - v) > 1e-9:
        prev = pdc                                     # during the session prev_day_close is still yesterday's close
    elif chg:
        prev = v - chg                                 # after the close prev_day_close already equals today's close
    t = parse_et(d.get("last_trade_time"))
    return {"value": v, "prev": prev, "change": (v - prev) if prev else None, "open": _num(d.get("open")),
            "high": _num(d.get("high")), "low": _num(d.get("low")), "time": t, "iv30": _num(d.get("iv30")) or None}


def parse_history_csv(text: str) -> list:
    """Cboe daily history CSV -> [(date, close)], oldest first. Tolerant of the column layout: it looks for a DATE column and a
    CLOSE column, and falls back to the last numeric column (VVIX's file has only DATE and the value)."""
    rows = list(csv.reader(io.StringIO(text or "")))
    if len(rows) < 2:
        return []
    head = [h.strip().upper() for h in rows[0]]
    di = next((i for i, h in enumerate(head) if "DATE" in h), 0)
    ci = next((i for i, h in enumerate(head) if h == "CLOSE"), None)
    out = []
    for r in rows[1:]:
        if len(r) <= di:
            continue
        s = r[di].strip()
        dt = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
            try:
                dt = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                pass
        if dt is None:
            continue
        idx = ci if ci is not None and ci < len(r) else max((i for i in range(len(r)) if i != di and _num(r[i]) is not None), default=None)
        v = _num(r[idx]) if idx is not None else None
        if v and v > 0:
            out.append((dt, v))
    out.sort()
    return out


def percentile(values, x):
    """Share of past values below x (0..1)."""
    vals = [v for v in values if v is not None]
    if not vals or x is None:
        return None
    return sum(1 for v in vals if v < x) / len(vals)


def merge_today(hist: list, q: dict | None) -> list:
    """History plus today's live reading (replacing a same-day row), so percentiles and changes include today."""
    if not q:
        return hist
    d = to_et(q["time"]).date() if q.get("time") else None
    out = [(dd, v) for dd, v in hist if d is None or dd != d]
    if d:
        out.append((d, q["value"]))
    return out


def regime(r_3m, vix, vix9d_ratio, vvix):
    """Term-structure regime from VIX / VIX3M (the standard read), with stress flags. Returns (label, color_key, meaning)."""
    if r_3m is None:
        return "Unknown", "neutral", "VIX or VIX3M is missing, so the term structure cannot be read."
    if r_3m >= 1.10 and (vix or 0) >= 30:
        return ("Panic", "bad", "Short-dated fear is far above long-dated fear (deep backwardation) with VIX above 30. Moves are large and fast; "
                "levels break more often and liquidity is thin. Size down.")
    if r_3m >= 1.0:
        return ("Stressed", "bad", "The curve is inverted: traders pay more for protection now than later. Expect wider ranges, trend days and "
                "levels that break rather than hold.")
    if r_3m >= 0.95:
        return ("Tense", "warn", "The curve is nearly flat, which usually happens just before or after a shock. Ranges are wider than normal; "
                "be quicker to take profits.")
    if r_3m >= 0.85:
        return ("Normal", "neutral", "A normal upward-sloping curve. No special stress priced; levels behave as usual.")
    return ("Calm", "good", "A steep upward-sloping curve (strong contango): little near-term fear. Ranges tend to be small and dip-buying and "
            "fading the walls tend to work.")


def analyze(quotes: dict, histories: dict, ndx: float | None = None, spx: float | None = None, nq_ratio: float | None = None,
            es_ratio: float | None = None, now: datetime | None = None) -> dict:
    """quotes: {"_VIX": parse_quote(...)}; histories: {"VIX": [(date, close)]}. ndx/spx: index prices; *_ratio: futures/index."""
    q = {k: quotes.get(k) for k, *_ in INDICES}
    val = lambda k: (q.get(k) or {}).get("value")
    rows = []
    for k, n, days, meaning in INDICES:
        x = q.get(k)
        h = merge_today(histories.get(n, []), x) if x else histories.get(n, [])
        last_year = [v for _, v in h[-TRADING_DAYS:]]
        chg = x and x.get("change")
        if x and chg is None and len(h) >= 2:           # VXN: day change from the history
            chg = h[-1][1] - h[-2][1]
        day_moves = [b - a for (_, a), (_, b) in zip(h[-TRADING_DAYS - 1:-1], h[-TRADING_DAYS:])]
        sd = (sum(m * m for m in day_moves) / len(day_moves)) ** 0.5 if len(day_moves) > 20 else None
        rows.append({"key": k, "name": n, "days": days, "meaning": meaning, "value": x and x["value"], "change": chg,
                     "change_pct": (chg / (x["value"] - chg)) if x and chg is not None and x["value"] - chg else None,
                     "high": x and x.get("high"), "low": x and x.get("low"), "time": x and x.get("time") and x["time"].isoformat(),
                     "pct_1y": percentile(last_year[:-1], x["value"]) if x and len(last_year) > 20 else None,
                     "change_z": (chg / sd) if chg is not None and sd else None,
                     "history_days": len(h)})
    by = {r["key"]: r for r in rows}
    r3m = (val("_VIX") / val("_VIX3M")) if val("_VIX") and val("_VIX3M") else None
    r9d = (val("_VIX9D") / val("_VIX")) if val("_VIX9D") and val("_VIX") else None
    r1d = (val("_VIX1D") / val("_VIX")) if val("_VIX1D") and val("_VIX") else None
    vvix = val("_VVIX") or ((q.get("_VIX") or {}).get("iv30"))
    label, color, meaning = regime(r3m, val("_VIX"), r9d, vvix)

    flags = []
    if r9d is not None and r9d > 1.0:
        flags.append(("warn", f"Next-9-day fear is above 30-day fear (VIX9D/VIX {r9d:.2f}): the market expects trouble soon, often a scheduled event."))
    if r1d is not None and r1d > 1.15:
        flags.append(("warn", f"VIX1D is {r1d:.2f}x VIX: a big move is priced for today itself (an event day). Expect the range to be used."))
    elif r1d is not None and r1d < 0.6:
        flags.append(("good", f"VIX1D is only {r1d:.2f}x VIX: today is priced quiet. Ranges often stay inside the expected move and walls hold."))
    if vvix is not None and vvix >= 115:
        flags.append(("bad", f"VVIX {vvix:.0f}: VIX itself is expected to swing hard. Volatility spikes come fast from here."))
    elif vvix is not None and vvix <= 85:
        flags.append(("good", f"VVIX {vvix:.0f}: VIX is expected to stay settled."))
    vxn, vix = val("_VXN"), val("_VIX")
    spread = (vxn - vix) if vxn and vix else None
    if spread is not None:
        flags.append(("neutral", f"VXN is {spread:+.1f} points vs VIX: Nasdaq volatility runs {'above' if spread > 0 else 'below'} the S&P's, as it normally "
                      f"does ({'wider than usual' if spread > 9 else 'narrower than usual' if spread < 3 else 'a usual gap'})."))
    for r in rows:
        if r["change_z"] is not None and abs(r["change_z"]) >= 2.5 and r["name"] in ("VIX", "VXN"):
            flags.append(("bad" if r["change"] > 0 else "good", f"{r['name']} moved {r['change']:+.2f} today, a {abs(r['change_z']):.1f}-sigma day: "
                          f"{'fear jumped' if r['change'] > 0 else 'fear collapsed'}."))

    def move(index_px, vol, days, ratio):
        if not index_px or not vol:
            return None
        pts = index_px * vol / 100 * math.sqrt(days / TRADING_DAYS) if days else None   # the 'rule of 16'
        return {"index_points": pts, "futures_points": pts * ratio if pts and ratio else None}

    moves = {
        "nq_day": {**(move(ndx, vxn, 1, nq_ratio) or {}), "from": "VXN (30-day Nasdaq-100 vol) scaled to one day", "available": bool(ndx and vxn)},
        "es_day": {**(move(spx, val("_VIX1D") or vix, 1, es_ratio) or {}), "from": "VIX1D (today's S&P vol)" if val("_VIX1D") else "VIX scaled to one day",
                   "available": bool(spx and (val("_VIX1D") or vix))},
    }
    if moves["nq_day"]["available"] and val("_VIX1D") and vix:     # NQ today: VXN scaled by today's S&P event premium
        f = val("_VIX1D") / vix
        p = move(ndx, vxn * f, 1, nq_ratio)
        moves["nq_today"] = {**p, "from": "VXN adjusted by VIX1D/VIX (today's event premium)", "available": True}

    curve_today = [{"name": n, "days": d, "value": val(k)} for k, n, d in CURVE if val(k)]
    curve_prev = [{"name": n, "days": d, "value": (q.get(k) or {}).get("prev")} for k, n, d in CURVE if (q.get(k) or {}).get("prev")]
    shape = None
    if len(curve_today) >= 3:
        shape = "upward (contango)" if curve_today[-1]["value"] > curve_today[0]["value"] else "inverted (backwardation)"
    summary = [f"{label}: {meaning}"]
    if vxn:
        nm = moves.get("nq_today") or moves["nq_day"]
        if nm.get("futures_points"):
            summary.append(f"Options price a typical NQ day of about {nm['futures_points']:.0f} points (one standard deviation, {nm['from']}).")
        elif nm.get("index_points"):
            summary.append(f"Options price a typical NDX day of about {nm['index_points']:.0f} points (one standard deviation, {nm['from']}).")
    return {"available": any(r["value"] for r in rows), "rows": rows, "regime": {"label": label, "color": color, "meaning": meaning},
            "ratios": {"vix_vix3m": r3m, "vix9d_vix": r9d, "vix1d_vix": r1d, "vxn_vix_spread": spread, "vvix": vvix},
            "curve": {"today": curve_today, "prev": curve_prev, "shape": shape}, "moves": moves,
            "flags": [{"tone": t, "text": s} for t, s in flags], "summary": summary,
            "rules": "Regime from VIX/VIX3M: under 0.85 Calm, 0.85-0.95 Normal, 0.95-1.00 Tense, 1.00 and above Stressed, 1.10+ with VIX over 30 Panic. "
                     "Percentiles compare today with the last 252 trading days of Cboe's daily history. A one-day move is index x vol / 100 / sqrt(252) (the 'rule of 16'), "
                     "one standard deviation; about two days in three stay inside it."}
