"""1.23: the All indicators tab, near-price zones for key and GEX levels, and vivid see-through colors. TEST DATA ONLY."""
from pathlib import Path

from backend.services.level_kinds import CAT
from backend.services.paste_pine import build_paste_script
from backend.services.tab_pine import INK_FUNCS, SETTINGS
from tests.test_session_features import simulated_day

ROOT = Path(__file__).resolve().parents[1]


def test_all_indicators_tab_lists_every_indicator():
    js, app = (ROOT / "frontend" / "indicators.js").read_text(), (ROOT / "frontend" / "app.js").read_text()
    assert '["indicators", "All indicators"]' in app and '<script src="indicators.js"></script>' in (ROOT / "frontend" / "index.html").read_text()
    for route in ("/export/levels-script", "/export/hodlod-pine", "/export/heatmap-pine", "/export/tab-pine", "tvScript()", "tvLevels()", "indicatorText("):
        assert route in js, route
    assert "TAB_PINE" in js and "Download every one" in js


def test_key_and_gex_levels_near_price_are_zones_and_settings_come_last():
    code = build_paste_script([("stackmap", "Stack map"), ("gex", "GEX by strike")])
    assert 'kzMode   = input.string("Near price", "Draw as zones", options = ["Near price", "All of them", "Off"]' in code
    inputs = [l for l in code.splitlines() if "input." in l and not l.startswith(" ")]
    assert inputs[-1].startswith("kzTransp")                                   # new settings are last: older settings keep their place
    assert "kzWant(i)" in code and 'str.contains(lw, "gex")' in code and "bgcolor = color.new(c, kz ? kzTransp : zoneTransp)" in code
    assert [s["var"] for s in SETTINGS][-4:] == ["kzMode", "kzNear", "kzH", "kzTransp"]


def test_tab_indicator_draws_near_key_and_gex_zones():
    c, db, now = simulated_day()
    code = None
    for tab in ("gex", "zerodte", "stackmap", "levelmap"):
        r = c.get("/api/export/tab-pine", params={"tab": tab, "underlying": "_NDX"})
        if r.status_code == 200:
            code = r.json()["code"]
            break
    assert code
    assert 'kzMode = input.string("Near price"' in code and "kzWant(kindI" in code and "kzI ? kzTransp : zoneTransp" in code


def test_colors_are_vivid_and_fills_see_through():
    assert CAT["gex0_call_wall"][1] == "#00e5ff" and CAT["gamma_flip"][1] == "#ffc400" and CAT["gex_put_zone"][1] == "#ff3b30"
    ink = "\n".join(INK_FUNCS)
    assert "* 1.3" in ink and "lum > 165" in ink                                # saturation boost; only very light colors darkened on white
    zt = {s["var"]: s["default"] for s in SETTINGS}
    assert 55 <= zt["kzTransp"] < zt["zTransp"] <= 75 and zt["zoneTransp"] <= 72  # see-through, never solid
    pine = (ROOT / "tradingview" / "options_levels_indicator.pine").read_text()
    assert "Zones near price, lines farther" in pine and "lzNear" in pine and "* 1.3" in pine
    assert all(ord(ch) < 128 for ch in pine)
