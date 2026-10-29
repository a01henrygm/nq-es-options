"""The classic Q DATA All Tabs paste-in indicator, back in 1.24.4 next to Q DATA GEX and Q DATA Levels. TEST DATA ONLY."""
from backend.api_tabs import TABS
from tests.test_session_features import simulated_day


def test_script_is_stable_and_has_a_switch_per_tab():
    c, db, now = simulated_day()
    a = c.get("/api/tv/alltabs/script").json()
    code = a["code"]
    assert code == c.get("/api/tv/alltabs/script").json()["code"] and a["filename"].endswith(".pine")
    assert code.startswith("//@version=6") and 'indicator("Q DATA All Tabs"' in code
    assert 'dataTxt = input.text_area("", "Paste the levels from Q DATA here"' in code
    for i, (_k, v) in enumerate(TABS.items()):
        assert f't{i} = input.bool(true, "{v[0].replace("Q DATA ", "")}"' in code


def test_levels_include_every_tab_by_default():
    c, db, now = simulated_day()
    r = c.post("/api/tv/alltabs/levels", params={"underlying": "_NDX"}, json={}).json()
    assert r["text"].startswith("Q|1|") and r["levels"] > 0 and r["chars"] <= 30000
    seen = {x.split("|")[4] for x in r["text"].splitlines() if x.startswith("L|")}
    got = {t["tab"] for t in r["tabs"]}
    assert got | {s["tab"] for s in r["skipped"]} == set(TABS)           # every tab was tried
    assert len(seen) >= 5 and seen <= set(TABS)
    one = c.post("/api/tv/alltabs/levels", params={"underlying": "_NDX"}, json={"prefs": {"tabs_on": ["stackmap"]}}).json()
    assert {x.split("|")[4] for x in one["text"].splitlines() if x.startswith("L|")} <= {"stackmap"}


def test_bad_input_is_refused():
    c, db, now = simulated_day()
    assert c.post("/api/tv/alltabs/levels", params={"underlying": "_NDX", "convention": "nope"}, json={}).status_code == 422
