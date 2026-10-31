"""Build a rota with a primary and a backup every day, written as date,email,role."""
import argparse
import csv
from datetime import date

from app.rota import build_rota, parse_unavailable, summarise, uncovered_days


def read_team(path: str) -> tuple[list[str], dict[str, set[date]]]:
    emails, leave = [], {}
    with open(path, newline="", encoding="utf-8") as team_file:
        for member in csv.DictReader(team_file):
            email = member["email"].strip().lower()
            emails.append(email)
            leave[email] = parse_unavailable(member.get("unavailable") or "")
    return emails, leave


def read_holidays(path: str | None) -> set[date]:
    if not path:
        return set()
    with open(path, newline="", encoding="utf-8") as holiday_file:
        return {date.fromisoformat(holiday["date"]) for holiday in csv.DictReader(holiday_file)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("team_csv", help="columns: email, unavailable (days or a..b ranges, separated by ;)")
    parser.add_argument("--start", type=date.fromisoformat, default=date.today())
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--holidays", help="csv with a date column")
    parser.add_argument("--out", default="rota.csv")
    args = parser.parse_args()

    emails, leave = read_team(args.team_csv)
    holidays = read_holidays(args.holidays)
    rota = build_rota(emails, args.start, args.days, holidays, leave)

    with open(args.out, "w", newline="", encoding="utf-8") as rota_file:
        writer = csv.writer(rota_file, lineterminator="\n")
        writer.writerow(["date", "email", "role"])
        for day, primary, backup in rota:
            for email, role in ((primary, "PRIMARY"), (backup, "BACKUP")):
                if email:
                    writer.writerow([day.isoformat(), email, role])

    print(f"{'person':32} primary backup heavy-day primaries")
    for email, shifts in sorted(summarise(rota, holidays).items()):
        print(f"{email:32} {shifts['primary']:7} {shifts['backup']:6} {shifts['heavy']:7}")

    on_duty = {day: {email for email in (primary, backup) if email} for day, primary, backup in rota}
    gaps = uncovered_days(on_duty, set(emails), args.start, args.days, 2)
    for day, count in gaps:
        print(f"GAP {day:%a %d %b %Y}: {count} available, need 2")
    print(f"Wrote {args.out}." if not gaps else f"Wrote {args.out} with {len(gaps)} short days.")
    raise SystemExit(1 if gaps else 0)


if __name__ == "__main__":
    main()
