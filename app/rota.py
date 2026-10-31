from datetime import date, timedelta

MAX_PRIMARY_STREAK = 4


def is_heavy(day: date, holidays: set[date]) -> bool:
    return day.weekday() >= 5 or day in holidays


def parse_unavailable(text: str) -> set[date]:
    """'2026-12-24..2026-12-27;2027-01-05' becomes a set of days."""
    days = set()
    for part in filter(None, (piece.strip() for piece in text.split(";"))):
        first, _, last = part.partition("..")
        start, end = date.fromisoformat(first), date.fromisoformat(last or first)
        days.update(start + timedelta(days=n) for n in range((end - start).days + 1))
    return days


def build_rota(
    people: list[str], start: date, days: int, holidays: set[date], unavailable: dict[str, set[date]]
) -> list[tuple[date, str | None, str | None]]:
    """One primary and one backup a day. Weekends and holidays weigh double."""
    primary_load = dict.fromkeys(people, 0)
    backup_load = dict.fromkeys(people, 0)
    streak = dict.fromkeys(people, 0)
    rota = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        weight = 2 if is_heavy(day, holidays) else 1
        free = [person for person in people if day not in unavailable.get(person, set())]

        primary = min(free, key=lambda p: (streak[p] >= MAX_PRIMARY_STREAK, primary_load[p], streak[p], p), default=None)
        others = [person for person in free if person != primary]
        backup = min(others, key=lambda p: (backup_load[p], primary_load[p], p), default=None)

        for person in people:
            streak[person] = streak[person] + 1 if person == primary else 0
        if primary:
            primary_load[primary] += weight
        if backup:
            backup_load[backup] += weight
        rota.append((day, primary, backup))
    return rota


def summarise(rota: list[tuple[date, str | None, str | None]], holidays: set[date]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for day, primary, backup in rota:
        for person, role in ((primary, "primary"), (backup, "backup")):
            if person is None:
                continue
            shifts = summary.setdefault(person, {"primary": 0, "backup": 0, "heavy": 0})
            shifts[role] += 1
            if role == "primary" and is_heavy(day, holidays):
                shifts["heavy"] += 1
    return summary


def uncovered_days(rota: dict[date, set[str]], on_staff: set[str], start: date, days: int, minimum: int) -> list[tuple[date, int]]:
    """Days with fewer than `minimum` scheduled active staff."""
    gaps = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        covered = len(rota.get(day, set()) & on_staff)
        if covered < minimum:
            gaps.append((day, covered))
    return gaps
