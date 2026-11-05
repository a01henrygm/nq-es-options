"""IV walls (1.35.0): three kinds of level read from implied volatility instead of open interest or gamma.

  Vega walls     strikes holding the most vega exposure (open interest x vega). Where a change in volatility moves the most option
                 value, so where dealer hedging reacts most when IV jumps or gets crushed. Built into zones like the open-interest zones.
  IV spikes      strikes where implied volatility sits clearly ABOVE the strikes next to it on the same expiry: a bump in the smile where
                 traders are paying up for that one price. Only counted where real contracts trade (open interest or volume).
  Skew flip      the bottom of the smile. Below it IV rises as strikes go down (puts carry the skew); above it IV rises as strikes go up
                 (calls carry it). One level per expiry, like a gamma flip but for volatility.

Greeks are Black-Scholes from each contract's own implied volatility (r = 0, q = 0, time floored at 30 minutes), the same model as
charm and vanna. None of this is backtested: these are positions and prices, not a forecast.
"""
from __future__ import annotations
import math
from collections import defaultdict
from statistics import median

from . import analytics as an

MIN_T = 0.5 / (365.25 * 24)
VEGA_RULE = ("Vega exposure at a strike = Black-Scholes vega (per 1 volatility point, from each contract's own IV, r = 0, q = 0) x open interest x "
             "multiplier, summed over the expirations shown, calls and puts kept apart. Strikes are merged into zones like the open-interest zones. "
             "It is where a move in implied volatility changes the most option value, so where hedging reacts most when IV jumps or gets crushed.")
SPIKE_RULE = ("IV spike: on one expiry's clean smile (out-of-the-money quotes only, bad quotes dropped, no smoothing), a strike whose IV sits at least "
              "0.6 volatility points and 3 robust standard deviations above the straight line through the two strikes on each side of it. "
              "Only strikes within 6% of price with at least 100 contracts of open interest or volume count, so a single bad quote is not a wall.")
SKEW_RULE = ("Skew flip: the lowest point of one expiry's clean, lightly smoothed smile within 8% of price, refined between strikes with a parabola. "
             "Below it IV rises as strikes go down (puts carry the skew); above it IV rises as strikes go up (calls carry it). Only kept when IV "
             "really rises on both sides of it (by at least 0.3 volatility points).")


def bs_vega_point(S, K, T, iv):
    """Black-Scholes vega for a 1 volatility-point change, per share (same for calls and puts when r = q = 0)."""
    T = max(T, MIN_T)
    if min(S, K, iv) <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    return S * an._phi(d1) * math.sqrt(T) * 0.01


def vega_by_strike(contracts, spot, now):
    """Rows of strike / call / put vega exposure (dollars per 1 volatility point) and how many contracts went in."""
    by = defaultdict(lambda: {"call": 0.0, "put": 0.0})
    n = 0
    for c in contracts:
        iv = an._iv_dec(c.iv)
        T = an.year_fraction(c.expiry, now)
        if not (c.oi and iv and 0.01 <= iv <= 3 and T > 0):
            continue
        n += 1
        by[c.strike]["call" if c.right == "C" else "put"] += bs_vega_point(spot, c.strike, T, iv) * c.oi * c.multiplier
    return [{"strike": k, **v} for k, v in sorted(by.items())], n


def vega_walls(contracts, spot, now, top=2):
    """Call-side and put-side vega zones, biggest first (up to `top` per side)."""
    rows, n = vega_by_strike(contracts, spot, now)
    if not rows:
        return [], 0
    grid = sorted({c.strike for c in contracts})
    zs = an.series_zones(rows, grid, spot)
    out = []
    for side in ("call", "put"):
        out += sorted((z for z in zs if z["side"] == side), key=lambda z: -z["magnitude"])[:top]
    return out, n


def _activity(contracts):
    act = defaultdict(float)
    for c in contracts:
        act[(c.expiry.isoformat(), c.strike)] += (c.oi or 0) + (c.volume or 0)
    return act


def _smiles(contracts, spot, now, smooth, min_dte=0.1, window=0.08, min_points=9):
    """Clean smiles of the expirations far enough out, limited to strikes within `window` of price."""
    cl = an.clean_iv(contracts, spot, now, otm_only=True, max_spread=0.35, smooth=smooth)
    out = []
    for e in cl["expiries"]:
        if e["dte"] < min_dte:
            continue
        pts = [p for p in e["points"] if abs(p["strike"] - spot) <= window * spot]
        if len(pts) >= min_points:
            out.append({"expiry": e["expiry"], "dte": e["dte"], "ks": [p["strike"] for p in pts], "vs": [p["iv"] for p in pts]})
    return out


def _line_at(xs, ys, x):
    """Least-squares straight line through the points, evaluated at x."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((a - mx) ** 2 for a in xs)
    if sxx <= 0:
        return my
    b = sum((a - mx) * (c - my) for a, c in zip(xs, ys)) / sxx
    return my + b * (x - mx)


def iv_spikes(contracts, spot, now, n_exp=2, top=3, window=0.06, min_pts=0.006, min_activity=100):
    """IV spikes on the nearest `n_exp` usable expirations. Each: strike, expiry, iv, bump (decimal IV above its neighbours), activity."""
    act = _activity(contracts)
    out = []
    for sm in _smiles(contracts, spot, now, smooth=False)[:n_exp]:
        ks, vs = sm["ks"], sm["vs"]
        res = [None] * len(ks)
        for i in range(2, len(ks) - 2):
            nb = [i - 2, i - 1, i + 1, i + 2]
            res[i] = vs[i] - _line_at([ks[j] for j in nb], [vs[j] for j in nb], ks[i])
        vals = [r for r in res if r is not None]
        if len(vals) < 5:
            continue
        med = median(vals)
        scale = 1.4826 * median([abs(r - med) for r in vals])
        cands = []
        for i, r in enumerate(res):
            if r is None or r < max(min_pts, 3 * scale) or abs(ks[i] - spot) > window * spot:
                continue
            if any(res[j] is not None and res[j] > r for j in (i - 1, i + 1)):       # keep only the top of a bump
                continue
            a = act.get((sm["expiry"], ks[i]), 0.0)
            if a < min_activity:
                continue
            cands.append({"strike": ks[i], "expiry": sm["expiry"], "dte": sm["dte"], "iv": vs[i], "bump": r, "activity": a})
        out += sorted(cands, key=lambda x: -x["bump"])[:top]
    return sorted(out, key=lambda x: -x["bump"])[:top * n_exp]


def skew_flips(contracts, spot, now, window=0.08, min_rise=0.003):
    """The bottom of the smile for the nearest usable expiry and the first one at least a day out (when different)."""
    sms = _smiles(contracts, spot, now, smooth=True, window=window)
    pick = sms[:1] + [s for s in sms[1:] if s["dte"] >= 1.0 and sms[0]["dte"] < 1.0][:1]
    out = []
    for sm in pick:
        ks, vs = sm["ks"], sm["vs"]
        sv = [vs[0]] + [(vs[i - 1] + vs[i] + vs[i + 1]) / 3 for i in range(1, len(vs) - 1)] + [vs[-1]]
        i = min(range(len(sv)), key=lambda j: sv[j])
        if i < 2 or i > len(sv) - 3:
            continue                                                                # no bottom inside the window: the smile keeps falling
        lo = sv[i]
        if max(sv[:i]) - lo < min_rise or max(sv[i + 1:]) - lo < min_rise:
            continue
        x0, x1, x2, y0, y1, y2 = ks[i - 1], ks[i], ks[i + 1], sv[i - 1], sv[i], sv[i + 1]
        den = (x0 - x1) * (x0 - x2) * (x1 - x2)
        k = x1
        if den:
            a = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / den
            b = (x2 * x2 * (y0 - y1) + x1 * x1 * (y2 - y0) + x0 * x0 * (y1 - y2)) / den
            if a > 0:
                k = min(max(-b / (2 * a), x0), x2)
        out.append({"strike": round(k, 2), "expiry": sm["expiry"], "dte": sm["dte"], "iv": lo,
                    "put_side_iv": max(sv[:i]), "call_side_iv": max(sv[i + 1:])})
    return out
