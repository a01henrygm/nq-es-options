from datetime import timedelta

import pytest

from backend.collector import Collector
from backend.config import Settings
from backend.database import Database
from backend.models import ChainSnapshot
from backend.providers.base import OptionsProvider, ProviderError
from backend.providers.massive import content_hash
from tests.conftest import NOW, make_chain


class FakeProvider(OptionsProvider):
    """TEST provider: returns scripted results."""
    name = "fake"

    def __init__(self): self.queue, self.calls = [], 0

    def fetch_chain(self, underlying, *, max_dte, strike_window):
        self.calls += 1
        item = self.queue.pop(0) if self.queue else self.last
        self.last = item
        if isinstance(item, Exception):
            raise item
        return item


def snap(bid_shift=0.0, ts=NOW, spot=500.0):
    cons = make_chain(ts=ts)
    for c in cons:
        c.bid = (c.bid or 0) + bid_shift
    return ChainSnapshot("fake", "QQQ", NOW, spot, ts, cons, content_hash(cons))


def test_db_roundtrip_and_duplicate_detection():
    db = Database(":memory:")
    a = snap(); sid, new = db.save_snapshot(a)
    assert new and sid
    sid2, new2 = db.save_snapshot(snap())
    assert sid2 == sid and not new2                     # identical content is not stored twice
    _, new3 = db.save_snapshot(snap(bid_shift=0.5))
    assert new3
    back = db.load_snapshot("QQQ")
    assert back.from_database and back.spot == 500.0 and len(back.contracts) == len(a.contracts)
    assert back.source_ts == NOW


def test_retention_prunes_old_snapshots():
    db = Database(":memory:")
    for i in range(6): db.save_snapshot(snap(bid_shift=i), keep=3)
    assert len(db.list_snapshots("QQQ")) == 3


def test_prices_metrics_errors():
    db = Database(":memory:")
    db.save_price("NQ", 21000.0, "manual entry", NOW, NOW, "NQZ6", manual=True)
    assert db.latest_price("NQ")["manual"] == 1
    db.save_metric(1, "QQQ", "total_net_gex", 5.0, {"a": 1}, NOW)
    assert db.metric_history("QQQ", "total_net_gex")[0]["value"] == 5.0
    db.log_error("fake", "QQQ", NOW, "auth", "bad key")
    assert db.recent_errors()[0]["kind"] == "auth"


def make_collector(clock=lambda: NOW):
    s = Settings(api_key="k", underlyings=("QQQ",), poll_seconds=30)
    p, db = FakeProvider(), Database(":memory:")
    return Collector(s, p, db, clock), p, db


def test_new_data_triggers_storage_and_recalculation():
    c, p, db = make_collector()
    p.queue = [snap(), snap(), snap(bid_shift=1.0)]
    assert c.run_once("QQQ") is True
    assert db.metric_history("QQQ", "total_net_gex")                       # metrics calculated for new data
    n = len(db.metric_history("QQQ", "total_net_gex"))
    assert c.run_once("QQQ") is False                                      # unchanged content: not new, not re-stored
    assert len(db.metric_history("QQQ", "total_net_gex")) == n
    assert c.run_once("QQQ") is True and len(db.metric_history("QQQ", "total_net_gex")) == n + 1


def test_provider_error_keeps_last_snapshot_and_records_failure():
    c, p, db = make_collector()
    p.queue = [snap(), ProviderError("network", "down")]
    c.run_once("QQQ")
    assert c.run_once("QQQ") is False
    st = c.state["QQQ"]
    assert st["snapshot"] is not None and st["failures"] == 1 and st["last_error"]["kind"] == "network"
    assert db.recent_errors()[0]["message"] == "down"


def test_backoff_and_no_hammering_on_auth_errors():
    c, p, _ = make_collector()
    p.queue = [ProviderError("auth", "bad key")]
    c.run_once("QQQ")
    assert c._interval("QQQ") >= 900
    c2, p2, _ = make_collector()
    p2.queue = [ProviderError("network", "x")] * 3
    for _ in range(3): c2.run_once("QQQ")
    assert c2._interval("QQQ") == 30 * 8
