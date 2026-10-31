"""0DTE, the session / before-the-open / scorecard charts, the written case, the journal and phone access, against a SIMULATED day.

A fake provider returns synthetic chains (TEST DATA ONLY) while a fake clock walks from the previous afternoon through a session,
so the collector stores the same records it stores live."""
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.collector import Collector
from backend.config import Settings
from backend.database import Database
from backend.models import ChainSnapshot
from backend.providers.massive import content_hash
from backend.services import intraday as idy
from backend.services.narrative import build_case
from backend.timeutil import ET, UTC
from tests.conftest import make_chain

DAY = date(2026, 10, 14)


def chain_at(spot, t, vol_scale=1.0):
    cons = []
    for exp, oi in ((DAY, 4000), (date(2026, 10, 16), 2500), (date(2026, 11, 20), 6000)):
        cc = make_chain(spot=30000.0, n_strikes=41, step=50.0, iv=0.18, oi=oi, expiry=exp, now=t, ts=t)
        for c in cc:
            c.oi = float(oi * (3 if (c.right == "C") == (c.strike >= 30000) else 0.4))
            c.volume = (300.0 if c.right == "P" else 200.0) * vol_scale
            if exp == DAY and c.strike == 30200 and c.right == "C":
                c.oi = 150000.0                                                  # a big 0DTE call strike
            if exp == DAY and c.strike == 29800 and c.right == "P":
                c.oi = 150000.0                                                  # a big 0DTE put strike
        cons += cc
    return ChainSnapshot("cboe", "_NDX", t, spot, t, cons, content_hash(cons) + str(spot) + t.isoformat())


class FakeProvider:
    name = "cboe"

    def __init__(self, clock):
        self.clock = clock

    def fetch_chain(self, u, max_dte=30, strike_window=0.12):
        t = self.clock()
        mins = (t.astimezone(ET) - datetime(2026, 10, 14, 9, 30, tzinfo=ET)).total_seconds() / 60
        spot = 30000.0 + 0.6 * max(mins, 0) if t.astimezone(ET).date() == DAY else 29950.0
        return chain_at(spot, t, 1 + max(mins, 0) / 60)


def simulated_day():
    s = Settings(provider="cboe", underlyings=("_NDX",), retention_snapshots=20)
    db = Database(":memory:")
    now = {"t": datetime(2026, 10, 13, 15, 50, tzinfo=ET).astimezone(UTC)}
    clock = lambda: now["t"]
    col = Collector(s, FakeProvider(clock), db, clock)
    col.run_once("_NDX")                                                        # previous session's last snapshot
    t = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    while t <= datetime(2026, 10, 14, 15, 30, tzinfo=ET):
        now["t"] = t.astimezone(UTC)
        col.run_once("_NDX")
        t += timedelta(minutes=15)
    return TestClient(create_app(s, db, col, clock)), db, now


def test_zero_dte_isolates_todays_expiry():
    snap = chain_at(30000.0, datetime(2026, 10, 14, 11, 0, tzinfo=ET).astimezone(UTC))
    z = idy.zero_dte(snap.contracts, 30000.0, datetime(2026, 10, 14, 11, 0, tzinfo=ET).astimezone(UTC))
    assert z["available"] and z["is_today"] and z["expiry"] == "2026-10-14"
    assert z["call_wall"] == 30200 and z["put_wall"] == 29800 and 0 < z["gross_share"] < 1
    after = idy.zero_dte(snap.contracts, 30000.0, datetime(2026, 10, 14, 16, 30, tzinfo=ET).astimezone(UTC))
    assert after["expiry"] == "2026-10-16" and not after["is_today"]                    # after the close the next expiry takes over


def test_session_charts_fill_from_the_stored_day():
    c, db, now = simulated_day()
    j = c.get("/api/charts/session", params={"underlying": "_NDX"}).json()
    assert j["day"] == "2026-10-14" and "2026-10-13" in j["days"]
    g = j["gex_map"]
    assert len(g["times"]) == 25 and g["strikes"] and len(g["z"]) == len(g["strikes"]) and len(g["z"][0]) == 25
    assert j["open"]["price"] == 30000.0 and len(j["cone"]) == 41 and j["day_move"]["points"] > 0
    c0, cl = j["cone"][0], j["cone"][-1]
    assert c0["up1"] == c0["dn1"] == 30000.0 and abs((cl["up2"] - 30000) - 2 * (cl["up1"] - 30000)) < 1e-6       # the cone opens from the 9:30 price
    assert len(j["gamma_at_spot"]) == 25 and len(j["flow"]) == 25 and j["flow"][-1]["puts"] > j["flow"][0]["puts"]
    z = c.get("/api/charts/session", params={"underlying": "_NDX", "scope": "0dte"}).json()
    assert z["gex_map"]["times"] and z["scope"] == "0dte"
    prev = c.get("/api/charts/session", params={"underlying": "_NDX", "day": "2026-10-13"}).json()
    assert len(prev["gex_map"]["times"]) == 1 and prev["cone"] == []                      # no 9:30 price that day: no cone


def test_zero_dte_endpoint_and_levels():
    c, db, now = simulated_day()
    j = c.get("/api/analytics/zerodte", params={"underlying": "_NDX"}).json()
    d = j["data"]
    assert d["is_today"] and j["today"]["gex0_call_wall"] and j["today"]["gamma0_at_spot"]
    assert d["call_wall"] == max(d["strikes"], key=lambda s: abs(s["call_gex"]))["strike"]
    lv = c.get("/api/analytics/levels", params={"underlying": "_NDX"}).json()["levels"]
    cats = {l["category"] for l in lv}
    assert {"gex0_call_wall", "gex0_put_wall"} <= cats
    assert any(l["label"] == "0DTE call wall" and l["value"] == d["call_wall"] for l in lv)


def test_preopen_and_scorecard():
    c, db, now = simulated_day()
    p = c.get("/api/charts/preopen", params={"underlying": "_NDX"}).json()
    assert p["gamma_curve"]["all"] and p["gamma_curve"]["zero"] and p["gex_change"]["rows"]
    assert p["oi_change"]["available"] and p["term_structure"] and p["vol_days"]["atm_iv_front"][-1]["day"] == "2026-10-14"
    s = c.get("/api/charts/scorecard", params={"underlying": "_NDX"}).json()
    assert s["regime_days"] and s["regime_days"][0]["date"] == "2026-10-14" and s["regime_days"][0]["label"]
    r = s["regime_days"][0]
    assert r["range"] == r["high"] - r["low"] > 0 and r["range_vs_move"] > 0
    assert "levels" in s and "avg_points_30" in (s["levels"][0] if s["levels"] else {"avg_points_30": None})


def test_written_case_has_both_sides_and_a_plan():
    c, db, now = simulated_day()
    j = c.get("/api/analytics/bias-case", params={"underlying": "_NDX"}).json()
    case = j["case"]
    assert case["lean"] in ("Bullish", "Leans bullish", "Balanced", "Leans bearish", "Bearish")
    assert case["bull"] or case["bear"]
    assert all(p["detail"] and p["title"] for p in case["bull"] + case["bear"] + case["neutral"])
    assert set(case["plan"]) == {"bull", "bear"} and case["plan"]["bull"]["trigger"] and case["summary"]
    assert any("0DTE" in p["title"] for p in case["bull"] + case["bear"] + case["neutral"])


def test_case_rules_point_the_right_way():
    base = {"levels": {"spot": 100.0, "flip": 95.0, "call_wall": 120.0, "put_wall": 97.0, "expected_move": {"low": 98, "high": 102}}, "signals": []}
    up = build_case(base)
    assert up["lean"] in ("Bullish", "Leans bullish") and any("above the gamma flip" in p["title"].lower() for p in up["bull"])
    down = build_case({**base, "levels": {**base["levels"], "flip": 105.0, "call_wall": 102.0, "put_wall": 80.0}},
                      flow={"calls": 100, "puts": 400, "net_change_60m": -50})
    assert down["lean"] in ("Bearish", "Leans bearish") and down["plan"]["bear"]["targets"][0] < 100


def test_journal_records_context_and_stats():
    c, db, now = simulated_day()
    r = c.post("/api/journal", json={"instrument": "NQ", "side": "long", "entry": 30195, "stop": 30170, "setup": "Wall bounce"}).json()
    assert r["saved"] and r["context"]["nearest_level"] and r["context"]["regime"] and r["context"]["time_bucket"] == "14:00-16:00"
    tid = r["id"]
    assert c.patch(f"/api/journal/{tid}", json={"exit": 30215}).json()["saved"]
    c.post("/api/journal", json={"instrument": "NQ", "side": "short", "entry": 30220, "exit": 30230, "setup": "Fade"})
    j = c.get("/api/journal").json()
    assert len(j["trades"]) == 2 and j["stats"]["closed"] == 2 and j["stats"]["total_points"] == 20 - 10
    assert j["stats"]["win_rate"] == 0.5 and {g["key"] for g in j["stats"]["groups"]["Setup"]} == {"Wall bounce", "Fade"}
    assert c.post("/api/journal", json={"side": "sideways", "entry": 1}).status_code == 422
    assert c.delete(f"/api/journal/{tid}").json()["deleted"] and len(c.get("/api/journal").json()["trades"]) == 1


def test_phone_access_settings(tmp_path, monkeypatch):
    from backend import api_more
    monkeypatch.setattr(api_more, "DATA", tmp_path)
    (tmp_path / ".env").write_text("# my settings\nHOST=127.0.0.1\nMASSIVE_API_KEY=abc\n")
    c, db, now = simulated_day()
    j = c.get("/api/phone").json()
    assert j["enabled"] is False and j["password_set"] is False
    assert c.post("/api/phone", json={"enabled": True, "password": "short"}).status_code == 422
    assert c.post("/api/phone", json={"enabled": True, "password": "good-pass-123"}).json()["restart_needed"]
    env = (tmp_path / ".env").read_text()
    assert "HOST=0.0.0.0" in env and "ACCESS_PASSWORD=good-pass-123" in env and "MASSIVE_API_KEY=abc" in env and "# my settings" in env
    c.post("/api/phone", json={"enabled": False})
    assert "HOST=127.0.0.1" in (tmp_path / ".env").read_text()
    assert api_more.qr_svg("http://192.168.1.5:8000").startswith("<?xml") or "<svg" in api_more.qr_svg("http://192.168.1.5:8000")


def test_interval_map_every_measure_over_the_day():
    c, db, now = simulated_day()
    for m in ("gex", "dex", "charm", "vanna", "volume", "oi"):
        for sc in ("all", "0dte"):
            j = c.get("/api/charts/intervalmap", params={"underlying": "_NDX", "measure": m, "scope": sc, "interval": 0}).json()
            assert j["available"], (m, sc, j)
            assert len(j["z"]) == len(j["strikes"]) and all(len(r) == len(j["times"]) for r in j["z"])
            assert j["times"] == sorted(j["times"]) and j["price"]
            assert j["signed"] == (m not in ("volume", "oi"))
    a = c.get("/api/charts/intervalmap", params={"underlying": "_NDX", "measure": "dex", "interval": 0}).json()
    b = c.get("/api/charts/intervalmap", params={"underlying": "_NDX", "measure": "dex", "interval": 30}).json()
    assert a["source"] == "saved" and len(b["times"]) <= len(a["times"])
    assert any(v for r in a["z"] for v in r if v and v < 0) or any(v for r in a["z"] for v in r if v and v > 0)
    assert c.get("/api/charts/intervalmap", params={"underlying": "_NDX", "measure": "nope"}).status_code == 422
