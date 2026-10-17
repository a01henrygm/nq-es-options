"""The written case for the day: why it may lean bullish, why it may lean bearish, what is neutral, and the levels that decide it.

Every point comes from a number the app measured, and says which number. The weights are simple and stated (strong = 2, normal = 1).
It describes option positioning and what it implies for dealer hedging; it is not a forecast and has not been tested against outcomes.
"""
from __future__ import annotations


def _f(x, d=0):
    return "-" if x is None else f"{x:,.{d}f}"


def _low(t):
    """Lower-case the first letter for use mid-sentence, but keep words like 0DTE as they are."""
    return t[:1].lower() + t[1:] if t[:1].isalpha() and not t[:2].isupper() else t


def build_case(bias: dict, zero: dict | None = None, regime: dict | None = None, flow: dict | None = None,
               oi_shift: dict | None = None, session: dict | None = None) -> dict:
    """bias: compute_bias output. zero: intraday.zero_dte. regime: compute_regime. flow: {"net_change_60m", "calls", "puts", "calls0", "puts0"}.
    oi_shift: {"calls_added_above", "puts_added_below", "calls_added_below", "puts_added_above"}. session: {"open", "move_points", "day_move"}."""
    lv = bias.get("levels") or {}
    spot, flip, cw, pw = lv.get("spot"), lv.get("flip"), lv.get("call_wall"), lv.get("put_wall")
    em = lv.get("expected_move") or {}
    bull, bear, neutral = [], [], []

    def pt(side, title, detail, w=1):
        (bull if side > 0 else bear if side < 0 else neutral).append({"title": title, "detail": detail, "weight": w})

    # 1. where price sits against the walls
    if spot and cw and pw:
        up, dn = cw - spot, spot - pw
        if up > 1.5 * dn:
            pt(1, "More room up than down", f"{_f(up)} points of room up to the call wall {_f(cw)} against {_f(dn)} down to the put wall {_f(pw)}. Dealer hedging usually resists price near walls, so the open space is overhead.")
        elif dn > 1.5 * up:
            pt(-1, "More room down than up", f"{_f(dn)} points of room down to the put wall {_f(pw)} against {_f(up)} up to the call wall {_f(cw)}. The open space is below.")
        else:
            pt(0, "Price is mid-range between the walls", f"Call wall {_f(cw)} is {_f(up)} up, put wall {_f(pw)} is {_f(dn)} down: no side has clearly more room.")

    # 2. gamma regime and the flip (sets the character of the day; direction comes from which side of it price holds)
    if spot and flip:
        if spot > flip:
            pt(1, "Holding above the gamma flip", f"Price {_f(spot)} is {_f(spot - flip)} points above the flip {_f(flip)}. Above it dealers are long gamma: they buy dips and sell rips, which tends to support price and slow selloffs.", 2)
        else:
            pt(-1, "Below the gamma flip", f"Price {_f(spot)} is {_f(flip - spot)} points below the flip {_f(flip)}. Below it dealers are short gamma: they sell into drops and buy into rallies, which can speed up selloffs.", 2)

    # 3. same-day (0DTE) positioning
    if zero and zero.get("available"):
        tag = "0DTE" if zero.get("is_today") else "front-expiry"
        g0 = zero.get("exposure_at_spot")
        if g0 is not None:
            if g0 < 0:
                pt(-1, f"{tag} gamma is negative at price", f"Today's options alone leave dealers short gamma at {_f(spot)}: intraday moves can extend instead of reverting.", 2)
            else:
                pt(1 if spot and flip and spot > flip else 0, f"{tag} gamma is positive at price", f"Today's options alone leave dealers long gamma at {_f(spot)}: moves tend to get absorbed and price can pin near the biggest {tag} strikes ({', '.join(_f(k) for k in zero.get('top_positive', [])[:3]) or '-'}).")
        c0, p0 = zero.get("call_wall"), zero.get("put_wall")
        if spot and c0 and p0:
            if spot >= c0:
                pt(1, f"Above the {tag} call wall", f"Price is through today's call wall {_f(c0)}. Accepted above it, dealers who sold those calls must buy as price rises.")
            elif spot <= p0:
                pt(-1, f"Below the {tag} put wall", f"Price is through today's put wall {_f(p0)}. Accepted below it, dealers short those puts must sell as price falls.")
            else:
                pt(0, f"Inside today's {tag} walls", f"Today's put wall {_f(p0)} and call wall {_f(c0)} frame the likely range unless one breaks.")
        if zero.get("gross_share") is not None:
            pt(0, f"{tag} share of all gamma", f"{zero['gross_share'] * 100:.0f}% of all gamma near price comes from {tag} options, so {'today’s expiry dominates intraday hedging' if zero['gross_share'] > 0.4 else 'longer-dated options still carry most of the weight'}.")

    # 4. options flow so far and its recent turn
    if flow:
        c, p = flow.get("calls") or 0, flow.get("puts") or 0
        if c + p > 0:
            r = p / c if c else None
            if r is not None and r > 1.2:
                pt(-1, "Put-heavy volume", f"{_f(p)} puts traded against {_f(c)} calls today (put/call {r:.2f}). Heavy put buying is defensive or bearish, although some of it hedges long stock.")
            elif r is not None and r < 0.8:
                pt(1, "Call-heavy volume", f"{_f(c)} calls traded against {_f(p)} puts today (put/call {r:.2f}). Traders are reaching for upside.")
        ch = flow.get("net_change_60m")
        if ch is not None and abs(ch) > 0:
            if ch > 0:
                pt(1, "Last hour's flow tilted to calls", f"Over the last hour {_f(abs(ch))} more calls than puts traded.")
            else:
                pt(-1, "Last hour's flow tilted to puts", f"Over the last hour {_f(abs(ch))} more puts than calls traded.")

    # 5. what was added overnight
    if oi_shift:
        pb, ca = oi_shift.get("puts_added_below") or 0, oi_shift.get("calls_added_above") or 0
        if pb > 1.5 * max(ca, 1):
            pt(-1, "Puts added below price overnight", f"Open interest grew by {_f(pb)} puts below price against {_f(ca)} calls above: more downside protection or bets were opened.")
        elif ca > 1.5 * max(pb, 1):
            pt(1, "Calls added above price overnight", f"Open interest grew by {_f(ca)} calls above price against {_f(pb)} puts below: more upside positioning was opened.")

    # 6. the bias scorecard's own signals (skew, term structure, put/call) that the points above do not already cover
    for s in bias.get("signals", []):
        if s["name"] in ("Skew change vs last session", "Volatility term structure") and s.get("scored") and s["lean"]:
            pt(s["lean"], s["name"], f"{s['reading']}. {s['why']}")

    # 7. the move so far against what options priced
    if session and session.get("day_move") and session.get("move_points") is not None:
        used = abs(session["move_points"]) / session["day_move"]
        direction = "up" if session["move_points"] > 0 else "down"
        if used >= 1:
            pt(-1 if session["move_points"] > 0 else 1, f"Already moved a full expected move {direction}",
               f"Price is {_f(abs(session['move_points']))} points {direction} from the open, {used * 100:.0f}% of today's expected move ({_f(session['day_move'])}). Further extension is possible, but the easy part of the move has happened.")
        else:
            pt(0, "Move so far", f"{_f(abs(session['move_points']))} points {direction} from the open, {used * 100:.0f}% of today's expected move ({_f(session['day_move'])}).")

    # 8. regime
    if regime and regime.get("label"):
        pt(0, f"Regime: {regime['label']}", regime.get("meaning") or "")

    sb, sr = sum(p["weight"] for p in bull), sum(p["weight"] for p in bear)
    lean = "Bullish" if sb - sr >= 3 else "Leans bullish" if sb - sr >= 1 else "Bearish" if sr - sb >= 3 else "Leans bearish" if sr - sb >= 1 else "Balanced"
    em_lo, em_hi = em.get("low"), em.get("high")

    def targets(cands, above):
        xs = sorted({round(x, 2) for x in cands if x and spot and ((x > spot) if above else (x < spot))}, reverse=not above)
        return xs[:3]

    plan = {
        "bull": {"trigger": f"Holds above {_f(flip)} (gamma flip)" if flip and spot and spot > flip else f"Reclaims {_f(flip)} (gamma flip) and holds" if flip else "Holds above the opening range",
                 "targets": targets([zero.get("call_wall") if zero else None, cw, em_hi], True),
                 "invalidation": f"Accepted back below {_f(pw if not flip or (spot and flip > spot) else flip)}"},
        "bear": {"trigger": f"Loses {_f(flip)} (gamma flip)" if flip and spot and spot > flip else f"Fails below {_f(flip)} (gamma flip)" if flip else "Breaks the opening range low",
                 "targets": targets([zero.get("put_wall") if zero else None, pw, em_lo], False),
                 "invalidation": f"Accepted back above {_f(flip if flip else cw)}"},
    }
    top = sorted(bull + bear, key=lambda p: -p["weight"])[:2]
    summary = (f"{lean}. {len(bull)} points favour upside (weight {sb}) and {len(bear)} favour downside (weight {sr}). "
               + (f"The strongest: {_low(top[0]['title'])}" + (f" and {_low(top[1]['title'])}." if len(top) > 1 else ".") if top else "")
               + (f" The day turns on the gamma flip at {_f(flip)}." if flip else ""))
    return {"lean": lean, "bull_weight": sb, "bear_weight": sr, "bull": bull, "bear": bear, "neutral": neutral, "summary": summary, "plan": plan,
            "note": "Built from option positioning and stated rules. A reading of how dealers are positioned, not a prediction; check it against price action."}
