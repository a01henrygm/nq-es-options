"""QQQ levels come out in NQ points everywhere (1.35.0): through the NDX data, with a typed NQ basis or with nothing saved. TEST DATA ONLY."""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.collector import Collector
from backend.config import Settings
from backend.database import Database
from backend.models import ChainSnapshot
from backend.timeutil import ET, UTC
from tests.test_session_features import FakeProvider, chain_at

K = 41.0                                              # NDX / QQQ in this test


class TwoSymbols(FakeProvider):
    def fetch_chain(self, u, max_dte=30, strike_window=0.12):
        s = super().fetch_chain(u, max_dte, strike_window)
        if u != "QQQ":
            return s
        for c in s.contracts:                         # the same chain on the QQQ scale
            c.strike = round(c.strike / K, 2)
            for f in ("bid", "ask", "last"):
                setattr(c, f, getattr(c, f) / K if getattr(c, f) else getattr(c, f))
            c.ticker = c.ticker.replace("TEST", "QQQT")
        return ChainSnapshot("cboe", "QQQ", s.spot_ts, s.spot / K, s.retrieved_at, s.contracts, s.content_hash + "q")


def two_symbol_day():
    s = Settings(provider="cboe", underlyings=("_NDX", "QQQ"), retention_snapshots=20)
    db = Database(":memory:")
    now = {"t": datetime(2026, 10, 14, 10, 0, tzinfo=ET).astimezone(UTC)}
    clock = lambda: now["t"]
    col = Collector(s, TwoSymbols(clock), db, clock)
    t = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    while t <= datetime(2026, 10, 14, 11, 0, tzinfo=ET):
        now["t"] = t.astimezone(UTC)
        col.run_once("_NDX")
        col.run_once("QQQ")
        t += timedelta(minutes=15)
    return TestClient(create_app(s, db, col, clock)), db, now


def nq_of(lv, cat):
    x = next(l for l in lv if l["category"] == cat)
    return x["value"], x["mapped"]["mapped"] if x.get("mapped") else None


def test_qqq_key_levels_in_nq_with_nothing_saved_and_with_a_typed_basis():
    c, db, now = two_symbol_day()
    nd = c.get("/api/analytics/levels", params={"underlying": "_NDX"}).json()
    qq = c.get("/api/analytics/levels", params={"underlying": "QQQ"}).json()
    assert qq["mapping"].get("via") == "_NDX" and qq["mapping"]["futures_root"] == "NQ"
    n_v, n_nq = nq_of(nd["levels"], "gamma_flip")
    q_v, q_nq = nq_of(qq["levels"], "gamma_flip")
    assert n_nq and q_nq and abs(q_nq - q_v * K * n_nq / n_v) < 2.0          # QQQ x 41 then the same NQ conversion as NDX
    db.save_price("NQ_BASIS", 120.0, "manual entry", now["t"], now["t"], None, manual=True)
    nd = c.get("/api/analytics/levels", params={"underlying": "_NDX"}).json()
    qq = c.get("/api/analytics/levels", params={"underlying": "QQQ"}).json()
    n_v, n_nq = nq_of(nd["levels"], "gamma_flip")
    q_v, q_nq = nq_of(qq["levels"], "gamma_flip")
    assert abs(n_nq - (n_v + 120)) < 1e-6 and abs(q_nq - (q_v * K + 120)) < 1.0      # a typed NQ basis works for QQQ too


def test_qqq_tradingview_copies_are_in_nq_points():
    c, db, now = two_symbol_day()
    db.save_price("NQ_BASIS", 120.0, "manual entry", now["t"], now["t"], None, manual=True)
    for r in (c.post("/api/tv/combo/levels", params={"ticker": "QQQ"}, json={}), c.post("/api/tv/keylevels/levels", params={"underlying": "QQQ"}, json={}),
              c.post("/api/tv/levels", params={"underlying": "QQQ", "ind": "gex"}, json={})):
        assert r.status_code == 200, r.text
        j = r.json()
        prices = [float(l.split("|")[1]) for l in j["text"].splitlines() if l.startswith("L|")]
        assert j["mapped"] and prices and min(prices) > 25000, (j.get("ind"), prices[:3])       # NQ scale, not QQQ's ~730
