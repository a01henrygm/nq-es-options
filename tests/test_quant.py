"""The Quant lab, the HOD / LOD tab and the HOD / LOD indicator. Synthetic data only (TEST DATA)."""
import math
import random
import re
from datetime import date, datetime, timedelta

from backend.services import quant as qt
from backend.services.hodlod_pine import build_hodlod_pine
from backend.timeutil import ET, UTC
from tests.test_session_features import simulated_day


def ar1(phi, n, seed=1):
    r, x = random.Random(seed), [0.0]
    for _ in range(n):
        x.append(phi * x[-1] + r.gauss(0, 1))
    return [100.0 + v for v in x]


def test_mean_reversion_finds_a_real_pull_and_its_half_life():
    d = qt.mean_reversion(ar1(0.8, 400), step_minutes=2)
    assert d["significant"] and d["t_stat"] < -2.9
    assert abs(d["half_life_steps"] - math.log(2) / -math.log(0.8)) < 1.0          # built 3.1 steps, found close to it
    assert abs(d["half_life_minutes"] - 2 * d["half_life_steps"]) < 1e-9


def test_mean_reversion_does_not_call_a_random_walk_a_pull():
    hits = sum(qt.mean_reversion(ar1(1.0, 300, seed=s))["significant"] for s in range(40))
    assert hits <= 4                                                              # about 5% at the -2.9 limit
    assert not qt.mean_reversion([1.0] * 10)["available"]


def test_touch_chance_is_the_running_maximum_rule():
    assert abs(qt.touch_prob(1.0, 1.0) - 0.3173) < 1e-3 and qt.touch_prob(0, 1.0) == 1.0 and qt.touch_prob(1, 0) is None
    assert abs(qt.sigma_from_move(100, "today's ATM straddle") - 125.33) < 0.01 and qt.sigma_from_move(100, "front ATM IV") == 100


def test_monte_carlo_matches_the_textbook_with_a_tight_stop_and_the_clock_cuts_far_targets():
    tight = qt.monte_carlo(1000.0, 150.0, 10.0, rs=(1, 2, 3))
    for r in tight["rows"]:
        assert abs(r["long"]["win"] - 1 / (1 + r["r"])) < 0.05 and abs(r["short"]["win"] - 1 / (1 + r["r"])) < 0.05
    wide = qt.monte_carlo(1000.0, 40.0, 20.0, rs=(1, 5, 12))
    assert wide["rows"][-1]["long"]["win"] < 0.01 < wide["rows"][0]["long"]["win"]       # 240 points in a 40-point day: almost never
    for r in wide["rows"]:
        assert abs(r["long"]["win"] + r["long"]["stop"] + r["long"]["neither"] - 1) < 1e-9
    pulled = qt.monte_carlo(1000.0, 150.0, 20.0, rs=(5,), half_life_minutes=15, mean=1000.0)
    walk = qt.monte_carlo(1000.0, 150.0, 20.0, rs=(5,))
    assert pulled["model"].startswith("pulled") and pulled["rows"][0]["long"]["win"] < walk["rows"][0]["long"]["win"]
    assert not qt.monte_carlo(1000.0, None, 10)["available"]


def test_pca_splits_a_common_factor_and_flags_nq_running_ahead():
    r, t0, a, b, pa, pb = random.Random(3), datetime(2026, 10, 14, 13, 30, tzinfo=UTC), [], [], 20000.0, 6000.0
    for i in range(120):
        f = r.gauss(0, 0.001)
        pa *= math.exp(1.3 * f + r.gauss(0, 0.0002) + 0.0001)                 # NQ = 1.3 x the market, plus a steady extra drift up
        pb *= math.exp(f + r.gauss(0, 0.0002))
        t = t0 + timedelta(minutes=2 * i)
        a.append((t, pa))
        b.append((t + timedelta(seconds=20), pb))
    d = qt.pca_pair(qt.align(a, b))
    assert d["available"] and d["pc1_share"] > 0.95 and d["correlation"] > 0.9 and 1.1 < d["beta"] < 1.5
    assert d["pc1_loadings"]["nq"] > d["pc1_loadings"]["es"] > 0 and d["residual_z"] >= 2 and "ahead" in d["read"]
    assert not qt.pca_pair(qt.align(a[:5], b[:5]))["available"]


def test_hodlod_ladder_and_chances():
    d = qt.hodlod(1000.0, 1012.0, 990.0, 1005.0, 20.0, 15.0)
    up = {x["k"]: x for x in d["up"]}
    assert up[1.0]["price"] == 1020.0 and abs(up[1.0]["at_open"] - 0.3173) < 1e-3
    assert up[0.5]["hit"] and up[0.5]["now"] == 1.0 and not up[1.0]["hit"]
    assert abs(up[1.0]["now"] - qt.touch_prob(15.0, 15.0)) < 1e-12
    assert d["projection"]["hod"]["p50"] >= 1012.0 and d["projection"]["lod"]["p80"] <= 990.0
    assert d["projection"]["hod"]["p95"] > d["projection"]["hod"]["p80"] > d["projection"]["hod"]["p50"]
    assert not qt.hodlod(None, None, None, 1000.0, 20.0, 10.0)["available"]


def test_playbook_follows_dealer_gamma():
    z = {"available": True, "exposure_at_spot": -5e9, "flip": 1100.0, "call_wall": 1030.0, "put_wall": 980.0}
    s = qt.gamma_playbook(z, 1010.0, 1000.0, 20.0, [{"t": "a", "value": 1.0}, {"t": "b", "value": -1.0}], 15.0)
    assert s["state"] == "short" and s["targets"] and all(t["side"] == "long" and t["price"] > 1010 for t in s["targets"])
    assert s["flips"] == [{"t": "b", "from": "long", "to": "short"}]                     # the latest reading counts on its own
    flap = [{"t": i, "value": v} for i, v in enumerate([1, -1, 1, -1, 1, 1, -1, -1, -1])]
    assert [f["t"] for f in qt.regime_flips(flap)] == [6]                                  # one-reading blips are ignored
    lg = qt.gamma_playbook({**z, "exposure_at_spot": 5e9}, 1030.0, 1000.0, 20.0)
    assert lg["state"] == "long" and "expansion is likely done" in " ".join(lg["notes"])
    assert qt.gamma_playbook({**z, "flip": 1010.5}, 1010.0)["state"] == "transition"
    assert qt.gamma_playbook({"available": False}, 1010.0)["state"] == "unknown"


def test_hodlod_and_quant_endpoints_on_a_simulated_day():
    c, db, now = simulated_day()
    j = c.get("/api/analytics/hodlod", params={"underlying": "_NDX"}).json()
    d = j["data"]["hodlod"]
    assert d["available"] and d["open"] == 30000.0 and d["sigma_open"] > 0 and len(d["up"]) == len(qt.LADDER)
    assert j["data"]["playbook"]["state"] in ("short", "long", "transition") and j["price"]
    q = c.get("/api/analytics/quant", params={"underlying": "_NDX", "stop": 25}).json()["data"]
    assert q["playbook"]["state"] == j["data"]["playbook"]["state"]
    assert q["monte_carlo"]["available"] and abs(q["monte_carlo"]["stop_futures"] - 25) < 1e-9 and len(q["monte_carlo"]["rows"]) == 6
    assert not q["pca"]["available"] and "SPX" in q["pca"]["reason"]                     # only NDX is tracked in this simulation
    assert c.get("/api/analytics/quant", params={"underlying": "_NDX", "model": "nope"}).status_code == 422


def test_hodlod_indicator_export():
    c, db, now = simulated_day()
    r = c.get("/api/export/hodlod-pine", params={"underlying": "_NDX"}).json()
    code = r["code"]
    assert code.startswith("//@version=6")
    assert not re.search(r"__[A-Z]+__", code)                                           # every placeholder filled
    assert all(ord(ch) < 128 for ch in code) and "\t" not in code                       # plain ASCII, spaces only
    assert f"_QD_SIG_PCT = {r['sigma_pct']:.6f}" in code and r["sigma_pct"] > 0
    assert f'_QD_STATE   = "{r["state"]}"' in code and "_QD_Y       = 2026" in code


def test_pine_builder_handles_missing_values():
    code = build_hodlod_pine(0, "weird", None, None, None, [], 'a "quoted" source', "units", datetime(2026, 10, 14, 9, 0, tzinfo=ET), date(2026, 10, 14), "_SPX")
    assert '_QD_STATE   = "unknown"' in code and "_QD_CALL    = na" in code and "array.from(0)" in code and 'array.from("none")' in code
    assert '"quoted"' not in code


def test_stay_inside_matches_the_two_barrier_value():
    assert abs(qt.stay_inside(100, 90, 110, 5) - 0.909) < 0.002                       # +/-2 sd box: about 91% never touch either side
    assert qt.stay_inside(100, 90, 110, 0.5) > 0.999 and qt.stay_inside(100, 100, 110, 5) is None


def test_monte_carlo_returns_a_fan_of_paths():
    m = qt.monte_carlo(1000.0, 30.0, 5.0, minutes_left=200)
    f = m["fan"]
    assert len(f["paths"]) == 150 and len(f["paths"][0]) == len(f["minutes"]) and f["minutes"][0] == 0 and abs(f["minutes"][-1] - 200) < 1e-6
    b = f["bands"]
    assert b["p05"][-1] < b["p25"][-1] < b["p50"][-1] < b["p75"][-1] < b["p95"][-1]
    assert abs((b["p95"][-1] - b["p05"][-1]) - 2 * 1.645 * 30) < 8                      # the 90% spread is about 3.3 sd
    assert sum(f["final_hist"]["counts"]) == m["paths"]


def test_move_map_walks_the_levels_with_reasons():
    lv = [{"value": 1010.0, "label": "Call wall", "call": "DISRESPECT", "why": "a"}, {"value": 1020.0, "label": "Move zone", "call": "RESPECT", "why": "b"},
          {"value": 990.0, "label": "Put wall", "call": "RESPECT", "why": "c"}]
    g = {"drift_to_close": -2e9, "totals": {"vanna": 1e9, "dex": 5e9}}
    mv = qt.move_map(1000.0, 1004.0, 996.0, 1000.0, 20.0, 15.0, lv, "long", g, [{"name": "CPI", "time": "08:30"}], 200, lambda v: v + 50)
    assert [r["price"] for r in mv["up"]] == [1010.0, 1020.0] and mv["up"][1]["note"].startswith("First level that should reject")
    assert mv["up"][0]["chance"] > mv["up"][1]["chance"] and mv["up"][0]["futures"] == 1060.0
    assert mv["range"]["low"] == 990.0 and mv["range"]["high"] == 1010.0 and 0 < mv["range"]["stay_inside"] < 1
    names = [d["name"] for d in mv["drivers"]]
    assert names[:3] == ["Gamma regime", "Range used", "Time left"] and "Charm into the close" in names and "Scheduled event" in names
    assert "upward" in next(d for d in mv["drivers"] if d["name"] == "Charm into the close")["effect"]
    assert "Upside" in mv["summary"][0] and "Move zone" in mv["summary"][0]


def test_charm_vanna_prices_come_in_futures_points():
    c, db, now = simulated_day()
    j = c.get("/api/analytics/greeks", params={"underlying": "_NDX"}).json()
    assert j["futures"]["available"] and j["futures"]["root"] == "NQ" and "implied" in j["futures"]["method"]
    s0 = j["data"]["strikes"][0]
    assert abs(s0["nq"] / s0["strike"] - j["futures"]["ratio"]) < 1e-9 and j["futures"]["spot"]
    z = next(z for zs in j["zones"].values() for z in zs)
    assert z["nq_low"] <= z["nq_center"] <= z["nq_high"]
    mv = c.get("/api/analytics/hodlod", params={"underlying": "_NDX"}).json()["data"]["moves"]
    assert mv["available"] and mv["drivers"]


def test_already_in_rises_as_price_leaves_the_extreme():
    at_high = qt.already_in(1010.0, 990.0, 1010.0, 10.0)
    assert at_high["high"] == 0.0 and at_high["likely_first"] == "low"                       # sitting on the high: no reason to think it holds
    far = qt.already_in(1010.0, 990.0, 991.0, 3.0)
    assert far["high"] > 0.99 and far["low"] < 0.5 and far["likely_first"] == "high"
    assert qt.already_in(1010.0, 990.0, 1000.0, 10.0)["high"] < qt.already_in(1010.0, 990.0, 1000.0, 2.0)["high"]   # less time left, higher
    assert qt.already_in(None, None, 1000.0, 5.0) is None
