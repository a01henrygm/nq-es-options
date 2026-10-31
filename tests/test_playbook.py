"""Playbook tab (1.25.0): the biggest levels, three plans and the pick for today. TEST DATA ONLY."""
from backend.services import playbook as pbk
from tests.test_session_features import simulated_day


def test_playbook_has_candles_levels_three_plans_and_one_pick():
    c, db, now = simulated_day()
    r = c.get("/api/analytics/playbook", params={"underlying": "_NDX"})
    assert r.status_code == 200
    j = r.json()
    assert j["today"] in pbk.SCEN and j["confidence"] in ("high", "medium", "low") and j["banner"]
    assert set(j["scenarios"]) == set(pbk.SCEN) and sum(1 for s in j["scenarios"].values() if s["picked"]) == 1
    assert j["candles"] and all(k["h"] >= max(k["o"], k["c"]) - 1e-6 for k in j["candles"])
    assert j["levels"] and all(l["call"] in ("HOLD", "CHOP", "BREAK") for l in j["levels"])
    for k, s in j["scenarios"].items():
        assert s["trigger"] and s["invalid"] and s["path"] and s["levels"]
        assert all(p["t"] > j["candles"][-1]["t"] for p in s["path"])          # projected candles come after the last real one
    assert j["scenarios"]["choppy"]["range"]["low"] <= j["scenarios"]["choppy"]["range"]["high"]
    assert c.get("/api/analytics/playbook", params={"underlying": "_NDX", "tf": 15}).json()["tf"] == 15
    assert c.get("/api/analytics/playbook", params={"underlying": "_NDX", "convention": "nope"}).status_code == 422


def test_the_pick_follows_the_regime_and_the_flip():
    assert pbk.pick("long", 100, 99, 0.0, 0)[0] == "choppy"
    s, conf, sc, why = pbk.pick("short", 100, 98, 0.6, -1.0)
    assert s == "bullish" and conf == "high" and why
    assert pbk.pick("short", 100, 102, -0.6, 1.0)[0] == "bearish"
    assert pbk.pick("unknown", 100, None, None, None)[0] == "choppy"          # nothing leans: choppy


def test_plans_use_the_level_calls():
    lv = [{"value": 105, "call": "RESPECT", "strength": 0.9, "label": "Call wall", "category": "call_wall"},
          {"value": 103, "call": "DISRESPECT", "strength": 0.4, "label": "GEX-", "category": "gex"},
          {"value": 97, "call": "RESPECT", "strength": 0.8, "label": "Put wall", "category": "put_wall"},
          {"value": 95, "call": "CHOP", "strength": 0.3, "label": "OI", "category": "oi"}]
    big = pbk.biggest(lv, 100, 4)
    sc = pbk.scenarios(big, 100, 4, lambda v: v)
    assert "Put wall" in sc["bullish"]["trigger"] and sc["bullish"]["invalid"].startswith("A close below Put wall")
    assert "Call wall" in sc["bearish"]["invalid"]
    assert sc["choppy"]["range"] == {"high": 105, "low": 97, "mid": 101}
    p = pbk.path(sc["_path"]["bullish"], 30, lambda v: v)
    assert len(p) >= 20 and p[-1]["c"] > 100


def test_every_level_gets_an_expectation_and_a_reaction_in_all_three_plans():
    c, db, now = simulated_day()
    j = c.get("/api/analytics/playbook", params={"underlying": "_NDX"}).json()
    lm = c.get("/api/charts/level-map", params={"underlying": "_NDX", "count": 80}).json()["levels"]
    assert j["counts"]["all"] == len(lm)                                     # every Level map level, not just the top few
    assert j["counts"]["gex"] >= 1 and all(l["gex"] for l in j["levels"] if "GEX" in l["label"])
    for l in j["levels"]:
        assert l["expect"]["tag"] in ("BOUNCE", "REJECT", "CHOP", "BREAK UP", "BREAK DOWN") and l["expect"]["text"]
        assert all(l["react"][k] and l["react"][k]["action"] for k in pbk.SCEN)
    # the chart starts at the earliest stored price, before today's session
    assert j["candles"][0]["t"][:10] < j["candles"][-1]["t"][:10]


def test_gex_levels_are_never_squeezed_out_and_merged_rows_still_count_as_gex():
    lv = [{"value": 100 + i, "call": "RESPECT", "strength": 0.9, "label": f"OI {i}", "category": "oi"} for i in range(1, 30)]
    lv += [{"value": 160, "call": "CHOP", "strength": 0.1, "label": "Call OI zone / GEX+", "category": "oi_call_zone"}]
    big = pbk.biggest(lv, 100, 4, per_side=5)
    assert any(l["value"] == 160 and l["gex"] for l in big)
    assert pbk._nm(big[0]) == "Call OI zone (GEX+)"
    sc = pbk.scenarios(big, 100, 4, lambda v: v)
    tags = [r["tag"] for r in sc["bullish"]["levels"]]
    assert "TP1" in tags and all(r["role_title"] for r in sc["bullish"]["levels"])


def test_key_levels_paste_in_matches_the_tab_and_has_its_own_script():
    c, db, now = simulated_day()
    tab = c.get("/api/analytics/levels", params={"underlying": "_NDX", "key": 10}).json()
    r = c.post("/api/tv/keylevels/levels", params={"underlying": "_NDX", "key": 10}, json={})
    assert r.status_code == 200
    j = r.json()
    assert j["ind"] == "kl" and j["levels"] == len(tab["zones"]) and j["text"].startswith("Q|2|kl|")
    lines = j["text"].splitlines()
    assert any(l.startswith("K|Gamma flip|") for l in lines) and all(l.split("|")[7] in "HCB-" for l in lines if l.startswith("L|"))
    # all-levels mode follows the families switched on in the tab
    some = c.post("/api/tv/keylevels/levels", params={"underlying": "_NDX", "categories": "gamma_flip,gex0_call_wall"}, json={}).json()
    assert 1 <= some["levels"] <= 2
    s = c.get("/api/tv/keylevels/script").json()
    assert s["filename"] == "qdata_key_levels_paste_in.pine" and s["code"].startswith("//@version=6")
    assert 'indicator("Q DATA Key Levels"' in s["code"] and '"Your levels"' in s["code"] and "gexZones" in s["code"]
    assert s["code"].isascii()
