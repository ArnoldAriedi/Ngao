import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.identity import confirm_national_id
from app.models import User
from app.notify import try_deliver
from app.schemas import Login, Registration, Verification
from app.security import check_password, current_user, fingerprint, hash_password, issue_token
from app.throttle import (
    CODE_TARGET, LOGIN_IP, LOGIN_PAIR, REGISTER_IP, RESEND_ACCOUNT, VERIFY_IP,
    blocked, client_ip, guard, key_for, record,
)

MAX_CODE_ATTEMPTS = 5
DUMMY_HASH = hash_password("not-a-real-password")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def six_digits() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def issue_codes(user: User) -> tuple[str, str]:
    """New codes void the old ones."""
    email_code, phone_code = six_digits(), six_digits()
    user.email_code_hash = fingerprint(email_code)
    user.phone_code_hash = fingerprint(phone_code)
    user.codes_expire_at = datetime.now(timezone.utc) + timedelta(minutes=settings.code_ttl_minutes)
    user.code_attempts = 0
    return email_code, phone_code


def send_codes(user: User, email_code: str, phone_code: str) -> dict[str, bool]:
    email_text = f"Your Ngao email code is {email_code}. It expires in {settings.code_ttl_minutes} minutes. If you did not ask for it, ignore this message."
    return {
        "email": try_deliver("email", user.email, email_text, "Your Ngao verification code"),
        "phone": try_deliver("sms", user.phone, f"Your Ngao phone code is {phone_code}"),
    }


def code_reply(user: User, codes: tuple[str, str], delivered: dict[str, bool]) -> dict:
    reply = {"email": user.email, "delivered": delivered}
    if settings.demo_mode:
        reply["demo_codes"] = {"email": codes[0], "phone": codes[1]}
    return reply


def authenticate(body: Login, request: Request, db: Session) -> User:
    """Failures are counted per address and account, so outsiders cannot lock real users out."""
    ip, email = client_ip(request), body.email.lower()
    pair, by_ip = key_for("login", ip, email), key_for("login-ip", ip)
    if blocked(db, pair, *LOGIN_PAIR) or blocked(db, by_ip, *LOGIN_IP):
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again")

    user = db.scalar(select(User).where(User.email == email))
    password_ok = check_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not password_ok:
        record(db, pair)
        record(db, by_ip)
        db.commit()
        raise HTTPException(401, "Wrong email or password")
    return user


@router.post("/register", status_code=201)
def register(body: Registration, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    guard(db, key_for("register-ip", client_ip(request)), *REGISTER_IP)
    guard(db, key_for("code-email", email), *CODE_TARGET)
    guard(db, key_for("code-phone", body.phone), *CODE_TARGET)

    id_hash = fingerprint(body.national_id)
    clashes = db.scalars(
        select(User).where(or_(User.email == email, User.phone == body.phone, User.national_id_hash == id_hash))
    ).all()
    if any(account.is_verified for account in clashes):
        raise HTTPException(409, "An account already exists for one of these details")
    if not confirm_national_id(body.national_id, body.full_name):
        raise HTTPException(422, "Your national ID could not be verified")

    for abandoned in clashes:
        db.delete(abandoned)
    db.flush()

    user = User(
        full_name=body.full_name.strip(),
        email=email,
        phone=body.phone,
        national_id_hash=id_hash,
        password_hash=hash_password(body.password),
        id_verified=True,
    )
    codes = issue_codes(user)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account already exists for one of these details") from None

    db.commit()
    return code_reply(user, codes, send_codes(user, *codes))


@router.post("/verify")
def verify(body: Verification, request: Request, db: Session = Depends(get_db)):
    guard(db, key_for("verify-ip", client_ip(request)), *VERIFY_IP)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or user.is_verified or user.codes_expire_at is None:
        raise HTTPException(400, "These codes are no longer valid. Choose Send new codes")
    if user.codes_expire_at < datetime.now(timezone.utc):
        raise HTTPException(400, "These codes have expired. Choose Send new codes")

    spent = db.execute(
        update(User)
        .where(User.id == user.id, User.code_attempts < MAX_CODE_ATTEMPTS)
        .values(code_attempts=User.code_attempts + 1)
        .execution_options(synchronize_session=False)
    )
    if spent.rowcount == 0:
        db.rollback()
        raise HTTPException(429, "Too many wrong codes. Choose Send new codes")

    codes_match = (
        hmac.compare_digest(fingerprint(body.email_code), user.email_code_hash)
        and hmac.compare_digest(fingerprint(body.phone_code), user.phone_code_hash)
    )
    if not codes_match:
        db.commit()
        raise HTTPException(400, "One or both codes are wrong")

    user.email_verified = user.phone_verified = True
    user.email_code_hash = user.phone_code_hash = user.codes_expire_at = None
    db.commit()
    return {"token": issue_token(user.id)}


@router.post("/resend")
def resend(body: Login, request: Request, db: Session = Depends(get_db)):
    user = authenticate(body, request, db)
    if user.is_verified:
        raise HTTPException(409, "This account is already confirmed. Sign in instead")
    guard(db, key_for("resend", str(user.id)), *RESEND_ACCOUNT)

    codes = issue_codes(user)
    db.commit()
    return code_reply(user, codes, send_codes(user, *codes))


@router.get("/session")
def session(_user: User = Depends(current_user)):
    return {"ok": True}


@router.post("/login")
def login(body: Login, request: Request, db: Session = Depends(get_db)):
    user = authenticate(body, request, db)
    if not user.is_verified:
        raise HTTPException(403, "Finish confirming your codes first. Choose Send new codes")
    return {"token": issue_token(user.id)}
