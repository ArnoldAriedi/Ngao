from datetime import date
from types import SimpleNamespace

from app.retention import is_listed, listed_until, plus_years


def record(judged, released=None, count=1):
    return SimpleNamespace(judgment_date=judged, release_date=released, convictions_count=count)


def test_single_conviction_lists_for_seven_years_from_judgment():
    assert listed_until(record(date(2022, 5, 10))) == date(2029, 5, 10)


def test_clock_starts_at_release_when_release_is_later():
    assert listed_until(record(date(2020, 1, 1), date(2024, 6, 30))) == date(2031, 6, 30)


def test_repeat_conviction_is_permanent():
    assert listed_until(record(date(2005, 1, 1), count=2)) is None
    assert is_listed(record(date(2005, 1, 1), count=3), date(2090, 1, 1))


def test_listing_ends_on_the_seventh_anniversary():
    subject = record(date(2019, 3, 14))
    assert is_listed(subject, date(2026, 3, 13))
    assert not is_listed(subject, date(2026, 3, 14))


def test_leap_day_rolls_to_march_first():
    assert plus_years(date(2020, 2, 29), 7) == date(2027, 3, 1)
