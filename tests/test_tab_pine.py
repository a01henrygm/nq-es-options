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


def test_all_tabs_indicator_has_a_switch_per_tab_and_per_kind():
    c, db, now = simulated_day()
    j = c.get("/api/export/all-pine", params={"underlying": "_NDX"}).json()
    code = j["code"]
    assert 'indicator("Q DATA All Tabs"' in code and len(j["tabs"]) >= 14 and j["levels"] > 50
    for i, t in enumerate(j["tabs"]):
        assert f't{i} = input.bool({"true" if t["on"] else "false"}, "Show {t["name"]}"' in code and f"        {i} => t{i}" in code
    assert {t["tab"] for t in j["tabs"] if t["on"]} == {"stackmap", "gameplan", "session"}
    assert "showCone" in code and "label.set_text" in code
    on = c.get("/api/export/all-pine", params={"underlying": "_NDX", "on": "oi"}).json()
    assert [t["tab"] for t in on["tabs"] if t["on"]] == ["oi"]


def test_indicators_are_fully_customizable_and_draw_stack_zones():
    c, db, now = simulated_day()
    j = c.get("/api/export/all-pine", params={"underlying": "_NDX"}).json()
    code = j["code"]
    for want in ("zOn", "zMin", "zHeavy", "zDist", "zCount", "zColorMode", "box.new(startX, zh", "Nearest stack zone above", "What the colors mean",
                 "labelText", "nearestN", "c0 = input.color(", "s0 = input.string(", "w0 = input.int("):
        assert want in code, want
    assert "(ceiling)" not in code and '"ceiling"' in code                  # plain-English meanings are baked per kind
    one = c.get("/api/export/tab-pine", params={"tab": "levelmap", "underlying": "_NDX"}).json()["code"]
    assert "zOn" in one and "Levels: Level Map" in one


def test_all_tabs_indicator_keeps_the_main_body_short_and_names_unique():
    """TradingView refuses a script whose main body is too long (CE10295) and warns when a local name hides a setting (CW10013,
    e.g. a local t2 hiding the "Show" switch of tab 2). The drawing code and the long level lists live in functions."""
    import re
    from backend.services import tab_pine
    c, db, now = simulated_day()
    code = c.get("/api/export/all-pine", params={"underlying": "_NDX"}).json()["code"]
    for fn in ("qdVisible(int n) =>", "qdZones(", "qdLevels(", "qdInfoTable(", "qdLegend(", "var float[] lvP = "):
        assert fn in code, fn
    assert "array.from(" not in "\n".join(l for l in code.splitlines() if l.startswith("var "))     # lists are built by functions
    glob, loc = set(), set()
    for l in code.splitlines():
        m = re.match(r'^(?:var\s+\S+\s+)?([A-Za-z_]\w*)\s*(?:=[^=>]|\()', l)
        if m and not l.startswith(" "):
            glob.add(m.group(1))
        m = re.match(r'^\s+(?:\w+\s+)?([A-Za-z_]\w*)\s*=[^=]', l)
        if m:
            loc.add(m.group(1))
        m = re.match(r'^(\w+)\((.*)\)\s*=>', l)
        if m:
            loc |= {p.split()[-1] for p in m.group(2).split(",") if p.strip()}
    assert not (loc & glob), loc & glob
    items = [str(i) for i in range(tab_pine.CHUNK * 2 + 5)]                   # long lists are split over several small functions
    lines = tab_pine._arr("xs", "int", items)
    assert "_xs2() =>" in "\n".join(lines) and lines[-1] == "var int[] xs = _xs()"
