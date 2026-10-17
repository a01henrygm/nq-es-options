"""FastAPI endpoints. The browser only talks to these; the provider key never leaves the backend."""
from __future__ import annotations
import contextvars
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, ROOT
from .database import Database
from .services import analytics as an
from .services import market
from .services.freshness import classify
from .security import Auth, install_auth
from .services.bias import compute_bias
from .services.regime import compute_regime
from .services.importance import RULE as IMPORTANCE_RULE, QUOTA_RULE, make_zones, parse_quota, score_levels, select_by_quota
from .services.levels import RELIABILITY_RULE, build_levels
from .services.pine import build_pine
from .services import reactions as rx
from .services.mapping import (FUTURES_FOR, INDEX_GROUP, SAME_SCALE, PricePoint, evaluate_methods, map_level, map_with_typed_basis, pair_observations, roll_status)
from .timeutil import iso, parse_ts, to_et, utcnow

CONVENTIONS = list(an.SIGNS)


class CustomLevel(BaseModel):
    underlying: str
    label: str
    value: float
    units: str = "underlying"


class EventIn(BaseModel):
    date: str
    time: str = ""
    name: str
    importance: str = "high"
    note: str = ""


class BasisIn(BaseModel):
    root: str
    basis: float


class FuturesPrice(BaseModel):
    root: str
    price: float
    contract: str | None = None
    as_of: str | None = None


def create_app(primary_settings: Settings, primary_db: Database, primary_collector, now_fn=utcnow,
               extra_sources: dict | None = None, source_notes: list | None = None) -> FastAPI:
    """One dashboard, one or more data sources (Cboe, Massive). Each request may carry ?source=name; the rest of this
    function reads `settings`, `db` and `collector` through proxies that follow that choice."""
    app = FastAPI(title="NQ/ES Options Analytics", docs_url="/api/docs", openapi_url="/api/openapi.json")
    default_name = primary_settings.provider
    sources = {default_name: (primary_settings, primary_db, primary_collector)}
    sources.update(extra_sources or {})
    notes = source_notes or [{"name": n, "label": n, "enabled": True, "reason": ""} for n in sources]
    current = contextvars.ContextVar("source", default=default_name)

    class _Proxy:
        def __init__(self, i): self._i = i
        def __getattr__(self, n): return getattr(sources[current.get()][self._i], n)
        def __bool__(self): return sources[current.get()][self._i] is not None

    settings, db, collector = _Proxy(0), _Proxy(1), _Proxy(2)

    @app.middleware("http")
    async def choose_source(request, call_next):
        name = request.query_params.get("source")
        if name and name not in sources:
            return JSONResponse({"detail": f"Unknown data source '{name}'. Available: {', '.join(sources)}"}, status_code=404)
        tok = current.set(name or default_name)
        try:
            return await call_next(request)
        finally:
            current.reset(tok)

    def underlying_ok(u: str) -> str:
        u = u.upper()
        if u not in settings.underlyings:
            raise HTTPException(404, f"Unknown underlying {u}. Configured: {', '.join(settings.underlyings)}")
        return u

    def snapshot(u: str):
        st = collector.state.get(u) if collector else None
        snap = (st or {}).get("snapshot") or db.load_snapshot(u)
        if snap is None or not snap.spot:
            st = st or {}
            if st.get("last_error"):
                why = "The last download failed (details below). It retries automatically."
            elif snap is not None:
                why = ("A file was downloaded but it contained no underlying price that the app could read. Run diagnose.bat and "
                       "send logs\\diagnose_sample.json so the field name can be added.")
            elif st.get("last_attempt") is None:
                why = ("The first download has not finished yet. Cboe's files are large and can take up to a minute. "
                       "Wait a little, then press Refresh now.")
            else:
                why = "The last download finished but returned nothing usable. Check the Status tab and logs\\app.log."
            raise HTTPException(503, {"available": False, "reason": why, "last_error": st.get("last_error")})
        return snap

    def meta(snap, extra=None):
        now = now_fn()
        fr = classify(snap.source_ts, now, settings.options_plan)
        m = {"provider": snap.provider, "underlying": snap.underlying, "options_plan": settings.options_plan,
             "source_timestamp": iso(snap.source_ts), "retrieved_at": iso(snap.retrieved_at), "calculated_at": iso(now),
             "calculated_at_et": to_et(now).strftime("%Y-%m-%d %H:%M:%S %Z"), "data_status": fr.status, "freshness": fr.to_dict(),
             "spot": snap.spot, "spot_timestamp": iso(snap.spot_ts), "snapshot_id": snap.snapshot_id,
             "served_from": "database (last stored snapshot)" if snap.from_database else "live collector cache",
             "n_contracts": len(snap.contracts), "spot_note": snap.spot_note}
        m.update(extra or {})
        return m, fr, now

    def exps(expiration):
        return None if not expiration or expiration == "all" else [e for e in expiration.split(",") if e]

    # -- scheduled events (shared by every data source, kept in the default database) --------
    def upcoming_events(days=14):
        today = to_et(now_fn()).date()
        out = []
        for e in primary_db.list_events(today.isoformat()):
            d = (datetime.fromisoformat(e["date"]).date() - today).days
            if d <= days:
                out.append({**e, "days_away": d, "is_today": d == 0})
        return out

    @app.get("/api/events")
    def events(days: int = Query(21, ge=0, le=400)):
        ev = upcoming_events(days)
        return {"events": ev, "today": [e for e in ev if e["is_today"]], "note": "You maintain this list on the Events tab. The starter list came from published calendars and should be verified."}

    @app.post("/api/events")
    def add_event(e: EventIn):
        try:
            datetime.strptime(e.date, "%Y-%m-%d")
            if e.time:
                datetime.strptime(e.time, "%H:%M")
        except ValueError:
            raise HTTPException(422, "Date must look like 2026-12-09 and time like 14:00 (Eastern Time).") from None
        name = " ".join(e.name.split())[:60]
        if not name or e.importance not in ("high", "medium", "low"):
            raise HTTPException(422, "Give the event a name and an importance of high, medium or low.")
        return {"saved": True, "id": primary_db.add_event(e.date, e.time, name, e.importance, " ".join(e.note.split())[:120])}

    @app.delete("/api/events/{event_id}")
    def delete_event(event_id: int):
        if not primary_db.delete_event(event_id):
            raise HTTPException(404, "No such event")
        return {"deleted": True}

    # -- system ----------------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        from .version import __version__
        return {"ok": True, "time": iso(now_fn()), "version": __version__}

    @app.get("/api/status")
    def status():
        now = now_fn()
        per = {}
        for u in settings.underlyings:
            st = (collector.state.get(u) if collector else None) or {}
            snap = st.get("snapshot") or db.load_snapshot(u)
            fr = classify(snap.source_ts, now, settings.options_plan) if snap else None
            per[u] = {"last_attempt": iso(st.get("last_attempt")), "last_success": iso(st.get("last_success")),
                      "last_new_data": iso(st.get("last_new_data")), "consecutive_failures": st.get("failures", 0),
                      "last_error": st.get("last_error"), "has_snapshot": snap is not None,
                      "snapshot_source_timestamp": iso(snap.source_ts) if snap else None,
                      "data_status": fr.status if fr else "unavailable", "freshness": fr.to_dict() if fr else None}
        return {"source": current.get(), "default_source": default_name, "available_sources": notes,
                "provider": settings.provider, "requires_key": settings.requires_key,
                "api_key_configured": settings.key_configured if settings.requires_key else None, "options_plan": settings.options_plan,
                "market_state": market.market_state(now), "now_et": to_et(now).strftime("%Y-%m-%d %H:%M:%S %Z"),
                "next_open_et": to_et(market.next_open(now)).isoformat(), "poll_seconds": settings.poll_seconds,
                "underlyings": per, "recent_errors": db.recent_errors(10)}

    @app.get("/api/markets")
    def markets():
        now, out = now_fn(), {}
        for u in settings.underlyings:
            snap = (((collector.state.get(u) if collector else None) or {}).get("snapshot")) or db.load_snapshot(u)
            root = FUTURES_FOR.get(u)
            fp = db.latest_price(root) if root else None
            out[u] = {"spot": snap.spot if snap else None, "spot_timestamp": iso(snap.spot_ts) if snap else None,
                      "data_status": classify(snap.spot_ts, now, settings.options_plan).status if snap else "unavailable",
                      "futures_root": root, "futures_price": fp,
                      "contract": settings.futures_contracts.get(root) if root else None,
                      "roll": roll_status(settings.futures_contracts.get(root, ""), now.date()) if root else None}
        return {"market_state": market.market_state(now), "markets": out,
                "note": "Session highs/lows and previous-session levels need a price feed that this version does not include."}

    @app.post("/api/futures-price")
    def set_futures(p: FuturesPrice):
        root, now = p.root.upper(), now_fn()
        lim = {"NQ": (1000, 100000), "ES": (500, 20000)}
        if root not in lim or not (lim[root][0] <= p.price <= lim[root][1]):
            raise HTTPException(422, f"Price out of range for {root}")
        as_of = parse_ts(p.as_of) if p.as_of else now
        if as_of is None or as_of > now + timedelta(minutes=2):
            raise HTTPException(422, "as_of must be a valid time that is not in the future")
        contract = (p.contract or settings.futures_contracts.get(root, "")).upper()
        for _s, d, _c in sources.values():          # typed prices are shared by every data source
            d.save_price(root, p.price, "manual entry", as_of, now, contract, manual=True)
        return {"saved": True, "root": root, "contract": contract, "as_of": iso(as_of),
                "roll": roll_status(contract, now.date())}

    @app.post("/api/basis")
    def set_basis(b: BasisIn):
        root, now = b.root.upper(), now_fn()
        lim = {"NQ": 2000.0, "ES": 500.0}
        if root not in lim or abs(b.basis) > lim[root]:
            raise HTTPException(422, f"Basis out of range for {root} (limit +/-{lim.get(root, 0):.0f}). Type futures minus index, e.g. 260 for NQ.")
        for _s, d, _c in sources.values():
            d.save_price(f"{root}_BASIS", b.basis, "manual entry", now, now, None, manual=True)
        return {"saved": True, "root": root, "basis": b.basis, "entered_at": iso(now)}

    # -- options data ----------------------------------------------------------------------
    @app.get("/api/options/expirations")
    def expirations(underlying: str):
        snap = snapshot(underlying_ok(underlying))
        return {"expirations": sorted({c.expiry.isoformat() for c in snap.contracts})}

    @app.get("/api/options/chain")
    def chain(underlying: str, expiration: str | None = None, right: str = "all", strike_min: float | None = None,
              strike_max: float | None = None, limit: int = Query(500, le=5000)):
        snap = snapshot(underlying_ok(underlying))
        m, _, _ = meta(snap)
        sel = an.select(snap.contracts, exps(expiration), None if right == "all" else right.upper()[:1], strike_min, strike_max)
        sel.sort(key=lambda c: (c.expiry, c.strike, c.right))
        return {"meta": m, "total_matching": len(sel), "contracts": [c.to_dict() for c in sel[:limit]],
                "note": "Empty fields mean the provider did not supply that value. Nothing is estimated here."}

    @app.get("/api/options/flow")
    def flow(underlying: str = ""):
        return {"available": False,
                "reason": "Trade-level options flow needs the provider's trades feed, which this version does not collect. "
                          "The chain snapshot only has the last trade per contract, which is not a flow record."}

    # -- analytics -------------------------------------------------------------------------
    def analysed(underlying, expiration, right=None):
        u = underlying_ok(underlying)
        snap = snapshot(u)
        return snap, an.select(snap.contracts, exps(expiration), right)

    @app.get("/api/analytics/gex")
    def gex(underlying: str, expiration: str | None = None, convention: str = "standard"):
        if convention not in an.SIGNS:
            raise HTTPException(422, f"convention must be one of {CONVENTIONS}")
        snap, cons = analysed(underlying, expiration)
        m, _, now = meta(snap, {"expirations_included": exps(expiration) or "all", "convention": convention,
                                "contract_multiplier": "from provider (normally 100)",
                                "assumption": "Open interest does not show who holds contracts; the sign convention is a model assumption."})
        return {"meta": m, "data": an.gex_by_strike(cons, snap.spot, now, convention)}

    @app.get("/api/analytics/gamma-flip")
    def gamma_flip(underlying: str, expiration: str | None = None, convention: str = "standard"):
        if convention not in an.SIGNS:
            raise HTTPException(422, f"convention must be one of {CONVENTIONS}")
        snap, cons = analysed(underlying, expiration)
        m, _, now = meta(snap, {"convention": convention})
        return {"meta": m, "data": an.gamma_flip(cons, snap.spot, now, convention)}

    @app.get("/api/analytics/delta-exposure")
    def delta(underlying: str, expiration: str | None = None, convention: str = "standard"):
        if convention not in an.SIGNS:
            raise HTTPException(422, f"convention must be one of {CONVENTIONS}")
        snap, cons = analysed(underlying, expiration)
        m, _, now = meta(snap, {"convention": convention})
        return {"meta": m, "data": an.delta_exposure(cons, snap.spot, now, convention)}

    def session_prices(symbol, ref_time):
        """Stored observations from the same Eastern-time date as ref_time (usually the snapshot time)."""
        day = to_et(ref_time).date()
        out = []
        for r in db.price_history(symbol, 3000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t and to_et(t).date() == day:
                out.append({"t": iso(t), "price": r["price"]})
        return sorted(out, key=lambda x: x["t"])

    @app.get("/api/history/prices")
    def hist_prices(underlying: str):
        u = underlying_ok(underlying)
        snap = snapshot(u)
        pts = session_prices(u, snap.source_ts or snap.retrieved_at)
        root = FUTURES_FOR.get(u)
        fut = session_prices(root, snap.source_ts or snap.retrieved_at) if root else []
        return {"underlying": u, "points": pts, "futures_root": root, "futures_points": fut,
                "note": "Only prices this app observed are shown. It starts recording when you first run it and adds a point when new data arrives (about every 2 minutes). Futures points are the prices you typed in."}

    def actual_move(u, snap, now, d=None):
        """How far price has moved this session compared with the expected move. d may be a precomputed expected-move result."""
        d = d if d is not None else an.expected_move(snap.contracts, snap.spot, now)
        actual = {"available": False, "note": "Needs at least two stored price observations from the same session."}
        pts = session_prices(u, snap.source_ts or snap.retrieved_at)
        if d.get("available") and len(pts) >= 2:
            ref = pts[0]
            moved = snap.spot - ref["price"]
            em = (d.get("straddle") or {}).get("price") or (d.get("iv_1sd") or {}).get("move")
            actual = {"available": True, "reference_price": ref["price"], "reference_time": ref["t"], "observations": len(pts),
                      "move_points": moved, "move_pct": moved / ref["price"], "expected_move": em,
                      "fraction_of_expected": abs(moved) / em if em else None,
                      "note": "The reference is the first price this app saw in the session. If the app was started after the open, "
                              "the move since the open is larger than shown. Compare it with the expected move to avoid overreacting; it is not a signal."}
            root = FUTURES_FOR.get(u)
            fp = session_prices(root, snap.source_ts or snap.retrieved_at) if root else []
            if len(fp) >= 2:
                actual["futures"] = {"root": root, "first": fp[0]["price"], "last": fp[-1]["price"], "move_points": fp[-1]["price"] - fp[0]["price"],
                                     "note": "Based on the futures prices you typed in, not a data feed."}
        return actual

    @app.get("/api/analytics/expected-move")
    def expected(underlying: str, expiration: str | None = None, days: float | None = None):
        u = underlying_ok(underlying)
        snap = snapshot(u)
        m, _, now = meta(snap)
        d = an.expected_move(snap.contracts, snap.spot, now, expiration, days)
        actual = actual_move(u, snap, now, d)
        return {"meta": m, "data": d, "actual": actual,
                "note": f"{u} is not the futures contract. Use /api/analytics/levels for futures estimates."}

    @app.get("/api/analytics/moves")
    def moves(underlying: str, n: int = Query(5, ge=1, le=10)):
        u = underlying_ok(underlying)
        snap = snapshot(u)
        m, _, now = meta(snap)
        rows, spot = an.moves_table(snap.contracts, snap.spot, now, n), snap.spot
        root = FUTURES_FOR.get(u)
        brow = db.latest_price(f"{root}_BASIS") if root and u in SAME_SCALE else None
        offset = brow["price"] if brow else None
        for r in rows:
            for k in ("straddle", "sd1", "sd2"):
                r[k + "_levels"] = None if r[k] is None else {"up": spot + r[k], "down": spot - r[k],
                                                               "up_futures": spot + r[k] + offset if offset is not None else None,
                                                               "down_futures": spot - r[k] + offset if offset is not None else None}
            r["events"] = [ev for ev in upcoming_events(days=366) if ev["date"] <= r["expiry"]]
        explain = None
        if rows:
            r0 = rows[0]
            parts = []
            if r0["straddle"] is not None:
                parts.append(f"Straddle: the options market charges {r0['straddle']:,.1f} points for a call plus a put at the {r0['atm_strike']:,.0f} strike that expires {r0['expiry']}. "
                             f"That buyer only profits if price moves more than that in either direction, so {r0['straddle']:,.1f} is roughly what the market expects the move to be by then.")
            if r0["sd1"] is not None:
                parts.append(f"1 sigma: the at-the-money implied volatility is {r0['atm_iv'] * 100:.1f}% a year. Scaled to the {r0['days']:.1f} days left, "
                             f"{spot:,.0f} x {r0['atm_iv'] * 100:.1f}% x square root of ({r0['days']:.1f} / 365) = {r0['sd1']:,.1f} points. Under the usual bell-curve assumption, "
                             f"price finishes inside plus or minus {r0['sd1']:,.0f} about 68% of the time, and inside plus or minus {r0['sd2']:,.0f} (2 sigma) about 95% of the time.")
            parts.append("The straddle and 1 sigma are two views of the same idea and usually land close together; the straddle is typically a bit smaller. "
                         "Real markets have more large moves than a bell curve allows, so 2 sigma means 'unusual', not 'impossible'. These are estimates from option prices, not forecasts of direction.")
            explain = parts
        return {"meta": m, "rows": rows, "explain": explain, "futures_root": root, "basis": offset,
                "note": "Levels are spot plus or minus each distance. Futures levels need a saved basis on the Levels tab (index symbols only)."}

    @app.get("/api/analytics/oi")
    def oi(underlying: str, expiration: str | None = None):
        snap, cons = analysed(underlying, expiration)
        m, _, _ = meta(snap, {"oi_note": "Open interest is the end-of-previous-trading-day figure; it does not change intraday."})
        return {"meta": m, "data": an.concentration(cons, "oi")}

    @app.get("/api/analytics/volume")
    def volume(underlying: str, expiration: str | None = None):
        snap, cons = analysed(underlying, expiration)
        m, _, _ = meta(snap, {"volume_note": "Volume is the provider's latest session volume per contract. It does not say who bought or sold."})
        return {"meta": m, "data": an.concentration(cons, "volume"),
                "unusual_volume": an.unusual_volume(cons)}

    @app.get("/api/analytics/heatmap")
    def heatmap(underlying: str, field: str = "volume", side: str = "total", window: float = Query(0.04, ge=0, le=1)):
        if field not in ("volume", "oi") or side not in ("total", "call", "put", "net"):
            raise HTTPException(422, "field must be volume or oi; side must be total, call, put or net")
        u = underlying_ok(underlying)
        snap = snapshot(u)
        m, _, now = meta(snap, {"field_note": "Open interest is the previous day's figure." if field == "oi" else "Session volume per contract."})
        return {"meta": m, "data": an.strike_expiry_matrix(snap.contracts, now, field, side, snap.spot, window)}

    @app.get("/api/analytics/iv")
    def iv(underlying: str, expiration: str | None = None, otm_only: bool = True, smooth: bool = True, max_spread: float = 0.5):
        u = underlying_ok(underlying)
        snap = snapshot(u)
        m, _, now = meta(snap)
        cl = an.clean_iv(snap.contracts, snap.spot, now, otm_only, max_spread, smooth)
        want = exps(expiration)
        good = [r for r in cl["expiries"] if len(r["points"]) >= 5]
        smiles = [r for r in good if r["expiry"] in want] if want else good[:4]
        term = []
        for r in cl["expiries"]:
            p = min(r["points"], key=lambda p: abs(p["strike"] - snap.spot))
            if abs(p["strike"] / snap.spot - 1) <= 0.015:
                term.append({"expiry": r["expiry"], "dte": r["dte"], "atm_strike": p["strike"], "iv": p["iv"]})
        hist = db.metric_history(u, "atm_iv_front", 2000)
        days = {h["calculated_at"][:10] for h in hist}
        pct = None
        if len(hist) >= 30 and len(days) >= 5:
            cur = hist[-1]["value"]
            pct = sum(1 for h in hist if h["value"] <= cur) / len(hist)
        return {"meta": m, "smiles": smiles, "cleaning": {"stats": cl["stats"], "method": cl["method"]}, "term_structure": term,
                "percentile": {"available": pct is not None, "value": pct, "observations": len(hist), "days": len(days),
                               "note": "Needs 30+ observations over 5+ days of this application's own stored ATM IV."},
                "historical_volatility": {"available": False, "reason": "Needs daily underlying price history, which this version does not collect."}}

    @app.get("/api/analytics/surface")
    def surface(underlying: str, otm_only: bool = True, smooth: bool = True, max_spread: float = 0.5, min_points: int = Query(6, ge=3, le=40)):
        u = underlying_ok(underlying)
        snap = snapshot(u)
        m, _, now = meta(snap)
        cl = an.clean_iv(snap.contracts, snap.spot, now, otm_only, max_spread, smooth)
        return {"meta": m, "data": an.build_surface(cl, snap.spot, min_points), "cleaning": {"stats": cl["stats"], "method": cl["method"]}}

    def levels_payload(underlying, convention, method, categories, top=2, expiration=None, by_expiry=0, mid=0, moves=0, key=0, near=0, quota=None):
        u = underlying_ok(underlying)
        if convention not in an.SIGNS or method not in ("auto", "ratio", "basis", "typed_basis"):
            raise HTTPException(422, "invalid convention or method")
        q = None
        if quota:
            try:
                q = parse_quota(quota)
            except ValueError as e:
                raise HTTPException(422, f"Bad per-type count '{e}'. Use for example gex:8,oi:2,vol:1,move:2 (each 0 to 20).")
            key = near = 0
        gex_top = None
        if q and q["gex"]:                                   # build enough GEX candidates to fill the GEX count (about half each side)
            gex_top = max(top, min(10, -(-q["gex"] // 2) + 1))
        if q:                                                # same for open interest and volume
            top = max(top, min(10, -(-max(q["oi"], q["vol"]) // 2)))
        snap = snapshot(u)
        m, fr, now = meta(snap, {"convention": convention, "reliability_rule": RELIABILITY_RULE})
        lv = build_levels(snap, now, convention, fr, top=top, expirations=exps(expiration), per_expiry=by_expiry, mid=mid, moves=moves, gex_top=gex_top)
        for cl in db.list_custom_levels(u):
            lv.append({"instrument": snap.underlying, "source_timestamp": m["source_timestamp"], "data_status": fr.status, "provider": snap.provider,
                       "category": "custom", "label": cl["label"], "value": cl["value"], "method": "Typed in by you", "inputs": {},
                       "reliability": "user", "custom_id": cl["id"], "first_seen": cl["created_at"]})
        if categories:
            keep = set(categories.split(","))
            lv = [x for x in lv if x["category"] in keep]
        day = to_et(snap.source_ts or snap.retrieved_at).date().isoformat()
        runs = db.active_level_runs(u, day)
        for x in (y for y in lv if y["category"] != "custom"):
            hits = [r for r in runs if r["category"] == x["category"] and r["label"] == x["label"] and abs(r["value"] - x["value"]) <= 0.0005 * abs(x["value"])]
            x["first_seen"] = min(hits, key=lambda r: abs(r["value"] - x["value"]))["first_seen"] if hits else None
        mt = an.moves_table(snap.contracts, snap.spot, now, 1)
        scale = (mt[0]["sd1"] or mt[0]["straddle"]) if mt else None
        score_levels(lv, snap.spot, scale)
        zones = make_zones(lv, snap.spot, 999 if (near or q) else key) if (near or key or q) else []
        available = len(zones)
        if q:
            zones = select_by_quota(zones, q)
        if near and zones:                                      # the N zones closest to price (a band price is inside counts as distance 0)
            sp_ = snap.spot
            dist = lambda z: (0.0 if z["low"] <= sp_ <= z["high"] else min(abs(sp_ - z["low"]), abs(sp_ - z["high"]))) if z.get("low") is not None else abs(z["value"] - sp_)
            zones = sorted(sorted(zones, key=dist)[:near], key=lambda z: -z["value"])
        lv += zones
        root = FUTURES_FOR.get(u)
        mapping = {"futures_root": root, "available": False}
        if root:
            row = db.latest_price(root)
            contract = settings.futures_contracts.get(root, "")
            mapping["roll"] = roll_status(contract, now.date())
            base = PricePoint(u, snap.spot, snap.spot_ts, snap.provider)
            diag = evaluate_methods(pair_observations(db.price_history(u), db.price_history(root)))
            mapping["diagnostics"] = diag
            brow = db.latest_price(f"{root}_BASIS")
            if brow:
                mapping["typed_basis"] = {"value": brow["price"], "entered_at": brow["retrieved_at"],
                                          "age_minutes": (now - parse_ts(brow["retrieved_at"])).total_seconds() / 60}
            newer_basis = bool(brow) and (not row or brow["retrieved_at"] > row["retrieved_at"])
            if method == "typed_basis" or (method == "auto" and newer_basis):
                mapping["available"] = bool(brow)
                if brow:
                    mapper = lambda v: map_with_typed_basis(v, u, snap.spot, brow["price"], parse_ts(brow["retrieved_at"]), now)
                    for x in lv:
                        x["mapped"] = mapper(x["value"])
                        if x.get("low") is not None:                       # GEX wall zones: convert both edges of the band
                            x["mapped_low"], x["mapped_high"] = mapper(x["low"])["mapped"], mapper(x["high"])["mapped"]
                else:
                    mapping["note"] = f"Type a basis ({root} minus the index) on the Levels tab."
            elif row:
                fut = PricePoint(root, row["price"], parse_ts(row["source_ts"] or row["retrieved_at"]), row["source"], row["contract"],
                                 bool(row["manual"]))
                mapping["available"] = True
                prefer = diag.get("best") if diag.get("available") and method == "auto" else None
                mapper = lambda v: map_level(v, u, base, fut, now, method, prefer=prefer)
                for x in lv:
                    x["mapped"] = mapper(x["value"])
                    if x.get("low") is not None:
                        x["mapped_low"], x["mapped_high"] = mapper(x["low"])["mapped"], mapper(x["high"])["mapped"]
                if mapping["roll"]["status"] == "expired":
                    for x in lv:
                        x["mapped"]["warnings"].append("The selected futures contract has expired.")
                        x["mapped"]["status"] = "stale"
            else:
                mapping["note"] = f"Enter a {root} price on the dashboard to see levels in futures points."
        return {"meta": m, "levels": [x for x in lv if not x.get("zone")], "zones": [x for x in lv if x.get("zone")], "mapping": mapping,
                "selection": {"mode": "custom" if q else "nearest" if near else "key" if key else "all", "n": len(zones) if q else (near or key or None), "available": available,
                              **({"quota": q, "used": {f: sum(1 for z in zones if z.get("slot") == f) for f in q}, "quota_rule": QUOTA_RULE} if q else {})},
                "importance_rule": IMPORTANCE_RULE, "note": "Mapped values are estimates from a ratio or basis between two prices, not exact equivalents."}

    @app.get("/api/analytics/levels")
    def levels(underlying: str, convention: str = "standard", method: str = "auto", categories: str | None = None,
               top: int = Query(2, ge=1, le=10), expiration: str | None = None, by_expiry: int = Query(0, ge=0, le=8),
               mid: int = Query(0, ge=0, le=3), moves: int = Query(0, ge=0, le=8), key: int = Query(0, ge=0, le=25), near: int = Query(0, ge=0, le=60), quota: str | None = None):
        return levels_payload(underlying, convention, method, categories, top, expiration, by_expiry, mid, moves, key, near, quota)

    @app.post("/api/custom-levels")
    def add_custom(c: CustomLevel):
        u = underlying_ok(c.underlying)
        label = " ".join(c.label.replace(",", " ").replace('"', "").split())[:40]
        if not label or c.value <= 0:
            raise HTTPException(422, "Give the level a name and a positive price.")
        value = c.value
        if c.units == "futures":
            root = FUTURES_FOR.get(u)
            brow = db.latest_price(f"{root}_BASIS") if root else None
            if not brow or u not in SAME_SCALE:
                raise HTTPException(422, f"To enter a {root or 'futures'} price, this symbol must be an index (like _NDX) and you must save a basis first.")
            value = c.value - brow["price"]
        elif c.units != "underlying":
            raise HTTPException(422, "units must be underlying or futures")
        cid = db.add_custom_level(u, label, value, now_fn())
        return {"saved": True, "id": cid, "label": label, "value_in_underlying_units": value}

    @app.delete("/api/custom-levels/{level_id}")
    def delete_custom(level_id: int, underlying: str):
        if not db.delete_custom_level(underlying_ok(underlying), level_id):
            raise HTTPException(404, "No such level")
        return {"deleted": True}

    @app.get("/api/export/pine")
    def export_pine(underlying: str, convention: str = "standard", method: str = "auto", categories: str | None = None,
                    top: int = Query(2, ge=1, le=10), expiration: str | None = None, by_expiry: int = Query(0, ge=0, le=8),
                    mid: int = Query(0, ge=0, le=3), moves: int = Query(0, ge=0, le=8), key: int = Query(0, ge=0, le=25), near: int = Query(0, ge=0, le=60), quota: str | None = None):
        j = levels_payload(underlying, convention, method, categories, top, expiration, by_expiry, mid, moves, key, near, quota)
        m, root = j["meta"], j["mapping"].get("futures_root")
        rows, mapped_used = [], False
        for x in (j["zones"] if j["selection"]["mode"] != "all" else j["levels"]):
            mp = x.get("mapped")
            if mp and mp.get("mapped") is not None and mp.get("status") != "invalid":
                rows.append({"label": x["label"], "category": x["category"], "price": mp["mapped"], "start": parse_ts(x.get("first_seen")),
                             "low": x.get("mapped_low"), "high": x.get("mapped_high")})
                mapped_used = True
            else:
                rows.append({"label": x["label"], "category": x["category"], "price": x["value"], "start": parse_ts(x.get("first_seen")),
                             "low": x.get("low"), "high": x.get("high")})
        if mapped_used:
            first = next(x for x in (j["zones"] if j["selection"]["mode"] != "all" else j["levels"]) if x.get("mapped"))
            units = f"Levels are ESTIMATED {root} points (converted from {m['underlying']} with a {first['mapped']['method']} method)."
        else:
            units = f"Levels are in {m['underlying']} units (no {root or 'futures'} price or basis typed in yet). Use the offset input in TradingView to add your basis."
        src = f"Source: {m['provider']} {m['underlying']}, snapshot {m['calculated_at_et']}, data status: {m['data_status']}."
        t0 = parse_ts(m["source_timestamp"])
        return {"code": build_pine(rows, src, units, to_et(t0) if t0 else None), "levels": len(rows), "mapped": mapped_used, "meta": m,
                "note": "Paste into TradingView's Pine Editor and add to chart. Re-export and re-paste each session. I could not compile Pine from here; if TradingView reports an error, send it to me."}

    @app.get("/api/analytics/scenarios")
    def scenario_view(underlying: str):
        snap = snapshot(underlying_ok(underlying))
        m, _, now = meta(snap)
        return {"meta": m, "data": an.scenarios(snap.contracts, snap.spot, now)}

    def bias_for(u, convention, events):
        snap = snapshot(u)
        m, fr, now = meta(snap, {"convention": convention})
        ref = snap.source_ts or snap.retrieved_at
        prev = None
        for h in reversed(db.metric_history(u, "skew_25d", 3000)):
            t = parse_ts(h["calculated_at"])
            if t and to_et(t).date() < to_et(ref).date():
                prev = h["value"]
                break
        return snap, m, fr, now, compute_bias(snap, now, fr, convention, prev, actual_move(u, snap, now), events)

    @app.get("/api/analytics/bias")
    def bias(underlying: str, convention: str = "standard"):
        if convention not in an.SIGNS:
            raise HTTPException(422, f"convention must be one of {CONVENTIONS}")
        _snap, m, _fr, _now, data = bias_for(underlying_ok(underlying), convention, upcoming_events(2))
        return {"meta": m, "data": data}

    def regime_for(u, snap, fr, now, convention, zones=None):
        if zones is None:
            zones = [x for x in build_levels(snap, now, convention, fr, top=1) if x.get("low") is not None]
        hist = {k: db.metric_history(u, k, 6000) for k in ("iv_mid", "skew_25d")}
        return compute_regime(snap, now, fr, convention, hist, actual_move(u, snap, now), upcoming_events(1), INDEX_GROUP.get(u), zones)

    @app.get("/api/analytics/regime")
    def regime(underlying: str, convention: str = "standard"):
        """Is today pinned and mean-reverting, or can it trend and expand? A visible scorecard (see services/regime.py for the rules)."""
        if convention not in an.SIGNS:
            raise HTTPException(422, f"convention must be one of {CONVENTIONS}")
        u = underlying_ok(underlying)
        snap = snapshot(u)
        m, fr, now = meta(snap, {"convention": convention})
        root = FUTURES_FOR.get(u)
        brow = db.latest_price(f"{root}_BASIS") if root and u in SAME_SCALE else None
        return {"meta": m, "data": regime_for(u, snap, fr, now, convention), "futures_root": root, "futures_offset": brow["price"] if brow else None}

    @app.get("/api/analytics/bias-overview")
    def bias_overview(convention: str = "standard"):
        """The daily bias for EVERY configured symbol side by side (for example NQ via _NDX, QQQ, ES via _SPX, SPY), plus whether related symbols agree."""
        if convention not in an.SIGNS:
            raise HTTPException(422, f"convention must be one of {CONVENTIONS}")
        events, rows = upcoming_events(2), []
        word = {1: "bullish", -1: "bearish", 0: "mixed"}
        for u in settings.underlyings:
            base = {"underlying": u, "futures_root": FUTURES_FOR.get(u), "group": INDEX_GROUP.get(u)}
            try:
                snap, m, fr, now, d = bias_for(u, convention, events)
            except HTTPException as e:
                det = e.detail if isinstance(e.detail, dict) else {"reason": str(e.detail)}
                rows.append({**base, "available": False, "reason": det.get("reason", "No data yet.")})
                continue
            lv = build_levels(snap, now, convention, fr, top=1)
            rg = regime_for(u, snap, fr, now, convention, [x for x in lv if x.get("low") is not None])
            zone = lambda cat: next(({"low": x["low"], "high": x["high"], "center": x["value"]} for x in lv if x["category"] == cat), None)
            root = base["futures_root"]
            brow = db.latest_price(f"{root}_BASIS") if root and u in SAME_SCALE else None
            lean = 1 if d["verdict"].startswith("Leans bull") else -1 if d["verdict"].startswith("Leans bear") else 0
            rows.append({**base, "available": True, "usable": m["data_status"] not in ("stale", "no_source_time", "unavailable"), "data_status": m["data_status"],
                         "source_timestamp": m["source_timestamp"], "spot": snap.spot, "verdict": d["verdict"], "lean": lean, "score": d["score"],
                         "confidence": d["confidence"]["label"], "day_type": d["day_type"]["label"], "above_flip": d["day_type"].get("above_flip"),
                         "flip": d["levels"]["flip"], "call_wall": d["levels"]["call_wall"], "put_wall": d["levels"]["put_wall"],
                         "expected_move": d["levels"]["expected_move"], "futures_offset": brow["price"] if brow else None,
                         "regime": {"label": rg["label"], "confidence": rg["confidence"], "total": rg["total"]},
                         "zones": {"call": zone("gex_call_zone"), "put": zone("gex_put_zone"), "positive": zone("gex_pos_zone"), "negative": zone("gex_neg_zone"),
                                   "oi_call": zone("oi_call_zone"), "oi_put": zone("oi_put_zone"), "volume_call": zone("volume_call_zone"), "volume_put": zone("volume_put_zone")}})
        ok = [r for r in rows if r.get("available") and r["usable"]]
        groups, by_group = [], {}
        for r in ok:
            if r["group"]:
                by_group.setdefault(r["group"], []).append(r)
        for name, rs in by_group.items():
            leans = {r["lean"] for r in rs}
            names = " and ".join(r["underlying"] for r in rs)
            if len(rs) == 1:
                groups.append({"group": name, "symbols": [rs[0]["underlying"]], "state": "single", "lean": rs[0]["lean"], "text": f"{name}: {names} reads {word[rs[0]['lean']]}."})
            elif len(leans) == 1:
                groups.append({"group": name, "symbols": [r["underlying"] for r in rs], "state": "aligned", "lean": rs[0]["lean"], "text": f"{name}: {names} agree, both {word[rs[0]['lean']]}."})
            else:
                groups.append({"group": name, "symbols": [r["underlying"] for r in rs], "state": "disagree", "lean": None,
                               "text": f"{name}: the symbols disagree ({', '.join(f'{r['underlying']} {word[r['lean']]}' for r in rs)})."})
        firm = {g["group"]: g["lean"] for g in groups if g["lean"] is not None}
        if len(firm) >= 2:
            vals = set(firm.values())
            cross = (f"All groups read {word[vals.pop()]}." if len(vals) == 1 else
                     "The groups point different ways: " + "; ".join(f"{k} {word[v]}" for k, v in firm.items()) + ".")
        else:
            cross = None
        tally = {"bullish": sum(r["lean"] == 1 for r in ok), "bearish": sum(r["lean"] == -1 for r in ok), "mixed": sum(r["lean"] == 0 for r in ok)}
        summary = (f"{len(ok)} symbol{'s' if len(ok) != 1 else ''} with usable data: {tally['bullish']} lean bullish, {tally['bearish']} lean bearish, {tally['mixed']} mixed." if ok
                   else "No symbol has usable data yet.")
        return {"rows": rows, "groups": groups, "cross": cross, "tally": tally, "summary": summary, "events": events,
                "note": "Each symbol is scored on its own options data with the same rules as the Daily bias tab. Related symbols (for example NDX and QQQ, or SPX and SPY) are highly "
                        "correlated, so agreement is a consistency check, not independent confirmation. Symbols with stale data are left out of the agreement checks. "
                        "Add more symbols with CBOE_UNDERLYINGS in .env."}

    # -- history: levels through the day, and the reaction log --------------------------------
    @app.get("/api/history/levels")
    def hist_levels(underlying: str, date: str | None = None):
        u = underlying_ok(underlying)
        snap = snapshot(u)
        ref = snap.source_ts or snap.retrieved_at
        day = date or to_et(ref).date().isoformat()
        out = {}
        for name in ("gamma_flip", "call_wall", "put_wall", "em_low", "em_high"):
            pts = [{"t": h["calculated_at"], "value": h["value"]} for h in db.metric_history(u, name, 3000)
                   if (t := parse_ts(h["calculated_at"])) and to_et(t).date().isoformat() == day]
            out[name] = pts
        prices = []
        for r in db.price_history(u, 3000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t and to_et(t).date().isoformat() == day:
                prices.append({"t": iso(t), "price": r["price"]})
        return {"date": day, "price": sorted(prices, key=lambda x: x["t"]), "levels": out,
                "note": "Levels are recalculated whenever new data arrives, so they can drift during the session."}

    @app.get("/api/analytics/reactions")
    def reactions(underlying: str, days: int = Query(20, ge=1, le=90), tolerance_pct: float = Query(0.05, gt=0, le=1)):
        u = underlying_ok(underlying)
        dates = db.list_session_dates(u, days)
        by_day = {}
        for r in db.price_history(u, 20000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t:
                by_day.setdefault(to_et(t).date().isoformat(), []).append((t, r["price"]))
        all_t, sessions = [], []
        for d in sorted(dates):
            lv = db.load_session_levels(u, d)
            px = sorted(by_day.get(d, []))
            tc = rx.analyze(lv, px, tol=tolerance_pct / 100) if lv and len(px) >= 3 else []
            for t in tc:
                t["time"] = iso(t["time"])
            sessions.append({"date": d, "levels": len(lv), "price_observations": len(px), "touches": tc})
            all_t += tc
        return {"underlying": u, "sessions": sessions, "summary": rx.summarize(all_t), "tolerance_pct": tolerance_pct,
                "total_touches": len(all_t),
                "method": "The first set of levels of each session is kept. A touch is price within the tolerance of a level, or crossing it between two stored "
                          "observations. 'Held' means price was still on the side it approached from 15 or 30 minutes later.",
                "note": "Descriptive only. Samples are small, prices are about 15 minutes delayed, and observations arrive about every 2 minutes, so a touch can be missed or timed loosely. "
                        "It is not evidence of an edge until it has hundreds of touches."}

    # -- (history endpoints continue below) ---------------------------------------------------
    # -- history ---------------------------------------------------------------------------
    @app.get("/api/history/snapshots")
    def hist_snaps(underlying: str, limit: int = Query(100, le=500)):
        return {"snapshots": db.list_snapshots(underlying_ok(underlying), limit)}

    @app.get("/api/history/metric")
    def hist_metric(underlying: str, name: str, limit: int = Query(500, le=5000)):
        return {"name": name, "points": db.metric_history(underlying_ok(underlying), name, limit)}

    @app.get("/api/history/oi-change")
    def oi_change(underlying: str):
        u = underlying_ok(underlying)
        snaps = db.list_snapshots(u, 500)
        if not snaps:
            return {"available": False, "reason": "No stored snapshots."}
        latest = snaps[0]
        d0 = to_et(parse_ts(latest["retrieved_at"])).date()
        older = next((s for s in snaps if to_et(parse_ts(s["retrieved_at"])).date() < d0), None)
        if not older:
            return {"available": False, "reason": "Open interest is a daily figure. Snapshots from two different sessions are needed."}
        a, b = db.load_snapshot(u, older["id"]), db.load_snapshot(u, latest["id"])
        prev = {c.ticker: c.oi or 0 for c in a.contracts}
        by = {}
        for c in b.contracts:
            if c.ticker in prev:
                r = by.setdefault(c.strike, {"call": 0.0, "put": 0.0})
                r["call" if c.right == "C" else "put"] += (c.oi or 0) - prev[c.ticker]
        return {"available": True, "from": older["retrieved_at"], "to": latest["retrieved_at"],
                "change_by_strike": [{"strike": k, **v} for k, v in sorted(by.items())]}

    from types import SimpleNamespace
    from .api_more import register as register_more
    register_more(app, SimpleNamespace(db=db, settings=settings, snapshot=snapshot, meta=meta, underlying_ok=underlying_ok, levels_payload=levels_payload,
                                       bias_for=bias_for, regime_for=regime_for, upcoming_events=upcoming_events, now_fn=now_fn, primary_db=primary_db,
                                       oi_change=oi_change, reactions=reactions))

    @app.middleware("http")
    async def never_serve_stale_pages(request, call_next):
        """The page files (not the data) are re-checked on every load, so an updated app.js is used straight after you replace the folder."""
        resp = await call_next(request)
        if not request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    frontend = ROOT / "frontend"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")
    if primary_settings.access_password:                      # added last so it sits in front of everything
        install_auth(app, Auth(primary_settings.access_password, primary_settings.db_path.parent / ".session_secret", primary_settings.access_local_bypass))
    return app
