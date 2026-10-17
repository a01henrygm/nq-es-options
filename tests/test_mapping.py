from datetime import date, datetime, timedelta

import pytest

from backend.services.mapping import PricePoint, contract_expiry, evaluate_methods, map_level, pair_observations, roll_status
from backend.timeutil import UTC

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)


def pp(sym, price, age_s=0, manual=False): return PricePoint(sym, price, NOW - timedelta(seconds=age_s), "test", None, manual)


def test_ratio_mapping_exact():
    m = map_level(500.0, "QQQ", pp("QQQ", 500.0), pp("NQ", 21000.0), NOW)
    assert m["method"] == "ratio" and m["mapped"] == pytest.approx(21000.0) and m["status"] == "ok"
    assert map_level(510.0, "QQQ", pp("QQQ", 500.0), pp("NQ", 21000.0), NOW)["mapped"] == pytest.approx(21420.0)


def test_basis_mapping_for_index_and_rejected_for_etf():
    m = map_level(21050.0, "I:NDX", pp("I:NDX", 21000.0), pp("NQ", 21100.0), NOW)
    assert m["method"] == "basis" and m["mapped"] == pytest.approx(21150.0)
    bad = map_level(500.0, "QQQ", pp("QQQ", 500.0), pp("NQ", 21000.0), NOW, method="basis")
    assert bad["status"] == "invalid" and bad["mapped"] is None


def test_stale_asynchronous_and_missing_are_flagged():
    assert map_level(500.0, "QQQ", pp("QQQ", 500.0, 3600), pp("NQ", 21000.0, 3600), NOW)["status"] == "stale"
    a = map_level(500.0, "QQQ", pp("QQQ", 500.0, 900), pp("NQ", 21000.0, 0), NOW)
    assert a["status"] == "asynchronous" and any("apart" in w for w in a["warnings"])
    assert map_level(500.0, "QQQ", PricePoint("QQQ", 500.0, None), pp("NQ", 21000.0), NOW)["status"] == "degraded"
    assert map_level(500.0, "QQQ", pp("QQQ", 500.0), PricePoint("NQ", None, None), NOW)["status"] == "unavailable"


def test_manual_futures_price_is_disclosed():
    m = map_level(500.0, "QQQ", pp("QQQ", 500.0), pp("NQ", 21000.0, 0, True), NOW)
    assert m["futures_price_manual"] and any("typed in by hand" in w for w in m["warnings"])


def test_contract_codes_and_roll():
    assert contract_expiry("NQZ6", date(2026, 10, 14)) == date(2026, 12, 18)
    assert contract_expiry("ESH27", date(2026, 10, 14)) == date(2027, 3, 19)
    assert contract_expiry("MNQM6", date(2026, 1, 1)) == date(2026, 6, 19)
    assert contract_expiry("junk") is None
    assert roll_status("NQZ6", date(2026, 12, 14))["status"] == "roll_soon"
    assert roll_status("NQZ6", date(2026, 12, 20))["status"] == "expired"
    assert roll_status("NQZ6", date(2026, 10, 14))["status"] == "ok"


def _hist(prices, sym, step=60):
    return [{"price": p, "source_ts": (NOW + timedelta(seconds=i * step)).isoformat(), "retrieved_at": NOW.isoformat()} for i, p in enumerate(prices)]


def test_evaluate_methods_measures_error_on_synthetic_pairs():
    etf = [500 + i * 0.1 for i in range(30)]
    fut = [e * 42.0 + 3.0 for e in etf]              # exact ratio plus a constant: ratio must beat basis
    pairs = pair_observations(_hist(etf, "QQQ"), _hist(fut, "NQ"))
    r = evaluate_methods(pairs)
    assert r["available"] and r["n"] == 29 and r["ratio"]["mae"] < r["basis"]["mae"] and r["best"] == "ratio"


def test_evaluate_methods_needs_history():
    assert evaluate_methods([])["available"] is False


def test_pairing_drops_unsynchronized_prices():
    pairs = pair_observations(_hist([500.0], "QQQ"), _hist([21000.0], "NQ", 0)[:0] + [{"price": 21000.0, "source_ts": (NOW + timedelta(hours=1)).isoformat(), "retrieved_at": None}])
    assert pairs == []


def test_typed_basis_mapping_and_staleness():
    from backend.services.mapping import map_with_typed_basis
    m = map_with_typed_basis(29900.0, "_NDX", 29890.0, 260.0, NOW - timedelta(minutes=30), NOW)
    assert m["mapped"] == pytest.approx(30160.0) and m["method"] == "typed_basis" and m["status"] == "ok" and "typed in" in m["warnings"][0]
    old = map_with_typed_basis(29900.0, "_NDX", 29890.0, -15.5, NOW - timedelta(hours=8), NOW)
    assert old["status"] == "stale" and old["mapped"] == pytest.approx(29884.5)
    etf = map_with_typed_basis(500.0, "QQQ", 500.0, 260.0, NOW, NOW)
    assert etf["status"] == "invalid" and etf["mapped"] is None
