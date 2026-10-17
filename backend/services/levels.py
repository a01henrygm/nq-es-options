"""Build the key-level list for one underlying. Every level keeps its origin, method, inputs and reliability."""
from __future__ import annotations
from . import analytics as an
from . import intraday as idy

RELIABILITY_RULE = ("high: data fresh/closed-session and 100+ contracts used; medium: 30+ contracts; "
                    "low: fewer, stale, or no source timestamp. Open-interest levels are daily figures by nature.")


def reliability(fresh_status: str, n: int) -> str:
    if fresh_status in ("stale", "no_source_time", "unavailable"):
        return "low"
    return "high" if n >= 100 else "medium" if n >= 30 else "low"


MID_RULE = ("Mid-size zone: its total is at least 25% and at most 70% of the biggest zone on its side (big enough to matter, not just another top zone) and its "
            "peak strike has at least 300 contracts of open interest or 50 of volume.")
MIN_FLOOR = {"oi": 300, "volume": 50}


def tiered(zs, side, top, mid, floor):
    """Splits one side's zones into the biggest `top` and up to `mid` mid-size ones. See MID_RULE."""
    mine = sorted((z for z in zs if z["side"] == side), key=lambda z: -z["magnitude"])
    big = mine[0]["magnitude"] if mine else 0
    mids = [z for z in mine[top:] if 0.25 * big <= z["magnitude"] <= 0.70 * big and z["peak"] >= floor][:mid]
    return mine[:top], mids


def build_levels(snap, now, convention, fresh, top=2, expirations=None, per_expiry=0, mid=0, moves=0, gex_top=None) -> list:
    """top: how many strikes to keep per type. expirations: list of ISO dates to use (None = all in the snapshot).
    per_expiry: also add open-interest and volume strikes for each of the next N expirations on their own (0 = off).
    gex_top: how many GEX strikes and GEX zones to build per side (None = same as top, up to 3 zones). Lets GEX have more levels than the rest."""
    gt = gex_top or top
    gz = max(1, min(gex_top, 8)) if gex_top else max(1, min(top, 3))
    spot = snap.spot
    cons = an.select(snap.contracts, expirations) if expirations else snap.contracts
    base = {"instrument": snap.underlying, "source_timestamp": snap.source_ts.isoformat() if snap.source_ts else None,
            "data_status": fresh.status, "provider": snap.provider}
    out = []

    def add(cat, label, value, method, inputs, n, extra=None):
        if value is None:
            return
        out.append({**base, "category": cat, "label": label, "value": value, "method": method, "inputs": inputs,
                    "reliability": reliability(fresh.status, n), **(extra or {})})

    g = an.gex_by_strike(cons, spot, now, convention)
    n_g = sum(g["contracts_used"].values())
    f = an.gamma_flip(cons, spot, now, convention)
    if f["found"]:
        add("gamma_flip", "Estimated gamma flip", f["flip"], f["method"],
            {"convention": convention, "contracts": f["contracts_used"], "crossings": f.get("crossings"), "note": f["note"]}, f["contracts_used"])
    ranked = sorted(g["strikes"], key=lambda s: s["net_gex"])
    for s in ranked[-gt:][::-1]:
        if s["net_gex"] > 0:
            add("gex_concentration", "Large positive modeled GEX", s["strike"], g["formula"], {"net_gex": s["net_gex"], "convention": convention}, n_g)
    for s in ranked[:gt]:
        if s["net_gex"] < 0:
            add("gex_concentration", "Large negative modeled GEX", s["strike"], g["formula"], {"net_gex": s["net_gex"], "convention": convention}, n_g)
    # Call-wall and put-wall ZONES. Single strikes are NOT netted against each other here (a strike with huge call and put gamma nets to
    # almost nothing), and neighbouring wall strikes are merged into one band whose type is decided by which side has more walls in it.
    zs = an.gex_wall_zones(g["strikes"], spot, gz)
    for side in ("call", "put"):
        for i, z in enumerate(z for z in zs if z["side"] == side):
            add(f"gex_{side}_zone", f"{side.capitalize()} wall zone" + (f" #{i + 1}" if i else ""), z["center"], an.GEX_ZONE_RULE,
                {"low": z["low"], "high": z["high"], "zone_mag": z["magnitude"], "peak_gex": z["peak"], "call_strikes": z["call_strikes"],
                 "put_strikes": z["put_strikes"], "members": z["members"], "convention": convention}, n_g, {"low": z["low"], "high": z["high"]})
    nz = an.gex_net_zones(g["strikes"], spot, gz)
    for side, cat, lab in (("positive", "gex_pos_zone", "Positive GEX zone"), ("negative", "gex_neg_zone", "Negative GEX zone")):
        for i, z in enumerate(z for z in nz if z["side"] == side):
            add(cat, lab + (f" #{i + 1}" if i else ""), z["center"], an.GEX_NET_ZONE_RULE,
                {"low": z["low"], "high": z["high"], "zone_mag": z["magnitude"], "peak_gex": z["peak"], "pos_strikes": z["pos_strikes"],
                 "neg_strikes": z["neg_strikes"], "members": z["members"], "convention": convention}, n_g, {"low": z["low"], "high": z["high"]})
    zt = max(1, min(top, 3))
    grid = sorted({c.strike for c in cons})

    def zone_levels(rows, grid_, field, n, cat_main, cat_mid, names, tag="", extra_inputs=None, what="", top_=None, mid_=None):
        """One zone level per call-side and put-side zone of an open-interest or volume profile."""
        zs_ = an.series_zones(rows, grid_, spot)
        for side in ("call", "put"):
            main, mids = tiered(zs_, side, top_ or zt, mid_ if mid_ is not None else mid, MIN_FLOOR[field])
            for i, z in enumerate(main):
                cat = cat_main[side] if isinstance(cat_main, dict) else cat_main
                lab = f"{side.capitalize()} {names} zone" + (f" {tag}" if tag else "") + (f" #{i + 1}" if i else "")
                add(cat, lab, z["center"], what + ". " + an.SERIES_ZONE_RULE,
                    {"low": z["low"], "high": z["high"], "zone_mag": z["magnitude"], "peak": z["peak"], "call_strikes": z["call_strikes"], "put_strikes": z["put_strikes"],
                     "members": z["members"], **(extra_inputs or {})}, n, {"low": z["low"], "high": z["high"]})
            for z in mids:
                add(cat_mid, f"{side.capitalize()} {names} zone" + (f" {tag}" if tag else "") + " mid", z["center"], what + " (mid-size). " + MID_RULE,
                    {"low": z["low"], "high": z["high"], "zone_mag": z["magnitude"], "peak": z["peak"], "call_strikes": z["call_strikes"], "put_strikes": z["put_strikes"],
                     "members": z["members"], **(extra_inputs or {})}, n, {"low": z["low"], "high": z["high"]})

    oi = an.concentration(cons, "oi", top=10)
    zone_levels(oi["strikes"], grid, "oi", sum(1 for c in cons if c.oi), {"call": "oi_call_zone", "put": "oi_put_zone"}, "oi_mid", "OI",
                what="Open interest by strike (end of previous trading day), neighbouring strikes merged into a zone")
    vol = an.concentration(cons, "volume", top=10)
    zone_levels(vol["strikes"], grid, "volume", sum(1 for c in cons if c.volume), {"call": "volume_call_zone", "put": "volume_put_zone"}, "volume_mid", "volume",
                what="Session volume by strike, neighbouring strikes merged into a zone")
    if per_expiry:
        for e in sorted({c.expiry for c in cons if an.year_fraction(c.expiry, now) > 0})[:per_expiry]:
            ce, tag = [c for c in cons if c.expiry == e], f"{e:%m/%d}"
            dte = round(an.year_fraction(e, now) * 365.25, 1)
            eg = sorted({c.strike for c in ce})
            for field, cat, names, what in (("oi", "oi_by_expiry", "OI", "Open interest"), ("volume", "volume_by_expiry", "volume", "Session volume")):
                conc, n = an.concentration(ce, field, top=1), sum(1 for c in ce if getattr(c, field))
                zone_levels(conc["strikes"], eg, field, n, cat, "oi_mid" if field == "oi" else "volume_mid", names, tag=tag,
                            extra_inputs={"expiry": e.isoformat(), "days_to_expiry": dte}, what=f"{what} by strike for the {e.isoformat()} expiry only, neighbouring strikes merged into a zone", top_=1)
    # Expected-move ZONES. The straddle price and 1 sigma are two estimates of the same expected move, so the band between them is the
    # "expected move zone"; the band from 1 sigma out to 2 sigma is the "extended move zone" (unusual territory). With the moves option off,
    # only the nearest expiry is shown.
    for idx, r in enumerate(an.moves_table(cons, spot, now, moves or 1)):
        if not moves and idx:
            break
        tag = f"{r['expiry'][5:7]}/{r['expiry'][8:10]}"
        info = {"expiry": r["expiry"], "days": round(r["days"], 2), "atm_iv": r["atm_iv"], "straddle": r["straddle"], "sd1": r["sd1"], "sd2": r["sd2"]}
        for sign, word in ((1, "up"), (-1, "down")):
            est = [x for x in (r["straddle"], r["sd1"]) if x is not None]
            if est:
                lo_d, hi_d = min(est), max(est)
                if hi_d - lo_d < 0.05 * hi_d:                          # the two estimates nearly agree: still give the band some thickness
                    mid_d = (lo_d + hi_d) / 2
                    lo_d, hi_d = mid_d * 0.975, mid_d * 1.025
                edges = sorted((spot + sign * lo_d, spot + sign * hi_d))
                add("expected_move", f"Expected move zone {word} {tag}", spot + sign * (r["sd1"] if r["sd1"] is not None else r["straddle"]),
                    f"Band between the ATM straddle price and the 1 sigma move (spot x ATM IV x sqrt(time left)) for the {r['expiry']} expiry: two estimates of the same expected move. "
                    "If they nearly agree the band is widened to 5% of the distance.", {**info, "kind": "expected", "distance_low": lo_d, "distance_high": hi_d}, len(cons),
                    {"low": edges[0], "high": edges[1]})
            if r["sd1"] is not None and r["sd2"] is not None:
                edges = sorted((spot + sign * r["sd1"], spot + sign * r["sd2"]))
                add("expected_move_ext", f"Extended move zone {word} {tag}", spot + sign * r["sd2"],
                    f"Band from the 1 sigma move out to the 2 sigma move for the {r['expiry']} expiry: unusual territory (about 68% to 95% of outcomes inside it under the "
                    "bell-curve assumption; real markets have fatter tails).", {**info, "kind": "extended"}, len(cons), {"low": edges[0], "high": edges[1]})
    # 0DTE (nearest expiry only): its call wall, put wall and flip, kept apart from the all-expiry GEX levels.
    z = idy.zero_dte(cons, spot, now, convention)
    if z.get("available"):
        tag = "0DTE" if z["is_today"] else f"Front expiry {z['expiry'][5:7]}/{z['expiry'][8:10]}"
        n0 = z["contracts"]
        if z["call_wall"] is not None:
            add("gex0_call_wall", f"{tag} call wall", z["call_wall"], idy.ZERO_DTE_RULE, {"call_gex": z["call_wall_gex"], "expiry": z["expiry"]}, n0)
        if z["put_wall"] is not None:
            add("gex0_put_wall", f"{tag} put wall", z["put_wall"], idy.ZERO_DTE_RULE, {"put_gex": z["put_wall_gex"], "expiry": z["expiry"]}, n0)
        if z["flip"] is not None:
            add("gex0_flip", f"{tag} gamma flip", z["flip"], idy.ZERO_DTE_RULE, {"expiry": z["expiry"], "note": z["flip_note"]}, n0)
    return out
