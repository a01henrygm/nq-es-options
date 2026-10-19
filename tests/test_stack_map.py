"""Stack map: only areas where several DIFFERENT kinds of levels line up. TEST DATA ONLY."""
from backend.services import stack as sk
from tests.test_session_features import simulated_day


def it(price, fam, w=0.8, label="x"):
    return {"price": price, "family": fam, "weight": w, "label": label, "category": fam}


def test_a_family_counts_once_and_weak_areas_are_dropped():
    items = [it(1000.0, "oi"), it(1001.0, "oi"), it(1002.0, "oi"), it(1003.0, "oi"),                   # four of one kind: not a stack
             it(1100.0, "gex", 1.0), it(1101.0, "oi"), it(1099.5, "prior"), it(1100.5, "ladder", 0.5),   # four kinds: a stack
             it(1200.0, "vol"), it(1201.0, "move")]                                                        # two kinds: below the bar
    st = sk.find_stacks(items, 1050.0, tol=2.0, min_families=3, min_score=2.0)
    assert len(st) == 1 and abs(st[0]["center"] - 1100.0) < 1 and set(st[0]["families"]) == {"gex", "oi", "prior", "ladder"}
    assert st[0]["score"] == round(1.0 + 0.8 + 0.8 + 0.5, 3) and st[0]["low"] == 1099.5 and st[0]["high"] == 1101.0
    assert sk.find_stacks([], 1000.0, 2.0) == []


def test_stack_map_endpoint():
    c, db, now = simulated_day()
    j = c.get("/api/analytics/stack-map", params={"underlying": "_NDX"}).json()
    assert j["inputs"]["levels"] > 30 and len(j["inputs"]["by_family"]) >= 8
    assert j["stacks"] and all(len(s["families"]) >= 3 and s["call"] in ("RESPECT", "CHOP", "DISRESPECT") and s["headline"] and s["futures"] for s in j["stacks"])
    assert [s["center"] for s in j["stacks"]] == sorted((s["center"] for s in j["stacks"]), reverse=True)
    assert j["already_in"]["high"] is not None and 0 <= j["already_in"]["low"] <= 1
    loose = c.get("/api/analytics/stack-map", params={"underlying": "_NDX", "min_families": 2}).json()
    assert len(loose["stacks"]) >= len(j["stacks"])
