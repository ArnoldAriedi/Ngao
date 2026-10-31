import itertools
import re
import threading
import time
from datetime import date, timedelta

from fastapi import HTTPException

from app.config import settings
from app.db import SessionLocal
from app.models import ConvictionRecord, CorrectionRequest, Staff, User, utcnow
from app.review_policy import review_deadline
from app.security import fingerprint, hash_password, issue_staff_token, issue_token, totp_box
from app.totp import STEP_SECONDS, code_at, new_secret

PASSWORD = "correct-horse-battery"
PASSWORD_HASH = hash_password(PASSWORD)
NAIROBI = (-1.2864, 36.8172)
KM_PER_DEGREE = 111.19
counter = itertools.count(1)


def km_north(km: float) -> tuple[float, float]:
    return NAIROBI[0] + km / KM_PER_DEGREE, NAIROBI[1]


def make_user(db, verified=True, **overrides) -> User:
    n = next(counter)
    fields = dict(
        full_name="Test User", email=f"user{n}@example.co.ke", phone=f"+2547{n:08d}",
        national_id_hash=fingerprint(f"national-id-{n}"), password_hash=PASSWORD_HASH,
        id_verified=verified, email_verified=verified, phone_verified=verified,
    )
    user = User(**{**fields, **overrides})
    db.add(user)
    db.commit()
    return user


def make_record(db, km=2.5, **overrides) -> ConvictionRecord:
    n = next(counter)
    latitude, longitude = km_north(km)
    fields = dict(
        public_record_id=f"NGA-TEST{n:05d}", source_reference=f"REF-{n}", source_name="Test court",
        offense_category="SEXUAL_ASSAULT", offense_label="Sexual assault (test)", convictions_count=1,
        judgment_date=date.today() - timedelta(days=365), release_date=None, sentence_description="Test sentence",
        county="Nairobi County", area_label="Test area", latitude=latitude, longitude=longitude,
        publication_status="APPROVED", is_synthetic=True, last_verified_at=utcnow(),
    )
    record = ConvictionRecord(**{**fields, **overrides})
    db.add(record)
    db.commit()
    return record


def make_staff(db, role="REVIEWER", **overrides) -> tuple[Staff, str]:
    n = next(counter)
    secret = new_secret()
    fields = dict(
        email=f"staff{n}@example.go.ke", full_name="Staff Member", password_hash=PASSWORD_HASH,
        totp_secret_sealed=totp_box.seal(secret), role=role,
    )
    staff = Staff(**{**fields, **overrides})
    db.add(staff)
    db.commit()
    return staff, secret


def make_report(db, record, user, reason="WRONG_PERSON", hours_old=0, **overrides) -> CorrectionRequest:
    filed_at = utcnow() - timedelta(hours=hours_old)
    fields = dict(
        record_id=record.id, user_id=user.id, reason=reason, details="The court file shows a different person.",
        created_at=filed_at,
        due_at=review_deadline(reason, filed_at, settings.urgent_review_hours, settings.standard_review_days),
    )
    report = CorrectionRequest(**{**fields, **overrides})
    db.add(report)
    db.commit()
    return report


def user_headers(user) -> dict:
    return {"Authorization": f"Bearer {issue_token(user.id)}"}


def staff_headers(staff) -> dict:
    return {"Authorization": f"Bearer {issue_staff_token(staff.id)}"}


def current_otp(secret: str, steps_ago: int = 0) -> str:
    return code_at(secret, int(time.time() // STEP_SECONDS) - steps_ago)


def registration(**overrides) -> dict:
    n = next(counter)
    fields = dict(
        full_name="Wanjiku Kamau", email=f"New.Person{n}@Example.co.ke", phone=f"07{n:08d}",
        national_id=str(10000000 + n), password=PASSWORD,
    )
    return {**fields, **overrides}


def normalised_phone(local_number: str) -> str:
    return "+254" + local_number[1:]


def codes_sent_to(outbox, email: str, phone: str) -> tuple[str, str]:
    email_message = [m for m in outbox if m.channel == "email" and m.to == email][-1]
    phone_message = [m for m in outbox if m.channel == "sms" and m.to == phone][-1]
    return (re.search(r"\b(\d{6})\b", email_message.message).group(1), re.search(r"\b(\d{6})\b", phone_message.message).group(1))


def different_code(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def search(client, user, **body):
    payload = {"latitude": NAIROBI[0], "longitude": NAIROBI[1], **body}
    return client.post("/api/v1/safety/nearby", json=payload, headers=user_headers(user))


def run_in_parallel(work, count: int) -> list:
    """Each call gets its own session. Returns 'ok' or the HTTP status of each outcome."""
    outcomes, barrier = [], threading.Barrier(count)

    def run(index):
        barrier.wait()
        with SessionLocal() as db:
            try:
                work(db, index)
                outcomes.append("ok")
            except HTTPException as refusal:
                outcomes.append(refusal.status_code)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes
