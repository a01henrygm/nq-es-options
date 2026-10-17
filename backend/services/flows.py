"""Charm, vanna and dealer-delta exposure by strike, overnight open-interest change, and the activity map.

ALL OF THIS IS MODELED. Open interest does not say who holds a contract, so the dealer side comes from the same sign
assumption as GEX (standard: dealers long calls, short puts). Greeks are Black-Scholes with r = 0, q = 0 and expiry at 16:00 ET,
computed from each contract's implied volatility.

Charm  = how much an option's delta changes as time passes.      Exposure = dealer dollar delta that drifts per day.
Vanna  = how much an option's delta changes when IV moves.       Exposure = dealer dollar delta that changes per 1 volatility point.
Dealer delta (DEX) = dealer dollar delta held at each strike right now.

Reading the sign (under the chosen assumption):
  charm exposure > 0  dealers' delta GROWS as time passes, so to stay hedged they SELL futures as the day goes on.
  charm exposure < 0  their delta shrinks, so they BUY as time passes.
  vanna exposure > 0  their delta grows when IV rises: they SELL if IV rises and BUY if IV falls.
  vanna exposure < 0  the reverse: they BUY if IV rises and SELL if IV falls.
"""
from __future__ import annotations
import math
from collections import defaultdict
from datetime import datetime, time, timedelta

from . import analytics as an
from ..timeutil import ET

MIN_T = 0.5 / (365.25 * 24)          # half an hour: below this the greeks of same-day options blow up, so time is floored here

CHARM_RULE = ("Charm exposure per contract = sign x charm x open interest x multiplier x spot, where charm is the Black-Scholes change in delta per "
              "calendar day (r = 0, q = 0, time floored at 30 minutes). Positive means dealers' delta grows as time passes, so they would SELL to stay "
              "hedged; negative means they would BUY. Modeled from the dealer-positioning assumption, not observed.")
VANNA_RULE = ("Vanna exposure per contract = sign x vanna x 0.01 x open interest x multiplier x spot: the dealer dollar delta that changes when "
              "implied volatility moves 1 point (Black-Scholes, r = 0, q = 0). Positive means dealers would SELL if IV rises and BUY if IV falls; "
              "negative is the reverse. Modeled from the dealer-positioning assumption, not observed.")
DEX_RULE = ("Dealer delta exposure per contract = sign x delta x open interest x multiplier x spot (provider delta when supplied, otherwise "
            "Black-Scholes). It is how much of the option positions behaves like holding the underlying, under the dealer-positioning assumption.")
NEW_OI_RULE = ("New positioning = the rise in open interest at each strike since the previous session's last stored snapshot (contracts present in "
               "both). Only increases count. Strikes next to each other are merged into one zone like the other zone types.")


def _d1d2(S, K, T, iv):
    sq = iv * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / sq
    return d1, d1 - sq


def bs_charm_per_day(S, K, T, iv):
    """Change in delta per calendar day as time passes (same for calls and puts when r = q = 0)."""
    T = max(T, MIN_T)
    if min(S, K, iv) <= 0:
        return 0.0
    d1, d2 = _d1d2(S, K, T, iv)
    return an._phi(d1) * d2 / (2 * T) / 365.25


def bs_vanna(S, K, T, iv):
    """Change in delta for a 1.00 (100 point) change in IV (same for calls and puts when r = q = 0)."""
    T = max(T, MIN_T)
    if min(S, K, iv) <= 0:
        return 0.0
    d1, d2 = _d1d2(S, K, T, iv)
    return -an._phi(d1) * d2 / iv


def _usable(contracts, now):
    for c in contracts:
        iv = an._iv_dec(c.iv)
        T = an.year_fraction(c.expiry, now)
        if c.oi and iv and 0.01 <= iv <= 3 and T > 0:
            yield c, iv, T


def greek_exposure(contracts, spot, now, convention="standard"):
    """Charm, vanna and dealer delta exposure per strike, plus the delta that drifts by today's close from charm alone."""
    sgn = an.SIGNS[convention]
    by = defaultdict(lambda: {"charm": 0.0, "vanna": 0.0, "dex": 0.0})
    n, drift = 0, 0.0
    close = datetime.combine(now.astimezone(ET).date(), time(16, 0), tzinfo=ET)
    left = max(0.0, (close - now).total_seconds()) / (365.25 * 86400)
    for c, iv, T in _usable(contracts, now):
        n += 1
        w = sgn[c.right] * c.oi * c.multiplier * spot
        r = by[c.strike]
        r["charm"] += w * bs_charm_per_day(spot, c.strike, T, iv)
        r["vanna"] += w * bs_vanna(spot, c.strike, T, iv) * 0.01
        d = c.delta if c.delta is not None else an.bs_delta(spot, c.strike, T, iv, c.right)
        r["dex"] += w * d
        if left > 0:                                              # delta at the close minus delta now, price and IV unchanged
            T1 = T - left
            if T1 <= 1e-9:
                d1_ = (1.0 if spot > c.strike else 0.0) - (1.0 if c.right == "P" else 0.0)
            else:
                d1_ = an.bs_delta(spot, c.strike, T1, iv, c.right)
            drift += w * (d1_ - an.bs_delta(spot, c.strike, T, iv, c.right))
    strikes = [{"strike": k, **by[k]} for k in sorted(by)]
    tot = {k: sum(s[k] for s in strikes) for k in ("charm", "vanna", "dex")}
    if n == 0:
        drift_note = "No contracts with open interest and implied volatility."
    elif left <= 0:
        drift_note = "The regular session is over, so there is no drift left today."
    else:
        drift_note = (f"If price and IV stayed where they are, dealer delta would change by this much by 16:00 ET from time passing alone. "
                      f"{'Positive: dealers would need to SELL that amount to stay hedged.' if drift > 0 else 'Negative: dealers would need to BUY that amount to stay hedged.'}")
    return {"strikes": strikes, "totals": tot, "contracts_used": n, "convention": convention,
            "drift_to_close": drift if left > 0 else 0.0, "drift_note": drift_note, "hours_to_close": left * 365.25 * 24,
            "units": {"charm": "dollars of delta per day", "vanna": "dollars of delta per 1 IV point", "dex": "dollars of underlying"},
            "rules": {"charm": CHARM_RULE, "vanna": VANNA_RULE, "dex": DEX_RULE}, "estimate": True}


def signed_zones(strikes, key, spot, top=2):
    """Positive and negative zones of one per-strike exposure (charm, vanna or dex), built like the net GEX zones."""
    def pick(s):
        v = s[key]
        return ("positive" if v > 0 else "negative", abs(v))
    return an._band_zones(strikes, spot, pick, ("positive", "negative"), top)


# ---- overnight open interest ------------------------------------------------------------------------------
def oi_change_by_contract(contracts, prev_oi):
    """Per contract change in open interest against a {ticker: oi} map from the previous session. Contracts missing there are skipped."""
    out = {}
    for c in contracts:
        if c.ticker in prev_oi:
            out[c.ticker] = (c.oi or 0) - (prev_oi[c.ticker] or 0)
    return out


def new_positioning(contracts, prev_oi):
    """Rows of strike / call / put with only the INCREASE in open interest (for zones)."""
    ch = oi_change_by_contract(contracts, prev_oi)
    by = defaultdict(lambda: {"call": 0.0, "put": 0.0})
    for c in contracts:
        d = ch.get(c.ticker)
        if d and d > 0:
            by[c.strike]["call" if c.right == "C" else "put"] += d
    return [{"strike": k, **v} for k, v in sorted(by.items())]


# ---- activity map ---------------------------------------------------------------------------------------------
MEASURES = {
    "oi_change": ("Open interest change since the last session", "contracts", True),
    "volume": ("Volume today", "contracts", False),
    "oi": ("Open interest", "contracts", False),
    "gex": ("Modeled GEX", "$ delta per 1% move", True),
    "charm": ("Modeled charm exposure", "$ delta per day", True),
    "vanna": ("Modeled vanna exposure", "$ delta per IV point", True),
    "dex": ("Modeled dealer delta", "$ of underlying", True),
}
SIDES = ("total", "call", "put", "net")
HOT_RULE = ("Hot spots: the strike activity (summed over the expirations shown) is split into bands of neighbouring strikes, the same way the "
            "level zones are built, and the bands with the most activity are listed. The activity center is the price that splits the total "
            "activity in half (a weighted median strike).")


MEANING = {
    "oi_change": {"positive": "contracts added", "negative": "contracts closed"},
    "gex": {"positive": "positive gamma: dealer hedging dampens moves", "negative": "negative gamma: dealer hedging adds to moves"},
    "charm": {"positive": "dealers sell as time passes", "negative": "dealers buy as time passes"},
    "vanna": {"positive": "dealers buy if IV falls, sell if it rises", "negative": "dealers sell if IV falls, buy if it rises"},
    "dex": {"positive": "dealers long delta here", "negative": "dealers short delta here"},
    "net": {"positive": "more calls", "negative": "more puts"},
}


def side_meaning(measure, side, zone_side):
    if zone_side in ("call", "put"):
        return "calls" if zone_side == "call" else "puts"
    return MEANING.get(measure if measure in MEANING else "net", MEANING["net"])[zone_side] if not (side == "net" and measure in ("volume", "oi")) else MEANING["net"][zone_side]


def _cell_value(measure, c, spot, now, convention, chg):
    sgn = an.SIGNS[convention]
    if measure == "volume":
        return c.volume or 0.0
    if measure == "oi":
        return c.oi or 0.0
    if measure == "oi_change":
        return chg.get(c.ticker)
    iv, T = an._iv_dec(c.iv), an.year_fraction(c.expiry, now)
    if measure == "gex":
        g, _ = an._gamma_of(c, spot, now)
        return None if g is None or not c.oi else sgn[c.right] * g * c.oi * c.multiplier * spot * spot * 0.01
    if not c.oi or not iv or not (0.01 <= iv <= 3) or T <= 0:
        return None
    w = sgn[c.right] * c.oi * c.multiplier * spot
    if measure == "charm":
        return w * bs_charm_per_day(spot, c.strike, T, iv)
    if measure == "vanna":
        return w * bs_vanna(spot, c.strike, T, iv) * 0.01
    d = c.delta if c.delta is not None else an.bs_delta(spot, c.strike, T, iv, c.right)
    return w * d


def activity_map(contracts, spot, now, measure="oi_change", side="total", window=0.04, max_expiries=8, convention="standard", prev_oi=None, hot=5):
    """Strike (rows, highest first) by expiry (columns) grid of one measure, the strike profile, hot spots and the activity center.

    side applies to every measure: total (calls + puts), call, put, or net (calls minus puts; for the modeled measures this is the
    same as total because the sign is already in the value)."""
    if measure not in MEASURES or side not in SIDES:
        raise ValueError("bad measure or side")
    title, units, signed = MEASURES[measure]
    chg = oi_change_by_contract(contracts, prev_oi or {}) if measure == "oi_change" else {}
    exps = sorted({c.expiry for c in contracts if an.year_fraction(c.expiry, now) > 0})[:max_expiries]
    keep = set(exps)
    cell = defaultdict(lambda: defaultdict(lambda: {"C": 0.0, "P": 0.0, "n": 0}))
    for c in contracts:
        if c.expiry not in keep or (window and abs(c.strike / spot - 1) > window):
            continue
        v = _cell_value(measure, c, spot, now, convention, chg)
        if v is None or v == 0:
            continue
        d = cell[c.strike][c.expiry]
        d[c.right] += v
        d["n"] += 1
    modeled = measure in ("gex", "charm", "vanna", "dex")

    def val(d):
        if side == "call":
            return d["C"]
        if side == "put":
            return d["P"]
        if side == "net" and not modeled:
            return d["C"] - d["P"]
        return d["C"] + d["P"]
    strikes = sorted(cell, reverse=True)
    z, prof_c, prof_p = [], [], []
    for k in strikes:
        row = []
        for e in exps:
            d = cell[k].get(e)
            v = val(d) if d else None
            row.append(v if v else None)
        z.append(row)
        prof_c.append(sum(cell[k][e]["C"] for e in cell[k]))
        prof_p.append(sum(cell[k][e]["P"] for e in cell[k]))
    profile = [sum(v for v in r if v is not None) for r in z]
    is_signed = signed or side == "net"
    flat = sorted(abs(v) for r in z for v in r if v is not None)
    p95 = flat[int(0.95 * (len(flat) - 1))] if flat else 0
    # hot spots: band the strike profile like the level zones
    rows = []
    for k, tot, cc, pp in zip(strikes, profile, prof_c, prof_p):
        if is_signed:
            rows.append({"strike": k, "v": tot})
        else:
            rows.append({"strike": k, "call": cc if side != "put" else 0.0, "put": pp if side != "call" else 0.0})
    if is_signed:
        sides_ = ("positive", "negative")
        zs = an._band_zones(rows, spot, lambda r: ("positive" if r["v"] > 0 else "negative", abs(r["v"])), sides_, hot, min_frac=0.25)
    else:
        sides_ = ("call", "put")
        zs = an._band_zones(rows, spot, lambda r: ("call" if r["call"] >= r["put"] else "put", max(r["call"], r["put"])), sides_, hot, min_frac=0.25)
    grand = sum(abs(v) for v in profile) or 1.0
    spots = []
    for zz in sorted(zs, key=lambda q: -q["magnitude"])[:hot]:
        k = zz["center"]
        i = strikes.index(k)
        row = z[i]
        best = max(range(len(exps)), key=lambda j: abs(row[j] or 0)) if exps else None
        spots.append({"price": k, "low": zz["low"], "high": zz["high"], "side": zz["side"], "value": zz["magnitude"],
                      "share": zz["magnitude"] / grand, "meaning": side_meaning(measure, side, zz["side"]), "strike_value": profile[i], "top_expiry": exps[best].isoformat() if best is not None and row[best] else None,
                      "above_price": k > spot, "distance_pct": (k / spot - 1) * 100, "members": [m["strike"] for m in zz["members"]]})
    # activity center: weighted median strike of |activity|
    center = None
    if profile:
        asc = sorted(zip(strikes, (abs(v) for v in profile)))
        half, run = sum(w for _, w in asc) / 2, 0.0
        for k, w in asc:
            run += w
            if run >= half:
                center = k
                break
    above = sum(abs(v) for k, v in zip(strikes, profile) if k > spot)
    below = sum(abs(v) for k, v in zip(strikes, profile) if k < spot)
    return {"measure": measure, "title": title, "units": units, "signed": is_signed, "modeled": modeled, "side": side,
            "strikes": strikes, "expiries": [e.isoformat() for e in exps], "dte": [round(an.year_fraction(e, now) * 365.25, 2) for e in exps],
            "z": z, "profile": profile, "profile_call": prof_c, "profile_put": prof_p, "color_max": max(p95, 0.4 * flat[-1]) if flat else 0,
            "max": flat[-1] if flat else 0, "hot_spots": spots, "center": center, "share_above": above / grand if profile else None,
            "share_below": below / grand if profile else None, "window": window, "hot_rule": HOT_RULE, "convention": convention}


def summary_line(m, fmt_price):
    """One plain sentence about where the activity is. fmt_price(strike) -> text (adds the futures price when known)."""
    if not m["hot_spots"]:
        return "No activity in this window."
    top = m["hot_spots"][0]
    where = "above" if top["above_price"] else "below"
    side = top["meaning"]
    exp = f", mostly in the {top['top_expiry'][5:]} expiry" if top["top_expiry"] else ""
    head = {"oi_change": "The biggest change in positions since the last session",
            "volume": "The busiest trading today", "oi": "The largest open positions",
            "gex": "The largest modeled gamma", "charm": "The largest modeled charm", "vanna": "The largest modeled vanna",
            "dex": "The largest modeled dealer delta"}[m["measure"]]
    tilt = ""
    if m["share_above"] is not None and m["share_below"] is not None:
        a, b = m["share_above"], m["share_below"]
        if a > 0.6:
            tilt = f" {a:.0%} of the activity in view is above price."
        elif b > 0.6:
            tilt = f" {b:.0%} of the activity in view is below price."
        else:
            tilt = " Activity is spread on both sides of price."
    return f"{head} sits at {fmt_price(top['price'])} ({side}, {abs(top['distance_pct']):.2f}% {where} price{exp}), {top['share']:.0%} of the total in view.{tilt}"
