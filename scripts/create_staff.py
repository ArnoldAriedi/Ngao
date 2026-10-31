"""Create a reviewer or administrator. Prints the authenticator link once."""
import argparse
import getpass

from app.audit import audit
from app.db import SessionLocal
from app.models import Staff
from app.security import hash_password, totp_box
from app.totp import new_secret, provisioning_uri

MIN_PASSWORD = 12


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("full_name")
    parser.add_argument("--role", choices=["REVIEWER", "ADMIN"], default="REVIEWER")
    args = parser.parse_args()

    password = getpass.getpass(f"Password ({MIN_PASSWORD}+ characters): ")
    if len(password) < MIN_PASSWORD or password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords must match and be long enough.")

    secret = new_secret()
    with SessionLocal() as db:
        staff = Staff(
            email=args.email.lower(),
            full_name=args.full_name,
            password_hash=hash_password(password),
            totp_secret_sealed=totp_box.seal(secret),
            role=args.role,
        )
        db.add(staff)
        db.flush()
        audit(db, None, "STAFF_CREATED", "staff", staff.id, args.role)
        db.commit()
    print(f"Created {args.role} {args.email}.")
    print(f"Add to an authenticator app: {provisioning_uri(secret, args.email)}")


if __name__ == "__main__":
    main()
