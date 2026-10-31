from datetime import date

from app.rota import MAX_PRIMARY_STREAK, build_rota, is_heavy, parse_unavailable, summarise, uncovered_days

PEOPLE = ["a@x.ke", "b@x.ke", "c@x.ke", "d@x.ke"]
START = date(2026, 10, 27)
HOLIDAYS = {date(2026, 12, 12), date(2026, 12, 25), date(2026, 12, 26), date(2027, 1, 1)}


def test_parse_unavailable():
    assert parse_unavailable("2026-12-24..2026-12-26;2027-01-05") == {
        date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 26), date(2027, 1, 5)}
    assert parse_unavailable("") == set()


def test_two_different_people_every_day():
    for day, primary, backup in build_rota(PEOPLE, START, 90, HOLIDAYS, {}):
        assert primary and backup and primary != backup


def test_leave_is_respected():
    leave = {"a@x.ke": parse_unavailable("2026-12-24..2026-12-27")}
    for day, primary, backup in build_rota(PEOPLE, START, 90, HOLIDAYS, leave):
        if date(2026, 12, 24) <= day <= date(2026, 12, 27):
            assert "a@x.ke" not in (primary, backup)


def test_load_and_holiday_burden_are_spread():
    rota = build_rota(PEOPLE, START, 90, HOLIDAYS, {})
    shares = summarise(rota, HOLIDAYS)
    primaries = [row["primary"] for row in shares.values()]
    heavy = [row["heavy"] for row in shares.values()]
    assert max(primaries) - min(primaries) <= 2
    assert max(heavy) - min(heavy) <= 2


def test_primary_streak_is_capped():
    longest = run = 0
    last = None
    for _, primary, _ in build_rota(PEOPLE, START, 90, HOLIDAYS, {}):
        run = run + 1 if primary == last else 1
        last = primary
        longest = max(longest, run)
    assert longest <= MAX_PRIMARY_STREAK


def test_unstaffable_day_is_left_empty():
    everyone_off = {person: {date(2026, 12, 25)} for person in PEOPLE}
    rota = {day: (p, b) for day, p, b in build_rota(PEOPLE, START, 90, HOLIDAYS, everyone_off)}
    assert rota[date(2026, 12, 25)] == (None, None)


def test_weekends_and_holidays_are_heavy():
    assert is_heavy(date(2026, 10, 31), set()) and is_heavy(date(2026, 12, 25), HOLIDAYS)
    assert not is_heavy(date(2026, 10, 28), HOLIDAYS)


def test_gaps_count_only_active_staff():
    rota = {
        date(2026, 12, 24): {"a@x.ke", "b@x.ke"},
        date(2026, 12, 25): {"a@x.ke", "left@x.ke"},
        date(2026, 12, 26): set(),
    }
    gaps = uncovered_days(rota, {"a@x.ke", "b@x.ke"}, date(2026, 12, 24), 4, minimum=2)
    assert gaps == [(date(2026, 12, 25), 1), (date(2026, 12, 26), 0), (date(2026, 12, 27), 0)]
