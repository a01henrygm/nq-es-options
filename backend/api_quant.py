"""Endpoints for the HOD / LOD tab, the Quant lab tab and the HOD / LOD TradingView indicator.

register() is called from create_app with that function's helpers (see api_more.register for the namespace)."""
from __future__ import annotations
from datetime import datetime, time as dtime, timedelta
from statistics import median

from fastapi import HTTPException, Query

from .services import analytics as an
from .services import intraday as idy
from .services import behavior as bh
from .services import quant as qt
from .services.hodlod_pine import build_hodlod_pine
from .services.mapping import FUTURES_FOR, INDEX_GROUP
from .timeutil import ET, iso, parse_ts, to_et

RTH_OPEN, RTH_CLOSE = dtime(9, 30), dtime(16, 0)


def register(app, h):
    db = h.db

    def day_rows(u, day):
        out = []
        for r in db.price_history(u, 6000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t and to_et(t).date() == day:
                out.append((t, r["price"]))
        return sorted(out)

    def series(u, name, day):
        a = iso(datetime.combine(day, dtime(0, 0), ET))
        b = iso(datetime.combine(day + timedelta(days=1), dtime(0, 0), ET))
        return [r for r in db.metric_series(u, name, since=a) if a <= r["t"] < b]

    def sibling(u):
        """The other index the app tracks (SPX for NDX and the reverse), or None."""
        g = INDEX_GROUP.get(u)
        want = "S&P 500" if g == "Nasdaq 100" else "Nasdaq 100" if g == "S&P 500" else None
        return next((x for x in h.settings.underlyings if INDEX_GROUP.get(x) == want), None) if want else None

    def context(u, convention="standard"):
        """Everything the HOD / LOD and Quant lab views share: the session's open, high and low, the expected moves, 0DTE gamma."""
        snap = h.snapshot(u)
        m, fr, now = h.meta(snap, {"convention": convention})
        ref = snap.source_ts or snap.retrieved_at
        net = to_et(ref)
        day = net.date()
        op, cl = datetime.combine(day, RTH_OPEN, ET), datetime.combine(day, RTH_CLOSE, ET)
        rows = day_rows(u, day)
        rth = [(t, p) for t, p in rows if op <= t <= cl]
        open_px, open_note = None, None
        if rth:
            open_px = rth[0][1]
            late = (rth[0][0] - op).total_seconds() / 60
            if late > 30:
                open_note = f"The first price this app saw today was {late:.0f} minutes after 9:30, so it stands in for the open. TradingView uses the real open."
        hi = max((p for _, p in rth), default=None)
        lo = min((p for _, p in rth), default=None)
        dm = [r for r in series(u, "day_move", day) if r["t"] >= iso(op)]
        dm_open = dm[0] if dm else None
        cur = idy.day_move(snap.contracts, snap.spot, now)
        if dm_open:
            sig_open = qt.sigma_from_move(dm_open["value"], (dm_open["detail"] or {}).get("method"))
        elif cur:                                              # nothing stored near the open yet: the current day move
            sig_open = qt.sigma_from_move(cur["points"], cur["method"])
        else:
            sig_open = None
        tnow = to_et(now)
        if tnow.date() == day and op <= tnow <= cl:
            mins_left = (cl - tnow).total_seconds() / 60
        elif tnow.date() == day and tnow > cl:
            mins_left = 0.0
        else:
            mins_left = 390.0
        sig_rem = None
        if cur and mins_left > 0:
            if "straddle" in cur["method"]:
                sig_rem = qt.sigma_from_move(cur["points"], cur["method"])         # today's straddle prices only what is left of the day
            elif sig_open:
                sig_rem = sig_open * (mins_left / 390) ** 0.5
        z = idy.zero_dte(snap.contracts, snap.spot, now, convention)
        mapper, mapping = h.futures_mapper(u, snap, now, "auto")

        def conv(v):
            if v is None or not mapper:
                return None
            r = mapper(v)
            return r["mapped"] if r.get("mapped") is not None and r.get("status") != "invalid" else None
        spot_f = conv(snap.spot)
        return {"snap": snap, "m": m, "now": now, "day": day, "rth": rth, "rows": rows, "open": open_px, "open_note": open_note, "hi": hi, "lo": lo,
                "sig_open": sig_open, "sig_rem": sig_rem, "mins_left": mins_left, "z": z, "conv": conv, "spot_f": spot_f,
                "root": mapping.get("futures_root"), "ratio": (spot_f / snap.spot) if spot_f else None,
                "gamma_series": [{"t": r["t"], "value": r["value"]} for r in series(u, "gamma0_at_spot", day)]}

    def step_minutes(rows):
        gaps = [(rows[i][0] - rows[i - 1][0]).total_seconds() / 60 for i in range(1, len(rows))]
        return median(gaps) if gaps else None

    def fut(c, v):
        f = c["conv"](v) if v is not None else None
        return None if f is None else round(f, 2)

    def hodlod_data(u, convention):
        c = context(u, convention)
        snap, z = c["snap"], c["z"]
        walls = {"call_wall": z.get("call_wall"), "put_wall": z.get("put_wall"), "flip": z.get("flip")} if z.get("available") else None
        d = qt.hodlod(c["open"], c["hi"], c["lo"], snap.spot, c["sig_open"], c["sig_rem"], walls=walls)
        pb = qt.gamma_playbook(z, snap.spot, c["open"], c["sig_open"], c["gamma_series"], c["sig_rem"])
        if d.get("available"):
            for row in d["up"] + d["down"] + d["walls"]:
                row["futures"] = fut(c, row["price"])
            for side in ("hod", "lod"):
                if d["projection"]:
                    d["projection"][side + "_futures"] = {k: fut(c, v) for k, v in d["projection"][side].items()}
            d["open_futures"], d["high_futures"], d["low_futures"] = fut(c, d["open"]), fut(c, d["high"]), fut(c, d["low"])
            d["sigma_open_futures"] = d["sigma_open"] * c["ratio"] if c["ratio"] else None
        return c, {"hodlod": d, "playbook": pb, "open_note": c["open_note"], "minutes_left": c["mins_left"], "futures_root": c["root"],
                   "mapped": c["spot_f"] is not None, "spot_futures": c["spot_f"]}

    @app.get("/api/analytics/hodlod")
    def hodlod(underlying: str, convention: str = "standard"):
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c, data = hodlod_data(u, convention)
        return {"meta": c["m"], "data": data,
                "price": [{"t": iso(t), "price": p} for t, p in c["rows"]]}

    @app.get("/api/analytics/quant")
    def quant(underlying: str, convention: str = "standard", stop: float | None = Query(None, gt=0), model: str = "auto"):
        """The Quant lab: regime playbook, mean-reversion test, Monte Carlo of targets, ES/NQ principal components."""
        if convention not in an.SIGNS or model not in ("auto", "walk", "pull"):
            raise HTTPException(422, "invalid convention or model")
        u = h.underlying_ok(underlying)
        c = context(u, convention)
        snap = c["snap"]
        pb = qt.gamma_playbook(c["z"], snap.spot, c["open"], c["sig_open"], c["gamma_series"], c["sig_rem"])
        src = c["rth"] if len(c["rth"]) >= 30 else c["rows"]
        mr = qt.mean_reversion([p for _, p in src], step_minutes(src))
        ratio = c["ratio"] or 1.0
        stop_idx = (stop / ratio) if stop else (max(1.0, round(0.1 * c["sig_open"])) if c["sig_open"] else None)
        pull = model == "pull" or (model == "auto" and pb["state"] == "long" and mr.get("significant"))
        hl = mr.get("half_life_minutes") if pull and mr.get("available") else None
        mc = qt.monte_carlo(snap.spot, c["sig_rem"], stop_idx, minutes_left=c["mins_left"], half_life_minutes=hl, mean=mr.get("mean") if hl else None,
                            hi=c["hi"], lo=c["lo"]) if c["mins_left"] > 0 else {"available": False, "reason": "The regular session has closed. The Monte Carlo runs to the 16:00 ET close."}
        if pull and not hl and mc.get("available"):
            mc["note"] += " A pull to the average was asked for, but no significant half life was measured, so paths are a plain random walk."
        if mc.get("available"):
            mc["stop_futures"] = stop_idx * ratio
            for k in ("hod", "lod"):
                mc[k + "_futures"] = {q: fut(c, v) for q, v in mc[k].items()}
        sib = sibling(u)
        if sib:
            a = c["rows"]
            b = day_rows(sib, c["day"])
            nq_first = INDEX_GROUP.get(u) == "Nasdaq 100"
            pairs = qt.align(a, b) if nq_first else [(t, y, x) for t, x, y in qt.align(a, b)]
            pc = qt.pca_pair(pairs)
            pc["symbols"] = {"nq": u if nq_first else sib, "es": sib if nq_first else u}
        else:
            pc = {"available": False, "reason": "Track both NDX and SPX (Settings) to compare NQ and ES."}
        return {"meta": c["m"], "data": {"playbook": pb, "mean_reversion": mr, "monte_carlo": mc, "pca": pc, "open": c["open"], "open_note": c["open_note"],
                                         "sigma_open": c["sig_open"], "sigma_remaining": c["sig_rem"], "minutes_left": c["mins_left"], "futures_root": c["root"],
                                         "ratio": c["ratio"], "model_used": "pull" if hl else "walk", "stop_index": stop_idx}}

    @app.get("/api/export/hodlod-pine")
    def export_hodlod_pine(underlying: str, convention: str = "standard"):
        """The HOD / LOD indicator: options inputs baked in, everything price-based computed live on the chart."""
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c, data = hodlod_data(u, convention)
        snap, m, z, pb = c["snap"], c["m"], c["z"], data["playbook"]
        sig_pct = (c["sig_open"] / snap.spot) if c["sig_open"] else 0.0
        to_chart = (lambda v: fut(c, v)) if c["spot_f"] is not None else (lambda v: v)
        units = (f"Walls and flip are ESTIMATED {c['root']} points (converted from {m['underlying']})." if c["spot_f"] is not None
                 else f"Walls and flip are in {m['underlying']} units (no {c['root'] or 'futures'} price or basis saved). Use the offset setting.")
        src = f"Source: {m['provider']} {m['underlying']}, snapshot {m['calculated_at_et']}, data status: {m['data_status']}."
        flips = [{"t": parse_ts(f["t"]), "to": f["to"]} for f in pb["flips"]]
        code = build_hodlod_pine(sigma_pct=sig_pct, state=pb["state"], call_wall=to_chart(z.get("call_wall")) if z.get("available") else None,
                                 put_wall=to_chart(z.get("put_wall")) if z.get("available") else None, flip=to_chart(z.get("flip")) if z.get("available") else None,
                                 flips=flips, source=src, units=units, made_at=to_et(c["now"]), day=c["day"], symbol=m["underlying"])
        return {"code": code, "meta": m, "state": pb["state"], "sigma_pct": sig_pct, "mapped": c["spot_f"] is not None,
                "note": "Paste into TradingView's Pine Editor and add to chart. The ladder, chances, mean-reversion test, Monte Carlo and ES/NQ split run live "
                        "on your chart; the expected move, regime and walls are today's values from Q DATA, so re-copy each session."}

    @app.get("/api/charts/level-map")
    def level_map(underlying: str, convention: str = "standard", tf: int = Query(2, ge=1, le=30), ahead: int = Query(90, ge=10, le=390)):
        """Candles from the stored prices, the key levels with a respect / chop / disrespect call each, and projected candles acting them out."""
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c = context(u, convention)
        snap, z, now = c["snap"], c["z"], c["now"]
        pb = qt.gamma_playbook(z, snap.spot, c["open"], c["sig_open"], c["gamma_series"], c["sig_rem"])
        op = datetime.combine(c["day"], RTH_OPEN, ET)
        bars = bh.candles(c["rows"], op, tf)
        j = h.levels_payload(u, convention, "auto", None, key=14)
        try:
            rec = {r["category"]: r for r in h.reactions(u, 30, 0.05)["summary"]}
        except HTTPException:
            rec = {}
        from .services import analytics as _an
        gf = _an.gamma_flip(snap.contracts, snap.spot, now, convention)
        flips = [z.get("flip") if z.get("available") else None, gf["flip"] if gf["found"] else None]
        lv = bh.level_calls(j["zones"], snap, now, pb["state"], flips, convention, rec)
        steps = int(min(ahead, c["mins_left"]) // tf) if c["mins_left"] > 0 else int(ahead // tf)
        sd_day = c["sig_rem"] or c["sig_open"]
        mins = c["mins_left"] if c["mins_left"] > 0 else 390.0
        sd_c = sd_day * (tf / mins) ** 0.5 if sd_day else None
        if pb["state"] == "short" and c["open"]:
            d = 1 if snap.spot >= c["open"] else -1
        else:
            nl = min(lv, key=lambda x: abs(x["value"] - snap.spot), default=None)
            d = 1 if nl is None or nl["value"] >= snap.spot else -1
        start = bars[-1]["t"] + timedelta(minutes=tf) if bars else to_et(now)
        times = [iso(start + timedelta(minutes=tf * i)) for i in range(steps)]
        main = bh.ghost_path(lv, snap.spot, sd_c, steps, d) if sd_c and steps > 0 else None
        alt = bh.ghost_path(lv, snap.spot, sd_c, steps, d, flip_first=True) if sd_c and steps > 0 else None
        return {"meta": c["m"], "tf": tf, "candles": [{**b, "t": iso(b["t"])} for b in bars], "levels": lv, "regime": {k: pb[k] for k in ("state", "title", "tagline", "color", "flips")},
                "open": c["open"], "spot": snap.spot, "ratio": c["ratio"], "futures_root": c["root"], "mapped": c["spot_f"] is not None,
                "projection": {"times": times, "main": main, "alt": alt, "direction": d, "sd_candle": sd_c},
                "rule": bh.RULE, "note": ("Candles are built from the index prices this app stores (about one every 2 minutes, about 15 minutes delayed), so they are "
                                          "coarser than TradingView's. Projected candles picture the calls; they are scenarios, not forecasts.")}
