"""Playbook tab: the biggest levels on a candle chart, and how to react to them in three scenarios (bullish, bearish, choppy),
with the one that fits today picked from the app's own readings.

Pure logic, no web or database code. Prices come in index units with a unit function `u` that turns them into the units shown
(NQ / ES points when a futures price or basis is saved).

The biggest levels: every Level map level within about 1.5 expected moves of price, ranked by the dealer gamma at the level
(strength), with a bonus for flips and walls and for levels where several kinds stack. The top few on each side are kept.

The three scenarios (each is a plan to picture, not a forecast):
  BULLISH  price holds above the main support below, works through the levels above and reaches the targets.
           Level calls decide how: HOLD levels above get a pullback before a close through, BREAK levels get bought on the retest,
           CHOP levels need a clean close above before adding. Invalid on a close below the main support.
  BEARISH  the mirror image: holds under the main resistance and works down. Invalid on a close above it.
  CHOPPY   price stays between the strongest HOLD / CHOP level above and below within about one expected move (else the nearest
           HOLD / CHOP level, else the 0DTE walls): fade the edges, take
           profit in the middle, stand aside in the middle. A close outside the range hands over to the bullish or bearish plan.

Which one fits today (a visible score, not backtested):
  long gamma +2 choppy (dealers fade moves), transition +1 choppy, short gamma +2 to the side price is moving (or the side of the flip)
  price above the 0DTE flip +1 bullish, below +1 bearish
  moved more than a quarter of an expected move from the open +1 to that side; in long gamma, already more than one +1 choppy
  dealer delta drift to the close: dealers must buy +1 bullish, must sell +1 bearish
  The highest score wins; a tie goes to choppy. Two or more points ahead = high confidence, one = medium, none = low.
"""
from __future__ import annotations
import random

SCEN = ("bullish", "bearish", "choppy")
TITLE = {"bullish": "Bullish", "bearish": "Bearish", "choppy": "Choppy"}
COLOR = {"bullish": "#16a34a", "bearish": "#dc2626", "choppy": "#d97706"}
RULE = __doc__.split("\n\n", 1)[1].strip()
KEY_CATS = ("gamma_flip", "gex0_flip", "call_wall", "put_wall", "zero_dte_call_wall", "zero_dte_put_wall")


def _is_key(l) -> bool:
    lab = (l.get("label") or "").lower()
    return l.get("category") in KEY_CATS or "flip" in lab or "wall" in lab


def biggest(levels, spot, sig, per_side=4):
    """The strongest levels near price. levels: Level map rows (value, call, strength, label, category, low, high, chance)."""
    reach = 1.5 * sig if sig else 0.015 * spot
    near = [l for l in levels if abs(l["value"] - spot) <= reach]

    def score(l):
        return (l.get("strength") or 0) + (0.6 if _is_key(l) else 0) + 0.25 * l.get("label", "").count(" / ")
    up = sorted((l for l in near if l["value"] > spot), key=lambda l: -score(l))[:per_side]
    dn = sorted((l for l in near if l["value"] <= spot), key=lambda l: -score(l))[:per_side]
    out = [dict(l, score=round(score(l), 3), side="above" if l["value"] > spot else "below") for l in up + dn]
    return sorted(out, key=lambda l: -l["value"])


def pick(state, spot, flip, moved_sd, drift, u=None):
    """Which scenario fits today. u: index price -> shown price (for the reasons). Returns (scenario, confidence, scores, reasons)."""
    u = u or (lambda v: v)
    sc = {k: 0 for k in SCEN}
    why = []
    trend = None
    if moved_sd is not None and abs(moved_sd) > 0.1:
        trend = "bullish" if moved_sd > 0 else "bearish"
    elif flip:
        trend = "bullish" if spot > flip else "bearish"
    if state == "long":
        sc["choppy"] += 2
        why.append(("choppy", 2, "Long gamma: dealers sell rallies and buy dips, so moves tend to fade back into a range."))
    elif state == "transition":
        sc["choppy"] += 1
        why.append(("choppy", 1, "Price is sitting on the 0DTE gamma flip, where the regime can switch: expect two-way trade first."))
    elif state == "short" and trend:
        sc[trend] += 2
        why.append((trend, 2, f"Short gamma: dealer hedging adds to moves, so the {'up' if trend == 'bullish' else 'down'} side tends to keep running."))
    if flip:
        s = "bullish" if spot > flip else "bearish"
        sc[s] += 1
        why.append((s, 1, f"Price is {'above' if spot > flip else 'below'} the 0DTE gamma flip ({u(flip):,.0f})."))
    if moved_sd is not None:
        if abs(moved_sd) > 0.25:
            s = "bullish" if moved_sd > 0 else "bearish"
            sc[s] += 1
            why.append((s, 1, f"Price is {abs(moved_sd):.1f} expected moves {'above' if moved_sd > 0 else 'below'} the open."))
        if state == "long" and abs(moved_sd) > 1:
            sc["choppy"] += 1
            why.append(("choppy", 1, "Already more than one expected move from the open in long gamma: the day's expansion is likely done."))
    if drift:
        s = "bullish" if drift < 0 else "bearish"
        sc[s] += 1
        why.append((s, 1, f"Dealer delta drift to the close: dealers would need to {'BUY' if drift < 0 else 'SELL'} to stay hedged."))
    order = sorted(SCEN, key=lambda k: (-sc[k], 0 if k == "choppy" else 1))
    best = order[0]
    if sc[best] == sc[order[1]] and "choppy" in (best, order[1]):
        best = "choppy"
    lead = sc[best] - max(v for k, v in sc.items() if k != best)
    conf = "high" if lead >= 2 else "medium" if lead == 1 else "low"
    return best, conf, sc, [{"scenario": s, "points": p, "reason": r} for s, p, r in why]


def _nm(l):
    return (l.get("label") or "level").split(" / ")[0]


def _act(role, call, up):
    """What to do at one level in one scenario. role: support, resistance, target, edge_top, edge_bottom, middle."""
    if role == "support":
        return {"HOLD": "Must hold. Dips into it are the bull entry: look for a wick under and a close back above.",
                "CHOP": "Expect a stall and wicks both sides; buy only once price closes back above it.",
                "BREAK": "Weak support (should break): a close under it ends the bullish plan."}[call]
    if role == "resistance":
        return {"HOLD": "First test likely rejects. Let it pull back and hold, then buy the close through it.",
                "CHOP": "Expect overlapping candles here. Add only on a clean close above.",
                "BREAK": "Should give way quickly: buy the retest from above after it breaks."}[call]
    if role == "resistance_bear":
        return {"HOLD": "Must hold as a ceiling. Rallies into it are the short entry: look for a wick above and a close back under.",
                "CHOP": "Expect a stall; short only once price closes back under it.",
                "BREAK": "Weak ceiling (should break): a close above it ends the bearish plan."}[call]
    if role == "support_bear":
        return {"HOLD": "First test likely bounces. Let it bounce and fail, then short the close under it.",
                "CHOP": "Expect overlapping candles here. Add only on a clean close below.",
                "BREAK": "Should give way quickly: short the retest from below after it breaks."}[call]
    if role == "target":
        return ("Target: take profit into it" + (" (it should hold, so expect a reaction)." if call == "HOLD" else
                                                   ". It may give way, so trail the rest." if call == "BREAK" else ", it should chop."))
    if role == "edge_top":
        return "Top of the range: fade it. Short a wick above that closes back under; stop just above the zone."
    if role == "edge_bottom":
        return "Bottom of the range: fade it. Buy a wick under that closes back above; stop just under the zone."
    return "Middle of the range: no edge here. Take profit on fades, do not start new trades."


CALLW = {"RESPECT": "HOLD", "CHOP": "CHOP", "DISRESPECT": "BREAK"}


def _row(l, role, u, up=True):
    call = CALLW.get(l["call"], "CHOP")
    return {"price": u(l["value"]), "low": u(l["low"]) if l.get("low") else None, "high": u(l["high"]) if l.get("high") else None,
            "label": l.get("label"), "call": call, "role": role, "action": _act(role, call, up), "chance": l.get("chance")}


def scenarios(big, spot, sig, u, walls=None):
    """The three plans. big: biggest() rows. walls: {call_wall, put_wall, flip} in index units (any may be None)."""
    walls = walls or {}
    up = sorted((l for l in big if l["value"] > spot), key=lambda l: l["value"])
    dn = sorted((l for l in big if l["value"] <= spot), key=lambda l: -l["value"])
    sd = sig or 0.006 * spot
    f = lambda v: f"{u(v):,.2f}" if u(v) is not None else "-"
    out = {}
    # bullish: the strongest support below is the line in the sand; the levels above are worked through toward the targets
    sup = max(dn, key=lambda l: l["score"]) if dn else None
    tgt = up[-2:] if len(up) >= 2 else up
    rows = ([_row(sup, "support", u)] if sup else []) + [_row(l, "target" if l in tgt else "resistance", u) for l in up]
    out["bullish"] = {"trigger": (f"Holds above {_nm(sup)} ({f(sup['value'])}) and closes above {_nm(up[0])} ({f(up[0]['value'])})" if sup and up else
                                  "Holds the dips and makes higher lows"),
                      "invalid": f"A close below {_nm(sup)} ({f(sup['value'])})" if sup else f"A close below {f(spot - 0.5 * sd)}",
                      "targets": [u(l["value"]) for l in tgt], "levels": sorted(rows, key=lambda r: -(r["price"] or 0)),
                      "plan": "Buy pullbacks that hold support, add on closes through resistance, take profit into the targets."}
    res = max(up, key=lambda l: l["score"]) if up else None
    tgt = dn[-2:] if len(dn) >= 2 else dn
    rows = ([_row(res, "resistance_bear", u)] if res else []) + [_row(l, "target" if l in tgt else "support_bear", u) for l in dn]
    out["bearish"] = {"trigger": (f"Stays under {_nm(res)} ({f(res['value'])}) and closes below {_nm(dn[0])} ({f(dn[0]['value'])})" if res and dn else
                                  "Fails the rallies and makes lower highs"),
                      "invalid": f"A close above {_nm(res)} ({f(res['value'])})" if res else f"A close above {f(spot + 0.5 * sd)}",
                      "targets": [u(l["value"]) for l in tgt], "levels": sorted(rows, key=lambda r: -(r["price"] or 0)),
                      "plan": "Short rallies that fail under resistance, add on closes through support, take profit into the targets."}
    # choppy: the range between the strongest HOLD / CHOP levels within one expected move (or the 0DTE walls)
    hold = lambda arr: [l for l in arr if l["call"] in ("RESPECT", "CHOP")]
    edge = lambda arr: (max((l for l in hold(arr) if abs(l["value"] - spot) <= 1.2 * sd), key=lambda l: l["score"], default=None)
                        or (hold(arr)[0] if hold(arr) else None) or (arr[0] if arr else None))
    top, bot = edge(up), edge(dn)
    hi_v = top["value"] if top else (walls.get("call_wall") if walls.get("call_wall") and walls["call_wall"] > spot else spot + 0.5 * sd)
    lo_v = bot["value"] if bot else (walls.get("put_wall") if walls.get("put_wall") and walls["put_wall"] < spot else spot - 0.5 * sd)
    mid = (hi_v + lo_v) / 2
    rows = []
    if top:
        rows.append(_row(top, "edge_top", u))
    rows.append({"price": u(mid), "low": None, "high": None, "label": "Range middle", "call": "CHOP", "role": "middle", "action": _act("middle", "CHOP", True), "chance": None})
    if bot:
        rows.append(_row(bot, "edge_bottom", u))
    out["choppy"] = {"trigger": f"Stays between {f(lo_v)} and {f(hi_v)}: wicks at the edges, closes back inside",
                     "invalid": f"A close outside {f(lo_v)} to {f(hi_v)}: switch to the bullish plan above it, the bearish plan below it",
                     "targets": [u(mid)], "range": {"high": u(hi_v), "low": u(lo_v), "mid": u(mid)}, "levels": rows,
                     "plan": "Fade the edges, take profit in the middle, stand aside in the middle."}
    out["_path"] = {"bullish": _waypoints_trend(spot, sup, up, sd, +1), "bearish": _waypoints_trend(spot, res, dn, sd, -1),
                    "choppy": [spot, hi_v - 0.05 * sd, mid, lo_v + 0.05 * sd, mid + 0.15 * sd, hi_v - 0.1 * sd, mid]}
    return out


def _waypoints_trend(spot, guard, ahead, sd, d):
    """Price waypoints for a trend plan: a pullback toward the guard level (that holds), then each level ahead, pausing at HOLD / CHOP."""
    w = [spot]
    if guard is not None:
        w.append(spot + (guard["value"] - spot) * 0.55)
    else:
        w.append(spot - d * 0.2 * sd)
    for l in ahead:
        v = l["value"]
        if l["call"] == "RESPECT":
            w += [v - d * 0.05 * sd, v - d * 0.35 * sd, v + d * 0.1 * sd]
        elif l["call"] == "CHOP":
            w += [v + d * 0.05 * sd, v - d * 0.2 * sd, v + d * 0.08 * sd, v - d * 0.1 * sd, v + d * 0.15 * sd]
        else:
            w += [v + d * 0.2 * sd, v + d * 0.05 * sd]
    if len(w) <= 2:
        w += [spot + d * 0.6 * sd, spot + d * 0.4 * sd, spot + d * 0.9 * sd]
    return w


def path(waypoints, n, u, seed=11):
    """n candles that walk through the waypoints (index units), returned in display units {o, h, l, c}."""
    rng = random.Random(seed)
    if len(waypoints) < 2 or n < 2:
        return []
    legs = [abs(b - a) for a, b in zip(waypoints, waypoints[1:])]
    tot = sum(legs) or 1.0
    counts = [max(1, round(n * x / tot)) for x in legs]
    span = max(waypoints) - min(waypoints) or 1.0
    noise = span / max(n, 1) * 0.6
    out, p = [], waypoints[0]
    for (a, b), k in zip(zip(waypoints, waypoints[1:]), counts):
        for i in range(1, k + 1):
            o = p
            c = a + (b - a) * i / k + rng.gauss(0, noise * 0.5)
            h = max(o, c) + abs(rng.gauss(0.5, 0.3)) * noise
            lo = min(o, c) - abs(rng.gauss(0.5, 0.3)) * noise
            out.append({"o": u(o), "h": u(h), "l": u(lo), "c": u(c)})
            p = c
    return out
