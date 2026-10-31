"""Lock a staff member out now. Open sessions die on their next request."""
import argparse

from sqlalchemy import select

from app.audit import audit
from app.db import SessionLocal
from app.models import Staff


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    args = parser.parse_args()

    with SessionLocal() as db:
        staff = db.scalar(select(Staff).where(Staff.email == args.email.lower()))
        if staff is None:
            raise SystemExit("No such staff member.")
        staff.is_active = False
        audit(db, None, "STAFF_DEACTIVATED", "staff", staff.id, args.email.lower())
        db.commit()
    print(f"{args.email} deactivated.")


if __name__ == "__main__":
    main()
