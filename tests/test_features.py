"""Bias, scenarios, Pine export, reaction log, level history, autostart scripts. All data is SYNTHETIC TEST DATA."""
import re
from datetime import datetime, timedelta

import pytest

from backend.collector import Collector
from backend.config import Settings
from backend.database import Database
from backend.services import analytics as an
from backend.services import reactions as rx
from backend.services.bias import compute_bias
from backend.services.freshness import classify
from backend.timeutil import UTC
from tests.conftest import NOW, make_chain
from backend.config import ROOT


def skewed_chain(spot=500.0):
    """Calls dominate above spot, puts below, with a put skew in IV."""
    cons = make_chain(spot=spot, n_strikes=41, step=2.5, iv=0.20)
    for c in cons:
        c.oi = 5000.0 if (c.right == "C") == (c.strike >= spot) else 300.0
        c.volume = 400.0 if c.right == "P" else 200.0
        c.iv = 0.20 + (0.06 if c.right == "P" else 0.0)
    return cons


class Snap:
    def __init__(self, cons, spot=500.0):
        self.contracts, self.spot, self.underlying, self.provider, self.snapshot_id = cons, spot, "QQQ", "test", 1
        self.spot_ts = self.source_ts = self.retrieved_at = NOW


# ---- walls, skew, scenarios ---------------------------------------------------------------------------
def test_walls_use_open_interest_then_fall_back_to_volume():
    cons = skewed_chain()
    big_call = next(c for c in cons if c.right == "C" and c.strike == 515.0); big_call.oi = 20000.0
    big_put = next(c for c in cons if c.right == "P" and c.strike == 485.0); big_put.oi = 20000.0
    w = an.walls(cons, 500.0, NOW)
    assert (w["call_wall"], w["put_wall"], w["basis"]) == (515.0, 485.0, "open interest")
    for c in cons: c.oi = 0.0
    nxt = next(c for c in cons if c.right == "C" and c.strike == 520.0); nxt.volume = 9999.0
    w2 = an.walls(cons, 500.0, NOW)
    assert w2["basis"] == "volume" and w2["call_wall"] == 520.0


def test_skew_25d_measures_put_minus_call_iv():
    sk = an.skew_25d(skewed_chain(), 500.0, NOW)
    assert sk is not None and sk["value"] == pytest.approx(6.0, abs=0.01) and "25 delta" in sk["method"]
    assert an.skew_25d([], 500.0, NOW) is None


def test_scenarios_sign_does_not_move_the_flip_but_weighting_can():
    cons = skewed_chain()
    f_std = an.gamma_flip(cons, 500.0, NOW, "standard")
    f_rev = an.gamma_flip(cons, 500.0, NOW, "customers_long")
    assert f_std["found"] and f_rev["found"] and f_std["flip"] == pytest.approx(f_rev["flip"])      # mirrored curve, same zero crossing
    for c in cons:                                                  # today's trading is centred higher than the open interest
        c.volume = 5000.0 if (c.right == "C") == (c.strike >= 515.0) else 300.0
    s = an.scenarios(cons, 500.0, NOW)
    assert [r["weight"] for r in s["rows"]] == ["oi", "volume"] and "ABOVE" in s["sign_note"]
    assert s["rows"][0]["found"] and s["rows"][1]["found"] and s["flip_spread"] > 10               # weighting does move the level
    assert an.gamma_flip(cons, 500.0, NOW, weight="volume")["weight"] == "volume"


# ---- bias ----------------------------------------------------------------------------------------------
def test_bias_structure_confidence_and_honest_labels():
    snap = Snap(skewed_chain())
    b = compute_bias(snap, NOW, classify(NOW, NOW, "delayed"), prev_skew=4.0)
    assert b["verdict"] in ("Leans bullish", "Leans bearish", "Mixed, no clear edge") and b["score"] == sum(s["lean"] for s in b["signals"] if s["scored"])
    assert not any(s["scored"] for s in b["signals"] if s["name"].startswith("Day type")) and b["day_type"]["label"] != "Unknown"
    assert b["confidence"]["label"] in ("Low", "Medium", "High") and b["confidence"]["of"] == 5
    assert b["what_would_change"] and any("not a trade signal" in c for c in b["cautions"])
    skew_sig = next(s for s in b["signals"] if s["name"].startswith("Skew"))
    assert skew_sig["lean"] == -1                                   # skew rose from 4 to 6 vs the previous session: leans bearish


def test_bias_thin_data_is_low_confidence_and_says_so():
    snap = Snap(make_chain(n_strikes=3))
    for c in snap.contracts: c.oi = c.volume = None
    b = compute_bias(snap, NOW, classify(NOW, NOW, "delayed"))
    assert b["confidence"]["label"] == "Low" and b["verdict"] == "Mixed, no clear edge" and any("Open interest reads zero" in c for c in b["cautions"])


# ---- Pine export ---------------------------------------------------------------------------------------




# ---- reaction log --------------------------------------------------------------------------------------
def series(points, start=NOW, step=2):
    return [(start + timedelta(minutes=step * i), p) for i, p in enumerate(points)]


def test_reaction_detects_touch_and_held_vs_broke():
    # price rises toward 100.0 from below, touches it, then falls back: held (still below) at 15 and 30 minutes
    px = series([98.0, 98.5, 99.0, 99.6, 100.0] + [99.5] * 8 + [99.0] * 8)
    t = rx.analyze([{"label": "Call wall", "category": "open_interest", "value": 100.0}], px)
    assert len(t) == 1 and t[0]["approach"] == "from below" and t[0]["held_15"] is True and t[0]["held_30"] is True
    assert t[0]["max_above"] == pytest.approx(0.0) and t[0]["max_below"] > 0
    # price rises through the level and stays above: broke
    px2 = series([98.0, 99.0, 99.8, 100.4] + [101.0] * 20)
    t2 = rx.analyze([{"label": "Call wall", "category": "open_interest", "value": 100.0}], px2)
    assert t2[0]["held_15"] is False and t2[0]["move_15"] == pytest.approx(1.0)


def test_reaction_cooldown_and_summary_and_no_touch():
    px = series([99.0, 100.0, 99.0, 100.0, 99.0, 100.0] + [99.0] * 20)
    t = rx.analyze([{"label": "L", "category": "volume", "value": 100.0}], px)
    assert len(t) == 1                                                  # repeated wiggles inside the cooldown count once
    assert rx.analyze([{"label": "L", "category": "volume", "value": 150.0}], px) == []
    s = rx.summarize(t)
    assert s[0]["category"] == "volume" and s[0]["touches"] == 1 and s[0]["enough_data"] is False


# ---- collector stores the extra history and the levels of the day ---------------------------------------
def test_collector_captures_levels_once_per_session_and_extra_metrics():
    from tests.test_database_collector import FakeProvider
    from backend.models import ChainSnapshot
    from backend.providers.massive import content_hash
    s = Settings(api_key="k", underlyings=("QQQ",))
    db, p = Database(":memory:"), FakeProvider()
    col = Collector(s, p, db, lambda: NOW)
    mk = lambda shift: ChainSnapshot("fake", "QQQ", NOW, 500.0, NOW, [setattr(c, "bid", c.bid + shift) or c for c in skewed_chain()], str(shift))
    p.queue = [mk(0.0), mk(0.5)]
    assert col.run_once("QQQ") and col.run_once("QQQ")
    day = "2026-10-14"
    lv = db.load_session_levels("QQQ", day)
    assert lv and db.list_session_dates("QQQ") == [day]
    first_ids = {r["value"] for r in lv}
    assert len(db.load_session_levels("QQQ", day)) == len(lv)           # the second new snapshot did not add a second set
    for name in ("skew_25d", "call_wall", "put_wall", "total_net_gex"):
        assert db.metric_history("QQQ", name), name


# ---- API ----------------------------------------------------------------------------------------------

def ind_default(ind, cat):
    """The TradingView indicator gives every level type a color SETTING. Returns (family, default color) for one type."""
    import re
    fam = re.search(r'"%s" => "(\w+)"' % cat, ind.split("famOf(string cat)")[1].split("colorFor(")[0]).group(1)
    var = re.search(r'"%s" => (\w+)' % cat, ind.split("colorFor(string cat)")[1].split("showFor(")[0]).group(1)
    return fam, re.search(r"^%s\s*= input\.color\((#[0-9a-f]{6})" % var, ind, re.M).group(1)

def api_client(with_levels=True, mutate=None):
    from fastapi.testclient import TestClient
    from backend.api import create_app
    from backend.models import ChainSnapshot
    from backend.providers.massive import content_hash
    s = Settings(provider="cboe", underlyings=("_NDX",))
    db = Database(":memory:")
    col = Collector(s, None, db, lambda: NOW)
    cons = skewed_chain(30000.0)
    for c in cons:                                                     # rescale the synthetic 500-based chain to NDX-like prices
        c.strike = c.strike * 60.0
    if mutate:
        mutate(cons)
    snap = ChainSnapshot("cboe", "_NDX", NOW, 30000.0, NOW, cons, content_hash(cons)); snap.snapshot_id = 1
    col.state["_NDX"]["snapshot"] = snap
    return TestClient(create_app(s, db, col, lambda: NOW)), db




def test_levels_history_and_reactions_endpoints():
    c, db = api_client()
    day = "2026-10-14"
    db.save_session_levels("_NDX", day, [{"category": "open_interest", "label": "High call open interest", "value": 30100.0, "method": "t"}], 1, NOW)
    for i, px in enumerate([29950.0, 30040.0, 30095.0, 30101.0, 30090.0] + [30060.0] * 20):
        t = NOW - timedelta(hours=1) + timedelta(minutes=2 * i)
        db.save_price("_NDX", px, "t", t, t)
    db.save_metric(1, "_NDX", "gamma_flip", 30010.0, None, NOW)
    h = c.get("/api/history/levels", params={"underlying": "_NDX"}).json()
    assert h["date"] == day and len(h["price"]) >= 20 and h["levels"]["gamma_flip"][0]["value"] == 30010.0
    r = c.get("/api/analytics/reactions", params={"underlying": "_NDX"}).json()
    assert r["total_touches"] == 1 and r["sessions"][0]["touches"][0]["approach"] == "from below" and r["summary"][0]["category"] == "open_interest"
    assert r["summary"][0]["enough_data"] is False and "Descriptive only" in r["note"]


# ---- autostart scripts ----------------------------------------------------------------------------------
def test_autostart_scripts_are_present_and_consistent():
    task = "NQ-ES Options Analytics"
    ins, rem = (ROOT / "install_autostart.bat").read_text(), (ROOT / "remove_autostart.bat").read_text()
    assert task in ins and task in rem and "schtasks /Create" in ins and "/SC ONLOGON" in ins and "start_hidden.vbs" in ins and "schtasks /Delete" in rem
    assert "--no-browser" in (ROOT / "run_background.bat").read_text() and "run_background.bat" in (ROOT / "start_hidden.vbs").read_text()
    assert "--no-browser" in (ROOT / "backend" / "main.py").read_text()




# ---- levels remember when they first appeared ------------------------------------------------------------
def test_level_runs_keep_first_seen_while_a_level_persists():
    db = Database(":memory:")
    t0 = NOW
    lv = lambda flip, wall: [{"category": "gamma_flip", "label": "Estimated gamma flip", "value": flip}, {"category": "open_interest", "label": "High call open interest", "value": wall}]
    db.update_level_runs("U", "2026-10-14", lv(30000.0, 31200.0), t0)
    db.update_level_runs("U", "2026-10-14", lv(30004.0, 31200.0), t0 + timedelta(minutes=20))       # flip drifts a little, wall unchanged
    runs = {r["label"]: r for r in db.active_level_runs("U", "2026-10-14")}
    assert runs["Estimated gamma flip"]["first_seen"] == runs["High call open interest"]["first_seen"] == t0.isoformat()
    assert runs["Estimated gamma flip"]["value"] == 30004.0 and runs["High call open interest"]["last_seen"] == (t0 + timedelta(minutes=20)).isoformat()
    db.update_level_runs("U", "2026-10-14", lv(30400.0, 31200.0), t0 + timedelta(minutes=40))       # flip jumps far: a new run starts, the old one ends
    runs = {r["label"]: r for r in db.active_level_runs("U", "2026-10-14")}
    assert runs["Estimated gamma flip"]["first_seen"] == (t0 + timedelta(minutes=40)).isoformat()
    assert runs["High call open interest"]["first_seen"] == t0.isoformat()                          # the wall is still the original run
    db.update_level_runs("U", "2026-10-14", [lv(0, 0)[1]], t0 + timedelta(minutes=60))              # the flip disappears
    assert [r["label"] for r in db.active_level_runs("U", "2026-10-14")] == ["High call open interest"]
    assert db.active_level_runs("U", "2026-10-15") == []                                            # a new session starts fresh






# ---- levels that were missing: top-N, call/put GEX strikes, expirations, typed-in levels -----------------
def test_levels_keep_top_n_and_show_gex_wall_zones():
    from backend.services.levels import build_levels
    cons = skewed_chain()
    # a strike with huge call AND put gamma nets to almost nothing, so only the wall zones (which do not net) can show it
    for c in cons:
        if c.strike == 497.5: c.oi = 90000.0
    snap = Snap(cons)
    fr = classify(NOW, NOW, "delayed")
    two = build_levels(snap, NOW, "standard", fr, top=2)
    zones = [x for x in two if x["category"] in ("gex_call_zone", "gex_put_zone")]
    assert zones and any(x["low"] <= 497.5 <= x["high"] for x in zones) and all(x["inputs"]["members"] and x["low"] < x["value"] < x["high"] for x in zones)
    five = build_levels(snap, NOW, "standard", fr, top=5)
    assert len(five) > len(two) and sum(1 for x in five if x["label"] == "Large positive modeled GEX") <= 5
    assert sum(1 for x in two if x["label"] == "High call open interest") <= 2 and sum(1 for x in five if x["label"] == "High call open interest") <= 5


def test_levels_can_be_limited_to_chosen_expirations():
    from backend.services.levels import build_levels
    cons = make_chain(spot=500.0, n_strikes=21, step=5.0, expiry=NOW.date() + timedelta(days=2)) + make_chain(spot=500.0, n_strikes=21, step=2.5, iv=0.3, expiry=NOW.date() + timedelta(days=9))
    for c in cons: c.oi, c.volume = 1000.0, 100.0
    snap = Snap(cons)
    fr = classify(NOW, NOW, "delayed")
    only = build_levels(snap, NOW, "standard", fr, expirations=[(NOW.date() + timedelta(days=9)).isoformat()])
    allv = build_levels(snap, NOW, "standard", fr)
    assert only != allv and all(float(x["value"]) % 2.5 == 0 for x in only if x["category"] == "open_interest")




def test_top_parameter_is_validated():
    c, db = api_client()
    assert c.get("/api/analytics/levels", params={"underlying": "_NDX", "top": 0}).status_code == 422
    assert c.get("/api/analytics/levels", params={"underlying": "_NDX", "top": 11}).status_code == 422
    a = len(c.get("/api/analytics/levels", params={"underlying": "_NDX", "top": 2}).json()["levels"])
    b = len(c.get("/api/analytics/levels", params={"underlying": "_NDX", "top": 8}).json()["levels"])
    assert b > a


# ---- open interest and volume strikes for each expiry on its own -------------------------------------------
def test_levels_by_expiry_are_zones_from_each_expirys_own_profile():
    from backend.services.levels import build_levels
    e1, e2, e3 = (NOW.date() + timedelta(days=d) for d in (2, 5, 9))
    cons = []
    for e in (e1, e2, e3):
        cons += make_chain(spot=500.0, n_strikes=21, step=5.0, expiry=e)
    for c in cons: c.oi, c.volume = 100.0, 10.0
    pick = lambda e, right, strike, **kw: [setattr(c, k, v) for c in cons if c.expiry == e and c.right == right and c.strike == strike for k, v in kw.items()]
    pick(e1, "C", 510.0, oi=9000.0); pick(e1, "P", 485.0, oi=8000.0); pick(e1, "C", 505.0, volume=700.0); pick(e1, "P", 495.0, volume=800.0)
    pick(e2, "C", 520.0, oi=9500.0); pick(e2, "C", 515.0, volume=900.0)
    lv = build_levels(Snap(cons), NOW, "standard", classify(NOW, NOW, "delayed"), top=2, per_expiry=2)
    by = {x["label"]: x for x in lv if x["category"] in ("oi_by_expiry", "volume_by_expiry")}
    t1, t2 = f"{e1:%m/%d}", f"{e2:%m/%d}"
    assert by[f"Call OI zone {t1}"]["value"] == 510.0 and by[f"Put OI zone {t1}"]["value"] == 485.0 and by[f"Call OI zone {t2}"]["value"] == 520.0
    assert by[f"Call volume zone {t1}"]["value"] == 505.0 and by[f"Put volume zone {t1}"]["value"] == 495.0 and by[f"Call volume zone {t2}"]["value"] == 515.0
    z = by[f"Call OI zone {t1}"]
    assert z["low"] < 510.0 < z["high"] and z["inputs"]["expiry"] == e1.isoformat() and z["inputs"]["zone_mag"] == 9000.0
    assert not any(f"{e3:%m/%d}" in k for k in by)                                                                    # only the 2 nearest expiries
    assert not [x for x in build_levels(Snap(cons), NOW, "standard", classify(NOW, NOW, "delayed")) if x["category"].endswith("_by_expiry")]   # off by default




# ---- mid-size levels: meaningful but not the biggest ----------------------------------------------------------
def test_series_zones_and_tiers():
    from backend.services.levels import tiered
    grid = [100 + 5 * i for i in range(60)]
    prof = {120: 10000, 125: 400, 175: 8000, 220: 5000, 225: 300, 260: 3000, 300: 1000}        # a top, a too-big second, two mid-size, and a small one
    rows = [{"strike": k, "call": float(prof.get(k, 20)), "put": 5.0} for k in grid]
    zs = an.series_zones(rows, grid, 200.0)
    calls = [z for z in zs if z["side"] == "call"]
    assert [z["center"] for z in calls] == [120, 175, 220, 260]                      # 300 (1000) is under 30% of the peak, so it is not a zone at all
    main, mids = tiered(zs, "call", 1, 2, 300)
    assert [z["center"] for z in main] == [120] and [z["center"] for z in mids] == [220, 260]      # 175 is 80% of the top: neither main nor mid
    assert [z["center"] for z in tiered(zs, "call", 1, 1, 300)[1]] == [220]
    assert [z["center"] for z in tiered(zs, "call", 1, 2, 4000)[1]] == [220]                      # the absolute floor drops the 3000 zone
    assert tiered(zs, "put", 1, 2, 300) == ([], [])                                                 # no put-side zones in this profile
    assert all(0.25 * main[0]["magnitude"] <= z["magnitude"] <= 0.70 * main[0]["magnitude"] for z in mids)


def test_mid_zones_in_build_levels_combined_and_per_expiry():
    from backend.services.levels import build_levels
    e1 = NOW.date() + timedelta(days=2)
    cons = make_chain(spot=500.0, n_strikes=41, step=5.0, expiry=e1)
    for c in cons: c.oi, c.volume = 100.0, 5.0
    prof = {510.0: 10000.0, 540.0: 5000.0, 470.0: 3000.0}
    for c in cons:
        if c.right == "C" and c.strike in prof: c.oi = prof[c.strike]
        if c.strike == 515.0: c.volume = 1000.0
        if c.strike == 480.0: c.volume = 400.0
        if c.strike == 505.0: c.volume = 120.0
    snap, fr = Snap(cons), classify(NOW, NOW, "delayed")
    base = build_levels(snap, NOW, "standard", fr, top=1)
    assert not [x for x in base if x["category"].endswith("_mid")]                              # off by default
    assert next(x for x in base if x["label"] == "Call OI zone")["value"] == 510.0 and next(x for x in base if x["label"] == "Call volume zone")["value"] == 515.0
    lv = build_levels(snap, NOW, "standard", fr, top=1, mid=2, per_expiry=1)
    mids = [x for x in lv if x["category"].endswith("_mid")]
    assert sorted(x["value"] for x in mids if x["label"] == "Call OI zone mid") == [470.0, 540.0] and all("25%" in x["method"] and x["low"] < x["value"] < x["high"] for x in mids)
    assert any(x["label"] == "Call volume zone mid" and x["value"] == 480.0 for x in mids)          # 400 of 1000 is mid-size; 120 is too small to be a zone
    assert not any(x["label"] == "Call volume zone mid" and x["value"] == 505.0 for x in mids)
    assert any(x["label"].endswith(f"{e1:%m/%d} mid") and x["inputs"].get("expiry") == e1.isoformat() for x in mids)           # per-expiry mid zones exist too




# ---- importance ranking and zones ----------------------------------------------------------------------------
def lvl(cat, label, value, first_seen=None, **inputs):
    return {"category": cat, "label": label, "value": value, "inputs": inputs, "first_seen": first_seen, "instrument": "X", "source_timestamp": None,
            "data_status": "delayed", "provider": "t", "reliability": "high"}


def test_importance_size_closeness_and_type():
    from backend.services.importance import score_levels
    lv = [lvl("open_interest", "High call open interest", 30100.0, call_oi=9000.0), lvl("open_interest", "High call open interest", 30150.0, call_oi=3000.0),
          lvl("open_interest", "High call open interest", 32000.0, call_oi=9000.0), lvl("gamma_flip", "Estimated gamma flip", 29990.0),
          lvl("volume", "High session volume", 30100.0, call=1000.0, put=800.0), lvl("oi_mid", "Mid call open interest", 30120.0, call_oi=4000.0)]
    score_levels(lv, 30000.0, 300.0)
    big, small, far, flip, vol, mid = (x["importance"] for x in lv)
    assert big > small and big > far                       # bigger beats smaller; the same size far from price scores lower
    assert far == pytest.approx(0.85 * 1.0 * 0.35, abs=1e-6)  # beyond two expected moves it keeps 35% of its value
    assert flip > big and vol < big and mid < big            # flip beats others; mid-size and volume carry lower type weights
    assert all(0 <= x["importance"] <= 1 for x in lv)


def test_nearby_levels_stay_separate_lines_and_same_price_levels_share_one():
    from backend.services.importance import make_zones, score_levels
    lv = [lvl("open_interest", "High call open interest", 30010.0, "2026-10-14T14:00:00+00:00", call_oi=8000.0),
          lvl("volume", "High session volume", 30030.0, "2026-10-14T13:30:00+00:00", call=900.0, put=700.0),
          lvl("gex_concentration", "Large positive modeled GEX", 30020.0, "2026-10-14T15:00:00+00:00", net_gex=5e9),
          lvl("open_interest", "High put open interest", 29500.0, "2026-10-14T12:00:00+00:00", put_oi=8000.0),
          lvl("volume", "High session volume", 29500.0, "2026-10-14T12:30:00+00:00", call=100.0, put=900.0)]
    score_levels(lv, 30000.0, 400.0)
    zones = make_zones(lv, 30000.0, top_n=10)
    assert [z["value"] for z in zones] == [30030.0, 30020.0, 30010.0, 29500.0]                        # 10 points apart: still three lines
    assert all(len(z["inputs"]["members"]) == 1 for z in zones if z["value"] > 30000)
    same = next(z for z in zones if z["value"] == 29500.0)
    assert len(same["inputs"]["members"]) == 2 and " / " in same["label"] and same["importance"] > max(m["importance"] for m in same["inputs"]["members"])
    assert make_zones([], 30000.0) == []




# ---- GEX wall zones --------------------------------------------------------------------------------------------
def gstrikes(rows):
    return [{"strike": k, "call_gex": c, "put_gex": p, "net_gex": c + p} for k, c, p in rows]


def test_call_put_call_neighbours_become_one_call_wall_zone():
    rows = [(30050, 10, -10), (30075, 12, -8), (30100, 900, -50), (30125, 60, -700), (30150, 800, -40), (30175, 15, -12), (30200, 10, -5),
            (30500, 20, -900), (30525, 10, -800), (30550, 5, -30)]
    zs = an.gex_wall_zones(gstrikes(rows), 30100.0, top=2)
    call = [z for z in zs if z["side"] == "call"]
    put = [z for z in zs if z["side"] == "put"]
    assert len(call) == 1 and len(put) == 1
    c = call[0]
    assert (c["call_strikes"], c["put_strikes"]) == (2, 1) and c["center"] == 30100 and c["low"] == 30087.5 and c["high"] == 30162.5     # call, put, call: call wins, band spans all three
    assert [m["strike"] for m in c["members"]] == [30100, 30125, 30150] and c["magnitude"] == pytest.approx(1700)
    assert put[0]["low"] == 30487.5 and put[0]["high"] == 30537.5 and put[0]["put_strikes"] == 2          # a separate wall far away is its own zone


def test_zone_size_ties_gaps_and_thresholds():
    # the same neighbours with ONE call and ONE put: a tie on count goes to the bigger total
    tie = an.gex_wall_zones(gstrikes([(100, 900, -10), (125, 10, -950), (150, 5, -5)]), 100.0)
    put = next(z for z in tie if z["side"] == "put")
    assert put["put_strikes"] == 1 and put["call_strikes"] == 0 and put["center"] == 125              # the put wins the tie, and the call at the edge is its OWN zone
    assert any(z["side"] == "call" and z["center"] == 100 for z in tie)
    # a wall strike more than two strike gaps away is NOT part of the zone
    far = an.gex_wall_zones(gstrikes([(100, 900, 0), (125, 5, 0), (150, 5, 0), (175, 5, 0), (200, 800, 0)]), 100.0, top=2)
    assert len(far) == 2 and all(z["low"] < z["high"] for z in far) and far[0]["center"] == 100 and far[1]["center"] == 200
    # a lone wall still gets thickness (half a strike gap each side) and small strikes below 30% of the peak are ignored
    one = an.gex_wall_zones(gstrikes([(100, 1000, 0), (125, 200, 0), (150, 100, 0)]), 100.0)
    assert len(one) == 1 and (one[0]["low"], one[0]["high"]) == (87.5, 112.5) and len(one[0]["members"]) == 1
    assert an.gex_wall_zones([], 100.0) == [] and an.gex_wall_zones(gstrikes([(100, 0, 0)]), 100.0) == []




def test_lines_inside_a_gex_band_are_still_drawn():
    from backend.services.importance import make_zones, score_levels
    band = lvl("gex_call_zone", "Call wall zone", 30100.0, call_strikes=2) | {"low": 30087.5, "high": 30162.5, "method": "m"}
    band["inputs"] = {"zone_mag": 1700.0, "call_strikes": 2, "put_strikes": 1, "members": [{"strike": 30100, "side": "call", "gex": 900}, {"strike": 30125, "side": "put", "gex": 700}]}
    inner = lvl("open_interest", "High call open interest", 30125.0, call_oi=5000.0)
    outer = lvl("open_interest", "High put open interest", 29500.0, put_oi=5000.0)
    lv = [band, inner, outer]
    score_levels(lv, 30000.0, 400.0)
    zs = make_zones(lv, 30000.0, top_n=10)
    assert len(zs) == 3 and any(z["value"] == 30125.0 and z.get("low") is None for z in zs)
    b = next(z for z in zs if z.get("band"))
    assert b["low"] == 30087.5 and not any(m["label"] == "High call open interest" for m in b["inputs"]["members"])


def test_zone_width_is_capped_when_every_strike_is_a_wall():
    spot = 30000.0
    rows = [(30000 + 25 * k, 800 + (k * 37) % 150, -(30 + k % 7)) for k in range(-40, 41)]            # 81 strikes, all big call gamma
    zs = an.gex_wall_zones(gstrikes(rows), spot, top=3)
    assert len(zs) == 3 and all(z["side"] == "call" for z in zs)
    for z in zs:
        assert z["high"] - z["low"] <= 2 * 0.003 * spot + 25 and z["low"] < z["center"] < z["high"]         # never wider than about 0.6% of price
    assert zs[0]["magnitude"] >= zs[1]["magnitude"] >= zs[2]["magnitude"]
    spans = sorted((z["low"], z["high"]) for z in zs)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))                                          # the zones do not overlap


def test_zones_follow_the_strike_grid_not_a_fixed_price_gap():
    # near the money strikes are 5 apart, far out 25 apart: neighbours are neighbours on either grid
    near = [(30000 + 5 * k, 700 + (k % 3) * 10, -20) for k in range(-6, 7)]
    far = [(30300, 900, -30), (30325, 20, -800), (30350, 880, -30), (30375, 10, -10), (30400, 5, -5)]
    zs = an.gex_wall_zones(gstrikes(near + far), 30000.0, top=3)
    big = max(zs, key=lambda z: z["magnitude"])
    calls = [z for z in zs if z["side"] == "call"]
    assert any(z["call_strikes"] == 2 and z["put_strikes"] == 1 and z["low"] < 30300 < 30350 < z["high"] for z in calls)      # call, put, call on the 25 grid is ONE zone
    assert all(z["low"] < z["center"] < z["high"] for z in zs) and big["side"] == "call"
    nz = [z for z in calls if z["center"] < 30100]
    assert nz and all(z["high"] - z["low"] <= 2 * 0.003 * 30000 + 5 for z in nz)                                           # the 5-wide grid keeps its band tight


# ---- positive / negative GEX zones and the multi-symbol overview ------------------------------------------------
def test_positive_and_negative_net_gex_zones():
    rows = [(100, 400, -20), (125, 500, -60), (150, 450, -30), (175, 30, -20), (200, 20, -480), (225, 10, -450), (250, 15, -420), (275, 5, -10)]
    zs = an.gex_net_zones(gstrikes(rows), 200.0, top=2)
    pos = [z for z in zs if z["side"] == "positive"]
    neg = [z for z in zs if z["side"] == "negative"]
    assert len(pos) == 1 and len(neg) == 1
    assert (pos[0]["low"], pos[0]["high"], pos[0]["center"], pos[0]["pos_strikes"], pos[0]["neg_strikes"]) == (87.5, 162.5, 125, 3, 0)
    assert (neg[0]["low"], neg[0]["high"], neg[0]["neg_strikes"]) == (187.5, 262.5, 3) and neg[0]["center"] == 200
    # a negative strike sandwiched between two positive ones is absorbed by the majority
    mix = an.gex_net_zones(gstrikes([(100, 500, -10), (125, 10, -480), (150, 520, -20)]), 125.0)
    assert len(mix) == 1 and mix[0]["side"] == "positive" and (mix[0]["pos_strikes"], mix[0]["neg_strikes"]) == (2, 1)
    assert an.gex_net_zones([], 100.0) == []




def two_symbol_client(q_mutate=None, stale_q=False):
    from fastapi.testclient import TestClient
    from backend.api import create_app
    from backend.models import ChainSnapshot
    from backend.providers.massive import content_hash
    s = Settings(provider="cboe", underlyings=("_NDX", "QQQ", "_SPX", "SPY"))
    db = Database(":memory:")
    col = Collector(s, None, db, lambda: NOW)
    for u, scale, bearish in (("_NDX", 60.0, False), ("QQQ", 1.0, False), ("_SPX", 12.0, True)):
        cons = skewed_chain(500.0 * scale)
        for c in cons:
            c.strike = c.strike * scale
        if bearish:
            for c in cons:                                                     # lots of put volume and put open interest below price
                if c.right == "P": c.volume, c.oi = c.volume * 6, c.oi * 6
        if u == "QQQ" and q_mutate:
            q_mutate(cons)
        t = NOW - timedelta(days=3) if (u == "QQQ" and stale_q) else NOW
        for c in cons:
            c.quote_ts = t
        snap = ChainSnapshot("cboe", u, t, 500.0 * scale, t, cons, content_hash(cons)); snap.snapshot_id = 1
        col.state[u]["snapshot"] = snap
    return TestClient(create_app(s, db, col, lambda: NOW)), db                  # SPY deliberately has no data yet


def test_market_overview_rows_groups_and_agreement():
    c, db = two_symbol_client()
    c.post("/api/basis", json={"root": "NQ", "basis": 250.0})
    j = c.get("/api/analytics/bias-overview").json()
    by = {r["underlying"]: r for r in j["rows"]}
    assert set(by) == {"_NDX", "QQQ", "_SPX", "SPY"} and not by["SPY"]["available"] and "reason" in by["SPY"]          # no data yet is reported, not hidden
    assert by["_NDX"]["futures_root"] == "NQ" and by["_NDX"]["futures_offset"] == 250.0 and by["QQQ"]["futures_offset"] is None and by["_SPX"]["futures_root"] == "ES"
    for u in ("_NDX", "QQQ", "_SPX"):
        r = by[u]
        assert r["available"] and r["verdict"] in ("Leans bullish", "Leans bearish", "Mixed, no clear edge") and set(r["zones"]) >= {"call", "put", "positive", "negative", "oi_call", "oi_put", "volume_call", "volume_put"}
    single = c.get("/api/analytics/bias", params={"underlying": "_NDX"}).json()["data"]
    assert by["_NDX"]["verdict"] == single["verdict"] and by["_NDX"]["score"] == single["score"]                    # the overview never disagrees with the single-symbol tab
    assert {g["group"] for g in j["groups"]} == {"Nasdaq 100", "S&P 500"}
    nas = next(g for g in j["groups"] if g["group"] == "Nasdaq 100")
    assert nas["symbols"] == ["_NDX", "QQQ"] and nas["state"] in ("aligned", "disagree")
    spx = next(g for g in j["groups"] if g["group"] == "S&P 500")
    assert spx["state"] == "single" and "SPY" not in spx["symbols"]
    t = j["tally"]
    assert t["bullish"] + t["bearish"] + t["mixed"] == 3 and "3 symbols" in j["summary"] and "not independent confirmation" in j["note"]
    assert c.get("/api/analytics/bias-overview", params={"convention": "nope"}).status_code == 422


def test_overview_disagreement_and_stale_symbols_are_handled():
    def flat(cons):                                                        # make QQQ read opposite to NDX: lots of put activity
        for k in cons:
            if k.right == "P": k.volume, k.oi = k.volume * 8, k.oi * 8
    c, db = two_symbol_client(q_mutate=flat)
    j = c.get("/api/analytics/bias-overview").json()
    nas = next(g for g in j["groups"] if g["group"] == "Nasdaq 100")
    leans = {r["underlying"]: r["lean"] for r in j["rows"] if r.get("available")}
    if leans["_NDX"] != leans["QQQ"]:
        assert nas["state"] == "disagree" and nas["lean"] is None and "disagree" in nas["text"]
    c2, _ = two_symbol_client(stale_q=True)
    j2 = c2.get("/api/analytics/bias-overview").json()
    q = next(r for r in j2["rows"] if r["underlying"] == "QQQ")
    assert q["available"] and not q["usable"] and q["data_status"] in ("stale", "closed_last_session")
    if not q["usable"]:
        nas2 = next(g for g in j2["groups"] if g["group"] == "Nasdaq 100")
        assert nas2["symbols"] == ["_NDX"] and nas2["state"] == "single"            # stale symbols stay out of the agreement checks


def test_zones_start_and_end_on_their_own_side():
    # call, call, then a big put right at the edge: the put is not swallowed into the call zone, it forms its own
    zs = an.gex_wall_zones(gstrikes([(100, 800, -10), (125, 700, -10), (150, 20, -900), (175, 5, -5)]), 100.0, top=2)
    call = next(z for z in zs if z["side"] == "call")
    put = next(z for z in zs if z["side"] == "put")
    assert [m["strike"] for m in call["members"]] == [100, 125] and [m["strike"] for m in put["members"]] == [150] and call["high"] <= put["low"]
    # but a put SANDWICHED between calls is still absorbed (the rule you asked for)
    sand = an.gex_wall_zones(gstrikes([(100, 800, -10), (125, 20, -700), (150, 750, -10)]), 100.0)
    assert len(sand) == 1 and sand[0]["side"] == "call" and [m["strike"] for m in sand[0]["members"]] == [100, 125, 150]




def test_gamma_flip_and_custom_levels_are_never_absorbed_by_a_band():
    from backend.services.importance import make_zones, score_levels
    band = lvl("gex_call_zone", "Call wall zone", 30100.0, zone_mag=900.0, call_strikes=2, put_strikes=0, members=[{"strike": 30100, "side": "call", "gex": 900}]) | {"low": 30075.0, "high": 30150.0, "method": "m"}
    flip = lvl("gamma_flip", "Estimated gamma flip", 30110.0)
    mine = lvl("custom", "Quant GEX 205", 30120.0)
    plain = lvl("open_interest", "High call open interest", 30130.0, call_oi=5000.0)
    lv = [band, flip, mine, plain]
    score_levels(lv, 30000.0, 400.0)
    zs = make_zones(lv, 30000.0, top_n=10)
    labels = sorted(z["label"] for z in zs)
    assert len(zs) == 4 and any("Gamma flip" in x for x in labels) and any("Quant GEX 205" in x for x in labels) and "Call wall zone" in labels




# ---- "nearest N" really limits what is exported ------------------------------------------------------------------


def test_page_files_are_never_served_stale():
    c, db = api_client()
    for path in ("/", "/app.js", "/style.css"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    assert "cache-control" not in c.get("/api/health").headers or c.get("/api/health").headers["cache-control"] != "no-cache"


# ---- per-type counts: GEX can have more levels than the other kinds ----------------------------------------------


# ---- the TradingView indicator: per-kind settings, and paste rows that carry score and family -----------------------






# ---- 1.22: the paste-in Key levels indicator draws every level as a zone, and the app hands it out ----------------
