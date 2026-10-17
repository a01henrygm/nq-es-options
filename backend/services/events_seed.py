"""Starter list of scheduled market events. Dates came from published calendars (Federal Reserve, Bureau of Labor Statistics) on
2026-10-16 and from the third-Friday rule for options expiration. Calendars change, so verify before relying on them. You can add and
remove events on the Events tab; the starter list is only added once."""

SEED_SOURCE = "Starter list from published Fed and BLS calendars (2026-10-16). Verify."

SEED_EVENTS = [
    ("2026-10-16", "", "Monthly options expiration (third Friday)", "medium"),
    ("2026-10-28", "14:00", "FOMC rate decision", "high"),
    ("2026-11-06", "08:30", "Jobs report (October)", "high"),
    ("2026-11-10", "08:30", "CPI inflation (October)", "high"),
    ("2026-11-20", "", "Monthly options expiration (third Friday)", "medium"),
    ("2026-12-04", "08:30", "Jobs report (November)", "high"),
    ("2026-12-09", "14:00", "FOMC rate decision and projections", "high"),
    ("2026-12-10", "08:30", "CPI inflation (November)", "high"),
    ("2026-12-15", "08:30", "PPI inflation (November)", "medium"),
    ("2026-12-18", "", "Quarterly options expiration (quad witching)", "high"),
]


def seed_events(db) -> int:
    """Adds the starter list once per database. Returns how many were added."""
    if db.get_meta("events_seeded"):
        return 0
    for d, t, name, imp in SEED_EVENTS:
        db.add_event(d, t, name, imp, SEED_SOURCE)
    db.set_meta("events_seeded", "1")
    return len(SEED_EVENTS)
