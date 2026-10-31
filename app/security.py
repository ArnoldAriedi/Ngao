import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Staff, User
from app.secrets_box import SecretBox

SCRYPT = {"n": 2**14, "r": 8, "p": 1}
STAFF_AUDIENCE = "ngao-staff"

totp_box = SecretBox(settings.totp_key_list)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"{salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$")
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


def fingerprint(value: str) -> str:
    return hmac.new(settings.app_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def issue_token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.token_ttl_minutes)
    return jwt.encode({"sub": str(user_id), "exp": expires}, settings.app_secret, algorithm="HS256")


def issue_staff_token(staff_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.staff_token_ttl_minutes)
    claims = {"sub": str(staff_id), "aud": STAFF_AUDIENCE, "exp": expires}
    return jwt.encode(claims, settings.app_secret, algorithm="HS256")


def bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Sign in to continue")
    return token


def subject_of(token: str, audience: str | None = None) -> int | None:
    try:
        claims = jwt.decode(token, settings.app_secret, algorithms=["HS256"], audience=audience)
        return int(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    user_id = subject_of(bearer_token(authorization))
    if user_id is None:
        raise HTTPException(401, "Your session has expired. Sign in again")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "Sign in to continue")
    if not user.is_verified:
        raise HTTPException(403, "Confirm your email, phone and ID to continue")
    return user


def current_staff(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Staff:
    staff_id = subject_of(bearer_token(authorization), STAFF_AUDIENCE)
    if staff_id is None:
        raise HTTPException(401, "Staff session missing or expired")
    staff = db.get(Staff, staff_id)
    if staff is None or not staff.is_active:
        raise HTTPException(403, "Staff access required")
    return staff


def current_admin(staff: Staff = Depends(current_staff)) -> Staff:
    if staff.role != "ADMIN":
        raise HTTPException(403, "Administrator access required")
    return staff
