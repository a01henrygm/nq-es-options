"""Pin scoring and stack stats in the reaction log (1.32.0). TEST DATA ONLY."""
from datetime import datetime, timedelta
from backend.services import reactions as rx


def path(prices, start=datetime(2026, 11, 4, 15, 0)):
    return [(start + timedelta(minutes=2 * i), p) for i, p in enumerate(prices)]


def test_small_poke_through_is_pinned_not_broke():
    # approaches 100 from below, sits on it: never more than the band away afterwards
    px = path([99.0, 99.5, 100.0] + [100.02, 99.99, 100.03, 100.01] * 6)
    t = rx.analyze([{"label": "A", "category": "gex_pos_zone", "value": 100.0}], px, tol=0.0005)[0]
    assert t["outcome_15"] == "pinned" and t["held_15"] is None
    s = rx.summarize([t])[0]
    assert s["pinned_15"] == 1 and s["measured_15"] == 0


def test_real_break_and_hold_still_scored():
    up = path([99.0, 99.5, 100.0] + [101.0] * 20)
    dn = path([99.0, 99.5, 100.0] + [98.0] * 20)
    lv = [{"label": "A", "category": "x", "value": 100.0}]
    assert rx.analyze(lv, up)[0]["outcome_15"] == "broke"
    assert rx.analyze(lv, dn)[0]["outcome_15"] == "held"


def test_stacked_kinds_count_once():
    px = path([99.0, 99.5, 100.0] + [98.0] * 20)
    lv = [{"label": k, "category": k, "value": 100.0} for k in ("gex_pos_zone", "gex_call_zone", "oi_call_zone", "dex_pos_zone")]
    lv.append({"label": "solo", "category": "gamma_flip", "value": 99.0})
    tc = rx.analyze(lv, px)
    st = {r["stack"]: r for r in rx.summarize_stacks(tc)}
    assert st["4+ kinds"]["events"] == 1 and st["4+ kinds"]["held_pct_15"] == 1.0
    assert len(rx.stacks(tc)) == sum(r["events"] for r in st.values())
