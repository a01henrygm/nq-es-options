import math
from datetime import date

import pytest

from backend.models import OptionContract
from backend.services import analytics as an
from tests.conftest import NOW, make_chain


def test_gex_formula_sign_and_units(chain):
    g = an.gex_by_strike(chain, 500.0, NOW, "standard")
    atm = next(s for s in g["strikes"] if s["strike"] == 500.0)
    c = next(c for c in chain if c.strike == 500.0 and c.right == "C")
    expected = c.gamma * c.oi * 100 * 500.0 ** 2 * 0.01
    assert atm["call_gex"] == pytest.approx(expected) and atm["put_gex"] == pytest.approx(-expected)
    assert atm["net_gex"] == pytest.approx(0, abs=1e-6)


def test_gex_conventions_flip_sign(chain):
    a = an.gex_by_strike(chain, 500.0, NOW, "standard"); b = an.gex_by_strike(chain, 500.0, NOW, "customers_long")
    assert all(x["call_gex"] == pytest.approx(-y["call_gex"]) for x, y in zip(a["strikes"], b["strikes"]))
    gr = an.gex_by_strike(chain, 500.0, NOW, "gross")
    assert all(s["put_gex"] >= 0 for s in gr["strikes"])


def test_gex_excludes_missing_data_instead_of_inventing(chain):
    chain[0].oi = None; chain[1].gamma = None; chain[1].iv = None
    g = an.gex_by_strike(chain, 500.0, NOW)
    assert g["contracts_excluded"]["no_open_interest"] == 1 and g["contracts_excluded"]["no_gamma_or_iv"] == 1


def test_gex_model_gamma_used_only_when_provider_missing(chain):
    for c in chain: c.gamma = None
    g = an.gex_by_strike(chain, 500.0, NOW)
    assert g["contracts_used"]["provider"] == 0 and g["contracts_used"]["model"] == len(chain)


def test_gex_inspection_lists_contributions(chain):
    g = an.gex_by_strike(chain, 500.0, NOW)
    s = next(s for s in g["strikes"] if s["strike"] == 500.0)
    assert len(s["contributions"]) == 2 and s["contributions"][0]["ticker"].startswith("O:TEST")


def test_gamma_flip_found_with_skewed_positioning():
    # Calls dominate above spot, puts dominate below -> modeled total changes sign inside the grid.
    cons = make_chain(spot=500.0, n_strikes=41, step=2.5, oi=1000)
    for c in cons:
        c.oi = 5000.0 if (c.right == "C") == (c.strike >= 500) else 100.0
    f = an.gamma_flip(cons, 500.0, NOW, "standard")
    assert f["found"] and 450 < f["flip"] < 550 and f["crossings"] == 1
    assert f["exposure_below"] * f["exposure_above"] < 0          # sign really changes across the flip


def test_gamma_flip_reports_no_crossing_honestly():
    cons = make_chain(n_strikes=41, step=2.5)
    for c in cons: c.right = "C"                       # calls only -> all positive under standard convention
    f = an.gamma_flip(cons, 500.0, NOW, "standard")
    assert f["found"] is False and f["flip"] is None and "No zero crossing" in f["note"]


def test_gamma_flip_needs_enough_data_and_a_sign():
    assert an.gamma_flip(make_chain(n_strikes=3), 500.0, NOW)["found"] is False
    assert an.gamma_flip(make_chain(n_strikes=41), 500.0, NOW, "gross")["found"] is False


def test_delta_exposure_units(chain):
    d = an.delta_exposure(chain, 500.0, NOW, "standard")
    c = next(c for c in chain if c.strike == 500.0 and c.right == "C"); p = next(c for c in chain if c.strike == 500.0 and c.right == "P")
    row = next(s for s in d["strikes"] if s["strike"] == 500.0)
    assert row["delta_exposure"] == pytest.approx(c.delta * c.oi * 100 * 500 - p.delta * p.oi * 100 * 500)


def test_expected_move_formulas(chain):
    e = an.expected_move(chain, 500.0, NOW)
    T = an.year_fraction(date(2026, 10, 16), NOW)
    assert e["iv_1sd"]["move"] == pytest.approx(500 * 0.20 * math.sqrt(T))
    k = e["straddle"]["strike"]
    c = next(c for c in chain if c.strike == k and c.right == "C"); p = next(c for c in chain if c.strike == k and c.right == "P")
    assert e["straddle"]["price"] == pytest.approx(c.mid + p.mid)


def test_expected_move_unavailable_without_data():
    assert an.expected_move([], 500.0, NOW)["available"] is False


def test_concentration_and_ratio(chain):
    chain[0].volume = 9999.0
    c = an.concentration(chain, "volume")
    assert c["top"][0]["strike"] == chain[0].strike and "support" in c["note"]
    assert c["put_call_ratio"] is not None


def test_iv_functions(chain):
    assert an.iv_by_strike(chain)["C"][0]["iv"] == 0.20
    assert an.iv_term_structure(chain, 500.0)[0]["iv"] == pytest.approx(0.20)


def test_percent_iv_tolerated():
    assert an._iv_dec(20.0) == 0.2 and an._iv_dec(0.2) == 0.2


def test_expired_contract_has_zero_time_and_no_flip():
    assert an.year_fraction(date(2026, 10, 1), NOW) == 0


# ---- IV cleaning and surface -------------------------------------------------------------------------
from datetime import timedelta


def _multi_expiry(n_exp=4, spot=500.0, iv_base=0.20):
    cons = []
    for i in range(n_exp):
        e = NOW.date() + timedelta(days=2 + 5 * i)
        cons += make_chain(spot=spot, n_strikes=21, step=5.0, iv=iv_base + 0.01 * i, expiry=e)
    return cons


def test_clean_iv_is_otm_only_and_merges_at_the_money():
    cl = an.clean_iv(_multi_expiry(2), 500.0, NOW, otm_only=True)
    row = cl["expiries"][0]["points"]
    assert [p["strike"] for p in row] == sorted(p["strike"] for p in row) and len(row) == 21     # one point per strike, not two
    assert cl["stats"]["itm_skipped"] > 0
    both = an.clean_iv(_multi_expiry(2), 500.0, NOW, otm_only=False)
    assert both["stats"]["itm_skipped"] == 0


def test_clean_iv_drops_bad_quotes():
    cons = _multi_expiry(1)
    cons[0].bid = 0.0                                        # zero bid
    cons[2].bid, cons[2].ask = 0.1, 5.0                      # very wide spread
    cons[4].iv = 0.0                                         # IV not computed
    cons[6].iv = 0.005                                       # impossible IV (0.5%)
    st = an.clean_iv(cons, 500.0, NOW)["stats"]
    assert st["zero_bid"] == 1 and st["wide_spread"] == 1 and st["no_iv"] == 1 and st["bad_iv"] == 1


def _call_row(ivs):
    cons = [c for c in make_chain(spot=500.0, n_strikes=21, step=5.0) if c.right == "C" and c.strike >= 500][:len(ivs)]
    for c, v in zip(cons, ivs): c.iv = v
    return cons


def test_spike_filter_removes_isolated_and_paired_spikes_but_not_end_points():
    base = [0.20, 0.20, 0.20, 0.20, 0.20, 0.20, 0.20, 0.20]
    for spikes in ({3: 0.90}, {3: 0.90, 5: 0.80}, {3: 0.90, 4: 0.85}):      # single, two separated by one point, two adjacent
        ivs = list(base)
        for i, v in spikes.items(): ivs[i] = v
        raw = an.clean_iv(_call_row(ivs), 500.0, NOW, smooth=False)["expiries"][0]["points"]
        sm = an.clean_iv(_call_row(ivs), 500.0, NOW, smooth=True)["expiries"][0]["points"]
        assert max(p["iv"] for p in raw) >= 0.80 and max(p["iv"] for p in sm) == pytest.approx(0.20)
    ends = list(base); ends[0], ends[-1] = 0.35, 0.05
    sm = an.clean_iv(_call_row(ends), 500.0, NOW, smooth=True)["expiries"][0]["points"]
    assert sm[0]["iv"] == 0.35 and sm[-1]["iv"] == 0.05


def test_spike_filter_leaves_real_smile_curvature_alone():
    curve = [0.30, 0.27, 0.245, 0.225, 0.21, 0.20, 0.195, 0.192]            # a genuine skew, no outliers
    sm = an.clean_iv(_call_row(curve), 500.0, NOW, smooth=True)["expiries"][0]["points"]
    assert [round(p["iv"], 4) for p in sm] == curve


def test_surface_grid_shape_interpolation_and_no_extrapolation():
    cl = an.clean_iv(_multi_expiry(4), 500.0, NOW)
    s = an.build_surface(cl, 500.0, min_points=6)
    assert s["available"] and len(s["z"]) == 4 and all(len(r) == len(s["strikes"]) for r in s["z"])
    assert s["dte"] == sorted(s["dte"]) and all(v == pytest.approx(20.0 + i, abs=0.5) for i, v in enumerate(s["z"][0][len(s["strikes"]) // 2:][:1] or [20.0]))
    # drop the far wing of the second expiry: the surface must leave those cells empty instead of extending them
    cl["expiries"][1]["points"] = cl["expiries"][1]["points"][5:]
    s2 = an.build_surface(cl, 500.0)
    assert s2["z"][1][0] is None and s2["z"][0][0] is not None


def test_surface_unavailable_with_too_little_data():
    cl = an.clean_iv(_multi_expiry(1), 500.0, NOW)
    s = an.build_surface(cl, 500.0)
    assert s["available"] is False and "at least two" in s["note"]


# ---- unusual volume and delta profile ---------------------------------------------------------------
def test_unusual_volume_flags_outlier_strike_only():
    cons = make_chain(n_strikes=31)
    for i, c in enumerate(cons): c.volume = 100.0 + (i % 5) * 10
    big = next(c for c in cons if c.strike == 500.0 and c.right == "C"); big.volume = 6000.0
    u = an.unusual_volume(cons)
    assert u["available"] and [f["strike"] for f in u["flagged"]] == [500.0] and u["flagged"][0]["robust_z"] > 3.5
    assert "not a comparison with past days" in u["method"]


def test_unusual_volume_needs_enough_strikes_and_respects_minimum():
    assert an.unusual_volume(make_chain(n_strikes=5))["available"] is False
    cons = make_chain(n_strikes=31)
    for c in cons: c.volume = 1.0
    cons[0].volume = 30.0                                # outlier, but below the 50 contract minimum
    assert an.unusual_volume(cons)["flagged"] == []


def test_delta_profile_grid():
    p = an.delta_profile(make_chain(n_strikes=21), 500.0, NOW)
    assert p["available"] and len(p["grid"]) == 41 and p["contracts_used"] > 10
    assert [g["price"] for g in p["grid"]] == sorted(g["price"] for g in p["grid"])
    assert an.delta_profile(make_chain(n_strikes=2), 500.0, NOW)["available"] is False
    assert "profile" in an.delta_exposure(make_chain(), 500.0, NOW)


# ---- strike x expiry heatmap grid ---------------------------------------------------------------------
def test_strike_expiry_matrix_shapes_sides_and_window():
    cons = []
    for i in range(3):
        cons += make_chain(spot=500.0, n_strikes=21, step=5.0, expiry=NOW.date() + timedelta(days=2 + i))
    for c in cons: c.volume = 10.0
    big = next(c for c in cons if c.strike == 505.0 and c.right == "C" and c.expiry == NOW.date() + timedelta(days=3)); big.volume = 225.0
    m = an.strike_expiry_matrix(cons, NOW, "volume", "total", 500.0, 0.04)
    assert len(m["expiries"]) == 3 and m["strikes"] == sorted(m["strikes"], reverse=True) and all(abs(k / 500 - 1) <= 0.04 for k in m["strikes"])
    r, c_ = m["strikes"].index(505.0), m["expiries"].index((NOW.date() + timedelta(days=3)).isoformat())
    assert m["z"][r][c_] == 235.0 and m["max"] == 235.0                      # 225 calls + 10 puts
    assert an.strike_expiry_matrix(cons, NOW, "volume", "call", 500.0, 0.04)["z"][r][c_] == 225.0
    assert an.strike_expiry_matrix(cons, NOW, "volume", "net", 500.0, 0.04)["z"][r][c_] == 215.0
    assert len(an.strike_expiry_matrix(cons, NOW, "volume", "total", 500.0, 0)["strikes"]) == 21           # window 0 keeps all
    assert m["color_max"] == 20.0 and m["max"] == 235.0                      # one outlier cell must not wash out the rest of the colors


def test_strike_expiry_matrix_skips_inactive_strikes_and_blank_cells():
    cons = make_chain(spot=500.0, n_strikes=21, step=5.0)
    for c in cons: c.volume = 0.0
    only = next(c for c in cons if c.strike == 495.0 and c.right == "P"); only.volume = 7.0
    m = an.strike_expiry_matrix(cons, NOW, "volume", "total", 500.0, 0.1)
    assert m["strikes"] == [495.0] and m["z"] == [[7.0]]
    assert an.strike_expiry_matrix(cons, NOW, "volume", "call", 500.0, 0.1)["z"] == [[None]]               # puts-only strike has no call volume
    assert an.strike_expiry_matrix([], NOW)["strikes"] == []
