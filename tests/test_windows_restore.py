"""Window list kept across restarts (1.33.0). TEST DATA ONLY."""
from desktop.windows import WindowStore


def test_windows_and_pages_survive_a_restart(tmp_path):
    p = tmp_path / "windows.json"
    w = WindowStore(p)
    assert w.to_restore() == [] and w.main == {"tab": "", "u": ""}
    a = w.add("tv", "_NDX")
    b = w.add("levels", "QQQ")
    assert (a["n"], b["n"]) == (2, 3)
    assert w.update("main", "playbook", "_NDX") and w.update(3, "gex", "") and not w.update(9, "x", "y")
    again = WindowStore(p)                                   # the app quit and started again
    assert again.main == {"tab": "playbook", "u": "_NDX"}
    assert again.to_restore() == [{"n": 2, "tab": "tv", "u": "_NDX"}, {"n": 3, "tab": "gex", "u": "QQQ"}]
    again.remove(2)                                          # closed by hand while running
    assert [x["n"] for x in WindowStore(p).to_restore()] == [3]
    assert WindowStore(p).add("home", "_NDX")["n"] == 2       # the free number is reused


def test_bad_input_is_cleaned_and_damaged_file_ignored(tmp_path):
    p = tmp_path / "windows.json"
    p.write_text("{not json")
    w = WindowStore(p)
    r = w.add("t<v>!", "QQQ;rm")
    assert r["tab"] == "tv" and r["u"] == "QQQrm"
    for _ in range(20):
        w.add("home", "")
    assert len(w.to_restore()) == 8
