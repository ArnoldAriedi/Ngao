from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    national_id_hash: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    id_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_code_hash: Mapped[str | None] = mapped_column(String(64))
    phone_code_hash: Mapped[str | None] = mapped_column(String(64))
    codes_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    code_attempts: Mapped[int] = mapped_column(Integer, default=0)
    searches_today: Mapped[int] = mapped_column(Integer, default=0)
    search_day: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def is_verified(self):
        return self.email_verified and self.phone_verified and self.id_verified


class ConvictionRecord(Base):
    __tablename__ = "conviction_records"
    __table_args__ = (UniqueConstraint("source_name", "source_reference"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    public_record_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    source_reference: Mapped[str] = mapped_column(String(120))
    source_name: Mapped[str] = mapped_column(String(160))
    offense_category: Mapped[str] = mapped_column(String(40), index=True)
    offense_label: Mapped[str] = mapped_column(String(200))
    convictions_count: Mapped[int] = mapped_column(Integer, default=1)
    judgment_date: Mapped[date] = mapped_column(Date)
    release_date: Mapped[date | None] = mapped_column(Date)
    sentence_description: Mapped[str | None] = mapped_column(String(300))
    county: Mapped[str] = mapped_column(String(100), index=True)
    area_label: Mapped[str] = mapped_column(String(120))
    latitude: Mapped[float] = mapped_column(Float, index=True)
    longitude: Mapped[float] = mapped_column(Float, index=True)
    publication_status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    review_note: Mapped[str | None] = mapped_column(Text)


def published():
    return (
        ConvictionRecord.publication_status == "APPROVED",
        ConvictionRecord.is_synthetic.is_(settings.demo_mode),
    )


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(200))
    totp_secret_sealed: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="REVIEWER")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_totp_step: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEntry(Base):
    __tablename__ = "audit_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str | None] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(String(500), default="")


class CorrectionRequest(Base):
    __tablename__ = "correction_requests"
    __table_args__ = (
        Index("one_open_report_per_person_and_record", "record_id", "user_id", unique=True,
              postgresql_where=text("status IN ('OPEN', 'IN_REVIEW')")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("conviction_records.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(40))
    details: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    claimed_by_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(40), index=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[str] = mapped_column(String(200), default="")


class ThrottleEvent(Base):
    __tablename__ = "throttle_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
