from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.models import AuditEntry, ConvictionRecord, Staff, utcnow
from app.schemas import PUBLICATION_STATUSES, ApproveRecords, StaffLogin
from app.security import check_password, current_admin, issue_staff_token, totp_box
from app.totp import accepted_step

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)

router = APIRouter(tags=["staff"])


def second_factor_step(staff: Staff | None, body: StaffLogin) -> int | None:
    if staff is None or not staff.is_active:
        return None
    if not check_password(body.password, staff.password_hash):
        return None
    return accepted_step(totp_box.unseal(staff.totp_secret_sealed), body.otp, staff.last_totp_step)


def note_failed_login(db: Session, staff: Staff | None, email: str) -> None:
    if staff is None:
        audit(db, None, "STAFF_LOGIN_FAILED", "staff", None, email)
        return
    staff.failed_logins += 1
    if staff.failed_logins >= MAX_FAILED_LOGINS:
        staff.locked_until, staff.failed_logins = utcnow() + LOCKOUT, 0
    audit(db, staff.id, "STAFF_LOGIN_FAILED", "staff", staff.id, email)


@router.post("/api/v1/staff/login")
def staff_login(body: StaffLogin, db: Session = Depends(get_db)):
    staff = db.scalar(select(Staff).where(Staff.email == body.email.lower()))
    if staff and staff.locked_until and staff.locked_until > utcnow():
        raise HTTPException(429, "Account locked. Try again later")

    step = second_factor_step(staff, body)
    if step is None:
        note_failed_login(db, staff, body.email)
        db.commit()
        raise HTTPException(401, "Wrong email, password or code")

    staff.failed_logins = 0
    staff.last_totp_step = step
    audit(db, staff.id, "STAFF_LOGIN", "staff", staff.id)
    db.commit()
    return {"token": issue_staff_token(staff.id), "role": staff.role}


@router.post("/api/v1/admin/records/{record_id}/publication")
def set_publication(record_id: int, status: str, admin: Staff = Depends(current_admin), db: Session = Depends(get_db)):
    if status not in PUBLICATION_STATUSES:
        raise HTTPException(400, "Invalid publication status")
    record = db.get(ConvictionRecord, record_id)
    if record is None:
        raise HTTPException(404, "Record not found")
    audit(db, admin.id, "RECORD_STATUS_CHANGED", "record", record.id, f"{record.publication_status} -> {status}")
    record.publication_status = status
    db.commit()
    return {"record_id": record.id, "publication_status": record.publication_status}


@router.get("/api/v1/admin/records/pending")
def pending_records(
    limit: int = Query(default=100, ge=1, le=500),
    _: Staff = Depends(current_admin),
    db: Session = Depends(get_db),
):
    pending = db.scalars(
        select(ConvictionRecord)
        .where(ConvictionRecord.publication_status == "PENDING", ConvictionRecord.is_synthetic.is_(False))
        .order_by(ConvictionRecord.id)
        .limit(limit)
    )
    return [
        {
            "id": record.id,
            "source_name": record.source_name,
            "source_reference": record.source_reference,
            "offense_category": record.offense_category,
            "offense_label": record.offense_label,
            "convictions_count": record.convictions_count,
            "judgment_date": record.judgment_date,
            "release_date": record.release_date,
            "county": record.county,
            "area_label": record.area_label,
            "latitude": record.latitude,
            "longitude": record.longitude,
        }
        for record in pending
    ]


@router.post("/api/v1/admin/records/approve")
def approve_records(body: ApproveRecords, admin: Staff = Depends(current_admin), db: Session = Depends(get_db)):
    approved = []
    for record_id in dict.fromkeys(body.record_ids):
        flipped = db.execute(
            update(ConvictionRecord)
            .where(ConvictionRecord.id == record_id, ConvictionRecord.publication_status == "PENDING")
            .values(publication_status="APPROVED")
            .execution_options(synchronize_session=False)
        )
        if flipped.rowcount:
            audit(db, admin.id, "RECORD_STATUS_CHANGED", "record", record_id, "PENDING -> APPROVED")
            approved.append(record_id)
    db.commit()
    return {"approved": approved, "not_pending": [i for i in dict.fromkeys(body.record_ids) if i not in approved]}


@router.get("/api/v1/admin/audit")
def audit_log(
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: Staff = Depends(current_admin),
    db: Session = Depends(get_db),
):
    query = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
    if action:
        query = query.where(AuditEntry.action == action)
    return [
        {
            "id": entry.id,
            "at": entry.at,
            "staff_id": entry.staff_id,
            "action": entry.action,
            "target_type": entry.target_type,
            "target_id": entry.target_id,
            "detail": entry.detail,
        }
        for entry in db.scalars(query)
    ]
