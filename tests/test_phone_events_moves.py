"""Expected-move table, scheduled events, and password-protected phone access. All data is SYNTHETIC TEST DATA."""
import math
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.collector import Collector
from backend.config import Settings
from backend.database import Database
from backend.security import Auth, exposure_problem
from backend.services import analytics as an
from backend.services.events_seed import SEED_EVENTS, seed_events
from tests.conftest import NOW, make_chain
from tests.test_features import Snap, api_client, skewed_chain


# ---- expected-move table -------------------------------------------------------------------------------------
def multi(n=4, iv_step=0.01):
    cons = []
    for i in range(n):
        cons += make_chain(spot=500.0, n_strikes=21, step=5.0, iv=0.20 + iv_step * i, expiry=NOW.date() + timedelta(days=2 + 3 * i))
    return cons


def test_moves_table_formulas_and_order():
    rows = an.moves_table(multi(), 500.0, NOW, 3)
    assert len(rows) == 3 and [r["days"] for r in rows] == sorted(r["days"] for r in rows)
    r0 = rows[0]
    T = r0["days"] / 365.25
    assert r0["sd1"] == pytest.approx(500.0 * r0["atm_iv"] * math.sqrt(T)) and r0["sd2"] == pytest.approx(2 * r0["sd1"])
    assert r0["per_day_sd1"] == pytest.approx(500.0 * r0["atm_iv"] * math.sqrt(1 / 365.25))
    assert r0["straddle"] == pytest.approx(an.expected_move(multi(), 500.0, NOW, r0["expiry"])["straddle"]["price"])
    assert rows[1]["sd1"] > rows[0]["sd1"]                                          # a longer horizon gives a wider move
    assert an.moves_table([], 500.0, NOW) == []


def test_moves_levels_are_zones_up_and_down_for_each_expiry():
    from backend.services.levels import build_levels
    from backend.services.freshness import classify
    snap = Snap(multi())
    lv = build_levels(snap, NOW, "standard", classify(NOW, NOW, "delayed"), moves=2)
    ex = [x for x in lv if x["category"] == "expected_move"]
    ext = [x for x in lv if x["category"] == "expected_move_ext"]
    assert len(ex) == 4 and len(ext) == 4                                                # 2 expiries x (up, down) of each kind
    rows = an.moves_table(snap.contracts, 500.0, NOW, 2)
    assert not any("sigma" in x["label"] or "straddle" in x["label"] for x in lv)       # no more single lines for the straddle or sigma moves
    for r in rows:
        tag = f"{r['expiry'][5:7]}/{r['expiry'][8:10]}"
        up = next(x for x in ex if x["label"] == f"Expected move zone up {tag}")
        dn = next(x for x in ex if x["label"] == f"Expected move zone down {tag}")
        lo_d, hi_d = sorted((r["straddle"], r["sd1"]))
        assert up["low"] == pytest.approx(500.0 + lo_d) and up["high"] == pytest.approx(500.0 + hi_d) and up["value"] == pytest.approx(500.0 + r["sd1"])    # straddle to 1 sigma
        assert dn["high"] == pytest.approx(500.0 - lo_d) and dn["low"] == pytest.approx(500.0 - hi_d) and dn["inputs"]["kind"] == "expected"
        eu = next(x for x in ext if x["label"] == f"Extended move zone up {tag}")
        ed = next(x for x in ext if x["label"] == f"Extended move zone down {tag}")
        assert eu["low"] == pytest.approx(500.0 + r["sd1"]) and eu["high"] == pytest.approx(500.0 + r["sd2"]) and eu["value"] == pytest.approx(500.0 + r["sd2"])   # 1 sigma to 2 sigma
        assert ed["high"] == pytest.approx(500.0 - r["sd1"]) and ed["low"] == pytest.approx(500.0 - r["sd2"]) and ed["inputs"]["kind"] == "extended"
    off = [x for x in build_levels(snap, NOW, "standard", classify(NOW, NOW, "delayed")) if x["category"].startswith("expected_move")]
    assert len(off) == 4 and {x["inputs"]["expiry"] for x in off} == {rows[0]["expiry"]}      # off: only the nearest expiry, as zones
    assert all(x["low"] < x["high"] for x in off)


def test_nearly_equal_estimates_still_get_a_band():
    from backend.services.levels import build_levels
    from backend.services.freshness import classify
    snap = Snap(multi())
    r0 = an.moves_table(snap.contracts, 500.0, NOW, 1)[0]
    orig = an.moves_table
    try:
        an.moves_table = lambda *a, **k: [{**r0, "straddle": r0["sd1"] * 1.001}]                      # the two estimates almost agree
        z = next(x for x in build_levels(snap, NOW, "standard", classify(NOW, NOW, "delayed")) if x["label"].startswith("Expected move zone up"))
    finally:
        an.moves_table = orig
    assert z["high"] - z["low"] == pytest.approx(0.05 * r0["sd1"], rel=0.02)                          # widened to 5% of the distance


def test_moves_endpoint_explains_with_real_numbers_and_flags_events():
    c, db = api_client()
    day = (NOW.date() + timedelta(days=1)).isoformat()
    c.post("/api/events", json={"date": day, "time": "14:00", "name": "FOMC rate decision", "importance": "high"})
    j = c.get("/api/analytics/moves", params={"underlying": "_NDX", "n": 3}).json()
    assert j["rows"] and j["rows"][0]["sd1_levels"]["up"] > 30000 > j["rows"][0]["sd1_levels"]["down"] and j["rows"][0]["sd1_levels"]["up_futures"] is None
    text = " ".join(j["explain"])
    assert f"{j['rows'][0]['sd1']:,.1f}" in text and "68%" in text and "95%" in text and "not forecasts of direction" in text
    assert any(e["name"] == "FOMC rate decision" for e in j["rows"][-1]["events"])        # the event falls before the last expiry
    c.post("/api/basis", json={"root": "NQ", "basis": 250.0})
    j2 = c.get("/api/analytics/moves", params={"underlying": "_NDX", "n": 1}).json()
    assert j2["rows"][0]["sd1_levels"]["up_futures"] == pytest.approx(j2["rows"][0]["sd1_levels"]["up"] + 250.0)
    assert c.get("/api/analytics/moves", params={"underlying": "_NDX", "n": 0}).status_code == 422
    lv = c.get("/api/analytics/levels", params={"underlying": "_NDX", "moves": 2}).json()["levels"]
    assert sum(1 for x in lv if x["category"] in ("expected_move", "expected_move_ext") and "zone" in x["label"] and x["label"].startswith(("Expected", "Extended"))) == 4   # one expiry: 2 kinds x up/down


# ---- events ---------------------------------------------------------------------------------------------------
def test_seed_list_is_wellformed_and_added_once():
    from datetime import datetime
    for d, t, name, imp in SEED_EVENTS:
        datetime.strptime(d, "%Y-%m-%d"); assert (not t) or datetime.strptime(t, "%H:%M"); assert name and imp in ("high", "medium", "low")
    assert any("FOMC" in e[2] for e in SEED_EVENTS) and any("CPI" in e[2] for e in SEED_EVENTS)
    db = Database(":memory:")
    assert seed_events(db) == len(SEED_EVENTS) and seed_events(db) == 0
    first = db.list_events("2000-01-01")[0]
    db.delete_event(first["id"])
    assert seed_events(db) == 0 and len(db.list_events("2000-01-01")) == len(SEED_EVENTS) - 1            # a deleted event does not come back


def test_events_api_crud_validation_and_today_flag():
    c, db = api_client()
    today = (NOW.astimezone(__import__("backend.timeutil", fromlist=["ET"]).ET)).date().isoformat()
    bad = [{"date": "2026-13-45", "name": "x"}, {"date": today, "name": "x", "time": "25:99"}, {"date": today, "name": "", "importance": "high"}, {"date": today, "name": "x", "importance": "huge"}]
    assert all(c.post("/api/events", json=b).status_code == 422 for b in bad)
    r = c.post("/api/events", json={"date": today, "time": "08:30", "name": "CPI inflation", "importance": "high"}).json()
    c.post("/api/events", json={"date": (NOW.date() + timedelta(days=5)).isoformat(), "name": "Later", "importance": "low"})
    c.post("/api/events", json={"date": "2020-01-01", "name": "Old", "importance": "low"})
    j = c.get("/api/events", params={"days": 10}).json()
    assert [e["name"] for e in j["events"]] == ["CPI inflation", "Later"] and j["today"][0]["is_today"] and j["events"][1]["days_away"] == 5      # past events are not listed
    assert c.get("/api/events", params={"days": 2}).json()["events"][0]["name"] == "CPI inflation" and len(c.get("/api/events", params={"days": 2}).json()["events"]) == 1
    assert c.delete(f"/api/events/{r['id']}").json()["deleted"] and c.delete("/api/events/9999").status_code == 404


def test_bias_warns_on_event_days():
    c, db = api_client()
    today = NOW.date().isoformat()
    base = c.get("/api/analytics/bias", params={"underlying": "_NDX"}).json()["data"]
    assert not any(s["name"] == "Scheduled events" for s in base["signals"])
    c.post("/api/events", json={"date": today, "time": "14:00", "name": "FOMC rate decision", "importance": "high"})
    b = c.get("/api/analytics/bias", params={"underlying": "_NDX"}).json()["data"]
    ev = next(s for s in b["signals"] if s["name"] == "Scheduled events")
    assert "FOMC rate decision today 14:00 ET (high)" in ev["reading"] and not ev["scored"] and ev["lean"] == 0
    assert "TODAY" in b["cautions"][0] and b["score"] == base["score"]                    # a warning, never a change to the verdict


# ---- phone access ---------------------------------------------------------------------------------------------
def secured(tmp_path, local_bypass=True, password="correct-horse"):
    s = Settings(provider="cboe", underlyings=("_NDX",), db_path=tmp_path / "a.db", access_password=password, access_local_bypass=local_bypass)
    db = Database(":memory:")
    return s, db, Collector(s, None, db, lambda: NOW)


def test_password_gate_for_other_devices(tmp_path):
    s, db, col = secured(tmp_path)
    app = create_app(s, db, col, lambda: NOW)
    phone = TestClient(app, follow_redirects=False)                                    # the default test client is not "this PC"
    assert phone.get("/api/health").status_code == 200                                  # health reveals nothing
    assert phone.get("/api/status").status_code == 401 and phone.get("/api/status").json()["detail"] == "Sign in required."
    r = phone.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert "Password" in phone.get("/login").text
    wrong = phone.post("/login", data={"password": "nope-nope"})
    assert wrong.status_code == 401 and "Wrong password" in wrong.text and "set-cookie" not in wrong.headers
    ok = phone.post("/login", data={"password": "correct-horse"})
    cookie = ok.headers["set-cookie"].lower()
    assert ok.status_code == 303 and "httponly" in cookie and "samesite=strict" in cookie
    assert phone.get("/api/status").status_code == 200 and "correct-horse" not in phone.get("/api/status").text      # signed in; password never echoed
    phone.get("/logout")
    assert phone.get("/api/status").status_code == 401


def test_this_pc_is_not_asked_unless_bypass_is_off(tmp_path):
    s, db, col = secured(tmp_path)
    pc = TestClient(create_app(s, db, col, lambda: NOW), client=("127.0.0.1", 50000))
    assert pc.get("/api/status").status_code == 200
    s2, db2, col2 = secured(tmp_path, local_bypass=False)
    strict = TestClient(create_app(s2, db2, col2, lambda: NOW), client=("127.0.0.1", 50000), follow_redirects=False)
    assert strict.get("/api/status").status_code == 401


def test_open_app_without_password_is_unchanged(tmp_path):
    s = Settings(provider="cboe", underlyings=("_NDX",))
    db = Database(":memory:")
    assert TestClient(create_app(s, db, Collector(s, None, db, lambda: NOW), lambda: NOW)).get("/api/status").status_code == 200


def test_rate_limit_and_token_safety(tmp_path):
    a = Auth("long-password", tmp_path / "secret", max_fails=3, window=60)
    for _ in range(3):
        assert a.check("bad", "1.2.3.4", now=1000.0) is False
    assert a.blocked("1.2.3.4", now=1010.0) > 0 and a.blocked("5.6.7.8", now=1010.0) == 0 and a.blocked("1.2.3.4", now=1100.0) == 0
    tok = a.token(now=1000.0)
    assert a.valid(tok, now=1001.0) and not a.valid(tok, now=1000.0 + a.ttl + 5)             # expires
    exp, sig = tok.split(".")
    assert not a.valid(f"{int(exp) + 9999}.{sig}") and not a.valid("garbage") and not a.valid("")
    assert Auth("long-password", tmp_path / "secret").valid(tok, now=1001.0)                  # the secret persists, so sessions survive a restart
    assert not Auth("long-password", tmp_path / "other").valid(tok, now=1001.0)


def test_login_is_blocked_after_repeated_failures(tmp_path):
    s, db, col = secured(tmp_path)
    phone = TestClient(create_app(s, db, col, lambda: NOW), follow_redirects=False)
    for _ in range(5):
        assert phone.post("/login", data={"password": "wrong-pass"}).status_code == 401
    locked = phone.post("/login", data={"password": "correct-horse"})
    assert locked.status_code == 429 and "Too many wrong passwords" in locked.text and "set-cookie" not in locked.headers


def test_startup_refuses_open_network_without_a_password():
    assert exposure_problem("0.0.0.0", None) and "ACCESS_PASSWORD" in exposure_problem("0.0.0.0", "")
    assert exposure_problem("127.0.0.1", None) is None and exposure_problem("0.0.0.0", "long-enough-pass") is None
    assert "8 characters" in exposure_problem("127.0.0.1", "short")
    from backend.config import load_sources
    d, src, _ = load_sources({"ACCESS_PASSWORD": "  secret-word  ", "HOST": "0.0.0.0"})
    assert src[d].access_password == "secret-word" and src[d].host == "0.0.0.0" and src[d].access_local_bypass is True
    assert load_sources({"ACCESS_LOCAL_BYPASS": "0"})[1]["cboe"].access_local_bypass is False
    assert "secret-word" not in repr(src[d])
