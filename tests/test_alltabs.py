"""Q DATA All Tabs, rebuilt in 1.25.0 on the GEX / Levels script, and every GEX level as a zone. TEST DATA ONLY."""
from backend.services import tv_levels as tv
from backend.services.tv_pine import ALL_LV_OFFSET, ALL_SECTIONS, build_script
from tests.test_session_features import simulated_day


def lines(text, tag):
    return [x.split("|") for x in text.splitlines() if x.startswith(tag + "|")]


def test_all_tabs_script_has_every_section_and_the_paste_box_first():
    c, db, now = simulated_day()
    a = c.get("/api/tv/alltabs/script").json()
    code = a["code"]
    assert code == build_script("all") and a["filename"] == "qdata_all_tabs_paste_in.pine"
    assert code.startswith("//@version=6\n") and 'indicator("Q DATA All Tabs"' in code and all(ord(ch) < 128 for ch in code)
    inputs = [x for x in code.splitlines() if " input." in x and not x.startswith(" ")]
    assert inputs[0].startswith("dataTxt = input.text_area")
    for i, nm in enumerate(ALL_SECTIONS):
        assert f'sec{i} = input.bool(' in code and f'"{nm}"' in code
    heat = tv.HEAT_SECTION + ALL_LV_OFFSET
    assert f'sec{heat} = input.bool(false, "Heatmap"' in code and f"secOn({heat})" in code
    assert inputs[-1].startswith("gexZones = input.string(")                   # new settings go last


def test_all_tabs_levels_hold_gex_and_levels_sections():
    c, db, now = simulated_day()
    r = c.post("/api/tv/alltabs/levels", params={"underlying": "_NDX"}, json={}).json()
    g = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex"}).json()
    l = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "lv"}).json()
    q = lines(r["text"], "Q")[0]
    assert q[1] == "2" and q[2] == "all" and r["chars"] <= 30000
    secs = {int(k[6]) for k in lines(r["text"], "K")}
    assert any(s < ALL_LV_OFFSET for s in secs) and any(s >= ALL_LV_OFFSET for s in secs)
    assert max(secs) < len(ALL_SECTIONS)
    names = {k["name"] for k in r["kinds"]}
    assert {k["name"] for k in g["kinds"]} <= names and {k["name"] for k in l["kinds"]} <= names
    assert c.post("/api/tv/alltabs/levels", params={"underlying": "_NDX"}, json={"prefs": {"kinds": {"Gamma flip": {"on": False}}}}).json()["text"].count("|Gamma flip|") == 0


def test_every_gex_level_is_a_zone_by_default():
    for ind in ("gex", "all"):
        code = build_script(ind)
        assert 'gexZones = input.string("Every GEX level"' in code
        assert f"kindOf(g, 0) <= {len(tv.GEX_SECTIONS) - 1}" in code and "near = math.abs(p - refClose()) <= nd or gexZ" in code
    lv = build_script("lv")
    assert 'gexZones = "Only near price"' in lv and "input.string(\"Every GEX level\"" not in lv


def test_bad_input_is_refused():
    c, db, now = simulated_day()
    assert c.get("/api/tv/script", params={"ind": "nope"}).status_code == 422
    assert c.get("/api/tv/script", params={"ind": "all"}).json()["filename"] == "qdata_all_tabs_paste_in.pine"
