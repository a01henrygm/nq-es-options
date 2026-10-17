"""Market regime: is today a pinned, mean-reverting day or one that can trend and expand?

This is a plain scorecard, not a forecast, and it has NOT been backtested. Each dimension below gets a lean from -2 (unstable) to +2 (calm)
and the labels come from the total. Everything shown to you (reading, lean, reason) is what went into the label.

  Gamma         price above the estimated gamma flip = calm (+2), below = unstable (-2), within 0.25% of it = transition (no score, the label becomes Transition)
  Volatility    the 3-week at-the-money implied volatility: low +1, normal 0, elevated -1, high -2. Compared with its own stored history once about
                10 sessions exist, otherwise against rough fixed ranges for the Nasdaq 100 and S&P 500.
  Term shape    near-term vs 3-week volatility: contango (later costs more) +1, flat 0, backwardation (near-term costs more, stress or an event) -1
  Skew          the 25-delta skew rising more than 1 point against the last session -1 (more downside protection being bought); otherwise 0
  Range today   the move so far against the expected move: contained (under 40%) +1, normal 0, expanded (over 100%) -1
  Event today   a high-importance scheduled event -1, and it is flagged because it can break any regime

Total 3 or more: Pinned and calm. 1 to 2: Calm. -1 to 0 with no clear lean: Mixed. -2 to -1: Leaning unstable. -3 or less: Trending, expansion risk.
"""
from __future__ import annotations
from datetime import datetime

from . import analytics as an

ROUGH_IV = {"Nasdaq 100": (0.18, 0.26, 0.34), "S&P 500": (0.12, 0.18, 0.26)}        # low/normal, normal/elevated, elevated/high (decimals)
MIN_SESSIONS = 10
RULE = __doc__.split("\n\n", 1)[1].strip()
MEANING = {
    "Pinned and calm": "Hedging by option dealers tends to lean against moves, volatility is not stretched and price is staying inside what options expected. Ranges often stay contained and levels tend to hold more often. A tendency, not a rule.",
    "Calm": "The structure leans mean-reverting but not strongly. Moves are more likely to fade than extend, with less conviction than a pinned day.",
    "Mixed": "The measures disagree, so there is no clear regime. Treat levels one at a time and do not lean on the regime label.",
    "Leaning unstable": "More of the measures point to bigger moves than to a pinned day. Breaks of levels are more likely to extend.",
    "Trending, expansion risk": "Hedging can add to moves rather than dampen them, and volatility or its shape signals stress. Ranges can exceed the expected move and breaks of levels can run.",
    "Transition: near the gamma flip": "Price is within a quarter of a percent of the estimated gamma flip, so the regime can switch with a small move. Do not assume either regime until price moves away from the flip.",
    "Unclear": "There was not enough usable data to classify the day.",
}


def percentile_of(value, past):
    """Share of past values at or below `value`, 0 to 100, or None when there are too few."""
    if len(past) < MIN_SESSIONS:
        return None
    return 100.0 * sum(1 for p in past if p <= value) / len(past)


def daily_last(history, today_et):
    """One value per ET date (the last stored that day), today excluded. history: rows with value and calculated_at (UTC ISO)."""
    from ..timeutil import parse_ts, to_et
    by = {}
    for h in history:
        t = parse_ts(h["calculated_at"])
        if t is not None and h["value"] is not None:
            d = to_et(t).date()
            if d != today_et:
                by[d] = h["value"]
    return [by[d] for d in sorted(by)]


def decide(dims, event_today_high=False, transition=False):
    """Pure rule: from the dimension leans to a label, a confidence and the total."""
    scored = [d for d in dims if d["available"] and d["scored"]]
    total = sum(d["lean"] for d in scored)
    if transition:
        label = "Transition: near the gamma flip"
    elif not scored:
        label = "Unclear"
    elif total >= 3:
        label = "Pinned and calm"
    elif total >= 1:
        label = "Calm"
    elif total <= -3:
        label = "Trending, expansion risk"
    elif total <= -1:
        label = "Leaning unstable"
    else:
        label = "Mixed"
    n_av = sum(1 for d in dims if d["available"])
    agree = len({(d["lean"] > 0) - (d["lean"] < 0) for d in scored if d["lean"] != 0}) <= 1
    pts = (2 if n_av >= 5 else 1 if n_av >= 3 else 0) + (1 if agree and len(scored) >= 3 else 0) + (1 if any(d["key"] == "gamma" and d["available"] and not transition for d in dims) else 0)
    conf = "High" if pts >= 4 else "Medium" if pts >= 2 else "Low"
    return {"label": label, "total": total, "confidence": conf, "dimensions_available": n_av, "dimensions_agree": agree, "event_today_high": event_today_high}


def compute_regime(snap, now, fresh, convention="standard", hist=None, actual=None, events=None, group=None, zones=None):
    """hist: dict name -> list of stored rows (iv_mid, skew_25d, ...). actual: the actual-vs-expected move dict. events: upcoming events with days_away."""
    from ..timeutil import to_et
    hist, events = hist or {}, events or []
    spot, cons = snap.spot, snap.contracts
    today = to_et(snap.source_ts or snap.retrieved_at).date()
    dims, notes, change = [], [], []

    def dim(key, name, reading, lean, why, available=True, scored=True):
        dims.append({"key": key, "name": name, "reading": reading, "lean": lean if available else 0, "why": why, "available": available, "scored": scored})

    # ---- gamma ----
    fl = an.gamma_flip(cons, spot, now, convention)
    flip = fl["flip"] if fl["found"] else None
    transition, gamma = False, None
    if flip is not None and convention != "gross":
        dist = (spot - flip) / spot
        above = spot > flip
        calm = above if convention == "standard" else not above
        transition = abs(dist) < 0.0025
        gamma = {"flip": flip, "above": above, "distance_pct": dist * 100, "distance_points": spot - flip, "calm_side": calm}
        mt = an.moves_table(cons, spot, now, 1)
        sd = mt[0]["sd1"] if mt and mt[0]["sd1"] else None
        gamma["in_expected_moves"] = abs(spot - flip) / sd if sd else None
        reading = f"Price {spot:,.0f} is {abs(dist) * 100:.2f}% {'above' if above else 'below'} the estimated flip {flip:,.0f}" + (f" ({gamma['in_expected_moves']:.1f} expected moves away)" if gamma["in_expected_moves"] else "")
        dim("gamma", "Gamma (the flip)", reading, 0 if transition else (2 if calm else -2),
            "Within a quarter of a percent of the flip: a transition, so no score." if transition else
            f"{'On the calm side' if calm else 'On the unstable side'} of the flip under the '{convention}' sign scenario.")
        change.append(f"A move to {flip:,.0f} ({abs(spot - flip):,.0f} points {'down' if above else 'up'}) would put price at the gamma flip, where the regime can switch.")
    else:
        dim("gamma", "Gamma (the flip)", "No gamma flip could be estimated." if convention != "gross" else "The 'gross' sign scenario has no direction.", 0,
            "Needs a flip crossing and a signed scenario.", available=False)
    tot = an.gex_by_strike(cons, spot, now, convention)["total_net_gex"]
    split = False
    if gamma is not None and not transition and convention != "gross":
        total_calm = tot > 0 if convention == "standard" else tot < 0
        split = total_calm != gamma["calm_side"]
        notes.append(f"Total modeled GEX is {'positive' if tot > 0 else 'negative'} ({tot:,.0f}), which usually goes with a {'calm' if total_calm else 'less calm'} structure. "
                     + ("But price is on the " + ("calm" if gamma["calm_side"] else "unstable") + " side of the flip, so the two signals split and the label is held to Medium confidence at most."
                        if split else "That agrees with where price sits relative to the flip."))
    else:
        notes.append(f"Total modeled GEX is {'positive' if tot > 0 else 'negative'} ({tot:,.0f}).")

    # ---- volatility level and term shape ----
    pts = an.iv_points(cons, spot, now)
    mid_iv = pts["mid"]["atm_iv"] if pts and pts["mid"] else None
    front_iv = pts["front"]["atm_iv"] if pts else None
    if mid_iv is not None:
        past = daily_last(hist.get("iv_mid", []), today)
        pc = percentile_of(mid_iv, past)
        if pc is not None:
            band = ("low", 1) if pc < 20 else ("normal", 0) if pc < 60 else ("elevated", -1) if pc < 80 else ("high", -2)
            dim("vol", "Volatility level (3 weeks)", f"{mid_iv * 100:.1f}% is higher than {pc:.0f}% of the {len(past)} sessions stored: {band[0]}", band[1], "Percentile of its own stored history.")
        elif group in ROUGH_IV:
            a, b, c = ROUGH_IV[group]
            band = ("low", 1) if mid_iv < a else ("normal", 0) if mid_iv < b else ("elevated", -1) if mid_iv < c else ("high", -2)
            dim("vol", "Volatility level (3 weeks)", f"{mid_iv * 100:.1f}%: {band[0]} for the {group} (rough fixed ranges)", band[1],
                f"Only {len(past)} sessions of history are stored; a real percentile needs about {MIN_SESSIONS}. The fixed ranges are rough.")
        else:
            dim("vol", "Volatility level (3 weeks)", f"{mid_iv * 100:.1f}% (nothing to compare it with yet)", 0, f"Needs about {MIN_SESSIONS} stored sessions for this symbol.", available=False)
    else:
        dim("vol", "Volatility level (3 weeks)", "No expiry about 3 weeks out with usable volatility.", 0, "The chain needs an expiry between 1 and 6 weeks away.", available=False)
    if mid_iv is not None and front_iv is not None and pts["mid"]["expiry"] != pts["front"]["expiry"]:
        slope = (mid_iv - front_iv) * 100
        shape = ("backwardation", -1) if slope < -1.0 else ("contango", 1) if slope > 1.0 else ("flat", 0)
        dim("term", "Term shape", f"{shape[0]}: 3-week IV is {slope:+.1f} points versus the nearest expiry past today", shape[1],
            "Near-term volatility above later volatility (backwardation) usually means stress or an event; the reverse is the normal calm shape.")
    else:
        dim("term", "Term shape", "Needs two expiries.", 0, "Near-term versus 3-week volatility.", available=False)

    # ---- skew ----
    sk = an.skew_25d(cons, spot, now)
    prev = daily_last(hist.get("skew_25d", []), today)
    if sk and prev:
        ch = sk["value"] - prev[-1]
        dim("skew", "Skew change", f"25-delta skew {sk['value']:.1f} points, {ch:+.1f} versus the last stored session", -1 if ch > 1.0 else 0,
            "More put premium than before suggests downside protection is being bought. Only a rise over 1 point is scored.")
    elif sk:
        dim("skew", "Skew change", f"25-delta skew {sk['value']:.1f} points (no earlier session stored)", 0, "Needs a previous session to compare.", available=False)
    else:
        dim("skew", "Skew change", "Skew could not be measured.", 0, "Needs puts and calls near 25 delta.", available=False)

    # ---- range so far ----
    if actual and actual.get("available") and actual.get("fraction_of_expected") is not None:
        fr = actual["fraction_of_expected"]
        st = ("contained", 1) if fr < 0.4 else ("expanded", -1) if fr > 1.0 else ("normal", 0)
        dim("range", "Range so far today", f"Moved {fr * 100:.0f}% of the expected move: {st[0]}", st[1],
            "Compares this app's first price of the session with now. If the app started after the open the true move is larger.")
    else:
        dim("range", "Range so far today", "Needs two stored prices from this session.", 0, "Fills in as the app runs.", available=False)

    # ---- event ----
    hi = [e for e in events if e.get("days_away") == 0 and e.get("importance") == "high"]
    dim("event", "Scheduled event", "; ".join(f"{e['name']}{' ' + e['time'] + ' ET' if e.get('time') else ''}" for e in hi) if hi else "No high-importance event today.", -1 if hi else 0,
        "A big release can break any regime." if hi else "Nothing scheduled that is likely to override the structure.")

    # ---- where price sits among the zones ----
    inside = [z for z in (zones or []) if z.get("low") is not None and z["low"] <= spot <= z["high"]]
    notes.append("Price is inside: " + ", ".join(f"{z['label']} ({z['low']:,.0f} to {z['high']:,.0f})" for z in inside) + ". Zones are where hedging and positioning are heaviest, so moves can stall or accelerate there."
                 if inside else "Price is not inside any call, put, GEX, open-interest or volume zone right now.")

    res = decide(dims, event_today_high=bool(hi), transition=transition)
    if split and res["confidence"] == "High":
        res["confidence"] = "Medium"
    if fresh.status in ("stale", "no_source_time", "unavailable"):
        res["confidence"] = "Low"
        notes.append("The data is stale, so the confidence is capped at Low.")
    change.append("A high-importance event, a jump in near-term volatility (backwardation) or a break of the gamma flip are what would move the label fastest.")
    return {**res, "meaning": MEANING[res["label"]], "dimensions": dims, "gamma": gamma, "iv": {"front": front_iv, "mid": mid_iv}, "notes": notes,
            "what_would_change": change, "rule": RULE, "history_sessions": {"iv_mid": len(daily_last(hist.get("iv_mid", []), today)), "skew_25d": len(prev)}, "convention": convention,
            "caution": "A scorecard with my own thresholds, not backtested. It describes today's structure; it does not predict direction."}
