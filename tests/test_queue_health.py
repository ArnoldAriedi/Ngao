from datetime import datetime, timedelta, timezone

from app.queue_health import CLAIM_LATE, ESCALATE, ON_TRACK, OVERDUE, triage_state

FILED = datetime(2026, 12, 24, 17, 0, tzinfo=timezone.utc)
DUE = FILED + timedelta(hours=72)


def state(hours_after_filing, *, urgent=True, claimed=False):
    return triage_state(
        urgent=urgent, claimed=claimed, filed_at=FILED, due_at=DUE,
        now=FILED + timedelta(hours=hours_after_filing), claim_target_hours=24, escalate_hours=48,
    )


def test_unclaimed_urgent_report_escalates():
    assert state(10) == ON_TRACK
    assert state(24) == CLAIM_LATE
    assert state(48) == ESCALATE
    assert state(72) == OVERDUE


def test_claimed_report_waits_for_deadline():
    assert state(60, claimed=True) == ON_TRACK
    assert state(72, claimed=True) == OVERDUE


def test_standard_report_flagged_only_when_overdue():
    assert state(60, urgent=False) == ON_TRACK
    assert state(72, urgent=False) == OVERDUE
