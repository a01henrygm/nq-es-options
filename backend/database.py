"""SQLite storage. Snapshots are only stored when the content actually changed (duplicate detection by hash)."""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from .models import ChainSnapshot, OptionContract
from .timeutil import UTC, iso, parse_ts

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots(
  id INTEGER PRIMARY KEY, provider TEXT, underlying TEXT, retrieved_at TEXT, source_ts TEXT,
  spot REAL, spot_ts TEXT, content_hash TEXT, n_contracts INTEGER,
  UNIQUE(underlying, content_hash));
CREATE INDEX IF NOT EXISTS ix_snap_u ON snapshots(underlying, id);
CREATE TABLE IF NOT EXISTS contracts(
  snapshot_id INTEGER, ticker TEXT, right TEXT, strike REAL, expiry TEXT, multiplier INTEGER,
  bid REAL, ask REAL, last REAL, volume REAL, oi REAL, iv REAL, delta REAL, gamma REAL, theta REAL, vega REAL,
  quote_ts TEXT, trade_ts TEXT);
CREATE INDEX IF NOT EXISTS ix_con_s ON contracts(snapshot_id);
CREATE TABLE IF NOT EXISTS prices(
  id INTEGER PRIMARY KEY, symbol TEXT, contract TEXT, price REAL, source TEXT, source_ts TEXT, retrieved_at TEXT, manual INTEGER);
CREATE INDEX IF NOT EXISTS ix_price ON prices(symbol, id);
CREATE TABLE IF NOT EXISTS analytics(
  id INTEGER PRIMARY KEY, snapshot_id INTEGER, underlying TEXT, name TEXT, value REAL, detail TEXT, calculated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_an ON analytics(underlying, name, id);
CREATE TABLE IF NOT EXISTS session_levels(
  id INTEGER PRIMARY KEY, underlying TEXT, session_date TEXT, category TEXT, label TEXT, value REAL, method TEXT, snapshot_id INTEGER, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_sl ON session_levels(underlying, session_date);
CREATE TABLE IF NOT EXISTS level_runs(
  id INTEGER PRIMARY KEY, underlying TEXT, session_date TEXT, category TEXT, label TEXT, value REAL, first_seen TEXT, last_seen TEXT, active INTEGER);
CREATE INDEX IF NOT EXISTS ix_lr ON level_runs(underlying, session_date, active);
CREATE TABLE IF NOT EXISTS custom_levels(id INTEGER PRIMARY KEY, underlying TEXT, label TEXT, value REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, date TEXT, time TEXT, name TEXT, importance TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY, underlying TEXT, instrument TEXT, side TEXT, qty REAL, entry REAL, stop REAL, target REAL, exit REAL,
  opened_at TEXT, closed_at TEXT, setup TEXT, note TEXT, context TEXT);
CREATE TABLE IF NOT EXISTS provider_errors(id INTEGER PRIMARY KEY, provider TEXT, underlying TEXT, at TEXT, kind TEXT, message TEXT);
"""


class Database:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._mem = sqlite3.connect(":memory:", check_same_thread=False) if self.path == ":memory:" else None
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = self._mem or sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            if not self._mem:
                c.execute("PRAGMA journal_mode=WAL")
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            if not self._mem:
                c.close()

    # -- snapshots -------------------------------------------------------------------------
    def save_snapshot(self, s: ChainSnapshot, keep: int = 400) -> tuple[int | None, bool]:
        """Returns (snapshot_id, is_new). Identical content is not stored twice."""
        with self.conn() as c:
            row = c.execute("SELECT id FROM snapshots WHERE underlying=? AND content_hash=?", (s.underlying, s.content_hash)).fetchone()
            if row:
                return row["id"], False
            cur = c.execute(
                "INSERT INTO snapshots(provider,underlying,retrieved_at,source_ts,spot,spot_ts,content_hash,n_contracts) VALUES(?,?,?,?,?,?,?,?)",
                (s.provider, s.underlying, iso(s.retrieved_at), iso(s.source_ts), s.spot, iso(s.spot_ts), s.content_hash, len(s.contracts)))
            sid = cur.lastrowid
            c.executemany(
                "INSERT INTO contracts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(sid, k.ticker, k.right, k.strike, k.expiry.isoformat(), k.multiplier, k.bid, k.ask, k.last, k.volume, k.oi,
                  k.iv, k.delta, k.gamma, k.theta, k.vega, iso(k.quote_ts), iso(k.trade_ts)) for k in s.contracts])
            old = c.execute("SELECT id FROM snapshots WHERE underlying=? ORDER BY id DESC LIMIT -1 OFFSET ?", (s.underlying, keep)).fetchall()
            for r in old:
                c.execute("DELETE FROM contracts WHERE snapshot_id=?", (r["id"],))
                c.execute("DELETE FROM snapshots WHERE id=?", (r["id"],))
            return sid, True

    def load_snapshot(self, underlying: str, snapshot_id: int | None = None) -> ChainSnapshot | None:
        with self.conn() as c:
            q = "SELECT * FROM snapshots WHERE underlying=? " + ("AND id=?" if snapshot_id else "") + " ORDER BY id DESC LIMIT 1"
            r = c.execute(q, (underlying, snapshot_id) if snapshot_id else (underlying,)).fetchone()
            if not r:
                return None
            rows = c.execute("SELECT * FROM contracts WHERE snapshot_id=?", (r["id"],)).fetchall()
        cons = [OptionContract(ticker=x["ticker"], right=x["right"], strike=x["strike"], expiry=date.fromisoformat(x["expiry"]),
                               multiplier=x["multiplier"], bid=x["bid"], ask=x["ask"], last=x["last"], volume=x["volume"], oi=x["oi"],
                               iv=x["iv"], delta=x["delta"], gamma=x["gamma"], theta=x["theta"], vega=x["vega"],
                               quote_ts=parse_ts(x["quote_ts"]), trade_ts=parse_ts(x["trade_ts"])) for x in rows]
        return ChainSnapshot(r["provider"], underlying, parse_ts(r["retrieved_at"]), r["spot"], parse_ts(r["spot_ts"]), cons,
                             r["content_hash"], r["id"], from_database=True)

    def list_snapshots(self, underlying: str, limit: int = 200) -> list:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT id,retrieved_at,source_ts,spot,n_contracts FROM snapshots WHERE underlying=? ORDER BY id DESC LIMIT ?", (underlying, limit))]

    # -- prices ----------------------------------------------------------------------------
    def save_price(self, symbol, price, source, source_ts, retrieved_at, contract=None, manual=False):
        with self.conn() as c:
            c.execute("INSERT INTO prices(symbol,contract,price,source,source_ts,retrieved_at,manual) VALUES(?,?,?,?,?,?,?)",
                      (symbol, contract, price, source, iso(source_ts), iso(retrieved_at), int(manual)))

    def latest_price(self, symbol):
        with self.conn() as c:
            r = c.execute("SELECT * FROM prices WHERE symbol=? ORDER BY id DESC LIMIT 1", (symbol,)).fetchone()
        return dict(r) if r else None

    def price_history(self, symbol, limit=500):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM prices WHERE symbol=? ORDER BY id DESC LIMIT ?", (symbol, limit))][::-1]

    # -- analytics history / errors --------------------------------------------------------
    def save_metric(self, snapshot_id, underlying, name, value, detail, calculated_at):
        with self.conn() as c:
            c.execute("INSERT INTO analytics(snapshot_id,underlying,name,value,detail,calculated_at) VALUES(?,?,?,?,?,?)",
                      (snapshot_id, underlying, name, value, json.dumps(detail) if detail is not None else None, iso(calculated_at)))

    def metric_history(self, underlying, name, limit=500):
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT value,calculated_at,snapshot_id FROM analytics WHERE underlying=? AND name=? ORDER BY id DESC LIMIT ?",
                (underlying, name, limit))][::-1]

    def metric_series(self, underlying, name, since=None, limit=5000):
        """Like metric_history but with the stored detail (decoded) and an optional start time (ISO, UTC)."""
        q = "SELECT value,detail,calculated_at FROM analytics WHERE underlying=? AND name=?" + (" AND calculated_at>=?" if since else "") + " ORDER BY id DESC LIMIT ?"
        with self.conn() as c:
            rows = c.execute(q, (underlying, name, since, limit) if since else (underlying, name, limit)).fetchall()
        return [{"value": r["value"], "detail": json.loads(r["detail"]) if r["detail"] else None, "t": r["calculated_at"]} for r in rows][::-1]

    # -- trade journal ---------------------------------------------------------------------
    TRADE_FIELDS = ("underlying", "instrument", "side", "qty", "entry", "stop", "target", "exit", "opened_at", "closed_at", "setup", "note", "context")

    def add_trade(self, t: dict) -> int:
        row = {k: (json.dumps(t[k]) if k == "context" and t.get(k) is not None else t.get(k)) for k in self.TRADE_FIELDS}
        with self.conn() as c:
            return c.execute(f"INSERT INTO trades({','.join(row)}) VALUES({','.join('?' * len(row))})", tuple(row.values())).lastrowid

    def update_trade(self, trade_id: int, changes: dict) -> bool:
        ch = {k: (json.dumps(v) if k == "context" and v is not None else v) for k, v in changes.items() if k in self.TRADE_FIELDS}
        if not ch:
            return False
        with self.conn() as c:
            return c.execute(f"UPDATE trades SET {', '.join(k + '=?' for k in ch)} WHERE id=?", (*ch.values(), trade_id)).rowcount > 0

    def delete_trade(self, trade_id: int) -> bool:
        with self.conn() as c:
            return c.execute("DELETE FROM trades WHERE id=?", (trade_id,)).rowcount > 0

    def list_trades(self, limit=1000) -> list:
        with self.conn() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM trades ORDER BY opened_at DESC, id DESC LIMIT ?", (limit,))]
        for r in rows:
            r["context"] = json.loads(r["context"]) if r["context"] else None
        return rows

    # -- levels of the day (for the reaction log) ----------------------------------------
    def has_session_levels(self, underlying, day):
        with self.conn() as c:
            return c.execute("SELECT 1 FROM session_levels WHERE underlying=? AND session_date=? LIMIT 1", (underlying, day)).fetchone() is not None

    def save_session_levels(self, underlying, day, levels, snapshot_id, created_at):
        with self.conn() as c:
            c.executemany("INSERT INTO session_levels(underlying,session_date,category,label,value,method,snapshot_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
                          [(underlying, day, x["category"], x["label"], x["value"], x.get("method"), snapshot_id, iso(created_at)) for x in levels])

    def load_session_levels(self, underlying, day):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT category,label,value,method FROM session_levels WHERE underlying=? AND session_date=? ORDER BY value DESC", (underlying, day))]

    def list_session_dates(self, underlying, limit=30):
        with self.conn() as c:
            return [r["session_date"] for r in c.execute("SELECT DISTINCT session_date FROM session_levels WHERE underlying=? ORDER BY session_date DESC LIMIT ?", (underlying, limit))]

    # -- how long each level has been showing ("runs") -----------------------------------
    def active_level_runs(self, underlying, day):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM level_runs WHERE underlying=? AND session_date=? AND active=1", (underlying, day))]

    def update_level_runs(self, underlying, day, levels, now, tol=0.0005):
        """Match this snapshot's levels to the runs that were already showing. A level that is still there keeps its first_seen time
        (its value follows any small drift); a new level starts a run now; a level that disappeared ends its run."""
        with self.conn() as c:
            runs = [dict(r) for r in c.execute("SELECT * FROM level_runs WHERE underlying=? AND session_date=? AND active=1", (underlying, day))]
            used = set()
            for lv in levels:
                best = None
                for r in runs:
                    if r["id"] in used or r["category"] != lv["category"] or r["label"] != lv["label"]:
                        continue
                    d = abs(r["value"] - lv["value"])
                    if d <= tol * abs(lv["value"]) and (best is None or d < best[0]):
                        best = (d, r)
                if best:
                    used.add(best[1]["id"])
                    c.execute("UPDATE level_runs SET value=?, last_seen=? WHERE id=?", (lv["value"], iso(now), best[1]["id"]))
                else:
                    c.execute("INSERT INTO level_runs(underlying,session_date,category,label,value,first_seen,last_seen,active) VALUES(?,?,?,?,?,?,?,1)",
                              (underlying, day, lv["category"], lv["label"], lv["value"], iso(now), iso(now)))
            for r in runs:
                if r["id"] not in used:
                    c.execute("UPDATE level_runs SET active=0 WHERE id=?", (r["id"],))

    # -- levels typed in by the user ---------------------------------------------------------
    def add_custom_level(self, underlying, label, value, created_at):
        with self.conn() as c:
            return c.execute("INSERT INTO custom_levels(underlying,label,value,created_at) VALUES(?,?,?,?)", (underlying, label, value, iso(created_at))).lastrowid

    def list_custom_levels(self, underlying):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM custom_levels WHERE underlying=? ORDER BY value DESC", (underlying,))]

    def delete_custom_level(self, underlying, level_id):
        with self.conn() as c:
            return c.execute("DELETE FROM custom_levels WHERE id=? AND underlying=?", (level_id, underlying)).rowcount

    # -- scheduled events (FOMC, CPI, ...) -----------------------------------------------------
    def add_event(self, date, time, name, importance, note=""):
        with self.conn() as c:
            return c.execute("INSERT INTO events(date,time,name,importance,note) VALUES(?,?,?,?,?)", (date, time or "", name, importance, note or "")).lastrowid

    def list_events(self, from_date):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM events WHERE date>=? ORDER BY date, time", (from_date,))]

    def delete_event(self, event_id):
        with self.conn() as c:
            return c.execute("DELETE FROM events WHERE id=?", (event_id,)).rowcount

    def get_meta(self, key):
        with self.conn() as c:
            r = c.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None

    def set_meta(self, key, value):
        with self.conn() as c:
            c.execute("INSERT INTO app_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def log_error(self, provider, underlying, at, kind, message):
        with self.conn() as c:
            c.execute("INSERT INTO provider_errors(provider,underlying,at,kind,message) VALUES(?,?,?,?,?)",
                      (provider, underlying, iso(at), kind, message[:500]))

    def recent_errors(self, limit=20):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM provider_errors ORDER BY id DESC LIMIT ?", (limit,))]
