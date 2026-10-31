"""Create the least-privilege runtime role and make audit_entries append-only. Run as the owner."""
import os

from psycopg import sql
from sqlalchemy import create_engine

from app.config import settings

APP_ROLE = "ngao_app"
MIN_PASSWORD = 24

STATEMENTS = [
    f"""DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
        END IF;
    END $$""",
    f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}",
    f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}",
    f"REVOKE CREATE ON SCHEMA public FROM {APP_ROLE}",
    f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}",
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON users TO {APP_ROLE}",
    f"GRANT SELECT, INSERT, UPDATE ON staff, conviction_records, correction_requests TO {APP_ROLE}",
    f"GRANT SELECT, INSERT ON audit_entries TO {APP_ROLE}",
    f"GRANT SELECT, INSERT, DELETE ON job_runs TO {APP_ROLE}",
    f"GRANT SELECT, INSERT, DELETE ON throttle_events TO {APP_ROLE}",
    f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}",
    """CREATE OR REPLACE FUNCTION audit_entries_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'audit_entries is append-only'; END $$""",
    "DROP TRIGGER IF EXISTS audit_entries_no_change ON audit_entries",
    """CREATE TRIGGER audit_entries_no_change BEFORE UPDATE OR DELETE ON audit_entries
        FOR EACH ROW EXECUTE FUNCTION audit_entries_append_only()""",
    "DROP TRIGGER IF EXISTS audit_entries_no_truncate ON audit_entries",
    """CREATE TRIGGER audit_entries_no_truncate BEFORE TRUNCATE ON audit_entries
        FOR EACH STATEMENT EXECUTE FUNCTION audit_entries_append_only()""",
]


def main():
    if not settings.migration_database_url:
        raise SystemExit("Set MIGRATION_DATABASE_URL to the database owner's connection string.")
    password = os.environ.get("APP_DB_PASSWORD", "")
    if len(password) < MIN_PASSWORD:
        raise SystemExit(f"Set APP_DB_PASSWORD to at least {MIN_PASSWORD} random characters.")

    engine = create_engine(settings.migration_database_url)
    connection = engine.raw_connection()
    try:
        with connection.driver_connection.cursor() as cursor:
            for statement in STATEMENTS:
                cursor.execute(statement)
            cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(APP_ROLE), sql.Literal(password)))
        connection.commit()
    finally:
        connection.close()
    print(f"Role {APP_ROLE} ready. Point DATABASE_URL at it, then run scripts.verify_hardening.")


if __name__ == "__main__":
    main()
