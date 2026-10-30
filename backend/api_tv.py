"""The two paste-in TradingView indicators (Q DATA GEX and Q DATA Levels), the level tracker behind them, and level-change alerts.

Why start times now work (they never did before):
  - every time is the OPTIONS DATA time of the snapshot (source_ts), not when the delayed data arrived (about 15 minutes later);
  - the levels you copy ARE the tracked levels (one list), so every level has its own start time;
  - any move of a strike level (even one strike) ends its run and starts a new one, so moves show on the chart;
  - the times travel in the pasted text as epoch milliseconds, TradingView's own bar-time clock.

The tracker runs on every new snapshot: from a background thread while the app runs, and also whenever the app asks for levels or
events (so nothing is missed when the thread is not running, as in tests).
"""
from __future__ import annotations
import json
import logging
import threading
import time
from datetime import datetime, timezone

from fastapi import Body, HTTPException

from . import notify
from .config import DATA
from .services import analytics as an
from .services import behavior as bh
from .services import flows as fl
from .services import quant as qt
from .services import tv_levels as tv
from .services.tv_pine import ALL_LV_OFFSET, build_script
from .timeutil import iso, to_et

log = logging.getLogger("tv")
NAMES = {"gex": "Q DATA GEX", "lv": "Q DATA Levels", "all": "Q DATA All Tabs"}
FILES = {"gex": "qdata_gex_paste_in.pine", "lv": "qdata_levels_paste_in.pine", "all": "qdata_all_tabs_paste_in.pine"}
HEAVY_TABS = ("gameplan", "quant")   # Monte Carlo based and recomputed every snapshot anyway: skipped when replaying older snapshots
REPLAY_VERSION = 1           # bump to rebuild today's levels from the stored snapshots (for example after a change to the matching)
SCHEMA = """
CREATE TABLE IF NOT EXISTS tv_runs(id INTEGER PRIMARY KEY, underlying TEXT, day TEXT, ind TEXT, sec INTEGER, kind TEXT, label TEXT, value REAL,
  low REAL, high REAL, first_ts TEXT, last_ts TEXT, end_ts TEXT, prev REAL, active INTEGER, live INTEGER, read TEXT, tip TEXT, short TEXT, style TEXT);
CREATE INDEX IF NOT EXISTS ix_tvr ON tv_runs(underlying, day, ind, active);
CREATE TABLE IF NOT EXISTS tv_events(id INTEGER PRIMARY KEY, underlying TEXT, day TEXT, ts TEXT, data_ts TEXT, ind TEXT, tier INTEGER, kind TEXT,
  label TEXT, action TEXT, old REAL, new REAL, text TEXT);
CREATE INDEX IF NOT EXISTS ix_tve ON tv_events(underlying, id);
CREATE TABLE IF NOT EXISTS tv_state(underlying TEXT PRIMARY KEY, snapshot_id INTEGER, data_ts TEXT);
CREATE TABLE IF NOT EXISTS tv_meta(k TEXT PRIMARY KEY, v TEXT);
"""
ALERT_FILE = DATA / "tv_alerts.json"
KIND_ALIAS = {"0DTE gamma flip": "0DTE flip"}           # the same level under two names on two tabs
LABEL_SHORT = [("Large positive modeled GEX", "+GEX strike"), ("Large negative modeled GEX", "-GEX strike")]
ALERT_DEFAULT = {"on": True, "sound": True, "notify": True, "which": "all"}       # which: all, important, gex


def ms(t: str | None) -> int:
    if not t:
        return 0
    d = datetime.fromisoformat(t)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def load_alert_settings() -> dict:
    try:
        return {**ALERT_DEFAULT, **json.loads(ALERT_FILE.read_text())}
    except Exception:
        return dict(ALERT_DEFAULT)


def tier_of(ind: str, kind: str) -> int:
    """2 = GEX, 1 = other important (key) kinds, 0 = everything else. Each tier has its own sound."""
    return 2 if ind == "gex" else 1 if tv.is_key(kind) else 0


def register(app, h, q, tab_parts):
    lock = threading.Lock()
    running = {"thread": False}
    ready = {"done": False}

    def db_init():
        if not ready["done"]:
            with h.db.conn() as c:
                c.executescript(SCHEMA)
            ready["done"] = True

    # ---- gathering one snapshot's levels, in index units -------------------------------------------------------------
    def gather(u, c, light=False):
        snap, now, z = c["snap"], c["now"], c["z"]
        raw = dict(c, spot_f=None)                                    # index units: the futures basis drifts, the levels should not
        pb = qt.gamma_playbook(z, snap.spot, c["open"], c["sig_open"], c["gamma_series"], c["sig_rem"])
        gf = an.gamma_flip(snap.contracts, snap.spot, now, "standard")
        flips = [z.get("flip") if z.get("available") else None, gf["flip"] if gf["found"] else None]
        strikes = an.gex_by_strike(snap.contracts, snap.spot, now, "standard")["strikes"]
        near = [s for s in strikes if abs(s["strike"] - snap.spot) <= 0.03 * snap.spot]
        scale = max((abs(bh.local_gex(near, s["strike"], snap.spot)) for s in near), default=0.0)
        out, seen = [], set()
        for tab in tv.GEX_TABS + tuple(tv.LV_TABS):
            if light and tab in HEAVY_TABS:
                continue
            try:
                groups, levels, _table, _cone, _about = tab_parts(tab, u, "standard", raw)
            except HTTPException:
                continue
            except Exception:
                log.exception("tv: tab %s failed", tab)
                continue
            ind = "gex" if tab in tv.GEX_TABS else "lv"
            for x in levels:
                g = groups[x["group"]]
                name = KIND_ALIAS.get(g["name"], g["name"])
                if ind == "lv" and any(k in name.lower() for k in ("gamma flip", "0dte flip", "call wall", "put wall")) and "zone" not in name.lower():
                    continue                                          # GEX levels live in the GEX indicator only
                v = x["price"]
                if v is None or v <= 0:
                    continue
                key = (ind, name, round(v, 2))
                if key in seen:
                    continue
                seen.add(key)
                rd = tv.fixed_read(name)
                why = ""
                if rd is None:
                    call, why, _s, _g = bh.call_for({"value": v, "category": tv.call_category(name), "members": []}, pb["state"], snap.spot, flips, strikes, scale)
                    rd = tv.READ.get(call, "-")
                tip = why or (x.get("tip") or x["label"])
                lab = x["label"]
                for a_, b_ in LABEL_SHORT:
                    lab = lab.replace(a_, b_)
                out.append({"ind": ind, "sec": tv.gex_section(name) if ind == "gex" else tv.LV_TABS[tab], "kind": name, "label": lab, "value": float(v),
                            "low": x.get("low"), "high": x.get("high"), "read": rd, "tip": tip, "short": g.get("short") or "", "style": g.get("style") or "solid"})
        return out

    def heat_rows(c):
        snap, now = c["snap"], c["now"]
        try:
            maps = {k: fl.activity_map(snap.contracts, snap.spot, now, k, "total", 0.03, 8, "standard", None, 5) for k in ("volume", "oi", "gex")}
            comb = fl.combined_activity(maps, snap.spot, 5)
        except Exception:
            return []
        ks, pr = comb.get("strikes") or [], comb.get("profile") or []
        top = max(pr + [0.0]) or 1.0
        rows = []
        step = min((abs(a - b) for a, b in zip(ks, ks[1:]) if a != b), default=5.0)
        for k, v in zip(ks, pr):
            hv = round(v / top * 100)
            if hv >= 15:
                rows.append({"price": k, "low": k - step / 2, "high": k + step / 2, "heat": hv})
        return rows

    # ---- the tracker -------------------------------------------------------------------------------------------------
    def process(u, snap, light=False):
        """Match one snapshot's levels to the runs (call with h.as_of set for a stored snapshot). Returns its events."""
        sid = getattr(snap, "snapshot_id", None)
        data_t = snap.source_ts or snap.retrieved_at
        if True:
            c = q.context(u, "standard")
            levels = gather(u, c, light)
            to_f, _ = h.futures_converter(u, snap, c["now"])
            px = (lambda v: f"{to_f(v):,.2f}" if to_f and to_f(v) is not None else f"{v:,.2f}")
            day = to_et(data_t).date().isoformat()
            ts = iso(data_t)
            events = []
            with h.db.conn() as cn:
                runs = [dict(r) for r in cn.execute("SELECT * FROM tv_runs WHERE underlying=? AND day=? AND active=1", (u, day))]
                first = cn.execute("SELECT COUNT(*) FROM tv_runs WHERE underlying=? AND day=?", (u, day)).fetchone()[0] == 0
                seen_kinds = {(r[0], r[1]) for r in cn.execute("SELECT DISTINCT ind, kind FROM tv_runs WHERE underlying=? AND day=?", (u, day))}
                byk = {}
                for r in runs:
                    byk.setdefault((r["ind"], r["kind"]), [[], []])[0].append(r)
                for lv in levels:
                    byk.setdefault((lv["ind"], lv["kind"]), [[], []])[1].append(lv)

                def start(lv, prev=None):
                    cn.execute("INSERT INTO tv_runs(underlying,day,ind,sec,kind,label,value,low,high,first_ts,last_ts,end_ts,prev,active,live,read,tip,short,style)"
                               " VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,?,1,?,?,?,?,?)",
                               (u, day, lv["ind"], lv["sec"], lv["kind"], lv["label"], lv["value"], lv["low"], lv["high"], ts, ts, prev,
                                1 if tv.is_live(lv["kind"]) else 0, lv["read"], lv["tip"], lv["short"], lv["style"]))

                def end(r):
                    cn.execute("UPDATE tv_runs SET active=0, end_ts=? WHERE id=?", (ts, r["id"]))

                def event(ind, kind, label, action, old, new, text):
                    events.append({"underlying": u, "day": day, "ts": iso(c["now"]), "data_ts": ts, "ind": ind, "tier": tier_of(ind, kind), "kind": kind,
                                   "label": label, "action": action, "old": old, "new": new, "text": text})

                for (ind, kind), (old, new) in byk.items():
                    same, moved, fresh, gone = tv.match(old, new)
                    for r, lv in same:
                        cn.execute("UPDATE tv_runs SET value=?, low=?, high=?, last_ts=?, read=?, tip=?, label=? WHERE id=?",
                                   (lv["value"], lv["low"], lv["high"], ts, lv["read"], lv["tip"], lv["label"], r["id"]))
                    live = tv.is_live(kind)
                    for r, lv in moved:
                        end(r)
                        start(lv, r["value"])
                        if not live:
                            event(ind, kind, lv["label"], "moved", r["value"], lv["value"], f"{lv['label']} moved {px(r['value'])} -> {px(lv['value'])}")
                    for lv in fresh:
                        start(lv)
                        if not live and not first and (ind, kind) in seen_kinds:    # a kind showing up for the first time today is not a change
                            event(ind, kind, lv["label"], "new", None, lv["value"], f"New {lv['label']} at {px(lv['value'])}")
                    for r in gone:
                        end(r)
                        if not live:
                            event(ind, kind, r["label"], "gone", r["value"], None, f"{r['label']} at {px(r['value'])} is gone")
                if first and levels:
                    ng = sum(1 for lv in levels if lv["ind"] == "gex")
                    event("gex", "session", "Today's levels", "session", None, None, f"Today's levels are in: {ng} GEX levels, {len(levels) - ng} other levels")
                for e in events:
                    cn.execute("INSERT INTO tv_events(underlying,day,ts,data_ts,ind,tier,kind,label,action,old,new,text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                               (e["underlying"], e["day"], e["ts"], e["data_ts"], e["ind"], e["tier"], e["kind"], e["label"], e["action"], e["old"], e["new"], e["text"]))
                cn.execute("INSERT OR REPLACE INTO tv_state(underlying, snapshot_id, data_ts) VALUES(?,?,?)", (u, sid, ts))
            return events

    def track(u, force=False):
        """Bring the runs up to date. Every stored snapshot of the day that has not been processed yet is replayed in order, each
        "as of" its own time, so a level's start is the data time it REALLY first appeared, even if the tracker was not running then
        (the app keeps the day's snapshots). Returns the events of the newest snapshot only (older ones go to the log, not to alerts)."""
        db_init()
        with lock:
            latest = h.snapshot(u)
            if not latest.spot:
                return []
            data_t = latest.source_ts or latest.retrieved_at
            day = to_et(data_t).date().isoformat()
            with h.db.conn() as cn:
                st = cn.execute("SELECT * FROM tv_state WHERE underlying=?", (u,)).fetchone()
                done = cn.execute("SELECT v FROM tv_meta WHERE k=?", (f"replayed:{REPLAY_VERSION}:{u}:{day}",)).fetchone()
                if not done:                                     # first look at this day (or levels made before replay existed): rebuild it
                    cn.execute("DELETE FROM tv_runs WHERE underlying=? AND day=?", (u, day))
                    cn.execute("DELETE FROM tv_events WHERE underlying=? AND day=?", (u, day))
                    cn.execute("INSERT OR REPLACE INTO tv_meta(k, v) VALUES(?, '1')", (f"replayed:{REPLAY_VERSION}:{u}:{day}",))
                    st = None
            if st and not force and st["snapshot_id"] == getattr(latest, "snapshot_id", None) and st["data_ts"] == iso(data_t):
                return []
            if force:
                return process(u, latest)
            last_ts = st["data_ts"] if st else None
            older = []
            for r in sorted(h.db.list_snapshots(u, 500), key=lambda r: r["id"]):
                t_ = r["source_ts"] or r["retrieved_at"]
                if not t_ or r["id"] == getattr(latest, "snapshot_id", None):
                    continue
                dt = datetime.fromisoformat(t_)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if to_et(dt).date().isoformat() == day and dt < data_t and (last_ts is None or iso(dt) > last_ts):
                    older.append(r["id"])
            for sid in older:
                snap = h.db.load_snapshot(u, sid)
                if not snap or not snap.spot:
                    continue
                tok = h.as_of.set((snap, snap.retrieved_at or snap.source_ts))
                try:
                    process(u, snap, light=True)
                except HTTPException:
                    pass
                except Exception:
                    log.exception("tv replay %s snapshot %s", u, sid)
                finally:
                    h.as_of.reset(tok)
            return process(u, latest)

    def alert(u, events):
        """Desktop notification + sound for one batch of changes (one notification per batch, not per level)."""
        a = load_alert_settings()
        if not a["on"] or not events:
            return
        want = [e for e in events if a["which"] == "all" or (a["which"] == "important" and e["tier"] >= 1) or (a["which"] == "gex" and e["tier"] == 2)]
        if not want:
            return
        tier = max(e["tier"] for e in want)
        ng = sum(1 for e in want if e["ind"] == "gex")
        title = (f"Q DATA {u.lstrip('_')}: GEX levels changed" if ng else f"Q DATA {u.lstrip('_')}: levels changed") + f" ({len(want)})"
        body = "; ".join(e["text"] for e in sorted(want, key=lambda e: -e["tier"])[:3]) + (f"; +{len(want) - 3} more" if len(want) > 3 else "")
        body += ". Copy " + ("GEX" if ng and ng == len(want) else "GEX and Levels" if ng else "Levels") + " in Q DATA and paste."
        notify.send(title, body, tier, sound=a["sound"], popup=a["notify"])

    def loop():
        while True:
            for u in list(h.settings.underlyings):
                try:
                    alert(u, track(u))
                except HTTPException:
                    pass
                except Exception:
                    log.exception("tv tracker %s", u)
            time.sleep(20)

    def start_thread():
        running["thread"] = True
        threading.Thread(target=loop, name="tv-tracker", daemon=True).start()

    def sync(u):
        """Pages bring the tracker up to date themselves only when the background tracker is not running (tests, plain server);
        otherwise they read what it has stored, so a long first replay of the day never makes a page wait."""
        if not running["thread"]:
            track(u)

    app.state.start_tv_tracker = start_thread              # started by main.py and the desktop app next to the collectors

    # ---- endpoints ---------------------------------------------------------------------------------------------------
    def runs_today(u, ind, day):
        with h.db.conn() as cn:
            rows = [dict(r) for r in cn.execute("SELECT * FROM tv_runs WHERE underlying=? AND day=? AND ind=?", (u, day, ind))]
        for r in rows:
            r["first_ts_ms"], r["end_ts_ms"] = ms(r["first_ts"]), ms(r["end_ts"])
        return rows

    def levels(u, ind, prefs=None, history=True):
        if ind not in NAMES:
            raise HTTPException(422, "ind must be gex, lv or all")
        u = h.underlying_ok(u)
        sync(u)
        snap = h.snapshot(u)
        m, _, now = h.meta(snap, {"convention": "standard"})
        data_t = snap.source_ts or snap.retrieved_at
        day = to_et(data_t).date().isoformat()
        to_f, finfo = h.futures_converter(u, snap, now)
        mapped = bool(to_f and to_f(snap.spot) is not None)
        conv = (lambda v: None if v is None else to_f(v)) if mapped else (lambda v: v)
        if ind == "all":                                      # All Tabs: the GEX runs, then the Levels runs with their sections moved past GEX's
            runs = runs_today(u, "gex", day) + [dict(r, sec=int(r["sec"]) + ALL_LV_OFFSET) for r in runs_today(u, "lv", day)]
        else:
            runs = runs_today(u, ind, day)
        if not history:
            runs = [r for r in runs if r["active"]]
        root = finfo.get("root")
        units = f"ESTIMATED {root} points (from {m['underlying']})" if mapped else f"{m['underlying']} units: no {root or 'futures'} price or basis saved, use the offset"
        made = to_et(now).strftime("%Y-%m-%d %H:%M ET")
        rows = [("Data as of", to_et(data_t).strftime("%H:%M ET") + " (about 15 min delayed)"), ("Copied", to_et(now).strftime("%H:%M ET")),
                ("Prices", f"{root} (estimated)" if mapped else m["underlying"])]
        heat = []
        if ind in ("lv", "all"):
            c = q.context(u, "standard")
            heat = [{**x, "price": conv(x["price"]), "low": conv(x["low"]), "high": conv(x["high"])} for x in heat_rows(c)]
            heat = [x for x in heat if x["price"] is not None]
        j = tv.build_text(ind, runs, conv, made, day, f"{u.lstrip('_')} -> {root}" if mapped else u.lstrip("_"), units, ms(iso(data_t)), rows, heat, prefs)
        with h.db.conn() as cn:
            st = cn.execute("SELECT snapshot_id FROM tv_state WHERE underlying=?", (u,)).fetchone()
        j["catching_up"] = not st or st["snapshot_id"] != getattr(snap, "snapshot_id", None)
        j.update({"ind": ind, "title": NAMES[ind], "mapped": mapped, "data_as_of": iso(data_t), "made": made, "heat": len(heat)})
        return j

    @app.get("/api/tv/levels")
    def tv_levels_get(underlying: str, ind: str = "gex", history: bool = True):
        return levels(underlying, ind, None, history)

    @app.post("/api/tv/levels")
    def tv_levels_post(underlying: str, ind: str = "gex", history: bool = True, body: dict = Body(default={})):
        return levels(underlying, ind, (body or {}).get("prefs"), history)

    @app.get("/api/tv/script")
    def tv_script(ind: str = "gex"):
        if ind not in NAMES:
            raise HTTPException(422, "ind must be gex, lv or all")
        return {"code": build_script(ind), "title": NAMES[ind], "filename": FILES[ind]}

    # Q DATA All Tabs (1.25.0): built on the same script as GEX and Levels, with every section of both in one indicator
    @app.get("/api/tv/alltabs/script")
    def alltabs_script():
        return {"code": build_script("all"), "title": NAMES["all"], "filename": FILES["all"],
                "note": "Add this to TradingView once (Pine Editor > new script > select all > paste > Save > Add to chart). Then paste the levels from Q DATA into its first setting."}

    @app.post("/api/tv/alltabs/levels")
    def alltabs_levels(underlying: str, history: bool = True, body: dict = Body(default={})):
        return levels(underlying, "all", (body or {}).get("prefs"), history)

    @app.post("/api/tv/track")
    def tv_track(underlying: str, force: bool = False):
        u = h.underlying_ok(underlying)
        ev = track(u, force)
        return {"events": ev}

    @app.get("/api/tv/events")
    def tv_events(underlying: str | None = None, since: int = 0, limit: int = 200):
        db_init()
        us = [h.underlying_ok(underlying)] if underlying else list(h.settings.underlyings)
        for u in us:
            try:
                sync(u)
            except HTTPException:
                pass
        with h.db.conn() as cn:
            last = cn.execute("SELECT COALESCE(MAX(id), 0) FROM tv_events").fetchone()[0]
            if since <= 0:
                return {"events": [], "last": last}
            qm = ",".join("?" * len(us))
            rows = [dict(r) for r in cn.execute(f"SELECT * FROM tv_events WHERE id>? AND underlying IN ({qm}) ORDER BY id LIMIT ?", (since, *us, limit))]
        return {"events": rows, "last": last}

    @app.get("/api/tv/log")
    def tv_log(underlying: str, day: str | None = None):
        u = h.underlying_ok(underlying)
        db_init()
        sync(u)
        snap = h.snapshot(u)
        d = day or to_et(snap.source_ts or snap.retrieved_at).date().isoformat()
        with h.db.conn() as cn:
            ev = [dict(r) for r in cn.execute("SELECT * FROM tv_events WHERE underlying=? AND day=? ORDER BY id DESC LIMIT 400", (u, d))]
            nrun = cn.execute("SELECT COUNT(*) FROM tv_runs WHERE underlying=? AND day=? AND active=1", (u, d)).fetchone()[0]
        for e in ev:
            e["time_et"] = to_et(datetime.fromisoformat(e["data_ts"])).strftime("%H:%M") if e.get("data_ts") else ""
        return {"day": d, "events": ev, "active_levels": nrun,
                "note": "Times are the options data time (the data reaches Q DATA about 15 minutes later). Open interest updates once a day."}

    @app.get("/api/tv/alerts")
    def tv_alerts_get():
        return load_alert_settings()

    @app.post("/api/tv/alerts")
    def tv_alerts_post(body: dict = Body(default={})):
        a = load_alert_settings()
        for k in ("on", "sound", "notify"):
            if isinstance(body.get(k), bool):
                a[k] = body[k]
        if body.get("which") in ("all", "important", "gex"):
            a["which"] = body["which"]
        try:
            ALERT_FILE.write_text(json.dumps(a))
        except OSError:
            raise HTTPException(500, "Could not save the alert settings")
        return a

    @app.post("/api/tv/alerts/test")
    def tv_alerts_test(tier: int = 2):
        notify.send("Q DATA: test alert", {2: "This is the GEX sound.", 1: "This is the important-level sound.", 0: "This is the sound for other levels."}.get(tier, ""),
                    max(0, min(2, tier)), sound=True, popup=True)
        return {"ok": True, "desktop": notify.available()}

    return track
