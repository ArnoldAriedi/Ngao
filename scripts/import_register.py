"""Import an authorised court-register CSV. Records land PENDING and need admin approval."""
import argparse
import hashlib
import secrets
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.audit import audit
from app.db import SessionLocal
from app.models import ConvictionRecord
from app.register_rows import read_export, write_rejects
from app.schemas import CATEGORIES

PUBLISHED_FIELDS = (
    "offense_category", "offense_label", "convictions_count", "judgment_date", "release_date",
    "sentence_description", "county", "area_label", "latitude", "longitude",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_csv", type=Path)
    parser.add_argument("--skip-invalid", action="store_true", help="import the valid rows even if some are rejected")
    args = parser.parse_args()

    clean_rows, rejects, skipped = read_export(args.export_csv, CATEGORIES, date.today())
    if rejects:
        rejects_path = write_rejects(args.export_csv, rejects)
        print(f"{len(rejects)} rows rejected, listed in {rejects_path}.")
        if not args.skip_invalid:
            raise SystemExit("Nothing imported. Fix the export, or pass --skip-invalid.")

    created = updated = unpublished = 0
    verified_at = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for clean in clean_rows:
            record = db.scalar(select(ConvictionRecord).where(
                ConvictionRecord.source_name == clean["source_name"],
                ConvictionRecord.source_reference == clean["source_reference"],
            ))
            if record is None:
                db.add(ConvictionRecord(
                    **clean,
                    public_record_id="NGA-" + secrets.token_hex(5).upper(),
                    publication_status="PENDING",
                    last_verified_at=verified_at,
                    is_synthetic=False,
                ))
                created += 1
                continue
            changed = any(getattr(record, field) != clean[field] for field in PUBLISHED_FIELDS)
            record.last_verified_at = verified_at
            if not changed:
                continue
            for field in PUBLISHED_FIELDS:
                setattr(record, field, clean[field])
            updated += 1
            if record.publication_status == "APPROVED":
                record.publication_status = "PENDING"
                unpublished += 1

        digest = hashlib.sha256(args.export_csv.read_bytes()).hexdigest()[:16]
        audit(db, None, "RECORDS_IMPORTED", "import", None,
              f"{args.export_csv.name} sha256={digest} new={created} changed={updated} unpublished={unpublished} skipped={skipped} rejected={len(rejects)}")
        db.commit()
    print(f"New {created}, changed {updated} ({unpublished} pulled back for re-approval), skipped {skipped}, rejected {len(rejects)}.")


if __name__ == "__main__":
    main()
