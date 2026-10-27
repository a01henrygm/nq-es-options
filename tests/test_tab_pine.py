"""One TradingView indicator per tab with levels, named after that tab. TEST DATA ONLY."""
import re

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
        for i in range(len(j["groups"])):                               # one show/hide box per group, gathered into the kOn array
            assert f"g{i} = input.bool(true" in j["code"] and re.search(rf"array\.from\([^)]*\bg{i}\b", j["code"])
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
    assert 'indicator("Q DATA Test"' in code and "array.from(1.00)" in code and '"say hi"' in code and "array.from(g0)" in code


def test_all_tabs_indicator_has_a_switch_per_tab_and_per_kind():
    c, db, now = simulated_day()
    j = c.get("/api/export/all-pine", params={"underlying": "_NDX"}).json()
    code = j["code"]
    assert 'indicator("Q DATA All Tabs"' in code and len(j["tabs"]) >= 14 and j["levels"] > 50
    for i, t in enumerate(j["tabs"]):
        assert f't{i} = input.bool({"true" if t["on"] else "false"}, "Show {t["name"]}"' in code and f"tc{i} = input.color(" in code
    assert "var bool[] tOn = _tOn0()" in code and "array.from(t0, t1" in code
    assert {t["tab"] for t in j["tabs"] if t["on"]} == {"stackmap", "gameplan", "session"}
    assert [t["tab"] for t in j["tabs"]] == list(c.get("/api/export/tab-pine/tabs").json()["tabs"][i]["tab"] for i in range(len(j["tabs"])))  # every tab, always
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


def external_elements(code):
    """Roughly what TradingView counts for CE10116: the settings a function reads, directly or through the functions it calls
    (int/float/bool count 2), plus its own parameters. The limit is 254; this estimate runs a little low, so tests want a big margin."""
    W = {"bool": 2, "int": 2, "float": 2, "color": 1, "string": 1}
    lines = code.splitlines()
    inputs = {m.group(1): W.get(m.group(2), 1) for l in lines for m in [re.match(r'^(\w+)\s*=\s*input\.(\w+)\(', l)] if m}
    funcs, cur = {}, None
    for l in lines:
        m = re.match(r'^(\w+)\((.*)\)\s*=>', l)
        if m:
            cur = m.group(1)
            funcs[cur] = [m.group(2), []]
        elif cur and l.startswith(" "):
            funcs[cur][1].append(l)
        else:
            cur = None
    ids = lambda text: set(re.findall(r'\b[A-Za-z_]\w*\b', re.sub(r'"[^"]*"', '', text)))
    memo = {}

    def reads(f, seen=()):
        if f not in memo:
            used = ids("\n".join(funcs[f][1]))
            out = {k for k in used if k in inputs}
            for g in used:
                if g in funcs and g != f and g not in seen:
                    out |= reads(g, seen + (f,))
            memo[f] = out
        return memo[f]

    def params(p):
        return sum(2 if x.split()[0] in ("int", "float", "bool") else 1 for x in p.split(",") if len(x.split()) == 2)
    return {f: sum(inputs[k] for k in reads(f)) + params(funcs[f][0]) for f in funcs}


def test_no_function_reads_too_many_settings():
    """CE10116: 'The "qdLevels" function uses 340 external elements. The limit is 254.' The per-tab and per-kind settings are gathered
    into arrays, so the drawing functions read a handful of settings however many tabs and kinds there are."""
    c, db, now = simulated_day()
    code = c.get("/api/export/all-pine", params={"underlying": "_NDX"}).json()["code"]
    ext = external_elements(code)
    assert max(ext.values()) <= 170, sorted(ext.items(), key=lambda x: -x[1])[:5]
    for fn in ("qdLevels", "qdVisible", "qdZones", "qdLegend", "qdInfoTable"):
        assert ext[fn] <= 60, (fn, ext[fn])
    # many more kinds than today: the gathering is split into more parts, and still no function goes near the limit
    from backend.services.tab_pine import build_all_pine
    big = [{"tab": f"t{k}", "name": f"Tab {k}", "on": True, "groups": [f"Kind {k}.{i}" for i in range(30)],
            "levels": [{"price": 100 + k + i / 10, "group": i, "label": "x"} for i in range(30)], "table": []} for k in range(10)]
    code = build_all_pine(big, [], "", "", "")
    ext = external_elements(code)
    assert max(ext.values()) <= 170 and "array.concat(kOn, _kOn1())" in code and "array.concat(kOn, _kOn3())" in code


def test_the_look_chosen_in_q_data_becomes_the_starting_settings():
    c, db, now = simulated_day()
    first = c.post("/api/export/all-pine", params={"underlying": "_NDX"}, json={}).json()
    kind = first["kinds"][0]
    assert {"name", "on", "color", "style", "width", "default", "tabs", "help"} <= set(kind) and kind["tabs"]
    assert {x["var"] for x in first["settings"]} >= {"zOn", "colorMode", "nearestN", "labelText", "tablePos"}
    assert next(x for x in first["settings"] if x["var"] == "zDist")["auto"] is True
    prefs = {"tabs_on": ["oi", "gex"], "tab_colors": {"oi": "#123456"},
             "kinds": {kind["name"]: {"on": False, "color": "#abcdef", "style": "dotted", "width": 4}},
             "set": {"colorMode": "Tab", "zMin": 4, "nearestN": 6, "showLegend": False, "labelSize": "Huge", "zPad": "oops", "zTransp": 500}}
    j = c.post("/api/export/all-pine", params={"underlying": "_NDX"}, json={"prefs": prefs}).json()
    code = j["code"]
    assert sorted(t["tab"] for t in j["tabs"] if t["on"]) == ["gex", "oi"]
    oi = [i for i, t in enumerate(j["tabs"]) if t["tab"] == "oi"][0]
    assert f"tc{oi} = input.color(#123456" in code
    assert re.search(r'g\d+ = input\.bool\(false, "' + re.escape(kind["name"]), code) and "input.color(#abcdef" in code and 'input.string("Dotted"' in code
    assert 'colorMode = input.string("Tab"' in code and "zMin = input.int(4," in code and "nearestN = input.int(6," in code
    assert "showLegend = input.bool(false," in code
    assert 'labelSize = input.string("Small"' in code and "zPad = input.float(2.00," in code and "zTransp = input.int(100," in code   # bad values fall back or clamp
    assert j["kinds"][0]["on"] is False and j["kinds"][0]["color"] == "#abcdef"
    # junk never breaks the export
    assert c.post("/api/export/all-pine", params={"underlying": "_NDX"}, json={"prefs": {"kinds": [1, 2], "set": "x", "tabs_on": "oi"}}).status_code == 200
    one = c.post("/api/export/tab-pine", params={"tab": "oi", "underlying": "_NDX"}, json={"prefs": prefs}).json()["code"]
    assert 'colorMode = input.string("Tab"' in one and "tc0 = input.color(#123456" in one


def test_quick_setup_comes_first_and_each_tab_has_a_color():
    c, db, now = simulated_day()
    code = c.get("/api/export/all-pine", params={"underlying": "_NDX"}).json()["code"]
    assert code.index('grpQ = "Quick setup"') < code.index('grp0 = "Tab: ') < code.index('grpZ = "Stack zones') < code.index('grpL = ') < code.index('grpT = ')
    for want in ("showLines", "emphNear", "levelColor(g, array.get(lvT, i), p)", "colUp", "colDn", 'colorMode == "Tab"', "array.get(tName, key)"):
        assert want in code, want
