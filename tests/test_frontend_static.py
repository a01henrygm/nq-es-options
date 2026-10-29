"""Static checks on the dashboard files: things that must stay true so the screens stay clean, zoomable and remembered."""
import re
from pathlib import Path

FRONT = Path(__file__).resolve().parents[1] / "frontend"
JS = (FRONT / "app.js").read_text()
CSS = (FRONT / "style.css").read_text()
HTML = (FRONT / "index.html").read_text()


def tab_keys():
    block = JS[JS.index("const TABS = ["):JS.index("const RB = ")]
    return re.findall(r'\["([a-z]+)", "[^"]+"\]', block)


def test_every_tab_is_in_exactly_one_group_and_has_a_help_text():
    keys = tab_keys()
    assert len(keys) == 38 and len(set(keys)) == 38
    groups = JS[JS.index("const GROUPS = ["):JS.index("const HELP = {")]
    grouped = re.findall(r'"([a-z]+)"', groups)
    for k in keys:
        assert grouped.count(k) == 1, k                                                      # in exactly one navigation group
        assert re.search(rf'\n  {k}: \["', JS), f"no help text for the {k} tab"


def test_charts_can_be_zoomed_reset_and_filled_to_the_screen():
    assert "scrollZoom: true" in JS and 'doubleClick: "reset+autosize"' in JS and 'displayModeBar: "hover"' in JS
    for label in ("Zoom +", "Zoom -", "Reset", "Full screen"):
        assert label in JS
    assert "ZOOM[" in JS and "plotly_relayout" in JS                                          # zoom is remembered across the automatic refresh
    assert ".chartwrap.full" in CSS and "Escape" in JS


def test_settings_are_remembered_and_the_vol_surface_defaults_to_both():
    assert 'svview: "both"' in JS and 'localStorage.setItem("nqes.ui"' in JS and "loadUI();\nboot();" in JS
    for key in ('"svview"', '"svx"', '"svotm"', '"lvkey"', '"lvnear"', '"tab"', '"zoom"'):
        assert key in JS[JS.index("const UIKEYS"):JS.index("function loadUI")], key
    assert "S.u = us.includes(S.u) ? S.u : us[0]" in JS                                      # the chosen symbol is not reset to the first one


def test_refresh_does_not_wipe_what_you_are_doing():
    assert "userBusy()" in JS and "if (!userBusy()) render();" in JS
    assert "S.again = true" in JS and "if (S.again)" in JS                                         # a menu change made during a refresh is queued, not lost
    assert "SELECT" not in JS[JS.index("const userBusy"):JS.index("function persistDetails")]       # a drop-down that keeps focus must not block refreshes


def test_text_size_buttons_and_scalable_fonts():
    assert 'id="zm"' in HTML and 'id="zp"' in HTML and "--z" in CSS and "calc(14px*var(--z))" in CSS
    assert not re.search(r"font-size:\d+px", CSS.split("@media print")[0])                      # sizes are relative, so the text-size buttons scale everything


def test_levels_tab_is_grouped_not_a_wall_of_checkboxes():
    block = JS[JS.index("const FAMILIES"):JS.index("const ALLCATS")]
    assert block.count('"#') >= 6 and "data-fam" in JS and 'data-k="lv-more"' in JS and "data-gotv" in JS
    assert "data-cat=" not in JS


def test_plus_window_button_opens_another_window_on_the_same_page():
    assert 'id="newwin"' in HTML and "/api/desktop/new-window" in JS and 'q.get("tab")' in JS and "EXTRA_WINDOW" in JS
    app = (FRONT.parent / "desktop" / "app.py").read_text()
    assert '"/api/desktop/new-window", new_window, "POST"' in app and "webview.create_window(f\"{APP_NAME} ({n})\"" in app
