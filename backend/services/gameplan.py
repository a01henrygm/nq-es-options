"""Game plan: every tool votes on each possible trade, and the best two or three come out as setup cards.

Candidates are the stacked areas (Stack map) and, if there are fewer than three, the strongest single levels price can reach. Each one
becomes a trade from its call:
  HOLD above price   SHORT, a fade at the level            HOLD below price   LONG, a fade at the level
  BREAK above price  LONG on a close through it            BREAK below price  SHORT on a close through it
  CHOP               no trade (listed under "stay away")
Stop: just past the far side of the area (at least 12% of the day's expected move). Target: the next level the trade points to; if that is
less than 1 R away, 2 R.

The team (each votes yes, no, or abstains):
  Coach        gamma regime: fades want long gamma, breaks want short gamma
  Scout        how stacked the area is: 4+ kinds yes, 3 kinds yes, a single level abstains
  Reach        the chance price gets to the entry today: 20%+ yes, under 8% no
  Timekeeper   "already in?": shorts want the high likely in (60%+), longs want the low likely in; under 30% is a no
  Referee      mean-reversion test: fades want a real pull (t below -2.9), breaks want no pull
  Odds maker   Monte Carlo from the entry: average result above 0 R yes, below -0.1 R no
  2nd opinion  ES/NQ residual: longs want NQ stronger than ES (z 1+), shorts want it weaker; abstains when they do not move together
  Clock        charm into the close: dealer selling helps shorts, dealer buying helps longs
  Film room    this app's touch log for the level type: fades want 55%+ held, breaks want 45% or less (10+ touches, otherwise abstains)

Grade: A = 5 or more yes and at most 1 no. B = 4 or more yes and yes beats no by 2+. C = more yes than no. Otherwise no trade.
My own rules and thresholds, not backtested. The log on the tab grades every card against what price did next.
"""
from __future__ import annotations

from . import quant as qt

RULE = __doc__.split("\n\n", 1)[1].strip()


def trade_for(c, spot, sigma_open, levels_sorted):
    """c: candidate {price, low, high, call, kinds, label}. levels_sorted: all candidate prices (for targets). Returns a trade dict or None."""
    above = c["price"] > spot
    if c["call"] == "CHOP":
        return None
    fade = c["call"] == "RESPECT"
    side = ("SHORT" if above else "LONG") if fade else ("LONG" if above else "SHORT")
    d = 1 if side == "LONG" else -1
    buf, floor = 0.04 * sigma_open, 0.12 * sigma_open
    if fade:                                   # enter at the level, stop just past the far side of the area
        entry = c["price"]
        far = c["high"] if side == "SHORT" else c["low"]
        stop_dist = max(abs(far - entry) + buf, floor)
    else:                                      # enter on a push through it, stop back on the near side of the area
        entry = c["price"] + d * 0.03 * sigma_open
        near = c["low"] if side == "LONG" else c["high"]
        stop_dist = max(abs(entry - near) + buf, floor)
    stop = entry - d * stop_dist
    nxt = [p for p in levels_sorted if (p - entry) * d > stop_dist * 0.5]
    target = min(nxt, key=lambda p: abs(p - entry)) if nxt else None
    r = abs(target - entry) / stop_dist if target is not None else None
    if r is None or r < 1:
        target, r = entry + d * 2 * stop_dist, 2.0
    return {"side": side, "kind": "fade" if fade else "break", "entry": entry, "stop": stop, "target": target, "stop_dist": stop_dist, "r": r}


def votes_for(t, c, ctx):
    """ctx: state, already_in, mr, pca, drift, record (held pct, n), chance, ev_r. Returns [(name, True/False/None, reason)]."""
    out = []
    long_ = t["side"] == "LONG"
    st = ctx["state"]
    if st in ("long", "short"):
        good = (t["kind"] == "fade") == (st == "long")
        out.append(("Coach", good, f"{'Long' if st == 'long' else 'Short'} gamma {'favours' if good else 'works against'} a {t['kind']}"))
    else:
        out.append(("Coach", None, "No clear regime (at the flip or unknown)"))
    k = c.get("kinds", 1)
    out.append(("Scout", True if k >= 3 else None, f"{k} different kinds stacked here" if k > 1 else "A single level, not a stack"))
    ch = ctx.get("chance")
    if ch is not None:
        out.append(("Reach", True if ch >= 0.2 else False if ch < 0.08 else None, f"{ch * 100:.0f}% chance price gets to the entry today"))
    ai = ctx.get("already_in")
    if ai:
        p = ai["low"] if long_ else ai["high"]
        nm = "low" if long_ else "high"
        out.append(("Timekeeper", True if p >= 0.6 else False if p < 0.3 else None, f"Today's {nm} is {p * 100:.0f}% likely already in"))
    mr = ctx.get("mr") or {}
    if mr.get("available"):
        if t["kind"] == "fade":
            out.append(("Referee", True if mr["significant"] else False if mr["lean"] == "trend" else None, f"Mean-reversion test: {mr['verdict'].split(':')[0].lower()} (t {mr['t_stat']:.1f})"))
        else:
            out.append(("Referee", True if mr["lean"] == "trend" else False if mr["significant"] else None, f"Mean-reversion test: {mr['verdict'].split(':')[0].lower()} (t {mr['t_stat']:.1f})"))
    ev = ctx.get("ev_r")
    if ev is not None:
        out.append(("Odds maker", True if ev > 0 else False if ev < -0.1 else None, f"Monte Carlo: {ctx['p_win'] * 100:.0f}% target first, average {ev:+.2f} R"))
    pc = ctx.get("pca") or {}
    if pc.get("available") and (pc.get("correlation") or 0) >= 0.5:
        z = pc["residual_z"]
        good = z >= 1 if long_ else z <= -1
        bad = z <= -1 if long_ else z >= 1
        out.append(("2nd opinion", True if good else False if bad else None, f"NQ vs ES residual {z:+.1f} z ({'stronger' if z > 0 else 'weaker'} than ES)"))
    else:
        out.append(("2nd opinion", None, "NQ and ES comparison not available or not moving together"))
    dr = ctx.get("drift")
    if dr:
        good = (dr < 0) if long_ else (dr > 0)
        out.append(("Clock", good, f"Charm: dealers {'buy' if dr < 0 else 'sell'} into the close"))
    rec = ctx.get("record")
    if rec and rec.get("n", 0) >= 10 and rec.get("held_pct") is not None:
        h = rec["held_pct"]
        good = h >= 0.55 if t["kind"] == "fade" else h <= 0.45
        bad = h < 0.45 if t["kind"] == "fade" else h > 0.55
        out.append(("Film room", True if good else False if bad else None, f"This level type held {h * 100:.0f}% of {rec['n']} logged touches"))
    else:
        out.append(("Film room", None, "Not enough logged touches of this level type yet"))
    return out


def grade(votes):
    yes = sum(1 for _, v, _ in votes if v is True)
    no = sum(1 for _, v, _ in votes if v is False)
    if yes >= 5 and no <= 1:
        g = "A"
    elif yes >= 4 and yes - no >= 2:
        g = "B"
    elif yes > no:
        g = "C"
    else:
        g = "No trade"
    return g, yes, no


def outcome(card, prices):
    """prices: [(datetime, price)] after the card was made. Did price reach the entry, then the target or the stop first?"""
    filled, res = False, "not filled"
    long_ = card["side"] == "LONG"
    for _, p in prices:
        if not filled:
            if (card["kind"] == "fade" and ((long_ and p <= card["entry"]) or (not long_ and p >= card["entry"]))) or \
               (card["kind"] == "break" and ((long_ and p >= card["entry"]) or (not long_ and p <= card["entry"]))):
                filled, res = True, "open"
            continue
        if (long_ and p <= card["stop"]) or (not long_ and p >= card["stop"]):
            return "stop"
        if (long_ and p >= card["target"]) or (not long_ and p <= card["target"]):
            return "target"
    return res
