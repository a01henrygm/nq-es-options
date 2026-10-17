from datetime import date, datetime, timedelta

from backend.services import market
from backend.services.freshness import classify
from backend.timeutil import UTC, ET, parse_ts


def utc(*a): return datetime(*a, tzinfo=UTC)


def test_parse_ts_units_and_missing():
    assert parse_ts(1_760_454_000_000_000_000) == parse_ts(1_760_454_000_000_000) == parse_ts(1_760_454_000_000) == parse_ts(1_760_454_000)
    assert parse_ts(None) is None and parse_ts("") is None and parse_ts("garbage") is None and parse_ts(0) is None
    assert parse_ts("2026-10-14T15:00:00Z") == utc(2026, 10, 14, 15)


def test_holidays_and_weekends():
    assert not market.is_trading_day(date(2026, 10, 17))            # Saturday
    assert not market.is_trading_day(date(2026, 11, 26))            # Thanksgiving 2026
    assert not market.is_trading_day(date(2026, 4, 3))              # Good Friday 2026
    assert not market.is_trading_day(date(2026, 7, 3))              # July 4 is a Saturday -> observed Friday July 3
    assert market.is_trading_day(date(2026, 10, 14))
    assert market.early_close(date(2026, 11, 27)) and market.early_close(date(2026, 12, 24))


def test_dst_session_times():
    summer = market.session(date(2026, 7, 14)); winter = market.session(date(2026, 12, 14))
    assert summer[0].astimezone(UTC).hour == 13 and winter[0].astimezone(UTC).hour == 14   # 9:30 ET in UTC differs by DST


def test_market_state():
    assert market.market_state(utc(2026, 10, 14, 15)) == "open"
    assert market.market_state(utc(2026, 10, 14, 11)) == "premarket"
    assert market.market_state(utc(2026, 10, 14, 21)) == "afterhours"
    assert market.market_state(utc(2026, 10, 17, 15)) == "closed"


def test_freshness_delayed_plan_open_market():
    now = utc(2026, 10, 14, 15)
    assert classify(now - timedelta(minutes=16), now, "delayed").status == "delayed"
    assert classify(now - timedelta(minutes=45), now, "delayed").status == "stale"


def test_freshness_realtime_plan():
    now = utc(2026, 10, 14, 15)
    assert classify(now - timedelta(seconds=30), now, "realtime").status == "live"
    assert classify(now - timedelta(minutes=10), now, "realtime").status == "stale"


def test_freshness_weekend_uses_last_session():
    fri_close = utc(2026, 10, 16, 20)           # Friday 16:00 ET
    sat = utc(2026, 10, 17, 15)
    assert classify(fri_close - timedelta(minutes=5), sat).status == "closed_last_session"
    assert classify(fri_close - timedelta(days=3), sat).status == "stale"


def test_missing_source_timestamp_is_not_invented():
    f = classify(None, utc(2026, 10, 14, 15))
    assert f.status == "no_source_time" and f.age_seconds is None


def test_open_interest_is_daily():
    now = utc(2026, 10, 14, 15)
    assert classify(now - timedelta(hours=5), now, kind="open_interest").status == "daily_snapshot"
