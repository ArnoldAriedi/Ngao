from datetime import date

LISTING_YEARS = 7
REPEAT_CONVICTIONS = 2


def plus_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return date(day.year + years, 3, 1)


def listed_until(record) -> date | None:
    """None means listed permanently."""
    if record.convictions_count >= REPEAT_CONVICTIONS:
        return None
    clock_start = max(filter(None, (record.judgment_date, record.release_date)))
    return plus_years(clock_start, LISTING_YEARS)


def is_listed(record, today: date) -> bool:
    until = listed_until(record)
    return until is None or today < until
