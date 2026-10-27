"""Q DATA All Tabs as a paste-in indicator: the script once, the levels text each session. TEST DATA ONLY."""
import re

from backend.services.paste_pine import MAX_CHARS, build_levels_text, build_paste_script, is_key_kind
from tests.test_session_features import simulated_day
from tests.test_tab_pine import external_elements


def test_script_is_the_same_every_day_and_has_a_paste_box():
    c, db, now = simulated_day()
    a = c.get("/api/export/all-script").json()
    assert a["code"] == c.get("/api/export/all-script").json()["code"] and a["filename"].endswith(".pine")
    code = a["code"]
    assert code.startswith("//@version=6") and 'indicator("Q DATA All Tabs"' in code
    assert 'dataTxt = input.text_area("", "Paste the levels from Q DATA here"' in code
    assert "Clean: zones + key lines" in code and "qdLevelsIn(dataTxt)" in code and "hexColor(" in code
    tabs = c.get("/api/export/tab-pine/tabs").json()["tabs"]
    for i, t in enumerate(tabs):
        assert f't{i} = input.bool(true, "{t["title"].replace("Q DATA ", "")}"' in code
    assert "display =" not in code and re.search(r"\blow =", code) is None          # no names that hide Pine built-ins


def test_no_function_reads_too_many_settings_and_names_are_unique():
    code = build_paste_script([(f"k{i}", f"Tab {i}") for i in range(40)])
    ext = external_elements(code)
    assert max(ext.values()) <= 120, sorted(ext.items(), key=lambda x: -x[1])[:4]
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
    for fn in re.findall(r"^\s+for \w+ = 0 to (.+?) - 1$", code, re.M):         # every 0..n-1 loop is guarded (Pine counts down when n is 0)
        assert fn


def test_levels_text_carries_the_look_and_marks_key_lines():
    c, db, now = simulated_day()
    j = c.post("/api/export/all-levels", params={"underlying": "_NDX"}, json={}).json()
    text = j["text"]
    assert text.startswith("Q|1|") and j["chars"] == len(text) < MAX_CHARS
    assert sorted(t["tab"] for t in j["tabs"] if t["on"]) == ["gameplan", "hodlod", "session", "stackmap"]
    L = [l.split("|") for l in text.splitlines() if l.startswith("L|")]
    K = [l.split("|") for l in text.splitlines() if l.startswith("K|")]
    assert len(L) == j["levels"] > 10 and all(len(x) == 10 for x in L) and all(re.fullmatch(r"#[0-9a-f]{6}", k[2]) for k in K)
    assert {x[4] for x in L} <= {"gameplan", "hodlod", "session", "stackmap"} and all(int(x[5]) < len(K) for x in L)
    keys = [x for x in L if x[6] == "1"]
    assert 0 < len(keys) < len(L) and j["key_lines"] == len(keys)
    assert any(x[8] == "HOD 80%" for x in keys) and not any(x[8] == "HOD 50%" for x in keys)       # of the projections, only 80% is a key line
    assert any(r.startswith("R|*|") for r in text.splitlines()) and "C|" in text                  # head rows and the Session cone
    # the look chosen in Q DATA travels in the text
    kind = next(k for k in j["kinds"] if k["name"] == "Gamma flip")
    assert kind["key"] is True and "Session" in kind["tabs"]
    prefs = {"tabs_on": ["session"], "kinds": {"Gamma flip": {"color": "#abcdef", "style": "dotted", "width": 4, "key": False}, "Call wall": {"on": False}}}
    t2 = c.post("/api/export/all-levels", params={"underlying": "_NDX"}, json={"prefs": prefs}).json()["text"]
    assert "K|Gamma flip|#abcdef|O|4|" in t2 and "Call wall" not in t2
    flip = next(l.split("|") for l in t2.splitlines() if l.startswith("L|") and l.split("|")[8] == "Gamma flip")
    assert flip[6] == "0" and {l.split("|")[4] for l in t2.splitlines() if l.startswith("L|")} == {"session"}


def test_long_texts_drop_hover_text_then_far_levels():
    secs = [{"tab": "stackmap", "name": "S", "groups": ["Open interest strikes", "Gamma flip"],
             "levels": [{"price": 20000 + i, "group": 0 if i else 1, "label": f"OI {i}", "tip": "x" * 200} for i in range(1200)], "table": []}]
    out = build_levels_text(secs, [], "now", "2026-10-27", "NDX", "u", spot=20100)
    assert out["chars"] <= MAX_CHARS and out["tips_dropped"] and out["cut"] > 0
    assert "Gamma flip" in out["text"] and "L|20100.00|" in out["text"] and "L|21150.00|" not in out["text"]           # key levels and the ones nearest price are kept
    assert is_key_kind("0DTE call wall") and is_key_kind("High of day so far") and not is_key_kind("GEX call wall zones") and not is_key_kind("Volume strikes")
    txt = build_levels_text([{"tab": "s", "name": "S", "groups": ["A|B"], "levels": [{"price": 1.0, "group": 0, "label": "x|y"}], "table": []}], [], "", "", "", "")["text"]
    assert "K|A/B|" in txt and "|x/y|" in txt                                     # a | inside a name never breaks the fields
