from sqlalchemy.orm import Session

from app.models import AuditEntry


def audit(db: Session, staff_id: int | None, action: str, target_type: str, target_id: int | None, detail: str = "") -> None:
    """Append-only. Shares the caller's transaction."""
    db.add(AuditEntry(
        staff_id=staff_id,
        action=action,
        target_type=target_type,
        target_id=None if target_id is None else str(target_id),
        detail=detail[:500],
    ))
