"""Charm, vanna, dealer delta, new positions and the activity heatmap. All data is SYNTHETIC TEST DATA."""
from datetime import datetime, timedelta

import pytest

from backend.config import ROOT
from backend.services import analytics as an
from backend.services import flows as fl
from backend.services.freshness import classify
from backend.services.importance import FAMILY, QUOTA_KEYS, make_zones, score_levels
from backend.services.levels import build_levels
from backend.timeutil import UTC
from tests.conftest import NOW, make_chain
from tests.test_features import Snap, api_client, ind_default, skewed_chain


# ---- the greeks --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("K", [480.0, 500.0, 515.0])
def test_charm_and_vanna_match_finite_differences(K):
    S, T, iv = 500.0, 10 / 365.25, 0.2
    dt = 1e-3 / 365.25
    fd_charm = (an.bs_delta(S, K, T - dt, iv, "C") - an.bs_delta(S, K, T, iv, "C")) / 1e-3      # per day as time passes
    assert fl.bs_charm_per_day(S, K, T, iv) == pytest.approx(fd_charm, rel=1e-3, abs=1e-7)
    h = 1e-6
    for r in "CP":                                                                               # vanna is the same for calls and puts
        fd_v = (an.bs_delta(S, K, T, iv + h, r) - an.bs_delta(S, K, T, iv - h, r)) / (2 * h)
        assert fl.bs_vanna(S, K, T, iv) == pytest.approx(fd_v, rel=1e-5, abs=1e-9)


def test_same_day_greeks_stay_finite():
    tiny = 1 / (365.25 * 24 * 3600)                                                              # one second left
    assert abs(fl.bs_charm_per_day(500, 501, tiny, 0.2)) < 1e6 and abs(fl.bs_vanna(500, 501, tiny, 0.2)) < 1e6


def test_greek_exposure_totals_signs_and_drift():
    cons = make_chain(n_strikes=31, step=2.5)
    g = fl.greek_exposure(cons, 500.0, NOW, "standard")
    assert g["contracts_used"] == len(cons) and g["estimate"] is True
    assert g["totals"]["charm"] == pytest.approx(sum(s["charm"] for s in g["strikes"]))
    rev = fl.greek_exposure(cons, 500.0, NOW, "customers_long")
    for k in ("charm", "vanna", "dex"):                                                          # the reversed assumption mirrors every sign
        assert rev["totals"][k] == pytest.approx(-g["totals"][k], rel=1e-9, abs=1e-6)
    assert g["hours_to_close"] == pytest.approx(5.0, abs=0.01)                                   # 11:00 ET -> 16:00 ET
    assert g["drift_to_close"] != 0 and ("SELL" in g["drift_note"] or "BUY" in g["drift_note"])
    late = fl.greek_exposure(cons, 500.0, NOW + timedelta(hours=6), "standard")                  # after the close
    assert late["drift_to_close"] == 0 and "over" in late["drift_note"]
    assert fl.greek_exposure([], 500.0, NOW)["contracts_used"] == 0


def test_signed_zones_split_positive_and_negative():
    g = fl.greek_exposure(skewed_chain(), 500.0, NOW)
    zs = fl.signed_zones(g["strikes"], "vanna", 500.0, 2)
    assert zs and {z["side"] for z in zs} <= {"positive", "negative"}
    assert all(z["low"] <= z["center"] <= z["high"] for z in zs)


# ---- new positions -----------------------------------------------------------------------------------------------------
def _prev_with_bump(cons, strike=510.0, right="C", added=4000):
    prev = {c.ticker: c.oi for c in cons}
    bumped = next(c for c in cons if c.strike == strike and c.right == right)
    bumped.oi += added
    return prev


def test_new_positioning_counts_only_increases():
    cons = make_chain(n_strikes=21)
    prev = _prev_with_bump(cons)
    cut = next(c for c in cons if c.strike == 490.0 and c.right == "P"); cut.oi -= 500           # a decrease is ignored here
    rows = fl.new_positioning(cons, prev)
    assert rows == [{"strike": 510.0, "call": 4000.0, "put": 0.0}]
    assert fl.oi_change_by_contract(cons, prev)[cut.ticker] == -500


def test_levels_include_flow_and_new_position_zones_as_their_own_lines():
    cons = skewed_chain()
    prev = _prev_with_bump(cons, 507.5)
    lv = build_levels(Snap(cons), NOW, "standard", classify(NOW, NOW, "delayed"), top=2, prev_oi=prev)
    cats = {l["category"] for l in lv}
    assert {"new_call_zone"} <= cats and cats & {"charm_sell_zone", "charm_buy_zone"} and cats & {"vanna_pos_zone", "vanna_neg_zone"} and cats & {"dex_pos_zone", "dex_neg_zone"}
    assert all("(est.)" in l["label"] for l in lv if l["category"].startswith(("charm", "vanna", "dex")))
    new = next(l for l in lv if l["category"] == "new_call_zone")
    assert new["value"] == 507.5 and new["low"] < 507.5 < new["high"]
    none = build_levels(Snap(cons), NOW, "standard", classify(NOW, NOW, "delayed"), top=2, greek_top=0)
    assert not {l["category"] for l in none} & set(c for c, f in FAMILY.items() if f in ("charm", "vanna", "dex", "new"))
    score_levels(lv, 500.0, 5.0)
    zones = make_zones(lv, 500.0, 999)
    flow_z = [z for z in zones if z["category"].startswith(("charm", "vanna", "dex", "new_"))]
    assert flow_z and all(len({m["category"] for m in z["inputs"]["members"]}) == 1 for z in flow_z)   # never merged with other kinds
    assert set(QUOTA_KEYS) >= {"charm", "vanna", "dex", "new"}


# ---- activity map -----------------------------------------------------------------------------------------------------
def test_activity_map_finds_the_hot_spot_and_center():
    cons = make_chain(n_strikes=41, step=2.5)
    for c in cons:
        c.volume = 50.0
    for c in cons:
        if c.strike in (515.0, 517.5) and c.right == "C":
            c.volume = 6000.0
    m = fl.activity_map(cons, 500.0, NOW, "volume", "total", 0.08)
    assert not m["signed"] and m["hot_spots"][0]["side"] == "call" and 515.0 <= m["hot_spots"][0]["price"] <= 517.5
    assert m["hot_spots"][0]["meaning"] == "calls" and m["hot_spots"][0]["above_price"]
    assert m["share_above"] > 0.6 and m["center"] > 500.0
    assert len(m["z"]) == len(m["strikes"]) and len(m["z"][0]) == len(m["expiries"]) and m["strikes"] == sorted(m["strikes"], reverse=True)
    assert m["profile"][m["strikes"].index(515.0)] == pytest.approx(6000 + 50)
    line = fl.summary_line(m, lambda k: f"{k:,.0f} (NQ {k + 250:,.0f})")
    assert "NQ 765" in line and "above price" in line


def test_activity_map_open_interest_change_is_signed():
    cons = make_chain(n_strikes=21)
    prev = _prev_with_bump(cons, 490.0, "P", 3000)
    m = fl.activity_map(cons, 500.0, NOW, "oi_change", "total", 0.08, prev_oi=prev)
    assert m["signed"] and m["hot_spots"][0]["price"] == 490.0 and m["hot_spots"][0]["meaning"] == "contracts added"
    assert sum(v for r in m["z"] for v in r if v) == 3000


@pytest.mark.parametrize("measure", ["gex", "charm", "vanna", "dex", "oi"])
def test_activity_map_every_measure_runs(measure):
    m = fl.activity_map(skewed_chain(), 500.0, NOW, measure, "total", 0.04)
    assert m["strikes"] and m["hot_spots"] and m["modeled"] == (measure != "oi")
    with pytest.raises(ValueError):
        fl.activity_map([], 500.0, NOW, "nope")


# ---- API -----------------------------------------------------------------------------------------------------------------
def test_greeks_and_activity_endpoints():
    c, db = api_client()
    g = c.get("/api/analytics/greeks", params={"underlying": "_NDX"}).json()
    assert g["data"]["contracts_used"] > 0 and set(g["zones"]) == {"charm", "vanna", "dex"}
    a = c.get("/api/analytics/activity", params={"underlying": "_NDX"}).json()
    assert a["available"] is False and "previous session" in a["reason"]                       # no stored open interest from yesterday yet
    v = c.get("/api/analytics/activity", params={"underlying": "_NDX", "measure": "volume", "window": 0}).json()
    assert v["available"] and v["data"]["hot_spots"] and v["mapped"] is False and v["data"]["hot_spots"][0]["futures"] is None
    c.post("/api/basis", json={"root": "NQ", "basis": 250.0})
    v2 = c.get("/api/analytics/activity", params={"underlying": "_NDX", "measure": "volume", "window": 0}).json()
    h = v2["data"]["hot_spots"][0]
    assert v2["mapped"] and h["futures"] == pytest.approx(h["price"] + 250.0) and "NQ" in v2["data"]["summary"]
    assert c.get("/api/analytics/activity", params={"underlying": "_NDX", "measure": "bad"}).status_code == 422


def test_previous_day_open_interest_feeds_heatmap_and_levels():
    c, db = api_client()
    # store yesterday's per-contract open interest with one strike 5000 contracts lower than today
    chain = c.get("/api/options/chain", params={"underlying": "_NDX", "limit": 5000}).json()["contracts"]
    calls = sorted({x["strike"] for x in chain if x["right"] == "C"})
    k = calls[len(calls) // 2 + 4]
    target = next(x for x in chain if x["right"] == "C" and x["strike"] == k)
    prev = [[x["ticker"], x["oi"] - (5000 if x["ticker"] == target["ticker"] else 0)] for x in chain]
    db.save_metric(1, "_NDX", "oi_contracts", 0.0, prev, NOW - timedelta(days=1))
    a = c.get("/api/analytics/activity", params={"underlying": "_NDX", "measure": "oi_change", "window": 0}).json()
    assert a["available"] and a["data"]["hot_spots"][0]["price"] == k and a["oi_from"]
    lv = c.get("/api/analytics/levels", params={"underlying": "_NDX"}).json()
    assert any(l["category"] == "new_call_zone" and l["value"] == k for l in lv["levels"])
    q = c.get("/api/analytics/levels", params={"underlying": "_NDX", "quota": "gex:2,oi:0,vol:0,move:0,charm:1,vanna:1,dex:1,new:1"}).json()
    used = q["selection"]["used"]
    assert used["new"] == 1 and used["charm"] <= 1 and used["vanna"] <= 1 and used["dex"] <= 1 and used["charm"] + used["vanna"] + used["dex"] >= 1
    txt = c.get("/api/export/pine", params={"underlying": "_NDX", "quota": "gex:2,charm:1,new:1"}).json()["code"]
    assert "new_call_zone" in txt and "showFlows" in txt


def test_collector_keeps_per_contract_open_interest_per_day():
    from backend.collector import Collector
    from backend.config import Settings
    from backend.database import Database
    from backend.models import ChainSnapshot
    from backend.providers.massive import content_hash
    s = Settings(provider="cboe", underlyings=("_NDX",))
    db = Database(":memory:")
    col = Collector(s, None, db, lambda: NOW)
    cons = skewed_chain()
    snap = ChainSnapshot("cboe", "_NDX", NOW, 500.0, NOW, cons, content_hash(cons))
    snap.snapshot_id, _ = db.save_snapshot(snap)
    col._store_intraday("_NDX", snap, NOW, an.gex_by_strike(cons, 500.0, NOW), an.gamma_flip(cons, 500.0, NOW))
    col._store_intraday("_NDX", snap, NOW, an.gex_by_strike(cons, 500.0, NOW), an.gamma_flip(cons, 500.0, NOW))
    rows = db.metric_series("_NDX", "oi_contracts")
    assert len(rows) == 1 and len(rows[0]["detail"]) == sum(1 for c in cons if c.oi)              # unchanged open interest is not stored twice
    cons[0].oi += 1
    col._store_intraday("_NDX", snap, NOW, an.gex_by_strike(cons, 500.0, NOW), an.gamma_flip(cons, 500.0, NOW))
    assert len(db.metric_series("_NDX", "oi_contracts")) == 2                                     # a change during the day is stored again
    assert db.latest_metric_before("_NDX", "oi_contracts", (NOW - timedelta(days=1)).isoformat()) is None


# ---- TradingView ---------------------------------------------------------------------------------------------------------
def test_indicator_has_groups_for_the_new_kinds():
    ind = (ROOT / "tradingview" / "options_levels_indicator.pine").read_text()
    for g in ("G_CHARM", "G_VANNA", "G_DEX", "G_NEW"):
        assert f"group = {g}" in ind
    for cat, fam in (("charm_sell_zone", "charm"), ("vanna_neg_zone", "vanna"), ("dex_pos_zone", "dex"), ("new_put_zone", "new")):
        assert ind_default(ind, cat)[0] == fam
    for v in ("maxCharm", "maxVanna", "maxDex", "maxNew", "wCharm", "sDex"):
        assert f"{v} " in ind
    assert ind.count("(") == ind.count(")") and "\t" not in ind
    js = (ROOT / "frontend" / "app.js").read_text()
    assert '"/analytics/activity"' in js and '"/analytics/greeks"' in js and 'c.startsWith("charm") ? "charm"' in js
