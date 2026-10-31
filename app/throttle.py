import secrets
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ThrottleEvent, utcnow
from app.netinfo import pick_client_ip
from app.security import fingerprint

LOGIN_PAIR = (5, timedelta(minutes=15))
LOGIN_IP = (30, timedelta(minutes=15))
REGISTER_IP = (5, timedelta(hours=1))
CODE_TARGET = (3, timedelta(hours=1))
VERIFY_IP = (20, timedelta(minutes=15))
RESEND_ACCOUNT = (3, timedelta(hours=1))
KEEP = timedelta(days=1)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    return pick_client_ip(request.headers.get("x-forwarded-for", ""), peer, settings.trusted_proxy_hops)


def key_for(*parts: str) -> str:
    """Hashed, so emails and numbers are not stored."""
    return fingerprint("|".join(parts))


def recent(db: Session, key: str, window: timedelta) -> int:
    return db.scalar(
        select(func.count()).select_from(ThrottleEvent).where(ThrottleEvent.key == key, ThrottleEvent.at > utcnow() - window)
    )


def record(db: Session, key: str) -> None:
    db.add(ThrottleEvent(key=key))
    if secrets.randbelow(100) == 0:
        db.execute(delete(ThrottleEvent).where(ThrottleEvent.at < utcnow() - KEEP))


def blocked(db: Session, key: str, limit: int, window: timedelta) -> bool:
    return recent(db, key, window) >= limit


def guard(db: Session, key: str, limit: int, window: timedelta) -> None:
    """Count first, then check, so parallel requests cannot all slip under."""
    record(db, key)
    db.commit()
    if recent(db, key, window) > limit:
        raise HTTPException(429, "Too many requests. Try again later", headers={"Retry-After": str(int(window.total_seconds()))})
