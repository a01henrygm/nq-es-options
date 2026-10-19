"""Level map: what price is likely to do at each level, and a projected path of candles that acts it out.

Each level gets a call:
  RESPECT     price tests it and rejects (wicks through, closes back on the side it came from)
  CHOP        price stalls around it, overlapping candles with wicks on both sides, before picking a side
  DISRESPECT  price closes through it and keeps going to the next level

How the call is made (a visible rule, not backtested):
  1. Within a quarter of a percent of the 0DTE or overall gamma flip, or a flip level itself: CHOP. The regime can switch there.
  2. Expected-move edges: RESPECT in long gamma, DISRESPECT in short gamma (short-gamma days run past what options priced).
  3. Otherwise the modeled net GEX of the strikes within 0.15% of the level decides, together with the session's 0DTE regime:
       long gamma  + positive GEX at the level   RESPECT     dealers sell rallies into it and buy dips into it
       long gamma  + negative GEX at the level   DISRESPECT  a pocket where dealer hedging speeds price up
       short gamma + negative GEX at the level   DISRESPECT  dealers add to the move
       short gamma + positive GEX at the level   CHOP        a positive strike can stall a trend for a while
       little GEX either way                     RESPECT in long gamma, DISRESPECT in short gamma
  Strength is the level's GEX against the biggest GEX near price. The record is how often that level type held in this app's
  own reaction log (held = still on the approach side 30 minutes after a touch).

The projected path starts at the current price and walks toward the next level (the trend direction in short gamma, the nearest
level in long gamma), at a pace set by the remaining expected move. At each level it does what the call says. The alternate
path is the same walk with the FIRST level's call turned the other way. Both are scenarios to picture the calls, not forecasts.
"""
from __future__ import annotations
import random
from datetime import timedelta

from . import analytics as an

CALLS = ("RESPECT", "CHOP", "DISRESPECT")
FLIP_BAND = 0.0025
GEX_BAND = 0.0015
RULE = __doc__.split("\n\n", 1)[1].strip()


def candles(rows, open_t, tf_min):
    """rows: [(datetime, price)] in time order. Buckets of tf_min minutes from open_t (the session open).
    Each candle opens at the previous close so the series has no gaps. Returns [{t, o, h, l, c, n}] (t = bucket start)."""
    out, cur, idx = [], None, None
    prev_close = None
    for t, p in rows:
        if t < open_t:
            prev_close = p
            continue
        k = int((t - open_t).total_seconds() // (tf_min * 60))
        if k != idx:
            if cur:
                out.append(cur)
                prev_close = cur["c"]
            o = prev_close if prev_close is not None else p
            cur = {"t": open_t + timedelta(minutes=k * tf_min), "o": o, "h": max(o, p), "l": min(o, p), "c": p, "n": 1}
            idx = k
        else:
            cur["h"], cur["l"], cur["c"], cur["n"] = max(cur["h"], p), min(cur["l"], p), p, cur["n"] + 1
    if cur:
        out.append(cur)
    return out


def local_gex(strikes, value, spot):
    return sum(s["net_gex"] for s in strikes if abs(s["strike"] - value) <= GEX_BAND * spot)


def call_for(level, state, spot, flips, strikes, gex_scale):
    """The call for one level. level: {value, category, members:[categories]}. state: short, long, transition or unknown."""
    cats = {level["category"], *level.get("members", [])}
    v = level["value"]
    g = local_gex(strikes, v, spot)
    strength = min(1.0, abs(g) / gex_scale) if gex_scale else 0.0
    long_g = state != "short"                                            # transition and unknown lean on the calmer reading
    if cats & {"gamma_flip", "gex0_flip"} or any(f and abs(v - f) / spot < FLIP_BAND for f in flips):
        return "CHOP", "At the gamma flip: dealers switch from absorbing moves to adding to them here, so price tends to stall and swing both ways.", max(strength, 0.5), g
    if cats & {"expected_move", "expected_move_ext"} and not (cats - {"expected_move", "expected_move_ext"}):
        return (("RESPECT", "Edge of what options priced for the day; in long gamma moves usually fade before or at it.", 0.5, g) if long_g else
                ("DISRESPECT", "Edge of what options priced for the day; short-gamma days often run past it.", 0.5, g))
    if strength < 0.1:
        return (("RESPECT", "Little dealer gamma here; in long gamma the default is a fade.", strength, g) if long_g else
                ("DISRESPECT", "Little dealer gamma here; in short gamma the default is that moves carry through.", strength, g))
    if g > 0:
        return (("RESPECT", "Positive dealer gamma at this level in a long-gamma session: dealers sell into rallies and buy dips here.", strength, g) if long_g else
                ("CHOP", "Positive dealer gamma can stall a short-gamma trend here for a while before it resumes.", strength, g))
    return ("DISRESPECT", ("Negative dealer gamma at this level: hedging adds to the move, so breaks tend to run to the next level."
                           if not long_g else "A negative-gamma pocket inside a long-gamma session: price tends to move through it quickly."), strength, g)


def level_calls(zones, snap, now, state, flips, convention="standard", record=None, window=0.015):
    """zones: from levels_payload (value, category, label, low, high, inputs.members). Keeps those within `window` of price."""
    spot = snap.spot
    strikes = an.gex_by_strike(snap.contracts, spot, now, convention)["strikes"]
    near = [s for s in strikes if abs(s["strike"] - spot) <= 0.03 * spot]
    scale = max((abs(local_gex(near, s["strike"], spot)) for s in near), default=0.0)
    out = []
    for z in zones:
        if abs(z["value"] - spot) > window * spot:
            continue
        mem = [m["category"] for m in (z.get("inputs") or {}).get("members", [])]
        lv = {"value": z["value"], "category": z["category"], "members": mem}
        c, why, strength, g = call_for(lv, state, spot, flips, strikes, scale)
        rec = None
        for cat in [z["category"], *mem]:
            r = (record or {}).get(cat.replace("_by_expiry", "").replace("_mid", ""))
            if r and r.get("measured_30"):
                rec = {"category": cat, "held_pct": r["held_pct_30"], "n": r["measured_30"], "enough": r["enough_data"]}
                break
        out.append({"label": z["label"], "category": z["category"], "value": z["value"], "low": z.get("low"), "high": z.get("high"),
                    "call": c, "why": why, "strength": round(strength, 3), "gex_at_level": g, "record": rec,
                    "side": "above" if z["value"] > spot else "below"})
    return sorted(out, key=lambda x: -x["value"])


def _next_level(levels, price, d, skip=None):
    cand = [l for l in levels if (l["value"] - price) * d > 0 and l is not skip]
    return min(cand, key=lambda l: abs(l["value"] - price)) if cand else None


def ghost_path(levels, spot, sd_c, n, start_dir, flip_first=False, seed=7):
    """Projected candles. levels: level_calls() rows. sd_c: one sd of a single candle's move. n: how many candles.
    start_dir: +1 up or -1 down. flip_first: turn the first level's call the other way (the alternate path).
    Returns {candles: [{o,h,l,c}], events: [{i, value, call, label}]}."""
    rng = random.Random(seed)
    p, d, out, ev = spot, start_dir, [], []
    first = True
    chop_left, chop_lvl, after_chop = 0, None, 0
    target = _next_level(levels, p, d)
    done = set()
    for i in range(n):
        o = p
        noise = rng.gauss(0, 0.35 * sd_c)
        if chop_left > 0:                                               # swing around the level, wicks both sides
            c = chop_lvl["value"] + (0.55 if chop_left % 2 else -0.55) * sd_c + noise * 0.4
            h, l = max(o, c) + abs(rng.gauss(0.45, 0.15)) * sd_c, min(o, c) - abs(rng.gauss(0.45, 0.15)) * sd_c
            chop_left -= 1
            if chop_left == 0:
                d = after_chop
                done.add(id(chop_lvl))
                target = _next_level([x for x in levels if id(x) not in done], c, d)
            out.append({"o": o, "h": h, "l": l, "c": c})
            p = c
            continue
        step = d * 0.75 * sd_c + noise
        c = o + step
        hit = target is not None and (c - target["value"]) * d >= -0.1 * sd_c
        if hit:
            call = target["call"]
            if first and flip_first:
                call = {"RESPECT": "DISRESPECT", "DISRESPECT": "RESPECT", "CHOP": "CHOP"}[call]
            ev.append({"i": i, "value": target["value"], "call": call, "label": target["label"]})
            v = target["value"]
            if call == "RESPECT":                                       # wick through, close back on the approach side, turn around
                wick = v + d * abs(rng.gauss(0.45, 0.12)) * sd_c
                c = v - d * abs(rng.gauss(0.55, 0.15)) * sd_c
                h, l = (max(o, wick, c), min(o, c) - 0.1 * sd_c) if d > 0 else (max(o, c) + 0.1 * sd_c, min(o, wick, c))
                done.add(id(target))
                d = -d
                target = _next_level([x for x in levels if id(x) not in done], c, d)
            elif call == "DISRESPECT":                                  # close through and keep going
                c = v + d * abs(rng.gauss(0.7, 0.15)) * sd_c
                h, l = max(o, c) + 0.15 * sd_c, min(o, c) - 0.15 * sd_c
                done.add(id(target))
                target = _next_level([x for x in levels if id(x) not in done], c, d)
            else:                                                       # chop for a few candles, then resolve
                c = v + d * 0.2 * sd_c
                h, l = max(o, c) + 0.3 * sd_c, min(o, c) - 0.3 * sd_c
                chop_left, chop_lvl = 4, target
                after_chop = (-d if flip_first and first else d)
            first = False
        else:
            h, l = max(o, c) + abs(rng.gauss(0.2, 0.1)) * sd_c, min(o, c) - abs(rng.gauss(0.2, 0.1)) * sd_c
        out.append({"o": o, "h": h, "l": l, "c": c})
        p = c
    return {"candles": out, "events": ev}


def prediction(level, side, beyond, back, state, chance):
    """Plain-English call for one level. side: 'above' or 'below' price. beyond: the next level further away on the same side,
    back: the level on the way back toward (and past) price. Returns {headline, plan}."""
    up = side == "above"
    nm = lambda l: f"{l['label'].split(' / ')[0]} ({l['value']:,.0f})" if l else "the next level"
    reach = "If price rallies up to it" if up else "If price drops down to it"
    c = level["call"]
    if c == "RESPECT":
        head = "Should hold as resistance" if up else "Should hold as support"
        plan = (f"{reach}, expect it to stall and reject: wicks {'above' if up else 'below'} it and closes back {'under' if up else 'over'}. "
                f"A fade from here aims back toward {nm(back)}. It only gives way if price closes through and holds; then {nm(beyond)} is next.")
    elif c == "DISRESPECT":
        head = "Should break"
        plan = (f"{reach}, expect it to give way: closes through it with little pause, then a run toward {nm(beyond)}. "
                f"Treat a quick reclaim back {'under' if up else 'over'} it as the sign the call failed.")
    else:
        head = "Should chop"
        plan = (f"{reach}, expect overlapping candles and wicks on both sides while dealers flip between absorbing and adding to the move. "
                f"Wait for a clean close away from it: {'above' if up else 'below'} points to {nm(beyond)}, back {'under' if up else 'over'} points to {nm(back)}.")
    if state == "short" and c != "DISRESPECT":
        plan += " Short gamma makes breaks more likely than usual today."
    elif state == "long" and c == "DISRESPECT":
        plan += " Long gamma means even breaks tend to slow down at the next level."
    return {"headline": head, "plan": plan, "chance": chance}
