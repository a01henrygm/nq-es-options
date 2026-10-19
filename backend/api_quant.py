"""Endpoints for the HOD / LOD tab, the Quant lab tab and the HOD / LOD TradingView indicator.

register() is called from create_app with that function's helpers (see api_more.register for the namespace)."""
from __future__ import annotations
from datetime import datetime, time as dtime, timedelta
from statistics import median

import os
import re

from dotenv import dotenv_values
from fastapi import HTTPException, Query, Request
from pydantic import BaseModel

from .services import analytics as an
from .services import intraday as idy
from .config import DATA
from .services import behavior as bh
from .services import chart_read as cr
from .services import flows as fl
from .services import gameplan as gp
from .services import stack as sk
from .services import quant as qt
from .services.hodlod_pine import build_hodlod_pine
from .services.mapping import FUTURES_FOR, INDEX_GROUP
from .timeutil import ET, iso, parse_ts, to_et

RTH_OPEN, RTH_CLOSE = dtime(9, 30), dtime(16, 0)


class ChartReadIn(BaseModel):
    image: str                     # data URL of the screenshot
    underlying: str
    convention: str = "standard"
    note: str = ""
    ahead: int = 30                # projected candles at most


class KeyIn(BaseModel):
    key: str


def _env_key(name):
    v = os.environ.get(name)
    if not v and (DATA / ".env").exists():
        v = dotenv_values(DATA / ".env").get(name)
    v = (v or "").strip()
    return v if v and not v.startswith("YOUR_") else None


def tf_minutes(tf: str) -> float:
    """'1m' / '5' / '1h' / '15 min' -> minutes. Unknown -> 1."""
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)", tf or "")
    if not m:
        return 1.0
    n, u = float(m.group(1)), m.group(2).lower()
    return n * 60 if u.startswith("h") else n * 1440 if u.startswith("d") else n / 60 if u.startswith("s") else n


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
        to_f, finfo = h.futures_converter(u, snap, now)
        mapping = {"futures_root": finfo.get("root")}

        def conv(v):
            if v is None or not to_f:
                return None
            return to_f(v)
        spot_f = conv(snap.spot)
        return {"snap": snap, "m": m, "now": now, "day": day, "rth": rth, "rows": rows, "open": open_px, "open_note": open_note, "hi": hi, "lo": lo,
                "sig_open": sig_open, "sig_rem": sig_rem, "mins_left": mins_left, "z": z, "conv": conv, "spot_f": spot_f,
                "root": mapping.get("futures_root"), "ratio": (spot_f / snap.spot) if spot_f else None, "futures_info": finfo,
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
        try:
            _c, _pb, lv = calls_for(u, convention, c)
            g = fl.greek_exposure(snap.contracts, snap.spot, c["now"], convention)
            day_iso = c["day"].isoformat()
            evs = [e for e in db.list_events(day_iso) if e["date"] == day_iso and e.get("importance") == "high"]
            moves = qt.move_map(snap.spot, c["hi"], c["lo"], c["open"], c["sig_open"], c["sig_rem"], lv, pb["state"], g, evs, c["mins_left"],
                                (lambda v: fut(c, v)) if c["spot_f"] is not None else None)
        except HTTPException as e:
            moves = {"available": False, "reason": str(e.detail)}
        if d.get("available"):
            for row in d["up"] + d["down"] + d["walls"]:
                row["futures"] = fut(c, row["price"])
            for side in ("hod", "lod"):
                if d["projection"]:
                    d["projection"][side + "_futures"] = {k: fut(c, v) for k, v in d["projection"][side].items()}
            d["open_futures"], d["high_futures"], d["low_futures"] = fut(c, d["open"]), fut(c, d["high"]), fut(c, d["low"])
            d["sigma_open_futures"] = d["sigma_open"] * c["ratio"] if c["ratio"] else None
        return c, {"hodlod": d, "playbook": pb, "moves": moves, "already_in": qt.already_in(c["hi"], c["lo"], snap.spot, c["sig_rem"]), "open_note": c["open_note"], "minutes_left": c["mins_left"], "futures_root": c["root"],
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
    def level_map(underlying: str, convention: str = "standard", count: int = Query(40, ge=5, le=80)):
        """Every key level, highest first, with what price should do there (respect / chop / disrespect), why, and the chance it is reached today."""
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c = context(u, convention)
        snap, z, now = c["snap"], c["z"], c["now"]
        pb = qt.gamma_playbook(z, snap.spot, c["open"], c["sig_open"], c["gamma_series"], c["sig_rem"])
        j = h.levels_payload(u, convention, "auto", None, key=count)
        try:
            rec = {r["category"]: r for r in h.reactions(u, 30, 0.05)["summary"]}
        except HTTPException:
            rec = {}
        gf = an.gamma_flip(snap.contracts, snap.spot, now, convention)
        flips = [z.get("flip") if z.get("available") else None, gf["flip"] if gf["found"] else None]
        raw = bh.level_calls(j["zones"], snap, now, pb["state"], flips, convention, rec, window=1.0)
        lv = []
        for l in sorted(raw, key=lambda x: -x["strength"]):              # levels at the same price become one row with both names
            twin = next((x for x in lv if abs(x["value"] - l["value"]) <= 0.0001 * l["value"]), None)
            if twin:
                twin["label"] = twin["label"] + " / " + l["label"]
            else:
                lv.append(dict(l))
        sig = c["sig_rem"] or c["sig_open"]
        above = sorted((l for l in lv if l["value"] > snap.spot), key=lambda l: l["value"])
        below = sorted((l for l in lv if l["value"] <= snap.spot), key=lambda l: -l["value"])
        for side, arr, other in (("above", above, below), ("below", below, above)):
            for i, l in enumerate(arr):
                beyond = arr[i + 1] if i + 1 < len(arr) else None
                back = arr[i - 1] if i > 0 else (other[0] if other else None)
                dist = abs(l["value"] - snap.spot)
                ch = qt.touch_prob(dist, sig) if sig else None
                l.update(bh.prediction(l, side, beyond, back, pb["state"], ch))
                l.update({"futures": c["conv"](l["value"]), "futures_low": c["conv"](l["low"]) if l.get("low") else None,
                          "futures_high": c["conv"](l["high"]) if l.get("high") else None, "points": l["value"] - snap.spot,
                          "sd": dist / sig if sig else None, "order": i + 1})
        counts = {k: sum(1 for l in lv if l["call"] == k) for k in bh.CALLS}
        return {"meta": c["m"], "levels": sorted(lv, key=lambda l: -l["value"]), "spot": snap.spot, "spot_futures": c["spot_f"],
                "futures_root": c["root"], "futures_info": c["futures_info"], "counts": counts, "sigma_remaining": sig, "minutes_left": c["mins_left"],
                "regime": {k: pb[k] for k in ("state", "title", "tagline", "color", "flips", "r_range")}, "rule": bh.RULE,
                "note": "Calls come from the 0DTE gamma regime and the dealer gamma at each level. Chance = how often price reaches that far before the "
                        "close, from the remaining expected move. Track record = how often that level type held in this app's own touch log. Not backtested."}

    # ---- chart read: a screenshot of your chart, marked up --------------------------------------------------------------
    def calls_for(u, convention, c=None):
        c = c or context(u, convention)
        snap, z, now = c["snap"], c["z"], c["now"]
        pb = qt.gamma_playbook(z, snap.spot, c["open"], c["sig_open"], c["gamma_series"], c["sig_rem"])
        j = h.levels_payload(u, convention, "auto", None, key=14)
        try:
            rec = {r["category"]: r for r in h.reactions(u, 30, 0.05)["summary"]}
        except HTTPException:
            rec = {}
        gf = an.gamma_flip(snap.contracts, snap.spot, now, convention)
        flips = [z.get("flip") if z.get("available") else None, gf["flip"] if gf["found"] else None]
        return c, pb, bh.level_calls(j["zones"], snap, now, pb["state"], flips, convention, rec, window=0.03)

    @app.get("/api/chart-read/status")
    def chart_read_status():
        return {"configured": _env_key("ANTHROPIC_API_KEY") is not None, "model": _env_key("CHART_READ_MODEL") or cr.DEFAULT_MODEL,
                "env_file": str(DATA / ".env")}

    @app.post("/api/chart-read/key")
    def chart_read_key(k: KeyIn, request: Request):
        if (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(403, "The API key can only be saved on the PC itself.")
        key = k.key.strip()
        if not re.match(r"^sk-ant-[A-Za-z0-9_\-]{20,}$", key):
            raise HTTPException(422, "That does not look like an Anthropic API key (it starts with sk-ant-).")
        from .api_more import env_set
        env_set(DATA / ".env", {"ANTHROPIC_API_KEY": key})
        os.environ["ANTHROPIC_API_KEY"] = key
        return {"saved": True}

    @app.post("/api/chart-read")
    def chart_read(req: ChartReadIn):
        """Claude reads the screenshot; Q DATA makes the calls and the projected path in the chart's own prices."""
        key = _env_key("ANTHROPIC_API_KEY")
        if not key:
            raise HTTPException(400, {"need_key": True, "reason": "Add your Anthropic API key to read screenshots."})
        if req.convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        try:
            media, b64 = cr.parse_data_url(req.image)
        except ValueError as e:
            raise HTTPException(422, str(e))
        u = h.underlying_ok(req.underlying)
        c, pb, lv = calls_for(u, req.convention)
        snap = c["snap"]
        mapped = c["spot_f"] is not None
        conv = (lambda v: c["conv"](v)) if mapped else (lambda v: v)
        unit = c["root"] if mapped else u.lstrip("_")
        sent = [{**l, "price": conv(l["value"])} for l in lv if conv(l["value"]) is not None]
        regime = f"{pb['title']} ({pb['tagline']})"
        try:
            rd = cr.read_chart(key, media, b64, sent, regime, unit, req.note.strip()[:300], _env_key("CHART_READ_MODEL") or cr.DEFAULT_MODEL)
        except RuntimeError as e:
            raise HTTPException(502, str(e))
        problems = cr.check_reading(rd)
        warnings = []
        last = rd.get("last_price")
        k = 1.0
        if isinstance(last, (int, float)) and last > 0:
            ref = c["spot_f"] if mapped else snap.spot
            gap = last / ref - 1
            if abs(gap) > 0.08:
                problems.append(f"The chart's price ({last:,.2f}) is {gap * 100:+.0f}% away from {unit} ({ref:,.2f}). Pick the matching symbol at the top "
                                "(NDX for NQ charts, SPX for ES charts) and try again.")
            elif not mapped:
                k = last / snap.spot
                warnings.append(f"No {c['root'] or 'futures'} basis is saved, so the levels were scaled to your chart with the price it shows. Options data is "
                                "delayed about 15 minutes, so they can be off by several points. Save a basis on the Key levels tab for exact prices.")
        else:
            problems.append("The last price could not be read from the chart.")
        seen = {round(float(x.get("price", 0)), 2): x for x in rd.get("levels_seen") or [] if isinstance(x.get("price"), (int, float))}
        levels = []
        for l in sent:
            p = l["price"] * k
            near = min(seen.items(), key=lambda kv: abs(kv[0] - l["price"]), default=(None, None))
            obs = near[1] if near[0] is not None and abs(near[0] - l["price"]) <= max(0.5, 0.0004 * l["price"]) else None
            levels.append({"label": l["label"], "category": l["category"], "price": p, "low": l["low"] and conv(l["low"]) and conv(l["low"]) * k,
                           "high": l["high"] and conv(l["high"]) and conv(l["high"]) * k, "call": l["call"], "why": l["why"], "strength": l["strength"],
                           "record": l["record"], "chart_behavior": (obs or {}).get("chart_behavior"), "chart_note": (obs or {}).get("note")})
        proj = None
        if not problems:
            tfm = tf_minutes(rd.get("timeframe") or "1m")
            space = rd["plot_right_x"] - rd["last_candle_x"]
            spacing = rd["candle_spacing"]
            n = int(min(max(0, req.ahead), max(0, space / spacing - 1)))
            if n < 8:
                n, spacing = 12, max(space, 0.06) / 13
            ratio = (last / snap.spot)
            sig = (c["sig_rem"] or c["sig_open"] or 0) * ratio
            mins = c["mins_left"] if c["mins_left"] > 0 else 390.0
            sd_c = sig * min(1.0, tfm / mins) ** 0.5 if sig else None
            path_lv = [{"label": l["label"], "value": l["price"], "call": l["call"]} for l in levels]
            if pb["state"] == "short" and c["open"]:
                d = 1 if snap.spot >= c["open"] else -1
            else:
                nl = min(path_lv, key=lambda x: abs(x["value"] - last), default=None)
                d = 1 if nl is None or nl["value"] >= last else -1
            if sd_c:
                proj = {"main": bh.ghost_path(path_lv, last, sd_c, n, d), "alt": bh.ghost_path(path_lv, last, sd_c, n, d, flip_first=True),
                        "spacing": spacing, "start_x": rd["last_candle_x"], "timeframe_minutes": tfm, "direction": d}
        return {"meta": c["m"], "reading": rd, "problems": problems, "warnings": warnings, "levels": levels, "projection": proj, "unit": unit,
                "regime": {k2: pb[k2] for k2 in ("state", "title", "tagline", "color", "r_range", "trades")},
                "note": "Claude read the picture; Q DATA made the calls from today's options data. Scenarios, not forecasts. One paid API request per read."}

    # ---- history: one day at a time, in plain terms -------------------------------------------------------------------
    HIST_METRICS = [("total_net_gex", "Total dealer gamma (GEX)", "Above zero, dealer hedging tends to calm moves; below zero it tends to speed them up. A drop toward zero or below means a jumpier market."),
                    ("gamma_flip", "Gamma flip", "The price where dealer gamma changes sign. Price above it tends to be calmer, below it rougher."),
                    ("atm_iv_front", "Implied volatility (nearest expiry)", "How big a move options are pricing. Rising = the market expects more movement."),
                    ("expected_move_straddle", "Expected move (straddle)", "The points options price for the move to the nearest expiry."),
                    ("pc_ratio_volume", "Put/call ratio (volume)", "Puts traded per call today. Above 1 = more put trading (hedging or bearish bets)."),
                    ("pc_ratio_oi", "Put/call ratio (open interest)", "Open puts per open call. Slow-moving; shows how hedged the market is.")]

    @app.get("/api/history/day")
    def history_day(underlying: str, date: str | None = None, metric: str = "total_net_gex"):
        """One stored session explained: how the day went against what options expected, how each level behaved when price got there,
        and how the main numbers moved, that day and across days."""
        from .services import reactions as rx
        u = h.underlying_ok(underlying)
        if metric not in {m[0] for m in HIST_METRICS}:
            raise HTTPException(422, "unknown metric")
        snap = h.snapshot(u)
        to_f, finfo = h.futures_converter(u, snap, h.now_fn())
        k = (to_f(snap.spot) / snap.spot) if to_f else None
        fx = (lambda v: None if v is None or k is None else v * k)
        all_rows = []
        for r in db.price_history(u, 20000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t:
                all_rows.append((t, r["price"]))
        days = sorted({to_et(t).date() for t, _ in all_rows}, reverse=True)[:40]
        if not days:
            return {"available": False, "reason": "No prices stored yet. History builds up while the app runs during the session."}
        day = datetime.fromisoformat(date).date() if date else days[0]
        rows = sorted((t, p) for t, p in all_rows if to_et(t).date() == day)
        op, cl = datetime.combine(day, RTH_OPEN, ET), datetime.combine(day, RTH_CLOSE, ET)
        rth = [(t, p) for t, p in rows if op <= t <= cl]
        S_ = {"observations": len(rows), "rth_observations": len(rth)}
        if rth:
            o, hi, lo, c_ = rth[0][1], max(p for _, p in rth), min(p for _, p in rth), rth[-1][1]
            late = (rth[0][0] - op).total_seconds() / 60
            dm = [r for r in series(u, "day_move", day) if r["t"] >= iso(op)]
            em = dm[0]["value"] if dm else None
            ratio = (hi - lo) / em if em else None
            ro = [r for r in series(u, "regime_open", day)]
            label = (ro[0]["detail"] or {}).get("label") if ro else None
            calm = label and label.startswith(("Pinned", "Calm"))
            wild = label and label.startswith(("Trending", "Leaning unstable"))
            if ratio is None:
                verdict = "No expected move was stored near the open, so the day cannot be compared with it."
            elif ratio > 1.2:
                verdict = f"A bigger day than options priced: the range was {ratio:.1f} times the expected move."
            elif ratio < 0.7:
                verdict = f"A quieter day than options priced: the range was only {ratio:.1f} times the expected move."
            else:
                verdict = f"About the size options priced: the range was {ratio:.1f} times the expected move."
            matched = None
            if label and ratio is not None and (calm or wild):              # transition / mixed mornings made no size call to grade
                matched = bool((calm and ratio <= 1.0) or (wild and ratio > 1.0))
            S_.update({"open": o, "high": hi, "low": lo, "close": c_, "range": hi - lo, "change": c_ - o, "expected_move": em, "range_vs_move": ratio,
                       "verdict": verdict, "regime_label": label, "regime_matched": matched, "open_late_minutes": late if late > 15 else None,
                       "open_futures": fx(o), "high_futures": fx(hi), "low_futures": fx(lo), "close_futures": fx(c_)})
        lv = db.load_session_levels(u, day.isoformat())
        tc = rx.analyze(lv, rows, tol=0.0005) if lv and len(rows) >= 3 else []
        touched = {(t["label"], t["level"]) for t in tc}
        touches = []
        grouped = {}
        for t in sorted(tc, key=lambda x: x["time"]):                     # one row per touch: level types at the same price are listed together
            key = (t["time"], round(t["level"], 2))
            if key in grouped:
                grouped[key]["label"] += " / " + t["label"]
                continue
            grouped[key] = t = dict(t)
            side = 1 if t["approach"] == "from above" else -1
            held = t.get("held_30") if t.get("held_30") is not None else t.get("held_15")
            bounce = t["max_above"] if side > 0 else t["max_below"]
            through = t["max_below"] if side > 0 else t["max_above"]
            touches.append({"_key": key, "time": iso(t["time"]), "label": t["label"], "category": t["category"], "level": t["level"], "level_futures": fx(t["level"]),
                            "approach": "came down to it" if side > 0 else "came up to it", "result": "held" if held else "broke" if held is False else "not measured",
                            "bounce": bounce, "through": through})
        for r in touches:
            r["label"] = grouped[r.pop("_key")]["label"]
        untouched = [{"label": x["label"], "level": x["value"], "level_futures": fx(x["value"]), "category": x["category"]} for x in lv if (x["label"], x["value"]) not in touched]
        lines = {}
        for name in ("gamma_flip", "call_wall", "put_wall", "em_low", "em_high", "gex0_flip", "gex0_call_wall", "gex0_put_wall"):
            lines[name] = [{"t": r["t"], "value": r["value"]} for r in series(u, name, day)]
        mh = db.metric_history(u, metric, 20000)
        daily = {}
        for r in mh:
            t = parse_ts(r["calculated_at"])
            if t and r["value"] is not None:
                daily[to_et(t).date().isoformat()] = r["value"]
        intraday = [{"t": r["t"], "value": r["value"]} for r in series(u, metric, day)]
        held_n = sum(1 for t in touches if t["result"] == "held")
        broke_n = sum(1 for t in touches if t["result"] == "broke")
        return {"available": True, "underlying": u, "day": day.isoformat(), "days": [d.isoformat() for d in days], "summary": S_,
                "price": [{"t": iso(t), "price": p} for t, p in rows], "lines": lines, "touches": touches, "untouched": untouched,
                "touch_counts": {"held": held_n, "broke": broke_n, "levels": len(lv), "touched_levels": len(touched)},
                "metric": {"name": metric, "options": [{"name": m[0], "label": m[1], "meaning": m[2]} for m in HIST_METRICS],
                           "daily": [{"day": d, "value": v} for d, v in sorted(daily.items())][-40:], "intraday": intraday},
                "futures_root": finfo.get("root"), "futures_ratio": k,
                "note": "Built only from what this app stored while it was running (a price about every 2 minutes, about 15 minutes delayed). "
                        "Futures prices use today's index-to-futures conversion, so older days are approximate."}

    # ---- stack map: where the most different kinds of levels pile up ----------------------------------------------------
    def prior_session(u, day):
        """Yesterday (the last earlier day with regular-session prices): high, low, last price."""
        by = {}
        for r in db.price_history(u, 20000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t:
                e = to_et(t)
                if e.date() < day and RTH_OPEN <= e.time() <= RTH_CLOSE:
                    by.setdefault(e.date(), []).append((t, r["price"]))
        if not by:
            return None
        d = max(by)
        px = sorted(by[d])
        return {"day": d.isoformat(), "high": max(p for _, p in px), "low": min(p for _, p in px), "close": px[-1][1]}

    @app.get("/api/analytics/stack-map")
    def stack_map(underlying: str, convention: str = "standard", min_families: int = Query(3, ge=2, le=8), tol_pct: float = Query(0.05, gt=0, le=0.5)):
        """Every level the app makes, by family, and only the areas where several different families pile up."""
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c = context(u, convention)
        snap, z, now = c["snap"], c["z"], c["now"]
        spot = snap.spot
        pb = qt.gamma_playbook(z, spot, c["open"], c["sig_open"], c["gamma_series"], c["sig_rem"])
        items = []
        j = h.levels_payload(u, convention, "auto", None, top=6, by_expiry=4, mid=2, moves=4)
        for x in j["levels"]:
            f = sk.family_of(x["category"])
            if f:
                items.append({"price": x["value"], "family": f, "label": x["label"], "category": x["category"],
                              "weight": float(x.get("importance") or sk.DEFAULT_W.get(f, 0.5))})
        if c["open"] and c["sig_open"]:
            for k_ in qt.LADDER:
                for sgn in (1, -1):
                    items.append({"price": c["open"] + sgn * k_ * c["sig_open"], "family": "ladder", "category": "ladder",
                                  "label": f"Ladder {'+' if sgn > 0 else '-'}{k_:g} sd", "weight": 0.6 if k_ in (1.0, 2.0) else 0.45})
            hl = qt.hodlod(c["open"], c["hi"], c["lo"], spot, c["sig_open"], c["sig_rem"])
            pr = (hl or {}).get("projection")
            if pr:
                for side, name in (("hod", "Projected HOD"), ("lod", "Projected LOD")):
                    for q_, w in (("p50", 0.65), ("p80", 0.5)):
                        items.append({"price": pr[side][q_], "family": "proj", "category": "projection", "label": f"{name} {q_[1:]}%", "weight": w})
            items.append({"price": c["open"], "family": "session", "category": "session", "label": "Today's open", "weight": 0.6})
        if c["hi"] is not None:
            items.append({"price": c["hi"], "family": "session", "category": "session", "label": "High so far", "weight": 0.6})
            items.append({"price": c["lo"], "family": "session", "category": "session", "label": "Low so far", "weight": 0.6})
        ps = prior_session(u, c["day"])
        if ps:
            for k_, name in (("high", "Yesterday's high"), ("low", "Yesterday's low"), ("close", "Yesterday's close")):
                items.append({"price": ps[k_], "family": "prior", "category": "prior", "label": name, "weight": 0.8 if k_ != "close" else 0.6})
        for meas in ("volume", "oi", "gex"):
            try:
                am = fl.activity_map(snap.contracts, spot, now, meas, "total", 0.04, 8, convention, None, 3)
            except (ValueError, KeyError):
                continue
            for hs in am.get("hot_spots", [])[:3]:
                items.append({"price": hs["price"], "family": "activity", "category": "activity", "label": f"{meas.upper() if meas != 'volume' else 'Volume'} hot spot",
                              "weight": round(0.5 + 0.5 * min(1.0, hs.get("share") or 0), 3)})
        tol = tol_pct / 100 * spot
        stacks = sk.find_stacks(items, spot, tol, min_families=min_families)
        strikes = an.gex_by_strike(snap.contracts, spot, now, convention)["strikes"]
        near = [s_ for s_ in strikes if abs(s_["strike"] - spot) <= 0.03 * spot]
        scale = max((abs(bh.local_gex(near, s_["strike"], spot)) for s_ in near), default=0.0)
        gf = an.gamma_flip(snap.contracts, spot, now, convention)
        flips = [z.get("flip") if z.get("available") else None, gf["flip"] if gf["found"] else None]
        sig = c["sig_rem"] or c["sig_open"]
        for st in stacks:
            cats = [m["category"] for m in st["members"]]
            call, why, strength, g = bh.call_for({"value": st["center"], "category": cats[0], "members": cats}, pb["state"], spot, flips, strikes, scale)
            st.update({"call": call, "why": why, "tier": sk.tier(st["score"]), "side": "above" if st["center"] > spot else "below",
                       "points": st["center"] - spot, "chance": qt.touch_prob(abs(st["center"] - spot), sig) if sig else None,
                       "futures": c["conv"](st["center"]), "futures_low": c["conv"](st["low"]), "futures_high": c["conv"](st["high"]),
                       "family_names": [sk.FAMILY_NAME.get(f, f) for f in st["families"]]})
            for m in st["members"]:
                m["futures"] = c["conv"](m["price"])
                m["family_name"] = sk.FAMILY_NAME.get(m["family"], m["family"])
        above = sorted((x for x in stacks if x["side"] == "above"), key=lambda x: x["center"])
        below = sorted((x for x in stacks if x["side"] == "below"), key=lambda x: -x["center"])
        for arr, other in ((above, below), (below, above)):
            for i, st in enumerate(arr):
                lvl = {"label": " / ".join(st["family_names"][:3]) + " stack", "value": st["center"], "call": st["call"]}
                nxt = arr[i + 1] if i + 1 < len(arr) else None
                back = arr[i - 1] if i > 0 else (other[0] if other else None)
                tolabel = lambda s_: {"label": "the next stacked area", "value": s_["center"]} if s_ else None
                here = {"label": "today's price area", "value": spot}
                st.update(bh.prediction(lvl, st["side"], tolabel(nxt), tolabel(back) or here, pb["state"], st["chance"]))
                if nxt is None:
                    st["plan"] = st["plan"].replace("the next level", "open air (no stacked area beyond it)")
        fams = {}
        for it in items:
            fams[it["family"]] = fams.get(it["family"], 0) + 1
        return {"meta": c["m"], "stacks": sorted(stacks, key=lambda x: -x["center"]), "spot": spot, "spot_futures": c["spot_f"],
                "futures_root": c["root"], "futures_info": c["futures_info"], "already_in": qt.already_in(c["hi"], c["lo"], spot, c["sig_rem"]),
                "high": c["hi"], "low": c["lo"], "open": c["open"], "prior": ps,
                "regime": {k_: pb[k_] for k_ in ("state", "title", "tagline", "color", "r_range")},
                "inputs": {"levels": len(items), "by_family": {sk.FAMILY_NAME.get(f, f): n for f, n in sorted(fams.items(), key=lambda kv: -kv[1])},
                           "tolerance_points": tol, "min_families": min_families},
                "price": [{"t": iso(t), "price": p} for t, p in c["rows"]], "rule": sk.RULE,
                "note": "Only areas where at least " + str(min_families) + " different kinds of levels sit within " + f"{tol:,.0f}" + " points of each other are shown. Not backtested."}

    # ---- game plan: every tool votes, the best two or three setups come out -------------------------------------------
    GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "No trade": 3}

    @app.get("/api/analytics/game-plan")
    def game_plan(underlying: str, convention: str = "standard"):
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c = context(u, convention)
        snap, now = c["snap"], c["now"]
        spot, sig_o, sig_r = snap.spot, c["sig_open"], c["sig_rem"]
        if not sig_o or not sig_r or c["mins_left"] <= 0:
            return {"meta": c["m"], "available": False, "reason": "The game plan runs during the regular session (9:30 to 16:00 ET) when the expected move is priced."}
        sm = stack_map(u, convention, 3, 0.05)
        lm = level_map(u, convention, 40)
        src = c["rth"] if len(c["rth"]) >= 30 else c["rows"]
        mr = qt.mean_reversion([p for _, p in src], step_minutes(src))
        sib = sibling(u)
        if sib:
            nq_first = INDEX_GROUP.get(u) == "Nasdaq 100"
            al = qt.align(c["rows"], day_rows(sib, c["day"]))
            pc = qt.pca_pair(al if nq_first else [(t, y, x) for t, x, y in al])
        else:
            pc = {"available": False}
        drift = fl.greek_exposure(snap.contracts, spot, now, convention).get("drift_to_close")
        try:
            rec_all = {r["category"]: r for r in h.reactions(u, 30, 0.05)["summary"]}
        except HTTPException:
            rec_all = {}
        state = lm["regime"]["state"]
        cands = []
        for st in sm["stacks"]:
            cands.append({"price": st["center"], "low": st["low"], "high": st["high"], "call": st["call"], "kinds": len(st["families"]),
                          "label": " / ".join(st["family_names"][:3]) + (" +" + str(len(st["family_names"]) - 3) if len(st["family_names"]) > 3 else ""),
                          "why": st["why"], "cats": [m["category"] for m in st["members"]], "source": "stack"})
        tol = 0.0005 * spot
        singles = sorted((l for l in lm["levels"] if (l.get("chance") or 0) >= 0.08 and not any(abs(l["value"] - x["price"]) <= tol for x in cands)),
                         key=lambda l: -((l.get("chance") or 0) * (0.3 + l["strength"])))
        for l in singles[:max(0, 6 - len(cands))]:
            cands.append({"price": l["value"], "low": l.get("low") or l["value"], "high": l.get("high") or l["value"], "call": l["call"], "kinds": 1,
                          "label": l["label"], "why": l["why"], "cats": [l["category"]], "source": "level"})
        prices = sorted({x["price"] for x in cands} | {l["value"] for l in lm["levels"]})
        pull = state == "long" and mr.get("significant")
        cards, avoid = [], []
        for cd in cands:
            t = gp.trade_for(cd, spot, sig_o, prices)
            if t is None:
                avoid.append({**cd, "reason": "CHOP: expect two-way trade here, no edge either way.", "futures": c["conv"](cd["price"])})
                continue
            if (t["entry"] - spot) * (1 if cd["price"] > spot else -1) < 0:
                continue
            mc = qt.monte_carlo(t["entry"], sig_r, t["stop_dist"], rs=(round(t["r"], 2),), paths=600, minutes_left=c["mins_left"],
                                half_life_minutes=mr.get("half_life_minutes") if pull else None, mean=mr.get("mean") if pull else None)
            row = mc["rows"][0][t["side"].lower()] if mc.get("available") else None
            rec = None
            for cat in cd["cats"]:
                r_ = rec_all.get(cat)
                if r_ and r_.get("measured_30") and (rec is None or r_["measured_30"] > rec["n"]):
                    rec = {"held_pct": r_["held_pct_30"], "n": r_["measured_30"]}
            ctx = {"state": state, "already_in": sm["already_in"], "mr": mr, "pca": pc, "drift": drift, "record": rec,
                   "chance": qt.touch_prob(abs(t["entry"] - spot), sig_r), "ev_r": row["ev_r"] if row else None, "p_win": row["win"] if row else None}
            votes = gp.votes_for(t, cd, ctx)
            g, yes, no = gp.grade(votes)
            card = {**t, "grade": g, "yes": yes, "no": no, "votes": [{"name": n, "vote": v, "reason": r} for n, v, r in votes],
                    "level": cd["price"], "label": cd["label"], "call": cd["call"], "kinds": cd["kinds"], "source": cd["source"], "why": cd["why"],
                    "chance": ctx["chance"], "p_win": ctx["p_win"], "ev_r": ctx["ev_r"],
                    "f": {k_: c["conv"](t[k_]) for k_ in ("entry", "stop", "target")}, "stop_points_f": c["conv"](t["entry"]) - c["conv"](t["entry"] - t["stop_dist"]) if c["spot_f"] else None}
            (cards if g != "No trade" else avoid).append(card)
        cards.sort(key=lambda x: (GRADE_ORDER[x["grade"]], -(x["yes"] - x["no"]), -(x["chance"] or 0)))
        top = cards[:3]
        day = c["day"].isoformat()
        block = to_et(now).hour * 2 + to_et(now).minute // 30
        for cd in top:                                       # log each card once per half hour so the record can grade it later
            key = f"gp:{u}:{day}:{block}:{cd['side']}:{round(cd['entry'])}"
            if not db.get_meta(key):
                db.save_metric(snap.snapshot_id, u, "game_plan_card", cd["yes"] - cd["no"],
                               {k_: cd[k_] for k_ in ("grade", "side", "kind", "entry", "stop", "target", "r", "label", "call")}, now)
                db.set_meta(key, "1")
        no_trade_reason = None
        if not top:
            no_trade_reason = ("No setup has more of the team for it than against it right now. " +
                               ("; ".join(f"{a.get('side', 'Area')} at {a.get('level', a.get('price')):,.0f}: " + ", ".join(v["reason"] for v in a.get("votes", []) if v["vote"] is False)[:200]
                                          for a in avoid[:2] if a.get("votes")) or "The nearby areas are CHOP."))
        return {"meta": c["m"], "available": True, "cards": top, "more": cards[3:6], "avoid": avoid[:5], "no_trade": no_trade_reason,
                "regime": {k_: lm["regime"][k_] for k_ in ("state", "title", "tagline", "color", "r_range")}, "already_in": sm["already_in"],
                "spot": spot, "spot_futures": c["spot_f"], "futures_root": c["root"], "minutes_left": c["mins_left"], "record": game_record(u),
                "rule": gp.RULE, "note": "The team's votes use my own thresholds and are not backtested. The record below grades every logged card against what price did next."}

    def game_record(u):
        rows = db.metric_series(u, "game_plan_card", limit=3000)
        if not rows:
            return {"cards": 0, "by_grade": [], "recent": []}
        px_all = []
        for r in db.price_history(u, 20000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t:
                px_all.append((t, r["price"]))
        px_all.sort()
        res, by = [], {}
        for r in rows:
            d = r["detail"] or {}
            t0 = parse_ts(r["t"])
            if not t0 or "entry" not in d:
                continue
            close = datetime.combine(to_et(t0).date(), RTH_CLOSE, ET)
            after = [(t, p) for t, p in px_all if t0 < t <= close]
            o = gp.outcome(d, after)
            res.append({"t": r["t"], **d, "outcome": o})
            g = by.setdefault(d.get("grade", "?"), {"grade": d.get("grade", "?"), "cards": 0, "target": 0, "stop": 0, "open": 0, "not_filled": 0, "r_sum": 0.0})
            g["cards"] += 1
            if o == "target":
                g["target"] += 1
                g["r_sum"] += d.get("r") or 0
            elif o == "stop":
                g["stop"] += 1
                g["r_sum"] -= 1
            elif o == "open":
                g["open"] += 1
            else:
                g["not_filled"] += 1
        for g in by.values():
            done = g["target"] + g["stop"]
            g["win_rate"] = g["target"] / done if done else None
            g["avg_r"] = g["r_sum"] / done if done else None
        return {"cards": len(res), "by_grade": sorted(by.values(), key=lambda g: GRADE_ORDER.get(g["grade"], 9)), "recent": res[-15:][::-1],
                "note": "Each card is logged once per half hour. Filled = price reached the entry after the card was made; then whichever of the target or stop came first. "
                        "Uses the app's stored prices (about every 2 minutes), so very fast moves can be judged loosely. Needs weeks of cards to mean anything."}
