"""Options analytics. Pure functions, no network access, so each one is unit-testable.

CONVENTIONS (stated on every API response):
* Contract exposure uses the contract multiplier supplied by the provider (normally 100 shares).
* Gamma exposure (GEX) per contract = gamma x open interest x multiplier x spot^2 x 0.01.
  Units: dollars of delta that change for a 1 percent move in the underlying.
* Delta exposure per contract = delta x open interest x multiplier x spot  (dollars of underlying).
* Sign convention ("dealer positioning scenario"). Open interest does NOT reveal who holds a contract, so the
  sign is an ASSUMPTION you can change:
    standard        dealers long calls, short puts  -> calls +, puts -
    customers_long  the opposite                     -> calls -, puts +
    gross           no sign, magnitude only          -> calls +, puts +
* Provider greeks are used when present. If gamma/delta is missing but implied volatility is available, a
  Black-Scholes value is computed (r = 0, q = 0, expiry at 16:00 ET) and counted separately as "model".
"""
from __future__ import annotations
import math
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, time
from statistics import median

from ..models import OptionContract
from ..timeutil import ET

SIGNS = {
    "standard": {"C": 1, "P": -1},
    "customers_long": {"C": -1, "P": 1},
    "gross": {"C": 1, "P": 1},
}


def _phi(x): return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
def _Phi(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def year_fraction(expiry: date, now: datetime) -> float:
    close = datetime.combine(expiry, time(16, 0), tzinfo=ET)
    return max((close - now).total_seconds(), 0.0) / (365.25 * 86400)


def bs_gamma(S, K, T, iv):
    if min(S, K, T, iv) <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    return _phi(d1) / (S * iv * math.sqrt(T))


def bs_delta(S, K, T, iv, right):
    if min(S, K, T, iv) <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    return _Phi(d1) if right == "C" else _Phi(d1) - 1


def _wt(c, weight):
    """Weight of a contract in exposure sums: open interest (default) or today's volume."""
    return c.volume if weight == "volume" else c.oi


def select(contracts, expirations=None, right=None, kmin=None, kmax=None):
    exp = set(expirations) if expirations else None
    return [c for c in contracts
            if (exp is None or c.expiry.isoformat() in exp) and (right in (None, "all") or c.right == right)
            and (kmin is None or c.strike >= kmin) and (kmax is None or c.strike <= kmax)]


def _iv_dec(iv):
    return iv / 100 if iv is not None and iv > 3 else iv  # tolerate a provider returning percent


def _gamma_of(c: OptionContract, spot, now):
    if c.gamma is not None:
        return c.gamma, "provider"
    iv = _iv_dec(c.iv)
    if iv and iv > 0:
        return bs_gamma(spot, c.strike, year_fraction(c.expiry, now), iv), "model"
    return None, None


def gex_by_strike(contracts, spot, now, convention="standard", weight="oi"):
    sgn = SIGNS[convention]
    by = defaultdict(lambda: {"call_gex": 0.0, "put_gex": 0.0, "contributions": []})
    used = {"provider": 0, "model": 0}
    excluded = {"no_open_interest": 0, "no_gamma_or_iv": 0}
    for c in contracts:
        w = _wt(c, weight)
        if not w:
            excluded["no_open_interest"] += 1
            continue
        g, src = _gamma_of(c, spot, now)
        if g is None:
            excluded["no_gamma_or_iv"] += 1
            continue
        used[src] += 1
        e = g * w * c.multiplier * spot * spot * 0.01 * sgn[c.right]
        row = by[c.strike]
        row["call_gex" if c.right == "C" else "put_gex"] += e
        row["contributions"].append({"ticker": c.ticker, "right": c.right, "expiry": c.expiry.isoformat(), "oi": w,
                                     "gamma": g, "gamma_source": src, "exposure": e})
    strikes = []
    for k in sorted(by):
        r = by[k]
        r["contributions"].sort(key=lambda x: -abs(x["exposure"]))
        strikes.append({"strike": k, "call_gex": r["call_gex"], "put_gex": r["put_gex"], "net_gex": r["call_gex"] + r["put_gex"],
                        "contributions": r["contributions"][:12]})
    return {"strikes": strikes, "total_net_gex": sum(s["net_gex"] for s in strikes), "contracts_used": used,
            "contracts_excluded": excluded, "convention": convention, "units": "dollars of delta per 1% move", "weight": weight,
            "formula": f"gamma x {'volume' if weight == 'volume' else 'open_interest'} x multiplier x spot^2 x 0.01 x sign"}


def _total_gex_at(S, cons, now, sgn):
    tot = 0.0
    for c, iv, T, w in cons:
        tot += sgn[c.right] * bs_gamma(S, c.strike, T, iv) * w * c.multiplier * S * S * 0.01
    return tot


def gamma_flip(contracts, spot, now, convention="standard", lo=0.9, hi=1.1, steps=81, weight="oi"):
    """Re-price every contract's gamma at hypothetical spot prices and look for a zero crossing of the total."""
    sgn = SIGNS[convention]
    cons = []
    for c in contracts:
        iv = _iv_dec(c.iv)
        T = year_fraction(c.expiry, now)
        w = _wt(c, weight)
        if w and iv and iv > 0 and T > 0:
            cons.append((c, iv, T, w))
    out = {"found": False, "flip": None, "convention": convention, "weight": weight, "contracts_used": len(cons), "reliability": "unavailable",
           "method": "Black-Scholes gamma re-priced at hypothetical prices (r=0, q=0), summed with the sign convention",
           "grid": [], "note": ""}
    if convention == "gross":
        out["note"] = "The gross convention has no sign, so a zero crossing is not defined."
        return out
    if len(cons) < 10:
        out["note"] = "Too few contracts with open interest and implied volatility to estimate a flip."
        return out
    grid = [spot * (lo + (hi - lo) * i / (steps - 1)) for i in range(steps)]
    vals = [_total_gex_at(S, cons, now, sgn) for S in grid]
    out["grid"] = [{"price": round(p, 4), "total_gex": v} for p, v in zip(grid, vals)]
    cross = []
    for i in range(steps - 1):
        a, b = vals[i], vals[i + 1]
        if a == 0 or a * b < 0:
            x = grid[i] if a == 0 else grid[i] + (grid[i + 1] - grid[i]) * (0 - a) / (b - a)
            cross.append(x)
    out["exposure_at_spot"] = _total_gex_at(spot, cons, now, sgn)
    if not cross:
        out["note"] = f"No zero crossing between {lo:.0%} and {hi:.0%} of spot. Modeled exposure stays on one side."
        return out
    flip = min(cross, key=lambda x: abs(x - spot))
    out.update(found=True, flip=flip, exposure_below=_total_gex_at(flip * 0.99, cons, now, sgn),
               exposure_above=_total_gex_at(flip * 1.01, cons, now, sgn), crossings=len(cross),
               reliability="low" if len(cross) > 1 or len(cons) < 40 else "medium")
    out["note"] = ("Several crossings were found; the one nearest spot is shown." if len(cross) > 1
                   else "A single crossing was found. The level depends on the sign assumption and on the quality of IV and open interest.")
    return out


def delta_profile(contracts, spot, now, convention="standard", lo=0.9, hi=1.1, steps=41):
    """Total dollar delta if the underlying were at hypothetical prices (delta re-priced with Black-Scholes, r=0, q=0)."""
    sgn = SIGNS[convention]
    cons = []
    for c in contracts:
        iv, T = _iv_dec(c.iv), year_fraction(c.expiry, now)
        if c.oi and iv and iv > 0 and T > 0:
            cons.append((c, iv, T))
    if len(cons) < 10:
        return {"available": False, "note": "Too few contracts with open interest and implied volatility.", "grid": []}
    grid = []
    for i in range(steps):
        S = spot * (lo + (hi - lo) * i / (steps - 1))
        grid.append({"price": round(S, 4), "total_delta": sum(sgn[c.right] * bs_delta(S, c.strike, T, iv, c.right) * c.oi * c.multiplier * S for c, iv, T in cons)})
    return {"available": True, "contracts_used": len(cons), "grid": grid, "convention": convention,
            "method": "Black-Scholes delta re-priced at each hypothetical price, times open interest x multiplier x price x sign"}


def delta_exposure(contracts, spot, now, convention="standard"):
    sgn = SIGNS[convention]
    by = defaultdict(float)
    n = {"provider": 0, "model": 0}
    for c in contracts:
        if not c.oi:
            continue
        d, src = c.delta, "provider"
        if d is None:
            iv = _iv_dec(c.iv)
            if not iv:
                continue
            d, src = bs_delta(spot, c.strike, year_fraction(c.expiry, now), iv, c.right), "model"
        n[src] += 1
        by[c.strike] += sgn[c.right] * d * c.oi * c.multiplier * spot
    strikes = [{"strike": k, "delta_exposure": by[k]} for k in sorted(by)]
    return {"strikes": strikes, "total": sum(s["delta_exposure"] for s in strikes), "contracts_used": n, "convention": convention,
            "units": "dollars of underlying", "formula": "delta x open_interest x multiplier x spot x sign",
            "note": "Delta exposure of each contract is signed by the dealer-positioning ASSUMPTION, not by observed positions.",
            "profile": delta_profile(contracts, spot, now, convention)}


def unusual_volume(contracts, nsig=3.5, min_volume=50, expirations=None):
    """Flags strikes whose volume is far above the rest of TODAY'S chain (a same-chain comparison, not a historical one).

    Method: total volume (calls + puts) per strike; robust z = (volume - median) / (1.4826 x MAD) over strikes that traded.
    A strike is flagged when robust z >= 3.5 and volume >= 50 contracts. A true historical baseline needs days of stored
    volume per contract, which this app builds up over time.
    """
    sel = select(contracts, expirations)
    by = defaultdict(float)
    for c in sel:
        if c.volume:
            by[c.strike] += c.volume
    vals = sorted(by.values())
    method = ("Robust z-score of each strike's total volume against the other strikes in today's chain "
              f"(median and MAD of strikes that traded). Flagged when z >= {nsig} and volume >= {min_volume}. "
              "Same-chain comparison only; it is not a comparison with past days.")
    if len(vals) < 10:
        return {"available": False, "method": method, "flagged": [], "note": "Fewer than 10 strikes have traded, too few for a baseline."}
    med = median(vals)
    mad = median([abs(v - med) for v in vals]) or max(1.0, 0.1 * med)
    flagged = []
    for k, v in sorted(by.items()):
        z = (v - med) / (1.4826 * mad)
        if z >= nsig and v >= min_volume:
            flagged.append({"strike": k, "volume": v, "robust_z": z, "times_median": v / med if med else None})
    flagged.sort(key=lambda r: -r["robust_z"])
    return {"available": True, "method": method, "median_strike_volume": med, "flagged": flagged,
            "note": "Unusual means high compared with other strikes today. Volume does not say who bought or sold."}


def strike_expiry_matrix(contracts, now, field="volume", side="total", spot=None, window=0.04):
    """Strike (rows, highest first) by expiry (columns) grid of volume or open interest.

    side: total (calls + puts), call, put, or net (calls minus puts). Strikes outside +/- window of spot are dropped
    (window 0 keeps everything) and strikes with no activity at all are left out, so rows are never empty."""
    cell = defaultdict(lambda: defaultdict(lambda: {"C": 0.0, "P": 0.0}))
    for c in contracts:
        v = getattr(c, field)
        if not v or (spot and window and abs(c.strike / spot - 1) > window) or year_fraction(c.expiry, now) <= 0 and c.expiry < now.date():
            continue
        cell[c.strike][c.expiry]["C" if c.right == "C" else "P"] += v
    expiries = sorted({e for r in cell.values() for e in r})
    strikes = sorted(cell, reverse=True)

    def val(d):
        v = {"total": d["C"] + d["P"], "call": d["C"], "put": d["P"], "net": d["C"] - d["P"]}[side]
        return v if (side == "net" or v > 0) else None
    z = [[val(cell[k][e]) if e in cell[k] else None for e in expiries] for k in strikes]
    flat = sorted(abs(v) for row in z for v in row if v is not None)
    p95 = flat[int(0.95 * (len(flat) - 1))] if flat else 0
    return {"color_max": p95 or (flat[-1] if flat else 0), "strikes": strikes, "expiries": [e.isoformat() for e in expiries],
            "dte": [round(year_fraction(e, now) * 365.25, 2) for e in expiries], "z": z, "field": field, "side": side,
            "window": window, "max": max(flat) if flat else 0,
            "note": "Each cell is the number of contracts at that strike and expiry. Empty cells had none."}


def concentration(contracts, field, top=5):
    by = defaultdict(lambda: {"call": 0.0, "put": 0.0})
    for c in contracts:
        v = getattr(c, field)
        if v:
            by[c.strike]["call" if c.right == "C" else "put"] += v
    rows = [{"strike": k, "call": v["call"], "put": v["put"], "total": v["call"] + v["put"]} for k, v in sorted(by.items())]
    tot = sum(r["total"] for r in rows) or 1
    top_rows = sorted(rows, key=lambda r: -r["total"])[:top]
    for r in top_rows:
        r["share_of_total"] = r["total"] / tot
    return {"strikes": rows, "top": top_rows, "total_calls": sum(r["call"] for r in rows), "total_puts": sum(r["put"] for r in rows),
            "put_call_ratio": (sum(r["put"] for r in rows) / sum(r["call"] for r in rows)) if sum(r["call"] for r in rows) else None,
            "note": "High concentration marks where positions or trading are large. It does not guarantee support or resistance."}


def iv_by_strike(contracts, expiry=None):
    pts = {"C": [], "P": []}
    for c in contracts:
        if (expiry is None or c.expiry.isoformat() == expiry) and c.iv:
            pts[c.right].append({"strike": c.strike, "iv": _iv_dec(c.iv)})
    for k in pts:
        pts[k].sort(key=lambda p: p["strike"])
    return pts


IV_CLEAN_METHOD = ("Out-of-the-money options only (puts below spot, calls above; both are averaged at the money). "
                   "Dropped: no IV, IV outside 1%-300%, zero bid, and quotes whose bid-ask spread is wider than the limit "
                   "(default 50% of the mid). Contracts at the same strike and expiry are averaged. Optional spike filter "
                   "(5-point window) replaces isolated outliers with the local median; end points are never changed.")


def _hampel(vals, k=2, nsig=3.0, floor=0.005):
    """Spike filter. A point is replaced by its neighbourhood median only if it sits far outside that neighbourhood
    (more than 3 robust standard deviations and at least half a volatility point). Smooth curvature is left alone,
    and the first and last points are never changed."""
    n = len(vals)
    if n < 5:
        return list(vals)
    out = list(vals)
    for i in range(1, n - 1):
        w = vals[max(0, i - k): i + k + 1]
        med = median(w)
        mad = median([abs(x - med) for x in w])
        if abs(vals[i] - med) > max(nsig * 1.4826 * mad, floor):
            out[i] = med
    return out


def clean_iv(contracts, spot, now, otm_only=True, max_spread=0.5, smooth=True):
    """Per-expiry implied-volatility smiles with obviously bad quotes removed. Nothing is extrapolated or invented."""
    by = defaultdict(lambda: defaultdict(list))
    st = {"used": 0, "no_iv": 0, "bad_iv": 0, "zero_bid": 0, "wide_spread": 0, "itm_skipped": 0, "expired": 0}
    for c in contracts:
        iv = _iv_dec(c.iv)
        if not iv:
            st["no_iv"] += 1
            continue
        if not (0.01 <= iv <= 3.0):
            st["bad_iv"] += 1
            continue
        if year_fraction(c.expiry, now) <= 0:
            st["expired"] += 1
            continue
        if c.bid is not None and c.ask is not None:
            if c.bid <= 0:
                st["zero_bid"] += 1
                continue
            mid = (c.bid + c.ask) / 2
            if mid > 0 and (c.ask - c.bid) / mid > max_spread:
                st["wide_spread"] += 1
                continue
        if otm_only and ((c.right == "P" and c.strike > spot) or (c.right == "C" and c.strike < spot)):
            st["itm_skipped"] += 1
            continue
        by[c.expiry][c.strike].append(iv)
        st["used"] += 1
    exps = []
    for e in sorted(by):
        ks = sorted(by[e])
        vs = [sum(by[e][k]) / len(by[e][k]) for k in ks]
        if smooth:
            vs = _hampel(vs)
        exps.append({"expiry": e.isoformat(), "dte": round(year_fraction(e, now) * 365.25, 3),
                     "points": [{"strike": k, "iv": v, "moneyness": k / spot} for k, v in zip(ks, vs)]})
    return {"expiries": exps, "stats": st, "method": IV_CLEAN_METHOD, "smoothed": smooth, "otm_only": otm_only, "max_spread": max_spread}


def _interp(x, xs, ys):
    i = bisect_left(xs, x)
    if i < len(xs) and xs[i] == x:
        return ys[i]
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def build_surface(cleaned, spot, min_points=6):
    """Grid of IV (percent) by strike and days to expiry. Linear interpolation inside each expiry's observed strike range only."""
    rows = [r for r in cleaned["expiries"] if len(r["points"]) >= min_points]
    if len(rows) < 2:
        return {"available": False, "expiries_found": len(cleaned["expiries"]),
                "note": f"A surface needs at least two expirations with {min_points}+ clean points each."}
    strikes = sorted({p["strike"] for r in rows for p in r["points"]})
    z = []
    for r in rows:
        ks, vs = [p["strike"] for p in r["points"]], [p["iv"] * 100 for p in r["points"]]
        z.append([None if (k < ks[0] or k > ks[-1]) else round(_interp(k, ks, vs), 4) for k in strikes])
    return {"available": True, "strikes": strikes, "dte": [r["dte"] for r in rows], "expiries": [r["expiry"] for r in rows],
            "z": z, "spot": spot, "units": "implied volatility, percent",
            "note": "Gaps are filled by straight-line interpolation between neighbouring strikes of the same expiry. Nothing is extrapolated."}


def walls(contracts, spot, now, max_dte=7):
    """Call wall = strike above spot with the most call open interest; put wall = strike below with the most put open
    interest, among expirations within max_dte days. Falls back to today's volume when open interest is all zero."""
    sel = [c for c in contracts if 0 < year_fraction(c.expiry, now) * 365.25 <= max_dte]
    basis = "open interest" if any(c.oi for c in sel) else "volume"
    wt = (lambda c: c.oi) if basis == "open interest" else (lambda c: c.volume)
    by = {"C": defaultdict(float), "P": defaultdict(float)}
    for c in sel:
        if wt(c):
            by[c.right][c.strike] += wt(c)
    up = {k: v for k, v in by["C"].items() if k > spot}
    dn = {k: v for k, v in by["P"].items() if k < spot}
    cw, pw = (max(up, key=up.get) if up else None), (max(dn, key=dn.get) if dn else None)
    return {"call_wall": cw, "put_wall": pw, "call_value": up.get(cw), "put_value": dn.get(pw), "basis": basis, "max_dte": max_dte}


def skew_25d(contracts, spot, now):
    """Put IV minus call IV at about 25 delta (volatility points) for the first expiry at least one day out."""
    for e in sorted({c.expiry for c in contracts}):
        T = year_fraction(e, now)
        if T * 365.25 < 1.0:
            continue
        R = [c for c in contracts if c.expiry == e and _iv_dec(c.iv)]
        d = lambda c: c.delta if c.delta is not None else bs_delta(spot, c.strike, T, _iv_dec(c.iv), c.right)
        puts = [(abs(d(c) + 0.25), c) for c in R if c.right == "P" and abs(d(c) + 0.25) <= 0.1]
        calls = [(abs(d(c) - 0.25), c) for c in R if c.right == "C" and abs(d(c) - 0.25) <= 0.1]
        if puts and calls:
            p, c = min(puts, key=lambda x: x[0])[1], min(calls, key=lambda x: x[0])[1]
            return {"value": (_iv_dec(p.iv) - _iv_dec(c.iv)) * 100, "expiry": e.isoformat(), "put_strike": p.strike, "call_strike": c.strike,
                    "method": "put IV minus call IV at about 25 delta, in volatility points"}
    return None


GEX_ZONE_RULE = ("A strike is a wall strike when its bigger side (call or put gamma) is at least 30% of the biggest single-side GEX. Wall strikes "
                 "next to each other (no more than one strike skipped between them) form ONE band. The side with MORE wall strikes in the band wins its type, so call wall, "
                 "put wall, call wall becomes a call-wall zone; a tie goes to the side with the larger total GEX. A zone starts and ends on a strike of its own side, so an opposite strike at the very edge forms its own zone instead. The band runs from the lowest to the highest "
                 "wall strike, widened by half the local strike gap on each side. A band never reaches more than 0.3% of price either side of its strongest strike "
                 "(about 90 points on NDX, more if strikes are far apart); a bigger run of wall strikes is split into several zones around its strongest strikes.")


def _band_zones(strikes, spot, pick, sides, top, min_frac=0.30, gap_mult=2, grid=None):
    """Shared builder. pick(strike_row) -> (side, size) or None. sides = the two kinds, e.g. ('call', 'put')."""
    rows = []
    for s in strikes:
        got = pick(s)
        if got and got[1] > 0:
            rows.append({"strike": s["strike"], "side": got[0], "mag": got[1]})
    if not rows:
        return []
    ks = sorted({s["strike"] for s in strikes} | set(grid or ()))
    pos = {k: i for i, k in enumerate(ks)}
    for r in rows:
        r["i"] = pos[r["strike"]]

    def gap_below(k):
        i = pos[k]
        return k - ks[i - 1] if i > 0 else (ks[1] - k if len(ks) > 1 else max(spot * 0.001, 1.0))

    def gap_above(k):
        i = pos[k]
        return ks[i + 1] - k if i + 1 < len(ks) else gap_below(k)

    peak = max(r["mag"] for r in rows)
    pool = sorted((r for r in rows if r["mag"] >= min_frac * peak), key=lambda r: r["strike"])
    clusters = []
    while pool:
        seed = max(pool, key=lambda r: r["mag"])
        half = max(0.003 * spot, 2 * min(gap_below(seed["strike"]), gap_above(seed["strike"])))      # a band stays near its strongest strike
        n = pool.index(seed)
        lo = hi = n
        while lo > 0 and pool[lo]["i"] - pool[lo - 1]["i"] <= gap_mult and seed["strike"] - pool[lo - 1]["strike"] <= half:
            lo -= 1
        while hi < len(pool) - 1 and pool[hi + 1]["i"] - pool[hi]["i"] <= gap_mult and pool[hi + 1]["strike"] - seed["strike"] <= half:
            hi += 1
        cl = pool[lo:hi + 1]
        a_, b_ = sides
        na_, nb_ = sum(r["side"] == a_ for r in cl), sum(r["side"] == b_ for r in cl)
        win = a_ if (na_, sum(r["mag"] for r in cl if r["side"] == a_)) > (nb_, sum(r["mag"] for r in cl if r["side"] == b_)) else b_
        while cl and cl[0]["side"] != win:                      # a zone must START and END on a strike of the winning side;
            cl = cl[1:]                                         # an opposite strike at the very edge forms its own zone instead
        while cl and cl[-1]["side"] != win:
            cl = cl[:-1]
        if seed not in cl:
            cl = [seed]
        clusters.append(cl)
        pool = [r for r in pool if r not in cl]
    clusters.sort(key=lambda c: c[0]["strike"])
    a_, b_ = sides
    local = lambda k: min(gap_below(k), gap_above(k))                                   # a hole in the strike list must not stretch the band
    zones = []
    for cl in clusters:
        n = {a_: sum(r["side"] == a_ for r in cl), b_: sum(r["side"] == b_ for r in cl)}
        tot = {k: sum(r["mag"] for r in cl if r["side"] == k) for k in n}
        side = a_ if (n[a_], tot[a_]) > (n[b_], tot[b_]) else b_
        center = max((r for r in cl if r["side"] == side), key=lambda r: r["mag"])
        zones.append({"side": side, "low": cl[0]["strike"] - local(cl[0]["strike"]) / 2, "high": cl[-1]["strike"] + local(cl[-1]["strike"]) / 2,
                      "center": center["strike"], "magnitude": tot[side], "peak": center["mag"], "counts": n,
                      "members": [{"strike": r["strike"], "side": r["side"], "gex": r["mag"]} for r in cl]})
    out = []
    for side in sides:
        out += sorted((z for z in zones if z["side"] == side), key=lambda z: -z["magnitude"])[:top]
    return out


def gex_wall_zones(strikes, spot, top=1, min_frac=0.30, gap_mult=2):
    """Call-wall and put-wall zones (see GEX_ZONE_RULE). Up to `top` of each kind, biggest first."""
    def pick(s):
        c, p = abs(s["call_gex"]), abs(s["put_gex"])
        return ("call" if c >= p else "put", max(c, p))
    zs = _band_zones(strikes, spot, pick, ("call", "put"), top, min_frac, gap_mult)
    for z in zs:
        z["call_strikes"], z["put_strikes"] = z["counts"]["call"], z["counts"]["put"]
    return zs


SERIES_ZONE_RULE = ("Zones for open interest and volume are built like the GEX wall zones: a strike counts when its bigger side (calls or puts) is at least 30% of the "
                    "biggest single-side value; strikes next to each other (one skipped at most) form ONE band; the side with MORE strikes in it decides call or put "
                    "(a tie goes to the larger total); a band starts and ends on a strike of its own side, never reaches more than 0.3% of price either side of its "
                    "strongest strike, and is widened by half the local strike gap.")


def series_zones(rows, grid, spot, top=50, min_frac=0.30):
    """Call-side and put-side zones for a per-strike series such as open interest or volume. rows: dicts with strike, call, put.
    grid: every strike that exists, so 'next to each other' follows the real strike grid. Returns up to `top` zones per side, biggest first."""
    def pick(r):
        return ("call" if r["call"] >= r["put"] else "put", max(r["call"], r["put"]))
    zs = _band_zones(rows, spot, pick, ("call", "put"), top, min_frac, 2, grid)
    for z in zs:
        z["call_strikes"], z["put_strikes"] = z["counts"]["call"], z["counts"]["put"]
    return zs


GEX_NET_ZONE_RULE = ("Positive and negative GEX zones use the NET gamma at each strike (calls minus puts under the chosen sign scenario). A strike counts when its net size is "
                     "at least 30% of the biggest net GEX anywhere. Strikes next to each other (no more than one skipped) form ONE band, and the sign with MORE strikes in it "
                     "decides whether it is a positive or a negative GEX zone (a tie goes to the larger total). A zone starts and ends on a strike of its own sign. Same width cap as the wall zones.")


def gex_net_zones(strikes, spot, top=1, min_frac=0.30, gap_mult=2):
    """Positive-GEX and negative-GEX zones from the net gamma at each strike (see GEX_NET_ZONE_RULE)."""
    def pick(s):
        return ("positive" if s["net_gex"] > 0 else "negative", abs(s["net_gex"]))
    zs = _band_zones(strikes, spot, pick, ("positive", "negative"), top, min_frac, gap_mult)
    for z in zs:
        z["pos_strikes"], z["neg_strikes"] = z["counts"]["positive"], z["counts"]["negative"]
    return zs


def scenarios(contracts, spot, now):
    """Gamma flip and regime under different weightings. The sign convention does NOT move the flip level (flipping every sign
    mirrors the curve and leaves its zero crossing in place); it only changes what each side of the flip means. The weighting
    (open interest versus today's volume) can move the level."""
    rows = []
    for weight in ("oi", "volume"):
        f = gamma_flip(contracts, spot, now, "standard", weight=weight)
        g = gex_by_strike(contracts, spot, now, "standard", weight=weight)
        st = g["strikes"]
        pos = sorted((s for s in st if s["net_gex"] > 0), key=lambda s: -s["net_gex"])[:3]
        neg = sorted((s for s in st if s["net_gex"] < 0), key=lambda s: s["net_gex"])[:3]
        rows.append({"weight": weight, "label": "Open interest (positions held)" if weight == "oi" else "Today's volume (where trading happened)",
                     "flip": f["flip"] if f["found"] else None, "found": f["found"], "note": f["note"], "contracts_used": f["contracts_used"],
                     "total_gex": g["total_net_gex"], "exposure_at_spot": f.get("exposure_at_spot"),
                     "top_positive_strikes": [s["strike"] for s in pos], "top_negative_strikes": [s["strike"] for s in neg]})
    spread = abs(rows[0]["flip"] - rows[1]["flip"]) if rows[0]["flip"] is not None and rows[1]["flip"] is not None else None
    return {"rows": rows, "flip_spread": spread, "flip_spread_pct": spread / spot if spread is not None else None,
            "sign_note": "Under the standard assumption (dealers long calls, short puts) price ABOVE the flip is the positive-gamma, calmer side. "
                         "Under the reverse assumption the same level exists, but ABOVE it is the negative-gamma, more trending side."}


def atm_iv(contracts, spot, expiry):
    sel = [c for c in contracts if c.expiry == expiry and c.iv]
    if not sel:
        return None
    k = min({c.strike for c in sel}, key=lambda s: abs(s - spot))
    ivs = [_iv_dec(c.iv) for c in sel if c.strike == k]
    return {"strike": k, "iv": sum(ivs) / len(ivs)}


def iv_points(contracts, spot, now):
    """The nearest expiry that is at least a day away ("front") and the one closest to three weeks out ("mid"), with their at-the-money IV."""
    rows = [r for r in moves_table(contracts, spot, now, 14) if r["atm_iv"]]
    if not rows:
        return None
    front = next((r for r in rows if r["days"] >= 1.0), rows[0])
    mids = [r for r in rows if 7 <= r["days"] <= 45]
    return {"front": front, "mid": min(mids, key=lambda r: abs(r["days"] - 21)) if mids else None}


def iv_term_structure(contracts, spot):
    out = []
    for e in sorted({c.expiry for c in contracts}):
        a = atm_iv(contracts, spot, e)
        if a:
            out.append({"expiry": e.isoformat(), **a})
    return out


def moves_table(contracts, spot, now, n=5):
    """Expected moves for each of the next n expirations, three ways, as distances and as price levels up and down.

    straddle  call mid + put mid at the strike nearest spot. What the market charges for a move either way.
    1 sigma   spot x ATM IV x sqrt(time left). Under the usual bell-curve assumption price finishes inside it about 68% of the time.
    2 sigma   twice that, about 95% of the time under the same assumption. Real markets have fatter tails, so treat it as 'unusual', not 'impossible'.
    """
    rows = []
    for e in sorted({c.expiry for c in contracts if year_fraction(c.expiry, now) > 0})[:n]:
        T = year_fraction(e, now)
        a = atm_iv(contracts, spot, e)
        st = expected_move(contracts, spot, now, e.isoformat()).get("straddle")
        sd1 = spot * a["iv"] * math.sqrt(T) if a else None
        rows.append({"expiry": e.isoformat(), "days": T * 365.25, "atm_strike": a["strike"] if a else (st["strike"] if st else None),
                     "atm_iv": a["iv"] if a else None, "straddle": st["price"] if st else None,
                     "sd1": sd1, "sd2": 2 * sd1 if sd1 is not None else None, "per_day_sd1": spot * a["iv"] * math.sqrt(1 / 365.25) if a else None})
    return rows


def expected_move(contracts, spot, now, expiry=None, days=None):
    """Two documented estimates for one expiry.

    straddle:  mid(call) + mid(put) at the strike nearest spot (the market price of a one-expiry move).
    iv_1sd:    spot x ATM IV x sqrt(T)   (one standard deviation under a lognormal assumption).
    Both are statistical estimates, not limits. Under that assumption E|move| is about 0.8 x one standard deviation.
    """
    expiries = sorted({c.expiry for c in contracts if year_fraction(c.expiry, now) > 0})
    if not expiries:
        return {"available": False, "note": "No unexpired contracts."}
    e = date.fromisoformat(expiry) if expiry else expiries[0]
    T = year_fraction(e, now) if days is None else days / 365.25
    out = {"available": True, "expiry": e.isoformat(), "reference_price": spot, "horizon_years": T,
           "horizon_days": T * 365.25, "straddle": None, "iv_1sd": None,
           "note": "A statistical estimate. Price can and does move beyond it."}
    by = defaultdict(dict)
    for c in contracts:
        if c.expiry == e and c.mid:
            by[c.strike][c.right] = c
    pairs = [k for k, v in by.items() if "C" in v and "P" in v]
    if pairs:
        k = min(pairs, key=lambda s: abs(s - spot))
        s = by[k]["C"].mid + by[k]["P"].mid
        out["straddle"] = {"strike": k, "price": s, "lower": spot - s, "upper": spot + s,
                           "note": "ATM straddle mid price, used as the market-implied expected absolute move."}
    a = atm_iv(contracts, spot, e)
    if a and T > 0:
        m = spot * a["iv"] * math.sqrt(T)
        out["iv_1sd"] = {"atm_strike": a["strike"], "atm_iv": a["iv"], "move": m, "lower": spot - m, "upper": spot + m}
    if out["straddle"] is None and out["iv_1sd"] is None:
        out.update(available=False, note="No valid quotes or implied volatility to estimate a move.")
    return out
