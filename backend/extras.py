"""Background feed for the Volatility and Earnings tabs. One thread, its own schedule, never touches the options collectors.

  job        source                                       how often
  vol        Cboe quote files, VIX family + VXN + VVIX     every POLL_SECONDS in market hours, every 15 min otherwise
  history    Cboe daily history CSVs                       once a day
  members    Nasdaq-100 members and market caps (Nasdaq)   every 6 hours
  reports    next report date and before/after the bell    every 6 hours
  chains     option chains of companies reporting soon     every 30 min in market hours, every 3 hours otherwise

Everything it learns is kept in the database (app_meta), so the tabs show the last known values straight after a restart.
A failed download only marks that job's status and is retried on the next cycle; the other jobs carry on.
"""
from __future__ import annotations
import json
import logging
import threading
from datetime import date, datetime, timedelta

import httpx

from .config import Settings
from .database import Database
from .providers.base import ProviderError
from .providers.cboe import CboeProvider
from .services import earnings as ea
from .services import market
from .services import volatility as vol
from .timeutil import iso, parse_ts, to_et, utcnow

log = logging.getLogger("extras")
QUOTES = "https://cdn.cboe.com/api/global/delayed_quotes/quotes"
HISTORY = "https://cdn.cboe.com/api/global/us_indices/daily_prices"
NASDAQ = "https://api.nasdaq.com/api"
CBOE_UA = {"User-Agent": "Mozilla/5.0 (personal analytics dashboard)", "Accept": "application/json,text/csv,*/*"}
NASDAQ_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
             "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
             "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}


class Extras:
    label = "VIX family and mega-cap earnings"

    def __init__(self, settings: Settings, db: Database, client: httpx.Client | None = None, clock=utcnow):
        self.s, self.db, self.clock = settings, db, clock
        self.client = client or httpx.Client(timeout=60.0, follow_redirects=True)
        self.cboe = CboeProvider(settings, self.client, clock=clock)
        self.status = {k: {"last_ok": None, "last_error": None, "next": None} for k in ("vol", "history", "members", "reports", "chains")}
        self.quotes, self.hist, self.weights, self.reports, self.timings, self.moves = {}, {}, {}, {}, {}, {}
        self._stop = threading.Event()
        self._thread = None
        self._load()

    # -- storage -------------------------------------------------------------------------------------------------------------
    def _save(self, key, value):
        try:
            self.db.set_meta("extras:" + key, json.dumps(value, default=str))
        except Exception:
            log.exception("could not store %s", key)

    def _get(self, key, default=None):
        try:
            v = self.db.get_meta("extras:" + key)
            return json.loads(v) if v else default
        except Exception:
            return default

    def _load(self):
        self.quotes = {k: dict(q, time=parse_ts(q.get("time"))) for k, q in (self._get("quotes", {}) or {}).items()}
        self.hist = {n: [(date.fromisoformat(d), v) for d, v in rows] for n, rows in (self._get("history", {}) or {}).items()}
        self.weights = self._get("weights", {}) or {}
        self.reports = {s: {"date": date.fromisoformat(r["date"]), "estimated": r["estimated"]} for s, r in (self._get("reports", {}) or {}).items()}
        self.timings = self._get("timings", {}) or {}
        self.moves = self._get("moves", {}) or {}
        for k, v in (self._get("status", {}) or {}).items():
            if k in self.status:
                self.status[k].update(last_ok=v.get("last_ok"), last_error=v.get("last_error"))

    def _mark(self, job, ok, err=None):
        st = self.status[job]
        if ok:
            st["last_ok"], st["last_error"] = iso(self.clock()), None
        else:
            st["last_error"] = {"at": iso(self.clock()), "message": err}
        self._save("status", {k: {"last_ok": v["last_ok"], "last_error": v["last_error"]} for k, v in self.status.items()})

    # -- downloads -----------------------------------------------------------------------------------------------------------
    def _fetch(self, url, headers, params=None, kind="json"):
        r = self.client.get(url, headers=headers, params=params)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} from {url.split('/')[2]}")
        return r.json() if kind == "json" else r.text

    def refresh_vol(self):
        got, errs = 0, []
        for k, *_ in vol.INDICES:
            try:
                q = vol.parse_quote(self._fetch(f"{QUOTES}/{k}.json", CBOE_UA))
            except Exception as e:                       # one missing index must not hide the others
                errs.append(f"{k}: {e}")
                continue
            if not q:
                errs.append(f"{k}: no price in the file")
                continue
            old = self.quotes.get(k)
            if not old or old.get("value") != q["value"] or old.get("time") != q["time"]:
                self.db.save_price(k, q["value"], "cboe", q["time"], self.clock())
            self.quotes[k] = q
            got += 1
        self._save("quotes", {k: dict(q, time=iso(q["time"])) for k, q in self.quotes.items()})
        self._mark("vol", got > 0, "; ".join(errs) if errs else None)
        if got and errs:
            self.status["vol"]["last_error"] = {"at": iso(self.clock()), "message": "Some indices were missing: " + "; ".join(errs)}

    def refresh_history(self):
        got, errs = 0, []
        for n in vol.HISTORY_NAMES:
            try:
                rows = vol.parse_history_csv(self._fetch(f"{HISTORY}/{n}_History.csv", CBOE_UA, kind="text"))
            except Exception as e:
                errs.append(f"{n}: {e}")
                continue
            if rows:
                self.hist[n] = rows[-600:]                # about two and a half years is plenty for the 1-year percentiles
                got += 1
            else:
                errs.append(f"{n}: the file had no rows the app could read")
        self._save("history", {n: [(d.isoformat(), v) for d, v in rows] for n, rows in self.hist.items()})
        self._mark("history", got > 0, "; ".join(errs) if errs else None)

    def refresh_members(self):
        try:
            j = self._fetch(f"{NASDAQ}/quote/list-type/nasdaq100", NASDAQ_UA)
            rows = (((j.get("data") or {}).get("data") or {}).get("rows")) or []
            w = ea.ndx_weights(rows)
            if len(w) < 50:
                raise RuntimeError(f"Nasdaq returned only {len(w)} members")
            self.weights = w
            self._save("weights", w)
            self._mark("members", True)
        except Exception as e:
            self._mark("members", False, str(e))

    def names(self):
        return [s for s, _ in sorted(self.weights.items(), key=lambda kv: -kv[1]["weight"])][: self.s.earnings_names]

    def refresh_reports(self):
        errs, today = [], to_et(self.clock()).date()
        for s in self.names():
            try:
                r = ea.parse_report_date(self._fetch(f"{NASDAQ}/analyst/{s}/earnings-date", NASDAQ_UA))
                if r:
                    self.reports[s] = r
                else:
                    errs.append(f"{s}: no date in Nasdaq's reply")
            except Exception as e:
                errs.append(f"{s}: {e}")
        for d in sorted({r["date"] for s, r in self.reports.items() if 0 <= (r["date"] - today).days <= 60}):
            try:
                cal = ea.parse_calendar(self._fetch(f"{NASDAQ}/calendar/earnings", NASDAQ_UA, params={"date": d.isoformat()}))
                for s, r in self.reports.items():
                    if r["date"] == d and s in cal:
                        self.timings[s] = cal[s]
            except Exception as e:
                errs.append(f"calendar {d}: {e}")
        self._save("reports", {s: {"date": r["date"].isoformat(), "estimated": r["estimated"]} for s, r in self.reports.items()})
        self._save("timings", self.timings)
        self._mark("reports", bool(self.reports), "; ".join(errs) if errs else None)

    def refresh_chains(self):
        now, today, errs, done = self.clock(), to_et(self.clock()).date(), [], 0
        for s in self.names():
            r = self.reports.get(s)
            if not r or not (0 <= (r["date"] - today).days <= ea.CHAIN_WINDOW_DAYS):
                continue
            react = ea.reaction_day(r["date"], self.timings.get(s, "unknown"))
            try:
                snap = self.cboe.fetch_chain(s, max_dte=max(45, (react - today).days + 10), strike_window=0.25)
                mv = ea.implied_move(snap.contracts, snap.spot, react, now)
                self.moves[s] = {**mv, "spot": snap.spot, "as_of": iso(snap.source_ts or now), "reaction_day": react.isoformat()}
                done += 1
            except ProviderError as e:
                errs.append(f"{s}: {e}")
            except Exception as e:
                log.exception("implied move failed for %s", s)
                errs.append(f"{s}: {type(e).__name__}")
        self._save("moves", self.moves)
        self._mark("chains", not errs or done > 0, "; ".join(errs) if errs else None)

    # -- schedule ------------------------------------------------------------------------------------------------------------
    def _every(self, job):
        live = market.market_state(self.clock()) in ("open", "premarket", "afterhours")
        return {"vol": self.s.poll_seconds if live else 900, "history": 6 * 3600, "members": 6 * 3600,
                "reports": 6 * 3600, "chains": 1800 if live else 3 * 3600}[job]

    def run_due(self):
        order = [("vol", self.refresh_vol), ("history", self.refresh_history), ("members", self.refresh_members),
                 ("reports", self.refresh_reports), ("chains", self.refresh_chains)]
        for job, fn in order:
            if self._stop.is_set():
                return
            st = self.status[job]
            if st["next"] is None or self.clock() >= st["next"]:
                if job == "history" and st["last_ok"] and to_et(parse_ts(st["last_ok"])).date() == to_et(self.clock()).date() and self.hist:
                    st["next"] = self.clock() + timedelta(hours=6)           # already have today's file
                    continue
                try:
                    fn()
                except Exception as e:                    # a job problem must never stop the thread
                    log.exception("extras job %s failed", job)
                    self._mark(job, False, f"{type(e).__name__}: {e}")
                st["next"] = self.clock() + timedelta(seconds=self._every(job))

    def _loop(self):
        while not self._stop.is_set():
            self.run_due()
            self._stop.wait(5)

    def start(self):
        if not self.s.extras_enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="extras", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def status_view(self):
        return {"enabled": self.s.extras_enabled, "jobs": {k: {"last_ok": v["last_ok"], "last_error": v["last_error"],
                                                               "next": iso(v["next"]) if isinstance(v["next"], datetime) else None} for k, v in self.status.items()}}
