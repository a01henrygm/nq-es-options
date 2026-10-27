"""One TradingView indicator per tab with levels, named after that tab. TEST DATA ONLY."""
from backend.services.tab_pine import build_tab_pine
from tests.test_session_features import simulated_day


def test_every_tab_indicator_is_named_after_its_tab():
    c, db, now = simulated_day()
    tabs = c.get("/api/export/tab-pine/tabs").json()["tabs"]
    assert {"stackmap", "levelmap", "gameplan", "gex", "zerodte", "oi", "volume", "move", "quant"} <= {t["tab"] for t in tabs}
    built = 0
    for t in tabs:
        r = c.get("/api/export/tab-pine", params={"tab": t["tab"], "underlying": "_NDX"})
        assert r.status_code in (200, 409), (t, r.text)
        if r.status_code == 409:
            continue
        j = r.json()
        built += 1
        assert j["title"] == t["title"] and f'indicator("{t["title"]}"' in j["code"] and j["code"].startswith("//@version=6")
        assert j["filename"].endswith("_NDX.pine") and j["filename"].startswith("qdata_")
        for i in range(len(j["groups"])):                               # one show/hide box per group, all wired into groupOn()
            assert f"g{i} = input.bool(true" in j["code"] and f"        {i} => g{i}" in j["code"]
    assert built >= 14
    sm = c.get("/api/export/tab-pine", params={"tab": "stackmap", "underlying": "_NDX"}).json()
    assert sm["levels"] >= 1 and "STACK" in sm["code"] and len(sm["groups"]) == 3
    assert c.get("/api/export/tab-pine", params={"tab": "nope", "underlying": "_NDX"}).status_code == 422


def test_vix_tab_indicator_uses_the_open_and_typical_day():
    c, db, now = simulated_day()
    route = next(r for r in c.app.routes if getattr(r, "path", None) == "/api/volatility")
    old = route.endpoint
    route.endpoint = lambda: {"available": True, "regime": {"label": "Calm"}, "moves": {"nq_day": {"index_points": 200.0, "futures_points": 201.0, "from": "VXN"}}}
    try:
        j = c.get("/api/export/tab-pine", params={"tab": "vix", "underlying": "_NDX"}).json()
    finally:
        route.endpoint = old
    assert j["title"] == "Q DATA Volatility (VIX)" and j["levels"] == 5 and "VIX day +1" in j["code"]


def test_builder_handles_no_levels_and_quotes():
    code = build_tab_pine('Q DATA "Test"', "QD T", ["A"], [], [("Note", 'say "hi"\\')])
    assert 'indicator("Q DATA Test"' in code and "array.from(1.00)" in code and '"say hi"' in code and "0 => g0" in code
