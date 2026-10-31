from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.db import get_db
from app.models import ConvictionRecord, CorrectionRequest, Staff, User, published, utcnow
from app.notify import try_deliver
from app.permissions import transition_allowed
from app.retention import is_listed
from app.queue_health import ON_TRACK, triage_state
from app.review_policy import OPEN_STATES, URGENT_REASONS, review_deadline
from app.schemas import CorrectionIn, Resolution
from app.security import current_staff, current_user
from app.throttle import guard, key_for

OUTCOME_WORDS = {"RESOLVED": "accepted", "REJECTED": "not accepted"}

router = APIRouter(tags=["corrections"])


def suspend_for_review(db: Session, report: CorrectionRequest, record: ConvictionRecord, staff_id: int | None, action: str) -> None:
    suspended = db.execute(
        update(ConvictionRecord)
        .where(ConvictionRecord.id == record.id, ConvictionRecord.publication_status == "APPROVED")
        .values(publication_status="SUSPENDED")
        .execution_options(synchronize_session=False)
    )
    if suspended.rowcount == 0:
        return
    record.publication_status = "SUSPENDED"
    report.auto_suspended = True
    audit(db, staff_id, action, "record", record.id, f"report {report.id}")


def suspend_overdue(db: Session) -> int:
    if not settings.suspend_on_deadline:
        return 0
    overdue = db.execute(
        select(CorrectionRequest, ConvictionRecord)
        .join(ConvictionRecord, ConvictionRecord.id == CorrectionRequest.record_id)
        .where(
            CorrectionRequest.status.in_(OPEN_STATES),
            CorrectionRequest.reason.in_(URGENT_REASONS),
            CorrectionRequest.due_at < utcnow(),
            CorrectionRequest.auto_suspended.is_(False),
            ConvictionRecord.publication_status == "APPROVED",
        )
    ).all()
    for report, record in overdue:
        suspend_for_review(db, report, record, None, "AUTO_SUSPEND_OVERDUE")
    if overdue:
        db.commit()
    return len(overdue)


def sweep_overdue(db: Session = Depends(get_db)) -> None:
    suspend_overdue(db)


@router.post("/api/v1/safety/records/{public_record_id}/corrections", status_code=201)
def report_mistake(
    public_record_id: str,
    body: CorrectionIn,
    user: User = Depends(current_user),
    _swept: None = Depends(sweep_overdue),
    db: Session = Depends(get_db),
):
    record = db.scalar(select(ConvictionRecord).where(
        ConvictionRecord.public_record_id == public_record_id, *published()
    ))
    if record is None or not is_listed(record, date.today()):
        raise HTTPException(404, "Record not found")
    already_open = db.scalar(select(CorrectionRequest.id).where(
        CorrectionRequest.record_id == record.id,
        CorrectionRequest.user_id == user.id,
        CorrectionRequest.status.in_(OPEN_STATES),
    ))
    if already_open:
        raise HTTPException(409, "You already have an open report for this record")
    guard(db, key_for("report", str(user.id)), settings.daily_report_limit, timedelta(days=1))

    report = CorrectionRequest(
        record_id=record.id,
        user_id=user.id,
        reason=body.reason,
        details=body.details.strip(),
        due_at=review_deadline(
            body.reason, utcnow(), settings.urgent_review_hours, settings.standard_review_days
        ),
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You already have an open report for this record") from None
    if body.reason in URGENT_REASONS and settings.review_alert_email:
        try_deliver("email", settings.review_alert_email, f"Urgent report {report.id} ({report.reason}) is due {report.due_at:%a %d %b %H:%M} UTC.", "Urgent Ngao report")
    return {"reference": report.id, "status": report.status, "review_by": report.due_at}


@router.get("/api/v1/safety/corrections")
def my_reports(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(CorrectionRequest, ConvictionRecord.public_record_id)
        .join(ConvictionRecord, ConvictionRecord.id == CorrectionRequest.record_id)
        .where(CorrectionRequest.user_id == user.id)
        .order_by(CorrectionRequest.created_at.desc())
    ).all()
    return [
        {
            "reference": report.id,
            "public_record_id": public_id,
            "status": report.status,
            "review_by": report.due_at if report.status in OPEN_STATES else None,
            "record_hidden": report.auto_suspended and report.status in OPEN_STATES,
            "resolution_note": report.resolution_note,
            "created_at": report.created_at,
        }
        for report, public_id in rows
    ]


@router.get("/api/v1/admin/corrections")
def review_queue(status: str = "ACTIVE", _: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    states = OPEN_STATES if status == "ACTIVE" else (status,)
    now = utcnow()
    rows = db.execute(
        select(CorrectionRequest, ConvictionRecord.public_record_id, ConvictionRecord.publication_status)
        .join(ConvictionRecord, ConvictionRecord.id == CorrectionRequest.record_id)
        .where(CorrectionRequest.status.in_(states))
        .order_by(CorrectionRequest.due_at)
    ).all()
    return [
        {
            "id": report.id,
            "public_record_id": public_id,
            "reason": report.reason,
            "details": report.details,
            "status": report.status,
            "due_at": report.due_at,
            "overdue": report.status in OPEN_STATES and report.due_at < now,
            "claimed_by_id": report.claimed_by_id,
            "record_status": record_status,
            "record_suspended_by_report": report.auto_suspended,
            "created_at": report.created_at,
        }
        for report, public_id, record_status in rows
    ]


def open_report_states(db: Session) -> list[tuple[CorrectionRequest, str]]:
    now = utcnow()
    reports = db.scalars(select(CorrectionRequest).where(CorrectionRequest.status.in_(OPEN_STATES))).all()
    return [
        (report, triage_state(
            urgent=report.reason in URGENT_REASONS,
            claimed=report.status == "IN_REVIEW",
            filed_at=report.created_at,
            due_at=report.due_at,
            now=now,
            claim_target_hours=settings.urgent_claim_target_hours,
            escalate_hours=settings.escalation_hours,
        ))
        for report in reports
    ]


@router.get("/api/v1/admin/queue/health")
def queue_health(_staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    counts = Counter(state for _, state in open_report_states(db))
    active_staff = db.scalar(select(func.count()).select_from(Staff).where(Staff.is_active.is_(True)))
    return {
        "open_reports": sum(counts.values()),
        "by_state": counts,
        "needs_attention": sum(count for state, count in counts.items() if state != ON_TRACK),
        "active_staff": active_staff,
        "understaffed": active_staff < settings.min_active_reviewers,
    }


@router.post("/api/v1/admin/corrections/{correction_id}/claim")
def claim(correction_id: int, staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    report = db.get(CorrectionRequest, correction_id)
    if report is None:
        raise HTTPException(404, "Report not found")
    took_it = db.execute(
        update(CorrectionRequest)
        .where(CorrectionRequest.id == correction_id, CorrectionRequest.status == "OPEN")
        .values(status="IN_REVIEW", claimed_by_id=staff.id, claimed_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if took_it.rowcount == 0:
        db.rollback()
        raise HTTPException(409, "Report is already claimed or closed")
    db.refresh(report)
    audit(db, staff.id, "REPORT_CLAIMED", "report", report.id, report.reason)
    if settings.suspend_on_review_start and report.reason in URGENT_REASONS:
        record = db.get(ConvictionRecord, report.record_id)
        suspend_for_review(db, report, record, staff.id, "AUTO_SUSPEND_ON_REVIEW")
    db.commit()
    return {"id": report.id, "status": report.status, "record_suspended": report.auto_suspended}


@router.post("/api/v1/admin/corrections/{correction_id}/resolve")
def resolve(correction_id: int, body: Resolution, staff: Staff = Depends(current_staff), db: Session = Depends(get_db)):
    report = db.get(CorrectionRequest, correction_id)
    if report is None:
        raise HTTPException(404, "Report not found")
    if report.status not in OPEN_STATES:
        raise HTTPException(409, "Report is already closed")
    if report.auto_suspended and body.record_status is None:
        raise HTTPException(422, "This report suspended the record. Choose what happens to it with record_status")
    record = db.get(ConvictionRecord, report.record_id)
    if body.record_status and not transition_allowed(staff.role, record.publication_status, body.record_status, report.auto_suspended):
        raise HTTPException(403, "That status change needs an administrator")

    closed = db.execute(
        update(CorrectionRequest)
        .where(CorrectionRequest.id == correction_id, CorrectionRequest.status.in_(OPEN_STATES))
        .values(status=body.outcome, resolution_note=body.note, resolved_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if closed.rowcount == 0:
        db.rollback()
        raise HTTPException(409, "Report is already closed")
    db.refresh(report)
    audit(db, staff.id, "REPORT_RESOLVED", "report", report.id, body.outcome)
    if body.record_status:
        audit(db, staff.id, "RECORD_STATUS_CHANGED", "record", record.id,
              f"{record.publication_status} -> {body.record_status}; report {report.id}")
        record.publication_status = body.record_status

    reporter = db.get(User, report.user_id)
    message = f"Ngao: your report {report.id} was reviewed and {OUTCOME_WORDS[body.outcome]}. Sign in to read the reviewer's note."
    if try_deliver("email", reporter.email, message, f"Update on your Ngao report {report.id}"):
        report.notified_at = utcnow()
    db.commit()
    return {"id": report.id, "status": report.status, "reporter_notified": report.notified_at is not None}
