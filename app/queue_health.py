from datetime import datetime, timedelta

ON_TRACK, CLAIM_LATE, ESCALATE, OVERDUE = "ON_TRACK", "CLAIM_LATE", "ESCALATE", "OVERDUE"


def triage_state(
    *, urgent: bool, claimed: bool, filed_at: datetime, due_at: datetime, now: datetime,
    claim_target_hours: int, escalate_hours: int,
) -> str:
    """Only urgent reports are chased before their deadline."""
    if now >= due_at:
        return OVERDUE
    if not urgent or claimed:
        return ON_TRACK
    waiting = now - filed_at
    if waiting >= timedelta(hours=escalate_hours):
        return ESCALATE
    if waiting >= timedelta(hours=claim_target_hours):
        return CLAIM_LATE
    return ON_TRACK
