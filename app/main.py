from datetime import date
from math import ceil
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import case, or_, select, update
from sqlalchemy.orm import Session

from app.auth import router as auth_router
from app.corrections import router as corrections_router, sweep_overdue
from app.config import settings
from app.db import get_db
from app.geo import bounding_box, distance_km
from app.job_health import MAX_AGE, job_state
from app.models import ConvictionRecord, JobRun, User, published, utcnow
from app.retention import is_listed, listed_until
from app.schemas import CATEGORIES, CORRECTION_REASONS, Point, PublicRecord, SearchRequest
from app.security import current_user
from app.staff import router as staff_router

app = FastAPI(title="Ngao", version="0.2.0", description="Court-recorded convictions near a verified user.")
app.include_router(auth_router)
app.include_router(corrections_router)
app.include_router(staff_router)

WEB_FILE = Path(__file__).parent / "static" / "index.html"


def as_options(labels: dict[str, str]) -> list[dict[str, str]]:
    return [{"code": code, "label": label} for code, label in labels.items()]


def to_public(record: ConvictionRecord, distance: float) -> PublicRecord:
    return PublicRecord(
        public_record_id=record.public_record_id,
        offense_category=record.offense_category,
        offense_label=record.offense_label,
        convictions_count=record.convictions_count,
        judgment_date=record.judgment_date,
        release_date=record.release_date,
        sentence_description=record.sentence_description,
        county=record.county,
        area_label=record.area_label,
        distance_km=max(1, ceil(distance)),
        listed_until=listed_until(record),
        last_verified_at=record.last_verified_at,
        synthetic=record.is_synthetic,
    )


def spend_search(user: User, db: Session) -> None:
    """Single atomic UPDATE, so parallel requests cannot overspend."""
    today = date.today()
    spent = db.execute(
        update(User)
        .where(
            User.id == user.id,
            or_(User.search_day.is_(None), User.search_day != today, User.searches_today < settings.daily_search_limit),
        )
        .values(searches_today=case((User.search_day == today, User.searches_today + 1), else_=1), search_day=today)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if spent.rowcount == 0:
        raise HTTPException(429, "Daily search limit reached. Try again tomorrow")


@app.get("/")
def home():
    return FileResponse(WEB_FILE)


def delivery_state(configured: bool) -> str:
    if configured:
        return "configured"
    return "demo" if settings.demo_mode else "missing"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "delivery": {"email": delivery_state(bool(settings.smtp_host or settings.brevo_api_key)), "sms": delivery_state(bool(settings.sms_gateway_url))},
    }


@app.get("/health/jobs")
def job_health(db: Session = Depends(get_db)):
    """503 when any scheduled job is late, failing or has never run."""
    now = utcnow()
    states = {}
    for job, max_age in MAX_AGE.items():
        last = db.scalar(select(JobRun).where(JobRun.job == job).order_by(JobRun.id.desc()).limit(1))
        states[job] = job_state(last.ran_at if last else None, last.ok if last else None, now, max_age)
    healthy = all(state == "OK" for state in states.values())
    return JSONResponse({"healthy": healthy, "jobs": states}, status_code=200 if healthy else 503)


@app.get("/api/v1/safety/categories")
def categories():
    return {
        "categories": as_options(CATEGORIES),
        "correction_reasons": as_options(CORRECTION_REASONS),
        "max_radius_km": settings.max_search_radius_km,
        "demo_mode": settings.demo_mode,
    }


@app.post("/api/v1/safety/nearby", response_model=list[PublicRecord])
def nearby(
    search: SearchRequest,
    user: User = Depends(current_user),
    _swept: None = Depends(sweep_overdue),
    db: Session = Depends(get_db),
):
    if search.category and search.category not in CATEGORIES:
        raise HTTPException(400, "Unsupported category")
    spend_search(user, db)

    south, north, west, east = bounding_box(search.latitude, search.longitude, search.radius_km)
    query = select(ConvictionRecord).where(
        *published(),
        ConvictionRecord.latitude.between(south, north),
        ConvictionRecord.longitude.between(west, east),
    )
    if search.category:
        query = query.where(ConvictionRecord.offense_category == search.category)

    today = date.today()
    hits = []
    for record in db.scalars(query):
        if not is_listed(record, today):
            continue
        distance = distance_km(search.latitude, search.longitude, record.latitude, record.longitude)
        if distance <= search.radius_km:
            hits.append((distance, record))
    hits.sort(key=lambda hit: hit[0])
    return [to_public(record, distance) for distance, record in hits]


@app.post("/api/v1/safety/records/{public_record_id}/lookup", response_model=PublicRecord)
def public_record(
    public_record_id: str,
    point: Point,
    user: User = Depends(current_user),
    _swept: None = Depends(sweep_overdue),
    db: Session = Depends(get_db),
):
    spend_search(user, db)
    record = db.scalar(select(ConvictionRecord).where(
        ConvictionRecord.public_record_id == public_record_id, *published()
    ))
    if record is None or not is_listed(record, date.today()):
        raise HTTPException(404, "Record not found")
    distance = distance_km(point.latitude, point.longitude, record.latitude, record.longitude)
    if distance > settings.max_search_radius_km:
        raise HTTPException(404, "Record not found")
    return to_public(record, distance)
