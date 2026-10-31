"""Exit non-zero, and email, if the rota has days with too few active staff. Run weekly."""
import argparse
import csv
from collections import defaultdict
from datetime import date

from sqlalchemy import select

from app.config import settings
from app.jobs import tracked
from app.models import Staff
from app.notify import try_deliver
from app.rota import uncovered_days

JOB = "check_rota"


def read_rota(path: str) -> dict[date, set[str]]:
    rota = defaultdict(set)
    with open(path, newline="", encoding="utf-8") as rota_file:
        for shift in csv.DictReader(rota_file):
            rota[date.fromisoformat(shift["date"])].add(shift["email"].strip().lower())
    return rota


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rota_csv", help="columns: date, email (a role column is ignored)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--minimum", type=int, default=2, help="people on duty each day")
    args = parser.parse_args()

    with tracked(JOB) as run:
        active_emails = {email for (email,) in run.db.execute(select(Staff.email).where(Staff.is_active.is_(True)))}
        gaps = uncovered_days(read_rota(args.rota_csv), active_emails, date.today(), args.days, args.minimum)
        gap_lines = "\n".join(f"{day:%a %d %b %Y}: {count} on duty, need {args.minimum}" for day, count in gaps)
        if gaps:
            run.ok = bool(settings.escalation_email) and try_deliver("email", settings.escalation_email, gap_lines, "Ngao review rota has gaps")
        run.detail = f"{len(gaps)} uncovered days"

    if not gaps:
        print(f"Next {args.days} days: {args.minimum}+ active staff on duty every day.")
        return
    print(gap_lines)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
