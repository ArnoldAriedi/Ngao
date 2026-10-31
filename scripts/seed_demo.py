from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ConvictionRecord

SOURCE = "Synthetic test source"
FICTION = "Fictional sentence. Not a real case"

DEMO_RECORDS = [
    ("DEMO-001", "SEXUAL_ASSAULT", "Sexual assault (fictional)", 1, date(2022, 5, 10), None, "Nairobi County", "Demo area A", -1.29, 36.82),
    ("DEMO-002", "CHILD_TRAFFICKING", "Child trafficking (fictional)", 1, date(2021, 9, 2), date(2024, 1, 15), "Nairobi County", "Demo area B", -1.30, 36.83),
    ("DEMO-003", "GENDER_BASED_VIOLENCE", "Domestic violence, repeat (fictional)", 2, date(2019, 3, 14), None, "Kiambu County", "Demo area C", -1.17, 36.83),
    ("DEMO-004", "CHILD_LABOUR", "Employing a child in hazardous work (fictional)", 1, date(2023, 2, 20), None, "Nairobi County", "Demo area D", -1.27, 36.80),
    ("DEMO-005", "CHILD_SEXUAL_OFFENCE", "Defilement (fictional)", 1, date(2024, 1, 12), None, "Nairobi County", "Demo area E", -1.29, 36.81),
    ("DEMO-006", "CHILD_SEXUAL_OFFENCE", "Defilement, repeat (fictional)", 2, date(2012, 6, 1), date(2018, 6, 1), "Kiambu County", "Demo area F", -1.22, 36.78),
    ("DEMO-007", "SEXUAL_ASSAULT", "Sexual assault, listing lapsed (fictional)", 1, date(2015, 4, 9), date(2016, 4, 9), "Nairobi County", "Demo area G", -1.28, 36.82),
]


def main():
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for ref, category, label, count, judged, released, county, area, lat, lon in DEMO_RECORDS:
            if db.scalar(select(ConvictionRecord.id).where(ConvictionRecord.public_record_id == ref)):
                continue
            db.add(ConvictionRecord(
                public_record_id=ref,
                source_reference=f"SYNTHETIC-{ref}",
                source_name=SOURCE,
                offense_category=category,
                offense_label=label,
                convictions_count=count,
                judgment_date=judged,
                release_date=released,
                sentence_description=FICTION,
                county=county,
                area_label=area,
                latitude=lat,
                longitude=lon,
                publication_status="APPROVED",
                last_verified_at=now,
                is_synthetic=True,
            ))
        db.commit()
    print(f"Seeded {len(DEMO_RECORDS)} fictional records.")


if __name__ == "__main__":
    main()
