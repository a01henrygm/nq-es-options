"""Daily bias summary: a plain reading of what today's options data shows. It is context, NOT a forecast."""
from __future__ import annotations
from . import analytics as an


def compute_bias(snap, now, fresh, convention="standard", prev_skew=None, actual=None, events=None):
    spot, cons = snap.spot, snap.contracts
    sig = []

    def add(name, reading, lean, why, scored=True):
        sig.append({"name": name, "reading": reading, "lean": lean if scored else 0, "scored": scored, "why": why})

    fl = an.gamma_flip(cons, spot, now, convention)
    flip = fl["flip"] if fl["found"] else None
    if flip is not None and convention != "gross":
        above = spot > flip
        calm = above if convention == "standard" else not above
        day = {"label": "Calmer, mean-reverting" if calm else "More trending, bigger moves", "flip": flip, "above_flip": above,
               "why": f"Price {spot:,.0f} is {'above' if above else 'below'} the estimated gamma flip {flip:,.0f}, and the sign scenario is '{convention}'."}
    else:
        day = {"label": "Unknown", "flip": None, "above_flip": None, "why": "No gamma flip could be estimated, so the day type is unknown."}
    add("Day type (gamma flip)", day["why"], 0, "Sets the type of day, not the direction.", scored=False)

    w = an.walls(cons, spot, now)
    if w["call_wall"] is not None and w["put_wall"] is not None:
        up, dn = w["call_wall"] - spot, spot - w["put_wall"]
        lean = 1 if up > 1.5 * dn else -1 if dn > 1.5 * up else 0
        add("Room to the walls", f"{up:,.0f} up to the call wall {w['call_wall']:,.0f}, {dn:,.0f} down to the put wall {w['put_wall']:,.0f} (by {w['basis']})", lean,
            "More room to the call wall leans up; more room to the put wall leans down. Walls are the heaviest strikes, not guaranteed barriers.")
    else:
        add("Room to the walls", "A call wall or put wall could not be found.", 0, "Needs open interest or volume on both sides of the price.")

    vol = an.concentration(cons, "volume")
    r = vol["put_call_ratio"]
    if r is not None:
        add("Put/call volume", f"{r:.2f} ({vol['total_puts']:,.0f} puts, {vol['total_calls']:,.0f} calls)", -1 if r > 1.2 else 1 if r < 0.8 else 0,
            "Rough thresholds: above 1.2 leans bearish, below 0.8 leans bullish. Volume does not say who bought or sold.")
    else:
        add("Put/call volume", "No volume yet.", 0, "Volume fills in after the open.")

    sk = an.skew_25d(cons, spot, now)
    if sk and prev_skew is not None:
        ch = sk["value"] - prev_skew
        add("Skew change vs last session", f"{sk['value']:.1f} pts ({ch:+.1f})", -1 if ch > 0.5 else 1 if ch < -0.5 else 0,
            "Rising put premium (skew up) leans bearish; falling leans bullish. Measured at about 25 delta.")
    elif sk:
        add("Skew change vs last session", f"{sk['value']:.1f} pts, no earlier session stored yet", 0, "Compares from the next session onward.")
    else:
        add("Skew change vs last session", "Skew could not be measured.", 0, "Needs puts and calls near 25 delta at least a day out.")

    term = an.iv_term_structure(cons, spot)
    if len(term) >= 2:
        slope = (term[-1]["iv"] - term[0]["iv"]) * 100
        add("Volatility term structure", f"back minus front ATM IV: {slope:+.1f} pts ({'inverted' if slope < -1 else 'normal'})", -1 if slope < -1 else 0,
            "Front expiries pricing more volatility than later ones signals stress; it leans cautious.")
    else:
        add("Volatility term structure", "Needs two expirations.", 0, "")

    if actual and actual.get("available") and actual.get("fraction_of_expected") is not None:
        add("Move so far vs expected", f"{actual['fraction_of_expected'] * 100:.0f}% of the expected move used ({actual['move_points']:+,.1f} pts)", 0,
            "Over 100% means price has already travelled more than the options implied for the period. Information only.", scored=False)

    ev = events or []
    if ev:
        txt = "; ".join(f"{e['name']} {'today' if e['days_away'] == 0 else 'tomorrow' if e['days_away'] == 1 else 'in ' + str(e['days_away']) + ' days'}"
                        f"{' ' + e['time'] + ' ET' if e['time'] else ''} ({e['importance']})" for e in ev[:4])
        add("Scheduled events", txt, 0, "Big scheduled releases can move price far more than the options implied, and levels can break more easily around them.", scored=False)
    scored = [s for s in sig if s["scored"]]
    score = sum(s["lean"] for s in scored)
    verdict = "Leans bullish" if score >= 2 else "Leans bearish" if score <= -2 else "Mixed, no clear edge"

    nstr = len({c.strike for c in cons})
    has_oi = any(c.oi for c in cons)
    pts, reasons = 0, []
    for ok, why in ((nstr >= 10, "10+ strikes"), (nstr >= 30, "30+ strikes"), (has_oi, "open interest present"),
                    (sum(1 for s in scored if "could not" not in s["reading"] and "Needs" not in s["reading"] and "No volume" not in s["reading"]) >= 3, "3+ signals measurable"),
                    (fresh.status in ("live", "delayed", "closed_last_session"), "data is current for its session")):
        pts += ok
        if not ok:
            reasons.append("missing: " + why)
    conf = {"label": "Low" if pts <= 1 else "Medium" if pts <= 3 else "High", "points": pts, "of": 5, "reasons": reasons}

    change = []
    if w["call_wall"] is not None:
        change.append(f"Price accepted above the call wall {w['call_wall']:,.0f}: the main ceiling is gone, which weakens a bearish lean.")
    if w["put_wall"] is not None:
        change.append(f"Price accepted below the put wall {w['put_wall']:,.0f}: the main floor is gone, which weakens a bullish lean.")
    if flip is not None:
        change.append(f"A move across the gamma flip {flip:,.0f} changes the day type, so expect the pace of moves to change.")

    cautions = []
    if any(e["days_away"] == 0 and e["importance"] == "high" for e in ev):
        cautions.append("A high-importance event is scheduled TODAY. Moves can be larger than the options implied and levels may break more easily around the release.")
    cautions += ["Context for the day, not a trade signal or a prediction. The signals use rough thresholds I chose; none has been tested against outcomes.",
                "Gamma figures assume dealer positioning (the sign scenario); open interest cannot show who holds contracts."]
    if not has_oi:
        cautions.append("Open interest reads zero here, so walls use today's volume, which only shows where trading happened.")
    if fresh.status in ("delayed", "closed_last_session"):
        cautions.append("Data is delayed or from the last session, so levels may trail the market.")
    if nstr < 10:
        cautions.append(f"Only {nstr} strikes were read, so signals are weak.")
    em = an.expected_move(cons, spot, now)
    emr = None
    if em.get("available"):
        src = em.get("straddle") or em.get("iv_1sd")
        emr = {"low": src["lower"], "high": src["upper"], "method": "ATM straddle" if em.get("straddle") else "one std. dev. from ATM IV"}
    return {"verdict": verdict, "score": score, "scored_signals": len(scored), "confidence": conf, "day_type": day, "signals": sig,
            "levels": {"spot": spot, "flip": flip, "call_wall": w["call_wall"], "put_wall": w["put_wall"], "walls_basis": w["basis"], "expected_move": emr},
            "what_would_change": change, "cautions": cautions, "convention": convention}
