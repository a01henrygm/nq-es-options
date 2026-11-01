"""Strat QS (1.31.0): the Q DATA Gamma Strategy script, its API route and the tab. TEST DATA ONLY."""
from pathlib import Path

from backend.services import strat_qs
from tests.test_session_features import simulated_day

FRONT = Path(__file__).resolve().parents[1] / "frontend"


def lines(text, tag):
    return [x.split("|") for x in text.splitlines() if x.startswith(tag + "|")]


def test_strategy_script_is_pine_v6_ascii_with_two_paste_boxes_first():
    code = strat_qs.CODE
    assert code.startswith("//@version=6") and 'strategy("Q DATA Gamma Strategy"' in code
    assert all(ord(ch) < 128 for ch in code)                                    # non-ASCII comments break the Pine parser
    inputs = [x for x in code.splitlines() if " input." in x and not x.startswith(" ")]
    assert inputs[0].startswith("gexTxt    = input.text_area") and inputs[1].startswith("lvTxt     = input.text_area")
    assert 'str.split(txt, "\\n")' in code                                     # the raw string keeps the newline escape for Pine
    for need in ("Data delay (minutes)", "Trade only the pasted day", "Show every setup", "Position boxes", "alert(", "strategy.exit("):
        assert need in code, need


def test_strategy_reads_the_fields_where_the_levels_text_puts_them():
    code = strat_qs.CODE
    # L|price|low|high|kind|start ms|end ms|read|prev|label|tip  (tv_levels.py)
    assert "array.size(a) >= 10" in code and "f_num(a, 1)" in code and "f_num(a, 4)" in code
    assert "lvS.push(f_num(a, 5))" in code and "lvE.push(f_num(a, 6))" in code and "lvR.push(f_fld(a, 7))" in code
    assert 'tag == "Q"' in code and "day := f_fld(a, 4)" in code                   # Q|2|ind|made|day|...


def test_strategy_kind_names_match_what_q_data_exports():
    c, _db, _now = simulated_day()
    g = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex"}).json()
    names = [k[1].lower() for k in lines(g["text"], "K")]
    assert any("flip" in n and "0dte" not in n for n in names)                 # S1 needs the gamma flip
    assert any("call wall" in n and "zone" not in n for n in names)            # plain or 0DTE call wall (the strategy takes either)
    assert any("put wall" in n and "zone" not in n for n in names)
    assert 'c := str.contains(n, "0dte") ? 12 : 3' in strat_qs.CODE and "callW := f_catPx(12)" in strat_qs.CODE
    assert lines(g["text"], "L")


def test_script_route_and_tab():
    c, _db, _now = simulated_day()
    r = c.get("/api/tv/strat/script").json()
    assert r["code"] == strat_qs.CODE and r["filename"].endswith(".pine") and r["title"] == "Q DATA Gamma Strategy"
    js = (FRONT / "strat.js").read_text()
    assert "R.stratqs = async function" in js and "/tv/strat/script" in js
    assert "prefs: { kinds: {} }" in js                                         # strategy copies ignore kinds hidden on the TradingView tab
    html = (FRONT / "index.html").read_text()
    assert html.index('src="tv.js"') < html.index('src="strat.js"')              # strat.js uses tvFetch from tv.js
