from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import JobRun, utcnow

KEEP_DAYS = 30


def record_run(db: Session, job: str, ok: bool, detail: str = "") -> None:
    db.add(JobRun(job=job, ok=ok, detail=detail[:200]))
    db.execute(delete(JobRun).where(JobRun.job == job, JobRun.ran_at < utcnow() - timedelta(days=KEEP_DAYS)))
    db.commit()


@contextmanager
def tracked(job: str):
    """Heartbeat on exit, failure on exception."""
    with SessionLocal() as db:
        run = SimpleNamespace(db=db, ok=True, detail="")
        try:
            yield run
        except Exception as failure:
            db.rollback()
            record_run(db, job, False, repr(failure))
            raise
        record_run(db, job, run.ok, run.detail)
