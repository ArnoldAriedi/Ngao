from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.categories import CATEGORIES, CORRECTION_REASONS, PUBLICATION_STATUSES  # noqa: F401
from app.config import settings
from app.geo import in_service_area
from app.identity import NATIONAL_ID, normalize_phone

class Registration(BaseModel):
    full_name: str = Field(min_length=3, max_length=120)
    email: EmailStr
    phone: str
    national_id: str
    password: str = Field(min_length=10, max_length=128)

    @field_validator("phone")
    @classmethod
    def kenyan_mobile(cls, raw):
        phone = normalize_phone(raw)
        if not phone:
            raise ValueError("Enter a Kenyan mobile number")
        return phone

    @field_validator("national_id")
    @classmethod
    def well_formed_id(cls, raw):
        national_id = raw.strip()
        if not NATIONAL_ID.fullmatch(national_id):
            raise ValueError("Enter your 7 or 8 digit national ID number")
        return national_id


class Verification(BaseModel):
    email: EmailStr
    email_code: str = Field(pattern=r"^\d{6}$")
    phone_code: str = Field(pattern=r"^\d{6}$")


class Login(BaseModel):
    email: EmailStr
    password: str


class PublicRecord(BaseModel):
    public_record_id: str
    offense_category: str
    offense_label: str
    convictions_count: int
    judgment_date: date
    release_date: date | None
    sentence_description: str | None
    county: str
    area_label: str
    distance_km: int
    listed_until: date | None
    last_verified_at: datetime | None
    synthetic: bool


class CorrectionIn(BaseModel):
    reason: str
    details: str = Field(min_length=20, max_length=2000)

    @field_validator("reason")
    @classmethod
    def known_reason(cls, value):
        if value not in CORRECTION_REASONS:
            raise ValueError("Choose what is wrong with the record")
        return value


class StaffLogin(BaseModel):
    email: EmailStr
    password: str
    otp: str = Field(pattern=r"^\d{6}$")


class Resolution(BaseModel):
    outcome: Literal["RESOLVED", "REJECTED"]
    note: str = Field(min_length=3, max_length=1000)
    record_status: str | None = None

    @field_validator("record_status")
    @classmethod
    def known_status(cls, value):
        if value is not None and value not in PUBLICATION_STATUSES:
            raise ValueError("Invalid publication status")
        return value


class Point(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def inside_service_area(self):
        if not in_service_area(self.latitude, self.longitude):
            raise ValueError("Searches are only available in and near Kenya")
        return self


class SearchRequest(Point):
    radius_km: float = Field(default=settings.max_search_radius_km, gt=0, le=settings.max_search_radius_km)
    category: str | None = None


class ApproveRecords(BaseModel):
    record_ids: list[int] = Field(min_length=1, max_length=200)
