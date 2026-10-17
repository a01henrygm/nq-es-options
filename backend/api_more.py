"""Endpoints for 0DTE, the session / before-the-open / scorecard charts, the written daily case, the trade journal and phone access.

register() is called from create_app with that function's helpers, so these endpoints follow the same data-source choice (?source=)."""
from __future__ import annotations
import os
import re
import socket
from datetime import datetime, time as dtime, timedelta

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel

from .config import DATA
from .services import analytics as an
from .services import intraday as idy
from .services.importance import short_tag
from .services.narrative import build_case
from .timeutil import ET, UTC, iso, parse_ts, to_et

INSTRUMENT_TO = {"NQ": "_NDX", "MNQ": "_NDX", "ES": "_SPX", "MES": "_SPX"}


class TradeIn(BaseModel):
    instrument: str = "NQ"
    side: str                      # long or short
    qty: float = 1
    entry: float
    stop: float | None = None
    target: float | None = None
    exit: float | None = None
    opened_at: str | None = None   # ISO; default now
    closed_at: str | None = None
    setup: str = ""
    note: str = ""


class TradeEdit(BaseModel):
    exit: float | None = None
    closed_at: str | None = None
    stop: float | None = None
    target: float | None = None
    setup: str | None = None
    note: str | None = None


class PhoneIn(BaseModel):
    enabled: bool
    password: str = ""


def _day_bounds(day):
    start = datetime.combine(day, dtime(0, 0), ET)
    return iso(start), iso(start + timedelta(days=1))


def _in_day(rows, day, key="t"):
    a, b = _day_bounds(day)
    return [r for r in rows if a <= r[key] < b]


def points(side, entry, exit_):
    return None if exit_ is None else (exit_ - entry) * (1 if side == "long" else -1)


def journal_stats(trades):
    """Closed trades grouped several ways: count, win rate, average and total points."""
    closed = [t for t in trades if t.get("exit") is not None]
    groups = {"Nearest level": lambda t: (t.get("context") or {}).get("level_kind") or "No level near",
              "Regime": lambda t: (t.get("context") or {}).get("regime") or "Unknown",
              "With or against the bias": lambda t: (t.get("context") or {}).get("with_bias") or "Unknown",
              "Gamma side": lambda t: (t.get("context") or {}).get("gamma_side") or "Unknown",
              "Time of day": lambda t: (t.get("context") or {}).get("time_bucket") or "Unknown",
              "Setup": lambda t: t.get("setup") or "(none)"}
    out = {}
    for name, fn in groups.items():
        rows = {}
        for t in closed:
            p = points(t["side"], t["entry"], t["exit"]) * (t.get("qty") or 1)
            r = rows.setdefault(fn(t), {"key": fn(t), "trades": 0, "wins": 0, "points": 0.0})
            r["trades"] += 1
            r["wins"] += p > 0
            r["points"] += p
        out[name] = sorted(({**r, "win_rate": r["wins"] / r["trades"], "avg_points": r["points"] / r["trades"]} for r in rows.values()), key=lambda r: -r["trades"])
    tot = [points(t["side"], t["entry"], t["exit"]) * (t.get("qty") or 1) for t in closed]
    return {"closed": len(closed), "open": len(trades) - len(closed), "total_points": sum(tot), "win_rate": (sum(p > 0 for p in tot) / len(tot)) if tot else None,
            "avg_points": (sum(tot) / len(tot)) if tot else None, "groups": out}


def time_bucket(t_et):
    m = t_et.hour * 60 + t_et.minute
    for lo, hi, name in ((0, 570, "Before 9:30"), (570, 630, "9:30-10:30"), (630, 720, "10:30-12:00"), (720, 840, "12:00-14:00"), (840, 960, "14:00-16:00")):
        if lo <= m < hi:
            return name
    return "After 16:00"


def env_set(path, values: dict):
    """Updates KEY=value lines in a .env file, adding the ones that are missing. Other lines are kept as they are."""
    lines = path.read_text().splitlines() if path.exists() else []
    done = set()
    for i, ln in enumerate(lines):
        m = re.match(r"\s*([A-Z_]+)\s*=", ln)
        if m and m.group(1) in values:
            lines[i] = f"{m.group(1)}={values[m.group(1)]}"
            done.add(m.group(1))
    lines += [f"{k}={v}" for k, v in values.items() if k not in done]
    path.write_text("\n".join(lines) + "\n")


def local_ips():
    ips = set()
    try:
        for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(a[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("10.255.255.255", 1))
            ips.add(sk.getsockname()[0])
    except OSError:
        pass
    lan = sorted(ip for ip in ips if re.match(r"^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)", ip))
    ts = sorted(ip for ip in ips if re.match(r"^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.", ip))     # Tailscale uses 100.64.0.0/10
    return lan, ts


def qr_svg(text):
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return None
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    import io
    b = io.BytesIO()
    img.save(b)
    return b.getvalue().decode()


def register(app, h):
    """h: namespace with db, settings, snapshot, meta, underlying_ok, levels_payload, bias_for, regime_for, upcoming_events,
    now_fn, primary_db, oi_change, reactions."""
    db = h.db

    def latest_day(u):
        px = db.price_history(u, 1)
        t = parse_ts(px[-1]["source_ts"] or px[-1]["retrieved_at"]) if px else None
        return to_et(t or h.now_fn()).date()

    def day_prices(u, day):
        out = []
        for r in db.price_history(u, 6000):
            t = parse_ts(r["source_ts"] or r["retrieved_at"])
            if t and to_et(t).date() == day:
                out.append({"t": iso(t), "price": r["price"]})
        return sorted(out, key=lambda x: x["t"])

    def series(u, name, day):
        a, _ = _day_bounds(day)
        return _in_day(db.metric_series(u, name, since=a), day)

    def oi_change_any(u):
        """Overnight open-interest change from the once-a-day profiles; falls back to two stored full snapshots."""
        prof = db.metric_series(u, "oi_profile", limit=60)
        if len(prof) >= 2 and to_et(parse_ts(prof[-1]["t"])).date() != to_et(parse_ts(prof[-2]["t"])).date():
            return {"available": True, "from": prof[-2]["t"], "to": prof[-1]["t"], "change_by_strike": idy.oi_change_from_profiles(prof[-2]["detail"] or [], prof[-1]["detail"] or [])}
        try:
            return h.oi_change(u)
        except HTTPException:
            return {"available": False, "reason": "No stored data yet."}

    def oi_shift(u, spot):
        ch = oi_change_any(u)
        if not ch.get("available"):
            return None
        rows = ch["change_by_strike"]
        return {"calls_added_above": sum(max(0, r["call"]) for r in rows if r["strike"] > spot), "puts_added_below": sum(max(0, r["put"]) for r in rows if r["strike"] < spot),
                "calls_added_below": sum(max(0, r["call"]) for r in rows if r["strike"] < spot), "puts_added_above": sum(max(0, r["put"]) for r in rows if r["strike"] > spot)}

    # ---- 0DTE ---------------------------------------------------------------------------------------------------------
    @app.get("/api/analytics/zerodte")
    def zerodte(underlying: str, convention: str = "standard"):
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        snap = h.snapshot(u)
        m, _fr, now = h.meta(snap, {"convention": convention})
        z = idy.zero_dte(snap.contracts, snap.spot, now, convention)
        day = to_et(snap.source_ts or now).date()
        hist = {k: [{"t": r["t"], "value": r["value"]} for r in series(u, k, day)] for k in ("gex0_call_wall", "gex0_put_wall", "gex0_flip", "gamma0_at_spot")}
        return {"meta": m, "data": z, "today": hist, "price": day_prices(u, day)}

    # ---- session charts -----------------------------------------------------------------------------------------------
    @app.get("/api/charts/session")
    def session_charts(underlying: str, day: str | None = None, scope: str = "all"):
        u = h.underlying_ok(underlying)
        d = datetime.fromisoformat(day).date() if day else latest_day(u)
        prof = series(u, "gex0_profile" if scope == "0dte" else "gex_profile", d)
        gmap = idy.gex_time_matrix([(r["t"], r["detail"] or []) for r in prof])
        px = day_prices(u, d)
        op = datetime.combine(d, dtime(9, 30), ET)
        cl = datetime.combine(d, dtime(16, 0), ET)
        rth = [p for p in px if p["t"] >= iso(op)]
        if rth and rth[0]["t"] > iso(op + timedelta(minutes=30)):
            rth = []                                         # no price near the open (app started late that day): no honest cone
        dm = series(u, "day_move", d)
        dm_open = next((r for r in dm if r["t"] >= iso(op)), dm[0] if dm else None)
        cone_pts = []
        if rth and dm_open:
            cone_pts = [{**c, "t": iso(c["t"])} for c in idy.cone(rth[0]["price"], dm_open["value"], op, cl)]
        flow = series(u, "flow_net", d)
        gam = series(u, "gamma_at_spot", d)
        gam0 = series(u, "gamma0_at_spot", d)
        days = sorted({to_et(parse_ts(r["source_ts"] or r["retrieved_at"])).date().isoformat() for r in db.price_history(u, 6000)
                       if parse_ts(r["source_ts"] or r["retrieved_at"])}, reverse=True)[:30]
        return {"underlying": u, "day": d.isoformat(), "days": days, "scope": scope, "price": px,
                "gex_map": gmap, "flip": [{"t": r["t"], "value": r["value"]} for r in series(u, "gamma_flip", d)],
                "call_wall": [{"t": r["t"], "value": r["value"]} for r in series(u, "call_wall", d)],
                "put_wall": [{"t": r["t"], "value": r["value"]} for r in series(u, "put_wall", d)],
                "cone": cone_pts, "open": rth[0] if rth else None, "day_move": dm_open and {"points": dm_open["value"], "method": (dm_open["detail"] or {}).get("method")},
                "gamma_at_spot": [{"t": r["t"], "value": r["value"]} for r in gam], "gamma0_at_spot": [{"t": r["t"], "value": r["value"]} for r in gam0],
                "flow": [{"t": r["t"], "net": r["value"], **(r["detail"] or {})} for r in flow],
                "notes": {"gex_map": "Net GEX per strike from every stored snapshot of the day (about every 2 minutes while data changes).",
                          "cone": "From the 9:30 price, +/-1 and 2 times the day's expected move, widening with the square root of time. "
                                  "Expected move: " + ((dm_open["detail"] or {}).get("method", "") if dm_open else "not stored yet") + ".",
                          "gamma": "Total modeled dealer gamma at the current price. Above zero dealers dampen moves; below zero they amplify them.",
                          "flow": "Cumulative session volume: calls minus puts. Volume does not show who bought or sold."}}

    # ---- before the open ----------------------------------------------------------------------------------------------
    @app.get("/api/charts/preopen")
    def preopen(underlying: str, convention: str = "standard"):
        u = h.underlying_ok(underlying)
        snap = h.snapshot(u)
        m, _fr, now = h.meta(snap, {"convention": convention})
        f = an.gamma_flip(snap.contracts, snap.spot, now, convention)
        z = idy.zero_dte(snap.contracts, snap.spot, now, convention)
        today = to_et(snap.source_ts or now).date()
        prof = db.metric_series(u, "gex_profile", limit=3000)
        cur = prof[-1] if prof else None
        prev = next((r for r in reversed(prof) if to_et(parse_ts(r["t"])).date() < today), None)
        gex_change = None
        if cur and prev:
            a = {row[0]: row[1] for row in prev["detail"] or []}
            b = {row[0]: row[1] for row in cur["detail"] or []}
            gex_change = {"from": prev["t"], "to": cur["t"], "rows": [{"strike": k, "prev": a.get(k, 0), "now": b.get(k, 0), "change": b.get(k, 0) - a.get(k, 0)} for k in sorted(set(a) | set(b))]}
        oi = oi_change_any(u)
        vol = {}
        for k in ("atm_iv_front", "iv_mid", "skew_25d"):
            by = {}
            for r in db.metric_history(u, k, 8000):
                t = parse_ts(r["calculated_at"])
                if t is not None and r["value"] is not None:
                    by[to_et(t).date()] = r["value"]                 # the last value stored each session
            vol[k] = [{"day": d.isoformat(), "value": v} for d, v in sorted(by.items())][-40:]
        return {"meta": m, "gamma_curve": {"all": f["grid"], "flip": f["flip"] if f["found"] else None, "zero": z.get("flip_grid") if z.get("available") else [],
                                           "zero_flip": z.get("flip"), "spot": snap.spot, "zero_expiry": z.get("expiry")},
                "gex_change": gex_change, "oi_change": oi, "term_structure": an.iv_term_structure(snap.contracts, snap.spot), "vol_days": vol,
                "notes": {"gamma_curve": "Total dealer gamma if price moved to each level, everything else unchanged. Zero crossing = flip.",
                          "gex_change": "Net GEX per strike now minus the last stored profile of the previous session.",
                          "vol_days": "The last stored value of each session. Rising front IV and steeper skew often come before rougher days."}}

    # ---- scorecard ----------------------------------------------------------------------------------------------------
    @app.get("/api/charts/scorecard")
    def scorecard(underlying: str, days: int = Query(30, ge=1, le=90)):
        u = h.underlying_ok(underlying)
        rx = h.reactions(u, days, 0.05)
        agg = {}
        for s in rx["sessions"]:
            for t in s["touches"]:
                side = 1 if t["approach"] == "from above" else -1
                a = agg.setdefault(t["category"], {"n30": 0, "pts30": 0.0, "nmax": 0, "bounce": 0.0})
                if t.get("move_30") is not None:
                    a["n30"] += 1
                    a["pts30"] += t["move_30"] * side
                mx = t.get("max_above") if side > 0 else t.get("max_below")
                if mx is not None:
                    a["nmax"] += 1
                    a["bounce"] += mx
        rows = []
        for r in rx["summary"]:
            a = agg.get(r["category"], {})
            rows.append({**r, "kind": short_tag({"category": r["category"], "label": r["category"]}),
                         "avg_points_30": a["pts30"] / a["n30"] if a.get("n30") else None, "avg_best_bounce": a["bounce"] / a["nmax"] if a.get("nmax") else None})
        reg = db.metric_series(u, "regime_open", limit=400)
        out_days = []
        for r in reg[-days:]:
            d = to_et(parse_ts(r["t"])).date()
            px = [p["price"] for p in day_prices(u, d) if p["t"] >= iso(datetime.combine(d, dtime(9, 30), ET)) and p["t"] <= iso(datetime.combine(d, dtime(16, 0), ET))]
            det = r["detail"] or {}
            out_days.append({"date": d.isoformat(), "label": det.get("label"), "score": r["value"], "open_move": det.get("day_move"),
                             "high": max(px) if px else None, "low": min(px) if px else None})
        return {"underlying": u, "levels": rows, "total_touches": rx["total_touches"], "regime_days": idy.regime_range_rows(out_days),
                "method": rx["method"] + " Avg points after 30 min: positive = price moved away from the level on the side it came from (the level held).",
                "note": rx["note"]}

    # ---- the written case ---------------------------------------------------------------------------------------------
    @app.get("/api/analytics/bias-case")
    def bias_case(underlying: str, convention: str = "standard"):
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        snap, m, fr, now, bias = h.bias_for(u, convention, h.upcoming_events(2))
        z = idy.zero_dte(snap.contracts, snap.spot, now, convention)
        try:
            reg = h.regime_for(u, snap, fr, now, convention)
        except Exception:
            reg = None
        day = to_et(snap.source_ts or now).date()
        fl = series(u, "flow_net", day)
        flow = None
        if fl:
            last = fl[-1]
            ago = next((r for r in reversed(fl) if r["t"] <= iso(parse_ts(last["t"]) - timedelta(minutes=60))), None)
            flow = {**(last["detail"] or {}), "net_change_60m": (last["value"] - ago["value"]) if ago else None}
        else:
            fl0 = idy.option_flow(snap.contracts)
            flow = {**fl0, "net_change_60m": None}
        px = day_prices(u, day)
        op = iso(datetime.combine(day, dtime(9, 30), ET))
        rth = [p for p in px if p["t"] >= op]
        dm = idy.day_move(snap.contracts, snap.spot, now)
        sess = {"open": rth[0]["price"], "move_points": snap.spot - rth[0]["price"], "day_move": dm["points"] if dm else None} if rth else None
        return {"meta": m, "case": build_case(bias, z, reg, flow, oi_shift(u, snap.spot), sess), "verdict": bias["verdict"]}

    # ---- trade journal ------------------------------------------------------------------------------------------------
    def trade_context(inst, side, entry, when):
        u = INSTRUMENT_TO.get(inst.upper())
        if not u or u not in h.settings.underlyings:
            u = h.settings.underlyings[0]
        ctx = {"underlying": u, "logged_at": iso(h.now_fn()), "time_bucket": time_bucket(to_et(when))}
        try:
            lv = h.levels_payload(u, "standard", "auto", None, key=12)
        except HTTPException as e:
            ctx["note"] = "No options data when the trade was logged, so no level context."
            return u, ctx
        same_units = any(z.get("mapped") and z["mapped"].get("mapped") is not None for z in lv["zones"])
        best = None
        for z in lv["zones"]:
            mp = z.get("mapped") or {}
            v = mp.get("mapped") if same_units and mp.get("mapped") is not None else z["value"]
            lo = z.get("mapped_low") if same_units else z.get("low")
            hi = z.get("mapped_high") if same_units else z.get("high")
            dist = 0.0 if lo is not None and hi is not None and lo <= entry <= hi else abs(entry - v)
            if best is None or dist < best[0]:
                best = (dist, z, v)
        if best:
            dist, z, v = best
            near = dist <= max(0.0015 * entry, 5)
            ctx.update(nearest_level=z["label"], nearest_value=round(v, 2), distance=round(dist, 2), level_kind=(z["label"].split(" / ")[0] if near else "No level near"),
                       units="futures points (mapped)" if same_units else f"{u} units (no basis saved)")
        try:
            snap, m, fr, now, bias = h.bias_for(u, "standard", h.upcoming_events(1))
            ctx["bias"] = bias["verdict"]
            want = 1 if bias["verdict"].startswith("Leans bull") else -1 if bias["verdict"].startswith("Leans bear") else 0
            ctx["with_bias"] = "No clear bias" if want == 0 else ("With the bias" if (want > 0) == (side == "long") else "Against the bias")
            flip = bias["levels"]["flip"]
            ctx["gamma_side"] = "Unknown" if flip is None else ("Above the flip" if snap.spot > flip else "Below the flip")
            reg = h.regime_for(u, snap, fr, now, "standard")
            ctx["regime"] = reg.get("label")
        except Exception:
            pass
        return u, ctx

    @app.get("/api/journal")
    def journal():
        tr = h.primary_db.list_trades()
        for t in tr:
            t["points"] = points(t["side"], t["entry"], t["exit"])
        return {"trades": tr, "stats": journal_stats(tr)}

    @app.post("/api/journal")
    def add_trade(t: TradeIn):
        side = t.side.lower()
        if side not in ("long", "short") or t.entry <= 0:
            raise HTTPException(422, "Side must be long or short, and the entry a positive price.")
        when = parse_ts(t.opened_at) if t.opened_at else h.now_fn()
        if when is None:
            raise HTTPException(422, "Could not read the time. Use YYYY-MM-DDTHH:MM.")
        u, ctx = trade_context(t.instrument, side, t.entry, when)
        tid = h.primary_db.add_trade({"underlying": u, "instrument": t.instrument.upper()[:6], "side": side, "qty": t.qty, "entry": t.entry, "stop": t.stop,
                                      "target": t.target, "exit": t.exit, "opened_at": iso(when), "closed_at": t.closed_at or (iso(h.now_fn()) if t.exit is not None else None),
                                      "setup": t.setup.strip()[:60], "note": t.note.strip()[:500], "context": ctx})
        return {"saved": True, "id": tid, "context": ctx}

    @app.patch("/api/journal/{trade_id}")
    def edit_trade(trade_id: int, t: TradeEdit):
        ch = {k: v for k, v in (t.model_dump() if hasattr(t, 'model_dump') else t.dict()).items() if v is not None}
        if "exit" in ch and "closed_at" not in ch:
            ch["closed_at"] = iso(h.now_fn())
        if not h.primary_db.update_trade(trade_id, ch):
            raise HTTPException(404, "No such trade")
        return {"saved": True}

    @app.delete("/api/journal/{trade_id}")
    def delete_trade(trade_id: int):
        if not h.primary_db.delete_trade(trade_id):
            raise HTTPException(404, "No such trade")
        return {"deleted": True}

    # ---- phone access -------------------------------------------------------------------------------------------------
    @app.get("/api/phone")
    def phone():
        s = h.settings
        lan, ts = local_ips()
        on = s.host not in ("127.0.0.1", "localhost", "::1")
        port = int(os.environ.get("NQES_PORT") or s.port)
        urls = [f"http://{ip}:{port}" for ip in lan]
        ts_urls = [f"http://{ip}:{port}" for ip in ts]
        return {"enabled": on, "password_set": bool(s.access_password), "host": s.host, "port": port, "lan_urls": urls, "tailscale_urls": ts_urls,
                "qr": qr_svg((ts_urls or urls or [""])[0]) if on and (urls or ts_urls) else None, "env_file": str(DATA / ".env")}

    @app.post("/api/phone")
    def set_phone(p: PhoneIn, request: Request):
        if (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(403, "Phone access can only be changed on the PC itself.")
        if p.enabled:
            pw = p.password.strip()
            if len(pw) < 8 and not h.settings.access_password:
                raise HTTPException(422, "Choose a password of at least 8 characters.")
            vals = {"HOST": "0.0.0.0"}
            if pw:
                if len(pw) < 8 or any(c in pw for c in " #\"'"):
                    raise HTTPException(422, "Use at least 8 characters, without spaces, quotes or #.")
                vals["ACCESS_PASSWORD"] = pw
        else:
            vals = {"HOST": "127.0.0.1"}
        env_set(DATA / ".env", vals)
        return {"saved": True, "restart_needed": True}
