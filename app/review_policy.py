from datetime import datetime, timedelta

URGENT_REASONS = {"WRONG_PERSON", "CONVICTION_OVERTURNED"}
OPEN_STATES = ("OPEN", "IN_REVIEW")


def review_deadline(reason: str, filed_at: datetime, urgent_hours: int, standard_days: int) -> datetime:
    if reason in URGENT_REASONS:
        return filed_at + timedelta(hours=urgent_hours)
    return filed_at + timedelta(days=standard_days)
