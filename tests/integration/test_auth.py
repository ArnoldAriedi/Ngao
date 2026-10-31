from datetime import timedelta
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import settings
from app.models import User, utcnow
from app.security import fingerprint, issue_staff_token
from tests.integration.helpers import (
    PASSWORD, codes_sent_to, different_code, make_staff, make_user, normalised_phone, registration, user_headers,
)

AUTH = "/api/v1/auth"


def sign_up(client, **overrides):
    payload = registration(**overrides)
    return payload, client.post(f"{AUTH}/register", json=payload)


def codes_for(outbox, payload):
    return codes_sent_to(outbox, payload["email"].lower(), normalised_phone(payload["phone"]))


def confirm(client, payload, email_code, phone_code):
    return client.post(f"{AUTH}/verify", json={"email": payload["email"], "email_code": email_code, "phone_code": phone_code})


def user_count(db, email):
    return db.scalar(select(func.count()).select_from(User).where(User.email == email.lower()))


def test_sign_up_confirm_and_search_end_to_end(client, outbox):
    payload, created = sign_up(client)
    assert created.status_code == 201
    assert created.json()["email"] == payload["email"].lower()

    verified = confirm(client, payload, *codes_for(outbox, payload))
    assert verified.status_code == 200
    token = verified.json()["token"]

    found = client.post("/api/v1/safety/nearby", json={"latitude": -1.28, "longitude": 36.8}, headers={"Authorization": f"Bearer {token}"})
    assert found.status_code == 200 and found.json() == []


def test_codes_go_to_the_lowercased_email_and_the_normalised_phone(client, outbox):
    payload, _ = sign_up(client)
    email_message = next(m for m in outbox if m.channel == "email")
    sms_message = next(m for m in outbox if m.channel == "sms")
    assert email_message.to == payload["email"].lower() and email_message.subject == "Your Ngao verification code"
    assert sms_message.to == normalised_phone(payload["phone"])
    assert "expires in 10 minutes" in email_message.message


def test_demo_mode_returns_the_codes_in_the_response(client, outbox):
    payload, created = sign_up(client)
    assert created.json()["demo_codes"] == dict(zip(("email", "phone"), codes_for(outbox, payload)))


@pytest.mark.parametrize("change", [
    {"phone": "0612345678"}, {"phone": "12345"}, {"national_id": "123456"}, {"national_id": "123456789"},
    {"password": "short"}, {"email": "not-an-email"}, {"full_name": "ab"},
])
def test_invalid_details_are_refused_and_nothing_is_created(client, db, change):
    payload, response = sign_up(client, **change)
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(User)) == 0


def test_a_confirmed_account_blocks_reuse_of_its_email_phone_or_id(client, db):
    make_user(db, email="taken@example.co.ke", phone="+254711111111", national_id_hash=fingerprint("22222222"))
    by_email = sign_up(client, email="TAKEN@example.co.ke")[1]
    by_phone = sign_up(client, phone="0711111111")[1]
    by_id = sign_up(client, national_id="22222222")[1]
    assert [r.status_code for r in (by_email, by_phone, by_id)] == [409, 409, 409]
    assert by_email.json()["detail"] == "An account already exists for one of these details"
    assert db.scalar(select(func.count()).select_from(User)) == 1


def test_registering_again_replaces_an_unconfirmed_account_and_voids_its_codes(client, db, outbox):
    payload, first = sign_up(client)
    old_codes = codes_for(outbox, payload)
    again = client.post(f"{AUTH}/register", json=payload)
    assert first.status_code == 201 and again.status_code == 201
    assert user_count(db, payload["email"]) == 1

    stale = confirm(client, payload, *old_codes)
    assert stale.status_code == 400 and stale.json()["detail"] == "One or both codes are wrong"
    assert confirm(client, payload, *codes_for(outbox, payload)).status_code == 200


def test_five_wrong_guesses_lock_the_codes_even_against_the_right_ones(client, outbox):
    payload, _ = sign_up(client)
    right_email, right_phone = codes_for(outbox, payload)
    wrong = (different_code(right_email), different_code(right_phone))
    attempts = [confirm(client, payload, *wrong) for _ in range(5)]
    assert [a.status_code for a in attempts] == [400] * 5
    assert attempts[0].json()["detail"] == "One or both codes are wrong"

    locked = confirm(client, payload, right_email, right_phone)
    assert locked.status_code == 429 and locked.json()["detail"] == "Too many wrong codes. Choose Send new codes"


def test_expired_codes_are_refused(client, db, outbox):
    payload, _ = sign_up(client)
    user = db.scalar(select(User).where(User.email == payload["email"].lower()))
    user.codes_expire_at = utcnow() - timedelta(minutes=1)
    db.commit()
    response = confirm(client, payload, *codes_for(outbox, payload))
    assert response.status_code == 400 and response.json()["detail"] == "These codes have expired. Choose Send new codes"


def test_confirming_an_unknown_or_already_confirmed_account_is_refused(client, db):
    make_user(db, email="done@example.co.ke")
    for email in ("done@example.co.ke", "nobody@example.co.ke"):
        response = client.post(f"{AUTH}/verify", json={"email": email, "email_code": "123456", "phone_code": "123456"})
        assert response.status_code == 400
        assert response.json()["detail"] == "These codes are no longer valid. Choose Send new codes"


def test_malformed_codes_are_rejected_before_any_attempt_is_spent(client, outbox):
    payload, _ = sign_up(client)
    response = client.post(f"{AUTH}/verify", json={"email": payload["email"], "email_code": "12ab56", "phone_code": "123456"})
    assert response.status_code == 422


def test_sending_new_codes_voids_the_old_ones(client, outbox):
    payload, _ = sign_up(client)
    old_codes = codes_for(outbox, payload)
    resent = client.post(f"{AUTH}/resend", json={"email": payload["email"], "password": PASSWORD})
    assert resent.status_code == 200
    new_codes = codes_for(outbox, payload)
    assert new_codes != old_codes

    assert confirm(client, payload, *old_codes).status_code == 400
    assert confirm(client, payload, *new_codes).status_code == 200


def test_new_codes_rescue_an_account_locked_by_wrong_guesses(client, outbox):
    payload, _ = sign_up(client)
    wrong = tuple(different_code(code) for code in codes_for(outbox, payload))
    for _ in range(5):
        confirm(client, payload, *wrong)
    assert confirm(client, payload, *codes_for(outbox, payload)).status_code == 429

    client.post(f"{AUTH}/resend", json={"email": payload["email"], "password": PASSWORD})
    assert confirm(client, payload, *codes_for(outbox, payload)).status_code == 200


def test_resend_needs_the_password_and_an_unconfirmed_account(client, db, outbox):
    payload, _ = sign_up(client)
    make_user(db, email="done@example.co.ke")
    wrong_password = client.post(f"{AUTH}/resend", json={"email": payload["email"], "password": "not-the-password"})
    unknown = client.post(f"{AUTH}/resend", json={"email": "nobody@example.co.ke", "password": PASSWORD})
    confirmed = client.post(f"{AUTH}/resend", json={"email": "done@example.co.ke", "password": PASSWORD})
    assert (wrong_password.status_code, unknown.status_code, confirmed.status_code) == (401, 401, 409)
    assert wrong_password.json()["detail"] == unknown.json()["detail"] == "Wrong email or password"
    assert confirmed.json()["detail"] == "This account is already confirmed. Sign in instead"


def test_resend_is_limited_to_three_an_hour(client, outbox):
    payload, _ = sign_up(client)
    body = {"email": payload["email"], "password": PASSWORD}
    assert [client.post(f"{AUTH}/resend", json=body).status_code for _ in range(3)] == [200, 200, 200]
    blocked = client.post(f"{AUTH}/resend", json=body)
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many requests. Try again later"
    assert blocked.headers["Retry-After"] == "3600"


def test_every_sign_up_reply_says_what_was_actually_delivered(client, outbox):
    payload, created = sign_up(client)
    assert created.json()["delivered"] == {"email": True, "phone": True}


def break_channel(monkeypatch, outbox, channel):
    state = {"broken": True}

    def flaky(sent_channel, destination, message, subject="Ngao"):
        if state["broken"] and sent_channel == channel:
            raise HTTPException(503, "gateway down")
        outbox.append(SimpleNamespace(channel=sent_channel, to=destination, message=message, subject=subject))

    monkeypatch.setattr("app.notify.deliver", flaky)
    return state


def test_a_dead_sms_channel_is_reported_and_leaves_a_recoverable_account(client, db, outbox, monkeypatch):
    sms = break_channel(monkeypatch, outbox, "sms")
    payload, created = sign_up(client)
    assert created.status_code == 201
    assert created.json()["delivered"] == {"email": True, "phone": False}
    assert user_count(db, payload["email"]) == 1

    again = client.post(f"{AUTH}/resend", json={"email": payload["email"], "password": PASSWORD})
    assert again.status_code == 200 and again.json()["delivered"] == {"email": True, "phone": False}

    sms["broken"] = False
    fixed = client.post(f"{AUTH}/resend", json={"email": payload["email"], "password": PASSWORD})
    assert fixed.json()["delivered"] == {"email": True, "phone": True}
    assert confirm(client, payload, *codes_for(outbox, payload)).status_code == 200


def test_a_dead_email_channel_is_reported_too(client, outbox, monkeypatch):
    break_channel(monkeypatch, outbox, "email")
    payload, created = sign_up(client)
    assert created.status_code == 201 and created.json()["delivered"] == {"email": False, "phone": True}


def test_the_session_check_accepts_a_live_session_and_refuses_the_rest(client, db):
    user = make_user(db)
    assert client.get(f"{AUTH}/session", headers=user_headers(user)).json() == {"ok": True}
    assert client.get(f"{AUTH}/session").status_code == 401
    assert client.get(f"{AUTH}/session", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get(f"{AUTH}/session", headers=user_headers(make_user(db, verified=False))).status_code == 403


def test_signing_up_is_limited_per_address(client):
    statuses = [sign_up(client)[1].status_code for _ in range(6)]
    assert statuses == [201, 201, 201, 201, 201, 429]


def test_one_email_cannot_be_hammered_with_codes(client):
    payload = registration()
    statuses = [client.post(f"{AUTH}/register", json=payload).status_code for _ in range(4)]
    assert statuses == [201, 201, 201, 429]


def test_login_returns_a_token_for_a_confirmed_account(client, db):
    user = make_user(db)
    response = client.post(f"{AUTH}/login", json={"email": user.email.upper(), "password": PASSWORD})
    assert response.status_code == 200
    claims = jwt.decode(response.json()["token"], settings.app_secret, algorithms=["HS256"])
    assert claims["sub"] == str(user.id)


def test_wrong_password_and_unknown_email_are_indistinguishable(client, db):
    user = make_user(db)
    wrong = client.post(f"{AUTH}/login", json={"email": user.email, "password": "not-the-password"})
    unknown = client.post(f"{AUTH}/login", json={"email": "nobody@example.co.ke", "password": PASSWORD})
    assert (wrong.status_code, unknown.status_code) == (401, 401)
    assert wrong.json() == unknown.json() == {"detail": "Wrong email or password"}


def test_unconfirmed_accounts_cannot_log_in(client, db):
    user = make_user(db, verified=False)
    response = client.post(f"{AUTH}/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["detail"] == "Finish confirming your codes first. Choose Send new codes"


def test_five_wrong_passwords_lock_that_account_but_not_other_accounts(client, db):
    target, bystander = make_user(db), make_user(db)
    wrong = {"email": target.email, "password": "not-the-password"}
    assert [client.post(f"{AUTH}/login", json=wrong).status_code for _ in range(5)] == [401] * 5

    locked = client.post(f"{AUTH}/login", json={"email": target.email, "password": PASSWORD})
    assert locked.status_code == 429
    assert locked.json()["detail"] == "Too many attempts. Wait a few minutes and try again"
    assert client.post(f"{AUTH}/login", json={"email": bystander.email, "password": PASSWORD}).status_code == 200


def test_thirty_failures_across_accounts_block_the_address(client, db):
    user = make_user(db)
    for n in range(30):
        assert client.post(f"{AUTH}/login", json={"email": f"nobody{n}@example.co.ke", "password": "x" * 12}).status_code == 401
    assert client.post(f"{AUTH}/login", json={"email": user.email, "password": PASSWORD}).status_code == 429


def forged(**claims):
    return jwt.encode(claims, settings.app_secret, algorithm="HS256")


@pytest.mark.parametrize("header,status,detail", [
    (None, 401, "Sign in to continue"),
    ("Basic abc", 401, "Sign in to continue"),
    ("Bearer garbage", 401, "Your session has expired. Sign in again"),
    ("Bearer " + forged(sub="1", exp=utcnow() - timedelta(hours=1)), 401, "Your session has expired. Sign in again"),
    ("Bearer " + forged(sub="not-a-number", exp=utcnow() + timedelta(hours=1)), 401, "Your session has expired. Sign in again"),
    ("Bearer " + forged(exp=utcnow() + timedelta(hours=1)), 401, "Your session has expired. Sign in again"),
    ("Bearer " + forged(sub="999999", exp=utcnow() + timedelta(hours=1)), 401, "Sign in to continue"),
])
def test_bad_credentials_are_refused_with_a_clean_401(client, header, status, detail):
    headers = {"Authorization": header} if header else {}
    response = client.post("/api/v1/safety/nearby", json={"latitude": -1.28, "longitude": 36.8}, headers=headers)
    assert response.status_code == status and response.json()["detail"] == detail


def test_a_staff_token_is_not_a_user_token_and_the_reverse(client, db):
    user = make_user(db)
    staff, _ = make_staff(db)
    as_user = client.post("/api/v1/safety/nearby", json={"latitude": -1.28, "longitude": 36.8},
                          headers={"Authorization": f"Bearer {issue_staff_token(staff.id)}"})
    as_staff = client.get("/api/v1/admin/corrections", headers=user_headers(user))
    assert as_user.status_code == 401 and as_staff.status_code == 401
    assert as_staff.json()["detail"] == "Staff session missing or expired"


def test_an_unconfirmed_account_cannot_use_a_valid_token(client, db):
    user = make_user(db, verified=False)
    response = client.post("/api/v1/safety/nearby", json={"latitude": -1.28, "longitude": 36.8}, headers=user_headers(user))
    assert response.status_code == 403
    assert response.json()["detail"] == "Confirm your email, phone and ID to continue"
