"""Try to rewrite the audit trail as both logins. Exits non-zero if anything gets through."""
import sys

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError

from app.audit import audit
from app.config import settings
from app.db import SessionLocal
from app.models import AuditEntry

TAMPERING = [
    "UPDATE audit_entries SET detail = 'edited' WHERE id = :id",
    "DELETE FROM audit_entries WHERE id = :id",
    "TRUNCATE audit_entries",
]


def refusal(url: str, statement: str, entry_id: int) -> str | None:
    """The database's refusal message, or None if the statement ran."""
    try:
        with create_engine(url).begin() as connection:
            connection.execute(text(statement), {"id": entry_id} if ":id" in statement else {})
    except DBAPIError as failure:
        return str(failure.orig).splitlines()[0]
    return None


def main():
    if not settings.migration_database_url:
        raise SystemExit("Set MIGRATION_DATABASE_URL so the owner can be tested too.")

    with SessionLocal() as db:
        audit(db, None, "HARDENING_VERIFIED", "database", None, "tamper test row")
        db.commit()
        entry_id = db.scalar(select(AuditEntry.id).order_by(AuditEntry.id.desc()).limit(1))

    with create_engine(settings.database_url).connect() as connection:
        runtime_is_superuser = connection.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar()
    failures = []
    if runtime_is_superuser:
        failures.append("Runtime role is a superuser, so its grants mean nothing.")

    for label, url in (("runtime role", settings.database_url), ("owner", settings.migration_database_url)):
        for statement in TAMPERING:
            message = refusal(url, statement, entry_id)
            print(f"{label:12} {statement.split()[0]:9} {'BLOCKED: ' + message if message else 'ALLOWED'}")
            if message is None:
                failures.append(f"{label} was able to run: {statement}")

    for failure in failures:
        print("FAIL:", failure)
    print("PASS" if not failures else "FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
