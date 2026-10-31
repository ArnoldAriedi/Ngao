"""Re-encrypt every staff authenticator secret under the first TOTP_ENCRYPTION_KEYS key."""
from sqlalchemy import select

from app.audit import audit
from app.db import SessionLocal
from app.models import Staff
from app.security import totp_box


def main():
    with SessionLocal() as db:
        rows = db.scalars(select(Staff)).all()
        for staff in rows:
            staff.totp_secret_sealed = totp_box.reseal(staff.totp_secret_sealed)
        audit(db, None, "TOTP_KEYS_ROTATED", "staff", None, f"{len(rows)} secrets")
        db.commit()
    print(f"Re-encrypted {len(rows)} secrets.")


if __name__ == "__main__":
    main()
