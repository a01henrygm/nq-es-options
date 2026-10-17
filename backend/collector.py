"""Background data collection. One collector thread, bounded retries, no duplicate storage."""
from __future__ import annotations
import logging
import threading

from .config import Settings
from .database import Database
from .providers.base import OptionsProvider, ProviderError
from .services import analytics as an
from .services import market
from .services.freshness import classify
from .services.levels import build_levels
from .timeutil import to_et, utcnow

log = logging.getLogger("collector")


class Collector:
    def __init__(self, settings: Settings, provider: OptionsProvider, db: Database, clock=utcnow):
        self.s, self.provider, self.db, self.clock = settings, provider, db, clock
        self.state = {u: {"snapshot": None, "last_attempt": None, "last_success": None, "last_new_data": None,
                          "last_error": None, "failures": 0, "next_try": None} for u in settings.underlyings}
        self._stop = threading.Event()
        self._thread = None

    def run_once(self, u: str) -> bool:
        """Fetch one underlying. Returns True when NEW market data (changed content) was received."""
        st, now = self.state[u], self.clock()
        st["last_attempt"] = now
        try:
            snap = self.provider.fetch_chain(u, max_dte=self.s.max_dte, strike_window=self.s.strike_window)
        except ProviderError as e:
            st["failures"] += 1
            st["last_error"] = {"kind": e.kind, "message": str(e), "at": now.isoformat(), "status": e.status}
            self.db.log_error(self.provider.name, u, now, e.kind, str(e))
            log.warning("%s: %s (%s)", u, e, e.kind)
            return False
        st["failures"], st["last_error"], st["last_success"] = 0, None, now
        sid, is_new = self.db.save_snapshot(snap, self.s.retention_snapshots)
        snap.snapshot_id = sid
        st["snapshot"] = snap
        if is_new:
            st["last_new_data"] = now
            if snap.spot:
                self.db.save_price(u, snap.spot, snap.provider, snap.spot_ts, snap.retrieved_at)
            self._store_metrics(u, snap, now)
            self._capture_levels(u, snap, now)
            self._track_runs(u, snap, now)
        return is_new

    def _track_runs(self, u, snap, now):
        try:
            if not snap.spot:
                return
            day = to_et(snap.source_ts or now).date().isoformat()
            lv = build_levels(snap, now, "standard", classify(snap.source_ts, now, self.s.options_plan), top=10, per_expiry=5, mid=3)
            self.db.update_level_runs(u, day, lv, now)
        except Exception:
            log.exception("could not track level runs for %s", u)

    def _capture_levels(self, u, snap, now):
        """Keep the first set of levels of each session so the reaction log can test them against later price action."""
        try:
            if not snap.spot:
                return
            day = to_et(snap.source_ts or now).date().isoformat()
            if self.db.has_session_levels(u, day):
                return
            lv = build_levels(snap, now, "standard", classify(snap.source_ts, now, self.s.options_plan))
            if lv:
                self.db.save_session_levels(u, day, lv, snap.snapshot_id, now)
        except Exception:
            log.exception("could not capture session levels for %s", u)

    def _store_metrics(self, u, snap, now):
        if not snap.spot:
            return
        try:
            g = an.gex_by_strike(snap.contracts, snap.spot, now)
            self.db.save_metric(snap.snapshot_id, u, "total_net_gex", g["total_net_gex"], None, now)
            f = an.gamma_flip(snap.contracts, snap.spot, now)
            if f["found"]:
                self.db.save_metric(snap.snapshot_id, u, "gamma_flip", f["flip"], {"reliability": f["reliability"]}, now)
            exp = sorted({c.expiry for c in snap.contracts if an.year_fraction(c.expiry, now) > 0})
            if exp:
                a = an.atm_iv(snap.contracts, snap.spot, exp[0])
                if a:
                    self.db.save_metric(snap.snapshot_id, u, "atm_iv_front", a["iv"], {"expiry": exp[0].isoformat()}, now)
            pts = an.iv_points(snap.contracts, snap.spot, now)
            if pts and pts["mid"]:
                self.db.save_metric(snap.snapshot_id, u, "iv_mid", pts["mid"]["atm_iv"], {"expiry": pts["mid"]["expiry"], "days": pts["mid"]["days"]}, now)
            em = an.expected_move(snap.contracts, snap.spot, now)
            if em.get("straddle"):
                self.db.save_metric(snap.snapshot_id, u, "expected_move_straddle", em["straddle"]["price"], {"expiry": em["expiry"]}, now)
            sk = an.skew_25d(snap.contracts, snap.spot, now)
            if sk:
                self.db.save_metric(snap.snapshot_id, u, "skew_25d", sk["value"], {"expiry": sk["expiry"]}, now)
            w = an.walls(snap.contracts, snap.spot, now)
            for k in ("call_wall", "put_wall"):
                if w[k] is not None:
                    self.db.save_metric(snap.snapshot_id, u, k, w[k], {"basis": w["basis"]}, now)
            if em.get("straddle"):
                self.db.save_metric(snap.snapshot_id, u, "em_low", em["straddle"]["lower"], None, now)
                self.db.save_metric(snap.snapshot_id, u, "em_high", em["straddle"]["upper"], None, now)
            for name, field in (("pc_ratio_volume", "volume"), ("pc_ratio_oi", "oi")):
                r = an.concentration(snap.contracts, field)["put_call_ratio"]
                if r is not None:
                    self.db.save_metric(snap.snapshot_id, u, name, r, None, now)
        except Exception:  # a calculation problem must never stop collection
            log.exception("metric calculation failed for %s", u)

    def _interval(self, u) -> float:
        st = self.state[u]
        base = self.s.poll_seconds if market.market_state(self.clock()) in ("open", "premarket", "afterhours") else max(self.s.poll_seconds, 900)
        if st["last_error"] and st["last_error"]["kind"] in ("auth", "plan"):
            return max(base, 900)  # do not hammer when the key or plan is the problem
        return min(base * (2 ** min(st["failures"], 5)), 900) if st["failures"] else base

    def _loop(self):
        while not self._stop.is_set():
            for u in self.s.underlyings:
                if self._stop.is_set():
                    return
                st = self.state[u]
                if st["next_try"] is None or self.clock() >= st["next_try"]:
                    self.run_once(u)
                    from datetime import timedelta
                    st["next_try"] = self.clock() + timedelta(seconds=self._interval(u))
            self._stop.wait(2)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="collector", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
