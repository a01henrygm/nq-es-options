"""Same-day (0DTE) gamma, and the intraday series behind the session charts.

0DTE: only the nearest expiry that has not expired yet. On SPX and NDX that is today's expiry on every trading day (after the
close it becomes the next one, and the page says so). Same-day options carry the most gamma per contract, so they drive most of
the intraday dealer hedging; looking at them alone shows today's pins and walls without monthly open interest mixed in.

The session charts are built from small records the collector saves with every new snapshot (see collector._store_metrics), so a
whole session is available even though only the most recent full snapshots are kept.
"""
from __future__ import annotations
import math
from datetime import datetime, time as dtime

from . import analytics as an
from ..timeutil import to_et

PROFILE_WINDOW = 0.04          # strikes within 4% of price are kept in each stored GEX profile
ZERO_DTE_RULE = ("0DTE = the nearest expiry that has not expired (today's on SPX/NDX trading days). Walls are the strikes with the largest call "
                 "gamma and the largest put gamma of that expiry alone, within 5% of price. The 0DTE flip re-prices only that expiry's gamma "
                 "at nearby prices and finds where the total crosses zero.")


def front_expiry(contracts, now):
    exps = sorted({c.expiry for c in contracts if an.year_fraction(c.expiry, now) > 0})
    return exps[0] if exps else None


def compact_profile(strikes, spot, window=PROFILE_WINDOW):
    """[[strike, net, call, put], ...] for strikes near price, rounded so a session of them stays small."""
    lo, hi = spot * (1 - window), spot * (1 + window)
    return [[s["strike"], round(s["net_gex"]), round(s["call_gex"]), round(s["put_gex"])] for s in strikes if lo <= s["strike"] <= hi]


def zero_dte(contracts, spot, now, convention="standard"):
    e = front_expiry(contracts, now)
    if e is None:
        return {"available": False, "reason": "No unexpired expiry in the data."}
    sel = [c for c in contracts if c.expiry == e]
    g = an.gex_by_strike(sel, spot, now, convention)
    f = an.gamma_flip(sel, spot, now, convention, lo=0.95, hi=1.05, steps=101)
    near = [s for s in g["strikes"] if abs(s["strike"] - spot) <= 0.05 * spot]
    cw = max(near, key=lambda s: abs(s["call_gex"]), default=None)
    pw = max(near, key=lambda s: abs(s["put_gex"]), default=None)
    allg = an.gex_by_strike(contracts, spot, now, convention)
    share = abs(g["total_net_gex"]) / abs(allg["total_net_gex"]) if allg["total_net_gex"] else None
    gross0 = sum(abs(s["call_gex"]) + abs(s["put_gex"]) for s in g["strikes"])
    gross = sum(abs(s["call_gex"]) + abs(s["put_gex"]) for s in allg["strikes"])
    today = to_et(now).date()
    pos = sorted((s for s in near if s["net_gex"] > 0), key=lambda s: -s["net_gex"])[:3]
    neg = sorted((s for s in near if s["net_gex"] < 0), key=lambda s: s["net_gex"])[:3]
    return {"available": True, "expiry": e.isoformat(), "is_today": e == today, "days": an.year_fraction(e, now) * 365.25,
            "contracts": len(sel), "strikes": [s for s in g["strikes"] if abs(s["strike"] - spot) <= 0.03 * spot],
            "total_net_gex": g["total_net_gex"], "gross_share": gross0 / gross if gross else None, "net_share": share,
            "flip": f["flip"] if f["found"] else None, "flip_note": f["note"], "flip_grid": f["grid"],
            "exposure_at_spot": f.get("exposure_at_spot"),
            "call_wall": cw["strike"] if cw and cw["call_gex"] else None, "put_wall": pw["strike"] if pw and pw["put_gex"] else None,
            "call_wall_gex": cw["call_gex"] if cw else None, "put_wall_gex": pw["put_gex"] if pw else None,
            "top_positive": [s["strike"] for s in pos], "top_negative": [s["strike"] for s in neg],
            "rule": ZERO_DTE_RULE, "convention": convention, "units": g["units"]}


def day_move(contracts, spot, now):
    """Expected move for the regular session. Today's at-the-money straddle when today's expiry exists (the market's own price for
    the rest of the day), otherwise one standard deviation from the front ATM IV over one trading day (sqrt(1/252))."""
    e = front_expiry(contracts, now)
    if e is None:
        return None
    if e == to_et(now).date():
        em = an.expected_move(contracts, spot, now, e.isoformat())
        if em.get("straddle"):
            return {"points": em["straddle"]["price"], "method": "today's ATM straddle"}
    a = an.atm_iv(contracts, spot, e)
    if a:
        return {"points": spot * a["iv"] * math.sqrt(1 / 252), "method": "front ATM IV over one trading day"}
    return None


def oi_profile(contracts, spot, window=0.06):
    """[[strike, call OI, put OI], ...] summed over expiries near price. Open interest is a daily figure, so one per day is enough."""
    by = {}
    for c in contracts:
        if abs(c.strike - spot) <= window * spot and c.oi:
            r = by.setdefault(c.strike, [c.strike, 0.0, 0.0])
            r[1 if c.right == "C" else 2] += c.oi
    return [by[k] for k in sorted(by)]


def oi_by_contract(contracts, spot, now, window=0.12, max_days=70):
    """[[ticker, open interest], ...] for contracts within 12% of price and 70 days, so a day's record stays small."""
    from datetime import timedelta
    from ..timeutil import ET as _ET
    last = now.astimezone(_ET).date() + timedelta(days=max_days)
    return [[c.ticker, c.oi] for c in contracts if c.oi and abs(c.strike / spot - 1) <= window and c.expiry <= last]


def oi_change_from_profiles(prev, cur):
    a = {r[0]: r for r in prev}
    b = {r[0]: r for r in cur}
    return [{"strike": k, "call": (b.get(k, [k, 0, 0])[1]) - (a.get(k, [k, 0, 0])[1]), "put": (b.get(k, [k, 0, 0])[2]) - (a.get(k, [k, 0, 0])[2])}
            for k in sorted(set(a) | set(b))]


def option_flow(contracts, expiry=None):
    calls = sum(c.volume or 0 for c in contracts if c.right == "C" and (expiry is None or c.expiry == expiry))
    puts = sum(c.volume or 0 for c in contracts if c.right == "P" and (expiry is None or c.expiry == expiry))
    return {"calls": calls, "puts": puts}


# ---- chart builders (pure functions over stored series) ------------------------------------------------------------
def session_open(day_et):
    return datetime.combine(day_et, dtime(9, 30))


def gex_time_matrix(points, max_strikes=60):
    """points: [(time, [[strike, net, call, put], ...]), ...] -> times, strikes, z[strike][time] (net GEX, None where missing)."""
    if not points:
        return {"times": [], "strikes": [], "z": []}
    last = dict((row[0], row) for row in points[-1][1])
    strikes = sorted({row[0] for _, prof in points for row in prof})
    if len(strikes) > max_strikes and last:                      # keep the strikes nearest the latest profile's centre
        mid = sorted(last)[len(last) // 2]
        strikes = sorted(sorted(strikes, key=lambda k: abs(k - mid))[:max_strikes])
    idx = {k: i for i, k in enumerate(strikes)}
    z = [[None] * len(points) for _ in strikes]
    for j, (_, prof) in enumerate(points):
        for row in prof:
            if row[0] in idx:
                z[idx[row[0]]][j] = row[1]
    return {"times": [t for t, _ in points], "strikes": strikes, "z": z}


def cone(open_price, move_points, start, end, steps=40):
    """Expected-move cone from the open: +/- 1 and 2 sigma, widening with the square root of the time elapsed in the session."""
    total = (end - start).total_seconds()
    out = []
    for i in range(steps + 1):
        t = start + (end - start) * (i / steps)
        f = math.sqrt(max(0.0, (t - start).total_seconds()) / total) if total > 0 else 1.0
        d = move_points * f
        out.append({"t": t, "up1": open_price + d, "dn1": open_price - d, "up2": open_price + 2 * d, "dn2": open_price - 2 * d})
    return out


def regime_range_rows(days):
    """days: [{date, label, open_move, high, low}] -> adds range and range as a share of the expected move."""
    out = []
    for d in days:
        rng = (d["high"] - d["low"]) if d.get("high") is not None and d.get("low") is not None else None
        out.append({**d, "range": rng, "range_vs_move": (rng / d["open_move"]) if rng is not None and d.get("open_move") else None})
    return out


# ---- the interval map (1.30.0): every exposure by strike, saved with each snapshot ----------------------------------------------
IMAP_MEASURES = ("dex", "charm", "vanna", "volume", "oi")      # columns 1-5 all expiries, 6-10 the same for 0DTE only
IMAP_WINDOW = 0.03                                              # strikes within 3% of price (about 750 NQ points)


def strike_measures(contracts, spot, now, window=IMAP_WINDOW):
    """[[strike, dex, charm, vanna, volume, oi, dex0, charm0, vanna0, volume0, oi0], ...] for strikes near price.
    dex / charm / vanna are the modeled dealer exposures in $ (standard convention, as on the Charm and vanna and Delta exposure tabs)."""
    from collections import defaultdict
    from . import flows as fl
    if not spot:
        return []
    fe = front_expiry(contracts, now)
    acc = defaultdict(lambda: [0.0] * 10)
    for c in contracts:
        if abs(c.strike / spot - 1) > window or an.year_fraction(c.expiry, now) <= 0:
            continue
        row = acc[c.strike]
        for i, m in enumerate(IMAP_MEASURES):
            v = fl._cell_value(m, c, spot, now, "standard", {})
            if v:
                row[i] += v
                if c.expiry == fe:
                    row[i + 5] += v
    return [[k] + [round(x) for x in acc[k]] for k in sorted(acc)]
