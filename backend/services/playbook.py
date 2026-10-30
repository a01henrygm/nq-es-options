"""Playbook tab: the biggest levels on a candle chart, and how to react to them in three scenarios (bullish, bearish, choppy),
with the one that fits today picked from the app's own readings.

Pure logic, no web or database code. Prices come in index units with a unit function `u` that turns them into the units shown
(NQ / ES points when a futures price or basis is saved).

Levels: every Level map level (GEX, walls, flips, OI, volume, charm / vanna, dealer delta,
expected-move edges and the rest), each with a reaction in all three plans.
The major ones (top 4 a side by dealer gamma at the level, with a bonus for flips, walls and stacked kinds) anchor the plans.

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


GEX_CATS = ("gamma_flip", "gex0_flip", "gex0_call_wall", "gex0_put_wall", "gex_concentration", "gex_call_zone", "gex_put_zone",
            "gex_pos_zone", "gex_neg_zone", "call_wall", "put_wall", "zero_dte_call_wall", "zero_dte_put_wall")


def _is_gex(l) -> bool:
    """A GEX level: any gamma level (GEX strike, GEX zone, gamma flip, call / put wall), also when it is merged into a row
    whose first name is something else (rows at the same price are joined as "A / B / C")."""
    lab = (l.get("label") or "").lower()
    return l.get("category") in GEX_CATS or "gex" in lab or "gamma" in lab or "flip" in lab or "wall" in lab


def _is_key(l) -> bool:
    lab = (l.get("label") or "").lower()
    return l.get("category") in KEY_CATS or "flip" in lab or "wall" in lab


def biggest(levels, spot, sig, per_side=None, major_per_side=4):
    """Every level (1.26.0: all of them, not just the top few near price). levels: Level map rows (value, call, strength, label,
    category, low, high, chance). Keeps up to `per_side` levels on each side within about 3 expected moves, nearest first, and
    marks the strongest `major_per_side` on each side as major (the ones the plans and projected candles are built around)."""
    reach = float("inf")                                               # 1.26.0: every Level map level, however far
    gex_reach = reach                                                  # GEX levels are always kept (never squeezed out by others)
    near = [l for l in levels if abs(l["value"] - spot) <= (gex_reach if _is_gex(l) else reach)]

    def score(l):
        return (l.get("strength") or 0) + (0.6 if _is_key(l) else 0) + 0.25 * (l.get("label") or "").count(" / ")
    out = []
    for side in ("above", "below"):
        arr = [l for l in near if (l["value"] > spot) == (side == "above")]
        gex = [l for l in arr if _is_gex(l)]
        rest = sorted((l for l in arr if not _is_gex(l) and abs(l["value"] - spot) <= reach), key=lambda l: abs(l["value"] - spot))
        arr = gex + (rest if per_side is None else rest[:max(0, per_side - len(gex))])
        arr = sorted(arr, key=lambda l: abs(l["value"] - spot))
        top = {id(l) for l in sorted(arr, key=lambda l: -score(l))[:major_per_side]}
        out += [dict(l, score=round(score(l), 3), side=side, major=id(l) in top, gex=_is_gex(l)) for l in arr]
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
    """Short name: the first name, plus the GEX name when the first one is not a GEX level (so GEX always shows)."""
    parts = (l.get("label") or "level").split(" / ")
    g = (next((x for x in parts if "gex" in x.lower()), None)
         or next((x for x in parts if any(w in x.lower() for w in ("gamma", "flip", "wall"))), None))
    return parts[0] if g is None or g == parts[0] else f"{parts[0]} ({g})"


CALLW = {"RESPECT": "HOLD", "CHOP": "CHOP", "DISRESPECT": "BREAK"}

# What to do at one level in one plan, by the level's role in that plan and its call (HOLD / CHOP / BREAK).
ACT = {
    "guard_bull": {"HOLD": "Line in the sand. Dips into it are the best long: wick under, close back above, buy.",
                   "CHOP": "Line in the sand, but expect wicks both sides. Buy only after a close back above it.",
                   "BREAK": "Line in the sand, and it is weak. A close under it ends the bullish plan: flat, no more longs."},
    "dip_bull": {"HOLD": "Dip-buy level: should hold. Buy the first touch that closes back above.",
                 "CHOP": "Pullbacks stall and chop here. Wait for a reclaim candle before buying.",
                 "BREAK": "Should not hold. Do not buy it; let price fall to the next support before looking for a long."},
    "res_bull": {"HOLD": "Will likely reject first. Take partials into it, then buy the pullback that holds and the close through.",
                 "CHOP": "Expect overlap and fake breaks here. Add only on a clean close above.",
                 "BREAK": "Should give way fast. Buy the retest from above after it breaks."},
    "tgt_bull": {"HOLD": "Target: take profit into it. It should hold, so expect a pullback.",
                 "CHOP": "Target: take most off here. Price should stall and chop.",
                 "BREAK": "Target: take some off, trail the rest. It may give way."},
    "off_bull": {"HOLD": "Below the line in the sand: the bullish plan is already off here. Bearish plan rules.",
                 "CHOP": "Below the line in the sand: the bullish plan is already off here. Bearish plan rules.",
                 "BREAK": "Below the line in the sand: the bullish plan is already off here. Bearish plan rules."},
    "guard_bear": {"HOLD": "Ceiling. Rallies into it are the best short: wick above, close back under, sell.",
                   "CHOP": "Ceiling, but expect wicks both sides. Short only after a close back under it.",
                   "BREAK": "Ceiling, and it is weak. A close above it ends the bearish plan: flat, no more shorts."},
    "pop_bear": {"HOLD": "Rally-sell level: should hold. Short the first touch that closes back under.",
                 "CHOP": "Bounces stall and chop here. Wait for a rejection candle before shorting.",
                 "BREAK": "Should not hold. Do not short it; let price reach the next resistance first."},
    "sup_bear": {"HOLD": "Will likely bounce first. Take partials into it, then short the bounce that fails and the close under.",
                 "CHOP": "Expect overlap and fake breaks here. Add only on a clean close below.",
                 "BREAK": "Should give way fast. Short the retest from below after it breaks."},
    "tgt_bear": {"HOLD": "Target: cover into it. It should hold, so expect a bounce.",
                 "CHOP": "Target: cover most here. Price should stall and chop.",
                 "BREAK": "Target: cover some, trail the rest. It may give way."},
    "off_bear": {"HOLD": "Above the ceiling: the bearish plan is already off here. Bullish plan rules.",
                 "CHOP": "Above the ceiling: the bearish plan is already off here. Bullish plan rules.",
                 "BREAK": "Above the ceiling: the bearish plan is already off here. Bullish plan rules."},
    "edge_top": {"HOLD": "Top of the range: fade it. Short a wick above that closes back under.",
                 "CHOP": "Top of the range: fade it, but expect a poke through first. Short the close back under.",
                 "BREAK": "Top of the range, but weak. Fade only small; a close above flips you to the bullish plan."},
    "edge_bottom": {"HOLD": "Bottom of the range: fade it. Buy a wick under that closes back above.",
                    "CHOP": "Bottom of the range: fade it, but expect a poke through first. Buy the close back above.",
                    "BREAK": "Bottom of the range, but weak. Fade only small; a close below flips you to the bearish plan."},
    "inside": {"HOLD": "Inside the range. Take partials on fades here; a quick scalp off it is OK, nothing bigger.",
               "CHOP": "Inside the range: no edge. Take partials on fades, no new trades.",
               "BREAK": "Inside the range: price should slide through it. Use it only to manage fades."},
    "out_top": {"HOLD": "Above the range: the range already broke if price gets here. Bullish plan: take profit into it.",
                "CHOP": "Above the range: the range already broke. Bullish plan: it should stall here.",
                "BREAK": "Above the range: the range already broke. Bullish plan: it should give way."},
    "out_bottom": {"HOLD": "Below the range: the range already broke if price gets here. Bearish plan: cover into it.",
                   "CHOP": "Below the range: the range already broke. Bearish plan: it should stall here.",
                   "BREAK": "Below the range: the range already broke. Bearish plan: it should give way."},
    "middle": {"CHOP": "Middle of the range: no edge here. Take profit on fades, do not start new trades."},
}
ROLE = {"guard_bull": "Line in the sand", "dip_bull": "Buy the dip", "res_bull": "Work through", "tgt_bull": "Target",
        "off_bull": "Plan off", "guard_bear": "Ceiling", "pop_bear": "Sell the rally", "sup_bear": "Work through",
        "tgt_bear": "Target", "off_bear": "Plan off", "edge_top": "Fade the top", "edge_bottom": "Fade the bottom",
        "inside": "Inside range", "out_top": "Range broke", "out_bottom": "Range broke", "middle": "Range middle"}
# A short tag for the chart marker at the level, by role and call.
TAG = {"guard_bull": "BUY / STOP", "dip_bull": {"HOLD": "BUY", "CHOP": "BUY RECLAIM", "BREAK": "SKIP"},
       "res_bull": {"HOLD": "PARTIAL", "CHOP": "ADD > CLOSE", "BREAK": "BUY RETEST"}, "tgt_bull": "TP", "off_bull": "PLAN OFF",
       "guard_bear": "SELL / STOP", "pop_bear": {"HOLD": "SELL", "CHOP": "SELL REJECT", "BREAK": "SKIP"},
       "sup_bear": {"HOLD": "PARTIAL", "CHOP": "ADD < CLOSE", "BREAK": "SELL RETEST"}, "tgt_bear": "TP", "off_bear": "PLAN OFF",
       "edge_top": "FADE SHORT", "edge_bottom": "FADE LONG", "inside": "PARTIAL", "out_top": "RANGE BROKE", "out_bottom": "RANGE BROKE", "middle": "TP"}
# Old role names (1.25.0) kept so anything reading them still works.
_act = lambda role, call, up=True: ACT.get(role, ACT["middle"]).get(call) or ACT["middle"]["CHOP"]


def _zone(l, zh):
    lo, hi = l.get("low"), l.get("high")
    if lo and hi and hi > lo:
        return lo, hi
    return l["value"] - zh / 2, l["value"] + zh / 2


def _trade(role, call, l, nxt, zh, buf):
    """Entry / stop / target (index units) for a level in a plan, or None where the plan does not trade it."""
    lo, hi = _zone(l, zh)
    v = l["value"]
    tg = nxt["value"] if nxt is not None else None
    if role in ("guard_bull", "dip_bull", "edge_bottom") and call != "BREAK" or role == "guard_bull":
        if role == "guard_bull" and call == "BREAK":
            return {"side": "flat", "entry": None, "stop": lo - buf, "target": None}
        return {"side": "long", "entry": hi if call == "HOLD" else v + buf / 2, "stop": lo - buf, "target": tg}
    if role in ("guard_bear", "pop_bear", "edge_top") and call != "BREAK" or role == "guard_bear":
        if role == "guard_bear" and call == "BREAK":
            return {"side": "flat", "entry": None, "stop": hi + buf, "target": None}
        return {"side": "short", "entry": lo if call == "HOLD" else v - buf / 2, "stop": hi + buf, "target": tg}
    if role == "res_bull" and call == "BREAK":
        return {"side": "long", "entry": hi, "stop": lo - buf, "target": tg}
    if role == "sup_bear" and call == "BREAK":
        return {"side": "short", "entry": lo, "stop": hi + buf, "target": tg}
    if role in ("res_bull", "sup_bear") and call == "CHOP":
        up = role == "res_bull"
        return {"side": "long" if up else "short", "entry": (hi + buf / 2) if up else (lo - buf / 2), "stop": (lo - buf) if up else (hi + buf), "target": tg}
    return None


_tp = lambda i: f"TP{i + 1}" if i < 3 else "RUNNER"


def _row(l, role, u, zh=0.0, buf=0.0, nxt=None, tag=None):
    call = CALLW.get(l["call"], "CHOP")
    if tag is None:
        tag = TAG.get(role, "")
        tag = tag.get(call, "") if isinstance(tag, dict) else tag
    tr = _trade(role, call, l, nxt, zh, buf) if zh else None
    if tr:
        tr = {"side": tr["side"], "entry": u(tr["entry"]) if tr["entry"] is not None else None,
              "stop": u(tr["stop"]) if tr["stop"] is not None else None, "target": u(tr["target"]) if tr["target"] is not None else None}
    return {"price": u(l["value"]), "low": u(l["low"]) if l.get("low") else None, "high": u(l["high"]) if l.get("high") else None,
            "label": l.get("label"), "call": call, "role": role, "role_title": ROLE.get(role, role), "tag": tag,
            "action": _act(role, call), "chance": l.get("chance"), "major": bool(l.get("major")), "gex": _is_gex(l), "trade": tr}


def scenarios(big, spot, sig, u, walls=None):
    """The three plans, with a row for EVERY level in `big` in each plan. big: biggest() rows.
    walls: {call_wall, put_wall, flip} in index units (any may be None)."""
    walls = walls or {}
    up = sorted((l for l in big if l["value"] > spot), key=lambda l: l["value"])          # nearest first
    dn = sorted((l for l in big if l["value"] <= spot), key=lambda l: -l["value"])
    sd = sig or 0.006 * spot
    zh, buf = max(0.06 * sd, 0.00005 * spot), 0.08 * sd
    f = lambda v: f"{u(v):,.2f}" if u(v) is not None else "-"
    major = lambda arr: [l for l in arr if l.get("major", True)] or arr
    nxt = lambda arr, i: arr[i + 1] if i + 1 < len(arr) else None
    out = {}

    # BULLISH: the strongest support below is the line in the sand; supports between it and price are dip buys; levels above are
    # worked through, and the far ones (beyond about one expected move, or the last two) are targets.
    sup = max(dn, key=lambda l: l["score"]) if dn else None
    far_up = [l for l in up if l["value"] - spot >= 0.9 * sd]
    tgt = far_up if far_up else up[-2:]                    # every level past about one expected move is a target (TP1, TP2, ...)
    rows = []
    for i, l in enumerate(dn):
        role = "guard_bull" if l is sup else "dip_bull" if sup is None or l["value"] > sup["value"] else "off_bull"
        rows.append(_row(l, role, u, zh, buf, up[0] if up else None))
    for i, l in enumerate(up):
        rows.append(_row(l, "tgt_bull", u, zh, buf, nxt(up, i), _tp(tgt.index(l))) if l in tgt else _row(l, "res_bull", u, zh, buf, nxt(up, i)))
    out["bullish"] = {"trigger": (f"Holds above {_nm(sup)} ({f(sup['value'])}) and closes above {_nm(up[0])} ({f(up[0]['value'])})" if sup and up else
                                  "Holds the dips and makes higher lows"),
                      "invalid": f"A close below {_nm(sup)} ({f(sup['value'])})" if sup else f"A close below {f(spot - 0.5 * sd)}",
                      "targets": [u(l["value"]) for l in tgt[:3]], "levels": sorted(rows, key=lambda r: -(r["price"] or 0)),
                      "plan": "Buy pullbacks that hold support, add on closes through resistance, take profit into the targets."}

    res = max(up, key=lambda l: l["score"]) if up else None
    far_dn = [l for l in dn if spot - l["value"] >= 0.9 * sd]
    tgt = far_dn if far_dn else dn[-2:]
    rows = []
    for i, l in enumerate(up):
        role = "guard_bear" if l is res else "pop_bear" if res is None or l["value"] < res["value"] else "off_bear"
        rows.append(_row(l, role, u, zh, buf, dn[0] if dn else None))
    for i, l in enumerate(dn):
        rows.append(_row(l, "tgt_bear", u, zh, buf, nxt(dn, i), _tp(tgt.index(l))) if l in tgt else _row(l, "sup_bear", u, zh, buf, nxt(dn, i)))
    out["bearish"] = {"trigger": (f"Stays under {_nm(res)} ({f(res['value'])}) and closes below {_nm(dn[0])} ({f(dn[0]['value'])})" if res and dn else
                                  "Fails the rallies and makes lower highs"),
                      "invalid": f"A close above {_nm(res)} ({f(res['value'])})" if res else f"A close above {f(spot + 0.5 * sd)}",
                      "targets": [u(l["value"]) for l in tgt[:3]], "levels": sorted(rows, key=lambda r: -(r["price"] or 0)),
                      "plan": "Short rallies that fail under resistance, add on closes through support, take profit into the targets."}

    # CHOPPY: the range between the strongest HOLD / CHOP levels within about one expected move (or the 0DTE walls)
    hold = lambda arr: [l for l in major(arr) if l["call"] in ("RESPECT", "CHOP")]
    edge = lambda arr: (max((l for l in hold(arr) if abs(l["value"] - spot) <= 1.2 * sd), key=lambda l: l["score"], default=None)
                        or (hold(arr)[0] if hold(arr) else None) or (arr[0] if arr else None))
    top, bot = edge(up), edge(dn)
    hi_v = top["value"] if top else (walls.get("call_wall") if walls.get("call_wall") and walls["call_wall"] > spot else spot + 0.5 * sd)
    lo_v = bot["value"] if bot else (walls.get("put_wall") if walls.get("put_wall") and walls["put_wall"] < spot else spot - 0.5 * sd)
    mid = (hi_v + lo_v) / 2
    mid_l = {"value": mid, "call": "CHOP", "label": "Range middle"}
    rows = []
    for l in up + dn:
        v = l["value"]
        role = ("edge_top" if l is top else "edge_bottom" if l is bot else "out_top" if v > hi_v else "out_bottom" if v < lo_v else "inside")
        rows.append(_row(l, role, u, zh, buf, mid_l))
    rows.append({"price": u(mid), "low": None, "high": None, "label": "Range middle", "call": "CHOP", "role": "middle", "role_title": ROLE["middle"],
                 "tag": "TP", "action": _act("middle", "CHOP"), "chance": None, "major": True, "gex": False, "trade": None})
    out["choppy"] = {"trigger": f"Stays between {f(lo_v)} and {f(hi_v)}: wicks at the edges, closes back inside",
                     "invalid": f"A close outside {f(lo_v)} to {f(hi_v)}: switch to the bullish plan above it, the bearish plan below it",
                     "targets": [u(mid)], "range": {"high": u(hi_v), "low": u(lo_v), "mid": u(mid)},
                     "levels": sorted(rows, key=lambda r: -(r["price"] or 0)),
                     "plan": "Fade the edges, take profit in the middle, stand aside in the middle."}
    out["_path"] = {"bullish": _waypoints_trend(spot, sup, major(up)[:4], sd, +1), "bearish": _waypoints_trend(spot, res, major(dn)[:4], sd, -1),
                    "choppy": [spot, hi_v - 0.05 * sd, mid, lo_v + 0.05 * sd, mid + 0.15 * sd, hi_v - 0.1 * sd, mid]}
    return out


def every_level(sc):
    """One row per level with its reaction in all three plans (the "Every level" table). sc: scenarios() output."""
    by = {}
    for k in SCEN:
        for r in sc[k]["levels"]:
            if r["role"] == "middle":
                continue
            d = by.setdefault(r["price"], {k_: r[k_] for k_ in ("price", "low", "high", "label", "call", "chance", "major", "gex")})
            d[k] = {k_: r[k_] for k_ in ("role", "role_title", "tag", "action", "trade")}
    return sorted(by.values(), key=lambda r: -(r["price"] or 0))


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


# What we expect price to do at a level, from its call and which side of price it is on (1.26.0).
EXPECT = {("above", "HOLD"): ("REJECT", "Should hold as resistance: expect a rejection, wicks above it and closes back under."),
          ("above", "CHOP"): ("CHOP", "Should chop: overlapping candles and wicks on both sides. Wait for a clean close away from it."),
          ("above", "BREAK"): ("BREAK UP", "Should give way: expect price to push through it, then use it as support on the retest."),
          ("below", "HOLD"): ("BOUNCE", "Should hold as support: expect a bounce, wicks under it and closes back above."),
          ("below", "CHOP"): ("CHOP", "Should chop: overlapping candles and wicks on both sides. Wait for a clean close away from it."),
          ("below", "BREAK"): ("BREAK DOWN", "Should give way: expect price to slice through it, then use it as resistance on the retest.")}


def expectations(big, spot, u):
    """{id(level): {tag, text, if_holds, if_breaks, why, record}} for every level: the reaction we expect there, in shown prices,
    and the next level price heads to if it holds or if it breaks."""
    order = sorted(big, key=lambda l: l["value"])
    out = {}
    for i, l in enumerate(order):
        side = "above" if l["value"] > spot else "below"
        call = CALLW.get(l["call"], "CHOP")
        tag, text = EXPECT[(side, call)]
        up = order[i + 1] if i + 1 < len(order) else None
        dn = order[i - 1] if i > 0 else None
        hold_to, break_to = (dn, up) if side == "above" else (up, dn)
        nm = lambda x: f"{_nm(x)} ({u(x['value']):,.2f})" if x is not None and u(x["value"]) is not None else None
        rec = l.get("record") or {}
        out[id(l)] = {"tag": tag, "text": text, "if_holds": nm(hold_to), "if_breaks": nm(break_to), "why": l.get("why"),
                      "record": (f"This kind held {round(100 * rec['held_pct'])}% of {rec['n']} touches" if rec.get("enough") and rec.get("n") else None)}
    return out
