from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditEntry, ConvictionRecord, Staff, utcnow
from tests.integration.helpers import (
    PASSWORD, current_otp, make_record, make_staff, make_user, staff_headers, user_headers,
)

LOGIN = "/api/v1/staff/login"
WRONG = "Wrong email, password or code"


def sign_in(client, staff, secret, **overrides):
    body = {"email": staff.email, "password": PASSWORD, "otp": current_otp(secret), **overrides}
    return client.post(LOGIN, json=body)


def audit_entries(db, action):
    db.expire_all()
    return list(db.scalars(select(AuditEntry).where(AuditEntry.action == action).order_by(AuditEntry.id)))


def test_staff_sign_in_with_password_and_code_gives_a_working_staff_token(client, db):
    staff, secret = make_staff(db, "ADMIN")
    response = sign_in(client, staff, secret)
    assert response.status_code == 200 and response.json()["role"] == "ADMIN"
    queue = client.get("/api/v1/admin/corrections", headers={"Authorization": f"Bearer {response.json()['token']}"})
    assert queue.status_code == 200
    assert [e.staff_id for e in audit_entries(db, "STAFF_LOGIN")] == [staff.id]


def test_a_code_from_the_previous_thirty_seconds_still_works(client, db):
    staff, secret = make_staff(db)
    assert sign_in(client, staff, secret, otp=current_otp(secret, steps_ago=1)).status_code == 200


@pytest.mark.parametrize("change", [{"password": "not-the-password"}, {"otp": "000000"}, {"email": "nobody@example.go.ke"}])
def test_any_wrong_factor_gives_the_same_answer_and_is_recorded(client, db, change):
    staff, secret = make_staff(db)
    response = sign_in(client, staff, secret, **change)
    assert response.status_code == 401 and response.json()["detail"] == WRONG
    failures = audit_entries(db, "STAFF_LOGIN_FAILED")
    assert len(failures) == 1
    assert failures[0].staff_id == (None if "email" in change else staff.id)


def test_a_code_cannot_be_used_twice(client, db):
    staff, secret = make_staff(db)
    code = current_otp(secret)
    assert sign_in(client, staff, secret, otp=code).status_code == 200
    replay = sign_in(client, staff, secret, otp=code)
    assert replay.status_code == 401 and replay.json()["detail"] == WRONG


def test_five_failures_lock_the_account_even_for_the_right_credentials(client, db):
    staff, secret = make_staff(db)
    for _ in range(5):
        assert sign_in(client, staff, secret, otp="000000").status_code == 401
    locked = sign_in(client, staff, secret)
    assert locked.status_code == 429 and locked.json()["detail"] == "Account locked. Try again later"
    db.refresh(staff)
    assert staff.locked_until > utcnow()


def test_the_lock_lifts_when_its_time_is_up(client, db):
    staff, secret = make_staff(db)
    for _ in range(5):
        sign_in(client, staff, secret, otp="000000")
    db.refresh(staff)
    staff.locked_until = utcnow() - timedelta(days=1)
    db.commit()
    assert sign_in(client, staff, secret).status_code == 200


def test_a_deactivated_member_cannot_sign_in_and_loses_open_sessions(client, db):
    staff, secret = make_staff(db, is_active=False)
    assert sign_in(client, staff, secret).status_code == 401
    session_before = staff_headers(staff)
    refused = client.get("/api/v1/admin/corrections", headers=session_before)
    assert refused.status_code == 403 and refused.json()["detail"] == "Staff access required"


def test_staff_endpoints_refuse_ordinary_users_and_anonymous_calls(client, db):
    user = make_user(db)
    for headers in ({}, user_headers(user)):
        assert client.get("/api/v1/admin/corrections", headers=headers).status_code == 401
        assert client.get("/api/v1/admin/queue/health", headers=headers).status_code == 401


ADMIN_ONLY = [
    ("get", "/api/v1/admin/audit"),
    ("get", "/api/v1/admin/records/pending"),
    ("post", "/api/v1/admin/records/1/publication?status=APPROVED"),
    ("post", "/api/v1/admin/records/approve"),
]


@pytest.mark.parametrize("method,path", ADMIN_ONLY)
def test_reviewers_cannot_use_administrator_endpoints(client, db, method, path):
    reviewer, _ = make_staff(db, "REVIEWER")
    kwargs = {"json": {"record_ids": [1]}} if path.endswith("approve") else {}
    response = getattr(client, method)(path, headers=staff_headers(reviewer), **kwargs)
    assert response.status_code == 403 and response.json()["detail"] == "Administrator access required"


def test_an_administrator_can_set_a_publication_status_and_it_is_audited(client, db):
    admin, _ = make_staff(db, "ADMIN")
    record = make_record(db)
    response = client.post(f"/api/v1/admin/records/{record.id}/publication?status=SUSPENDED", headers=staff_headers(admin))
    assert response.status_code == 200 and response.json() == {"record_id": record.id, "publication_status": "SUSPENDED"}
    db.refresh(record)
    assert record.publication_status == "SUSPENDED"
    entry = audit_entries(db, "RECORD_STATUS_CHANGED")[0]
    assert entry.staff_id == admin.id and entry.detail == "APPROVED -> SUSPENDED" and entry.target_id == str(record.id)


def test_publication_rejects_an_unknown_status_or_record(client, db):
    admin, _ = make_staff(db, "ADMIN")
    record = make_record(db)
    bad_status = client.post(f"/api/v1/admin/records/{record.id}/publication?status=DELETED", headers=staff_headers(admin))
    missing = client.post("/api/v1/admin/records/999999/publication?status=APPROVED", headers=staff_headers(admin))
    assert (bad_status.status_code, bad_status.json()["detail"]) == (400, "Invalid publication status")
    assert (missing.status_code, missing.json()["detail"]) == (404, "Record not found")


def test_pending_list_shows_real_unpublished_records_with_their_source(client, db):
    admin, _ = make_staff(db, "ADMIN")
    waiting = make_record(db, publication_status="PENDING", is_synthetic=False, source_reference="CASE-77")
    make_record(db, publication_status="PENDING", is_synthetic=True)
    make_record(db, publication_status="APPROVED", is_synthetic=False)
    listed = client.get("/api/v1/admin/records/pending", headers=staff_headers(admin)).json()
    assert [item["id"] for item in listed] == [waiting.id]
    assert listed[0]["source_reference"] == "CASE-77" and listed[0]["source_name"] == "Test court"


def test_pending_list_respects_its_limit(client, db):
    admin, _ = make_staff(db, "ADMIN")
    for _ in range(3):
        make_record(db, publication_status="PENDING", is_synthetic=False)
    assert len(client.get("/api/v1/admin/records/pending?limit=2", headers=staff_headers(admin)).json()) == 2
    assert client.get("/api/v1/admin/records/pending?limit=0", headers=staff_headers(admin)).status_code == 422


def test_approving_publishes_pending_records_and_audits_each_one(client, db):
    admin, _ = make_staff(db, "ADMIN")
    first = make_record(db, publication_status="PENDING", is_synthetic=False)
    second = make_record(db, publication_status="PENDING", is_synthetic=False)
    already = make_record(db, publication_status="APPROVED", is_synthetic=False)
    response = client.post(
        "/api/v1/admin/records/approve", headers=staff_headers(admin),
        json={"record_ids": [first.id, second.id, first.id, already.id, 999999]},
    )
    assert response.status_code == 200
    assert response.json() == {"approved": [first.id, second.id], "not_pending": [already.id, 999999]}
    db.expire_all()
    assert db.get(ConvictionRecord, first.id).publication_status == "APPROVED"
    entries = audit_entries(db, "RECORD_STATUS_CHANGED")
    assert [e.target_id for e in entries] == [str(first.id), str(second.id)]
    assert all(e.staff_id == admin.id and e.detail == "PENDING -> APPROVED" for e in entries)


@pytest.mark.parametrize("ids", [[], list(range(201))])
def test_approval_batches_must_be_between_one_and_two_hundred(client, db, ids):
    admin, _ = make_staff(db, "ADMIN")
    assert client.post("/api/v1/admin/records/approve", json={"record_ids": ids}, headers=staff_headers(admin)).status_code == 422


def test_the_audit_log_is_newest_first_filterable_and_bounded(client, db):
    admin, secret = make_staff(db, "ADMIN")
    sign_in(client, admin, secret)
    sign_in(client, admin, secret, otp="000000")
    log = client.get("/api/v1/admin/audit", headers=staff_headers(admin)).json()
    assert [e["action"] for e in log] == ["STAFF_LOGIN_FAILED", "STAFF_LOGIN"]
    assert log[0]["id"] > log[1]["id"]
    only_logins = client.get("/api/v1/admin/audit?action=STAFF_LOGIN", headers=staff_headers(admin)).json()
    assert [e["action"] for e in only_logins] == ["STAFF_LOGIN"]
    assert len(client.get("/api/v1/admin/audit?limit=1", headers=staff_headers(admin)).json()) == 1
    assert client.get("/api/v1/admin/audit?limit=0", headers=staff_headers(admin)).status_code == 422
    assert client.get("/api/v1/admin/audit?limit=501", headers=staff_headers(admin)).status_code == 422


def test_the_authenticator_secret_is_stored_encrypted(db):
    staff, secret = make_staff(db)
    stored = db.scalar(select(Staff.totp_secret_sealed).where(Staff.id == staff.id))
    assert secret not in stored and stored.startswith("gAAAA")
