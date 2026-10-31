"""Endpoints for the Volatility, Earnings and Replay tabs (added in 1.15)."""
from __future__ import annotations
import json
from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel

from .api_more import _day_bounds, _in_day
from .services import earnings as ea
from .services import intraday as idy
from .services import replay as rp
from .services import volatility as vol
from .timeutil import iso, parse_ts, to_et

WEIGHT_KEY = "extras:weight_overrides"


class WeightsIn(BaseModel):
    weights: dict          # {"NVDA": 8.1, ...} in percent; an empty value removes your weight for that symbol


def register(app, h):
    """h: namespace with db, primary_db, extras, snapshot, futures_converter, now_fn, underlying_ok, settings."""

    def index_ctx(u):
        """(index price, futures/index ratio) for _NDX or _SPX from the latest option snapshot, or (None, None)."""
        try:
            snap = h.snapshot(h.underlying_ok(u))
        except HTTPException:
            return None, None
        to_f, _ = h.futures_converter(u, snap, h.now_fn())
        f = to_f(snap.spot) if to_f else None
        return snap.spot, (f / snap.spot) if f and snap.spot else None

    def no_extras():
        return {"available": False, "reason": "The VIX and earnings feed is turned off (MARKET_EXTRAS=0 in your .env file)."}

    # ---- volatility ----------------------------------------------------------------------------------------------------------
    @app.get("/api/volatility")
    def volatility():
        x = h.extras
        if x is None or not x.s.extras_enabled:
            return no_extras()
        ndx, nqr = index_ctx("_NDX")
        spx, esr = index_ctx("_SPX")
        a = vol.analyze(x.quotes, x.hist, ndx, spx, nqr, esr, h.now_fn())
        if not a["available"]:
            return {"available": False, "reason": "No VIX readings yet. The first download runs a few seconds after the app starts.",
                    "status": x.status_view()}
        hist = {n: [{"d": d.isoformat(), "v": v} for d, v in rows[-vol.TRADING_DAYS:]] for n, rows in x.hist.items()}
        today = to_et(h.now_fn()).date()
        a0, _ = _day_bounds(today)
        intraday = {}
        for k, n, *_ in vol.INDICES:
            pts = []
            for r in h.primary_db.price_history(k, 2000):
                t = parse_ts(r["source_ts"] or r["retrieved_at"])
                if t and iso(t) >= a0:
                    pts.append({"t": iso(t), "v": r["price"]})
            intraday[n] = pts
        return {"available": True, **a, "history": hist, "intraday": intraday, "status": x.status_view(),
                "context": {"ndx": ndx, "spx": spx, "nq_ratio": nqr, "es_ratio": esr},
                "note": "Cboe's free index values, about 15 minutes delayed. Outside market hours they show the last close."}

    # ---- earnings ------------------------------------------------------------------------------------------------------------
    def overrides():
        try:
            return {k: float(v) for k, v in json.loads(h.primary_db.get_meta(WEIGHT_KEY) or "{}").items()}
        except (ValueError, TypeError):
            return {}

    @app.get("/api/earnings")
    def earnings(horizon: int = 45):
        x = h.extras
        if x is None or not x.s.extras_enabled:
            return no_extras()
        if not x.weights:
            return {"available": False, "reason": "Waiting for the Nasdaq-100 member list (the first download runs shortly after start).",
                    "status": x.status_view()}
        ndx, nqr = index_ctx("_NDX")
        nq = ndx * nqr if ndx and nqr else ndx
        names = x.names()
        tbl = ea.build_table(names, x.weights, x.reports, x.timings, x.moves, nq, to_et(h.now_fn()).date(),
                             max(1, min(120, horizon)), overrides())
        top = sorted(x.weights.items(), key=lambda kv: -kv[1]["weight"])[:25]
        return {"available": True, **tbl, "price_label": "NQ" if ndx and nqr else "NDX" if ndx else None,
                "weights_top": [{"symbol": s, "name": w["name"], "weight": w["weight"], "raw_weight": w["raw_weight"]} for s, w in top],
                "overrides": overrides(), "status": x.status_view(), "followed": names}

    @app.post("/api/earnings/weights")
    def set_weights(body: WeightsIn):
        cur = overrides()
        for k, v in body.weights.items():
            k = str(k).upper().strip()
            if v in (None, ""):
                cur.pop(k, None)
                continue
            try:
                p = float(v)
            except (TypeError, ValueError):
                raise HTTPException(422, f"Weight for {k} is not a number")
            if not 0 < p < 60:
                raise HTTPException(422, f"Weight for {k} must be between 0 and 60 percent")
            cur[k] = p / 100
        h.primary_db.set_meta(WEIGHT_KEY, json.dumps(cur))
        return {"ok": True, "overrides": cur}

    # ---- interval map (1.30.0): time x strike heatmap of any exposure ------------------------------------------------------------
    IMAP = {"gex": ("Modeled GEX", "$ per 1% move", True), "dex": ("Dealer delta exposure (DEX)", "$ of delta", True),
            "charm": ("Charm exposure", "$ delta per day", True), "vanna": ("Vanna exposure", "$ delta per IV point", True),
            "volume": ("Volume (calls + puts)", "contracts", False), "oi": ("Open interest (calls + puts)", "contracts", False)}

    def imap_frames(u, d, measure, z):
        """[(t, {strike: value})] for one day, oldest first, and where they came from."""
        if measure == "gex":
            rows = series(u, "gex0_profile" if z else "gex_profile", d)
            return [(r["t"], {s[0]: s[1] for s in (r["detail"] or [])}) for r in rows], "saved"
        col = 1 + idy.IMAP_MEASURES.index(measure) + (5 if z else 0)
        rows = series(u, "imap_profile", d)
        if rows:
            return [(r["t"], {s[0]: s[col] for s in (r["detail"] or [])}) for r in rows], "saved"
        out = []                                       # days before 1.30.0: rebuilt from the full option chains still stored for that day
        a, b = _day_bounds(d)
        for r in sorted(h.db.list_snapshots(u, 500), key=lambda r: r["id"]):
            t_ = r["source_ts"] or r["retrieved_at"]
            pt = parse_ts(t_) if t_ else None
            if not pt or not (a <= iso(pt) < b):
                continue
            s = h.db.load_snapshot(u, r["id"])
            if s and s.spot:
                out.append((iso(pt), {x[0]: x[col] for x in idy.strike_measures(s.contracts, s.spot, pt)}))
        return out, "rebuilt" if out else "none"

    @app.get("/api/charts/intervalmap")
    def interval_map(underlying: str, day: str | None = None, measure: str = "gex", scope: str = "all", interval: int = 5):
        u = h.underlying_ok(underlying)
        if measure not in IMAP or scope not in ("all", "0dte") or interval not in (0, 1, 5, 10, 15, 30):
            raise HTTPException(422, "measure: gex dex charm vanna volume oi; scope: all or 0dte; interval: 0 1 5 10 15 30")
        stamps = []
        for r in h.db.price_history(u, 20000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t:
                stamps.append(t)
        days = sorted({to_et(t).date().isoformat() for t in stamps}, reverse=True)[:40]
        title, units, signed = IMAP[measure]
        if not days:
            return {"available": False, "days": [], "reason": "Nothing stored yet. The map builds from what Q DATA saves while it runs."}
        d = datetime.fromisoformat(day).date() if day else datetime.fromisoformat(days[0]).date()
        frames, source = imap_frames(u, d, measure, scope == "0dte")
        base = {"days": days, "day": d.isoformat(), "measure": measure, "title": title, "units": units, "signed": signed, "scope": scope}
        if not frames:
            why = ("Dealer delta, charm, vanna, volume and open interest are saved over time from 1.30.0 on; for earlier days they can only be "
                   "rebuilt while that day's full option chains are still stored (the most recent ones). GEX works for every stored day.")
            return {"available": False, **base, "reason": f"No {title.lower()} stored for {d.isoformat()}. " + (why if measure != "gex" else "")}
        if interval:                                   # the last snapshot of each interval
            keep = {}
            for t_, v in frames:
                e = to_et(parse_ts(t_))
                keep[(e.hour * 60 + e.minute) // interval] = (t_, v)
            frames = [keep[k] for k in sorted(keep)]
        a, b = _day_bounds(d)
        price = [{"t": iso(parse_ts(r["source_ts"] or r["retrieved_at"])), "price": r["price"]} for r in h.db.price_history(u, 20000)
                 if parse_ts(r["source_ts"] or r["retrieved_at"]) and a <= iso(parse_ts(r["source_ts"] or r["retrieved_at"])) < b]
        ks = sorted({k for _, v in frames for k in v})
        zz = [[(v.get(k) or None) for _, v in frames] for k in ks]
        z0 = scope == "0dte"
        lines = {k: [{"t": r["t"], "value": r["value"]} for r in series(u, n, d)]
                 for k, n in (("gamma_flip", "gex0_flip" if z0 else "gamma_flip"), ("call_wall", "gex0_call_wall" if z0 else "call_wall"),
                              ("put_wall", "gex0_put_wall" if z0 else "put_wall"))}
        ratio, root, how = None, None, ""
        fr = series(u, "fut_ratio", d)
        try:
            snap = h.snapshot(u)
            to_f, info = h.futures_converter(u, snap, h.now_fn())
            root = info.get("root")
            if fr:
                ratio, how = fr[-1]["value"], "that day's saved ratio"
            elif to_f and snap.spot:
                ratio, how = to_f(snap.spot) / snap.spot, "today's conversion (approximate for older days)"
        except HTTPException:
            pass
        mags = sorted(abs(x) for row in zz for x in row if x)
        cap = mags[int(len(mags) * 0.98)] if mags else 1
        return {"available": True, **base, "source": source, "times": [t_ for t_, _ in frames], "strikes": ks, "z": zz, "cap": cap,
                "price": price, "lines": lines, "futures_ratio": ratio, "futures_root": root, "ratio_from": how,
                "note": ("Each column is the last stored snapshot of its interval (options data about 15 minutes delayed). "
                         + ("Rebuilt from the full option chains still stored for this day. " if source == "rebuilt" else ""))}

    # ---- session replay ------------------------------------------------------------------------------------------------------
    def series(u, name, day):
        a, _ = _day_bounds(day)
        return _in_day(h.db.metric_series(u, name, since=a), day)

    @app.get("/api/charts/replay")
    def replay(underlying: str, day: str | None = None, scope: str = "all"):
        u = h.underlying_ok(underlying)
        if scope not in ("all", "0dte"):
            raise HTTPException(422, "scope must be all or 0dte")
        stamps = []
        for r in h.db.price_history(u, 20000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t:
                stamps.append(t)
        days = sorted({to_et(t).date().isoformat() for t in stamps}, reverse=True)[:40]
        if not days:
            return {"available": False, "reason": "Nothing stored yet. Replay builds from what the app saves while it runs during the session."}
        d = datetime.fromisoformat(day).date() if day else datetime.fromisoformat(days[0]).date()
        z = scope == "0dte"
        prof = [{"t": r["t"], "detail": r["detail"] or []} for r in series(u, "gex0_profile" if z else "gex_profile", d)]
        a, b = _day_bounds(d)
        price = []
        for r in h.db.price_history(u, 20000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t and a <= iso(t) < b:
                price.append({"t": iso(t), "price": r["price"]})
        src = {"gamma_flip": "gex0_flip" if z else "gamma_flip", "call_wall": "gex0_call_wall" if z else "call_wall",
               "put_wall": "gex0_put_wall" if z else "put_wall", "em_low": "em_low", "em_high": "em_high",
               "gamma_at_spot": "gamma0_at_spot" if z else "gamma_at_spot"}
        lines = {k: [{"t": r["t"], "value": r["value"]} for r in series(u, name, d)] for k, name in src.items()}
        if not prof:
            return {"available": False, "day": d.isoformat(), "days": days,
                    "reason": f"No GEX snapshots were stored on {d.isoformat()} ({'0DTE' if z else 'all expiries'}). Pick another day."}
        out = rp.build_frames(prof, price, lines)
        ratio, root = None, None
        try:
            snap = h.snapshot(u)
            to_f, info = h.futures_converter(u, snap, h.now_fn())
            ratio = (to_f(snap.spot) / snap.spot) if to_f and snap.spot else None
            root = info.get("root")
        except HTTPException:
            pass
        return {"available": True, "underlying": u, "day": d.isoformat(), "days": days, "scope": scope, **out,
                "futures_ratio": ratio, "futures_root": root,
                "note": "Each frame is one stored snapshot (about every 2 minutes while the data changes, about 15 minutes delayed). "
                        "Lines show the last known value at that moment. Futures prices use today's index-to-futures conversion, so older days are approximate."}
