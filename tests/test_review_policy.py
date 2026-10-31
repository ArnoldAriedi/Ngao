from datetime import datetime, timedelta, timezone

from app.review_policy import review_deadline

FILED = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def test_urgent_reasons_get_the_short_deadline():
    assert review_deadline("WRONG_PERSON", FILED, 72, 14) == FILED + timedelta(hours=72)
    assert review_deadline("CONVICTION_OVERTURNED", FILED, 72, 14) == FILED + timedelta(hours=72)


def test_other_reasons_get_the_standard_deadline():
    assert review_deadline("WRONG_DETAILS", FILED, 72, 14) == FILED + timedelta(days=14)
    assert review_deadline("OTHER", FILED, 72, 14) == FILED + timedelta(days=14)
