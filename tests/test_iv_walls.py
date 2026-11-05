"""IV walls (1.35.0): vega walls, IV spikes and the skew flip, and where they show up. TEST DATA ONLY."""
from datetime import date

from backend.services import iv_walls as ivw
from backend.services import tv_levels as tv
from backend.services.importance import parse_quota
from backend.services.stack import family_of
from backend.services.tv_pine import ALL_SECTIONS, COMBO_SECTIONS, COMBO_IV, COMBO_YOURS, build_script, combo_sec_all, combo_sec_kl
from tests.conftest import NOW, make_chain
from tests.test_session_features import simulated_day

SPOT = 500.0


def smile_chain(bump_at=None, bump=0.02, big_put=None):
    cons = make_chain(spot=SPOT, n_strikes=41, step=2.5, iv=0.2, expiry=date(2026, 10, 21))
    for c in cons:
        m = c.strike / SPOT - 1
        c.iv = 0.20 - 0.6 * m + 10 * m * m                         # put skew, bottom 3% above price
        if c.strike == bump_at:
            c.iv += bump
        if c.strike == big_put and c.right == "P":
            c.oi = 20000.0
    return cons


def test_skew_flip_is_the_bottom_of_the_smile():
    f = ivw.skew_flips(smile_chain(), SPOT, NOW)
    assert len(f) == 1 and abs(f[0]["strike"] - 515) < 2.5 and f[0]["put_side_iv"] > f[0]["iv"] < f[0]["call_side_iv"]
    flat = make_chain(spot=SPOT, n_strikes=41, step=2.5, iv=0.2, expiry=date(2026, 10, 21))
    assert ivw.skew_flips(flat, SPOT, NOW) == []                     # no smile, no flip


def test_iv_spikes_need_a_real_bump_and_real_contracts():
    assert ivw.iv_spikes(smile_chain(), SPOT, NOW) == []             # a smooth smile has no spikes
    s = ivw.iv_spikes(smile_chain(510.0), SPOT, NOW)
    assert [x["strike"] for x in s] == [510.0] and abs(s[0]["bump"] - 0.02) < 0.005
    thin = smile_chain(510.0)
    for c in thin:
        if c.strike == 510.0:
            c.oi, c.volume = 10.0, 5.0
    assert ivw.iv_spikes(thin, SPOT, NOW) == []                      # too few contracts there: likely a bad quote, not a wall


def test_vega_walls_follow_open_interest_weighted_by_vega():
    z, n = ivw.vega_walls(smile_chain(big_put=480.0), SPOT, NOW, 2)
    assert n > 0 and z and z[0]["side"] == "put" and z[0]["center"] == 480.0 and z[0]["low"] < 480 < z[0]["high"]
    assert ivw.bs_vega_point(SPOT, SPOT, 0.1, 0.2) > ivw.bs_vega_point(SPOT, 560, 0.1, 0.2) > 0     # vega is biggest at the money


def test_iv_walls_have_their_own_section_and_kept_every_other_section_in_place():
    assert tv.LV_SECTIONS[-1] == "IV walls" and tv.LV_SECTIONS[tv.HEAT_SECTION] == "Heatmap" and tv.LV_TABS["ivwalls"] == 12
    assert tv.KL_SECTIONS[tv.KL_YOURS] == "Your levels" and tv.KL_YOURS == 10 and tv.KL_SECTIONS[-1] == "IV walls"
    assert COMBO_SECTIONS[COMBO_YOURS] == "Your levels" and COMBO_YOURS == 16 and COMBO_SECTIONS[COMBO_IV] == "IV walls"
    assert combo_sec_all(len(ALL_SECTIONS) - 1) == COMBO_IV and combo_sec_kl(tv.KL_YOURS) == COMBO_YOURS and combo_sec_kl(tv.KL_IV) == COMBO_IV
    assert tv.kl_section("iv_skew_flip", "IV wall: skew flip") == tv.KL_IV and tv.call_category("IV wall: skew flip") == "other"
    assert tv.is_live("IV wall: spike") and not tv.is_live("IV wall: vega") and family_of("iv_vega_wall") is None
    assert parse_quota("gex:8,iv:2")["iv"] == 2
    code = build_script("combo", "NDX")
    assert 'str.contains(n, "iv wall")' in code                     # not a "best zone" and not a break level


def test_iv_walls_reach_the_levels_tab_the_iv_tab_and_the_combined_indicator():
    c, db, now = simulated_day()
    lv = c.get("/api/analytics/levels", params={"underlying": "_NDX"}).json()["levels"]
    assert any(x["category"] == "iv_vega_wall" for x in lv)
    key = c.get("/api/analytics/levels", params={"underlying": "_NDX", "key": 10}).json()["zones"]
    assert not any(x["category"].startswith("iv_") for x in key)    # the Key levels top N is unchanged
    q = c.get("/api/analytics/levels", params={"underlying": "_NDX", "quota": "gex:4,iv:2"}).json()["zones"]
    assert any(x.get("slot") == "iv" for x in q)
    j = c.post("/api/tv/combo/levels", params={"ticker": "NDX"}, json={}).json()
    ks = [k for k in j["kinds"] if k["name"].startswith("IV wall")]
    assert ks and all(k["sec"] == COMBO_IV for k in ks)
    assert all(k["sec"] != COMBO_IV for k in j["kinds"] if not k["name"].startswith("IV wall"))
