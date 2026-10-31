from types import SimpleNamespace

from sqlalchemy import func, select

from app.auth import register, verify
from app.config import settings
from app.models import AuditEntry, ConvictionRecord, Staff, User
from app.schemas import ApproveRecords, Registration, Verification
from app.staff import approve_records
from app.main import spend_search
from tests.integration.helpers import codes_sent_to, different_code, make_record, make_staff, make_user, run_in_parallel

REQUEST = SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.9"))


def test_parallel_duplicate_sign_ups_produce_one_account_and_no_server_error(db):
    body = Registration(full_name="Same Person", email="same@example.co.ke", phone="0712345678", national_id="12345678", password="long-enough-pw")
    outcomes = run_in_parallel(lambda session, _: register(body, REQUEST, session), 3)
    assert set(outcomes) <= {"ok", 409} and "ok" in outcomes
    assert db.scalar(select(func.count()).select_from(User).where(User.email == "same@example.co.ke")) == 1


def test_parallel_wrong_guesses_cannot_exceed_five_attempts(db, outbox):
    body = Registration(full_name="Guess Target", email="target@example.co.ke", phone="0712345679", national_id="12345679", password="long-enough-pw")
    run_in_parallel(lambda session, _: register(body, REQUEST, session), 1)
    email_code, phone_code = codes_sent_to(outbox, "target@example.co.ke", "+254712345679")
    wrong = Verification(email="target@example.co.ke", email_code=different_code(email_code), phone_code=different_code(phone_code))

    outcomes = run_in_parallel(lambda session, _: verify(wrong, REQUEST, session), 12)
    assert outcomes.count(429) >= 12 - 5
    db.expire_all()
    assert db.scalar(select(User.code_attempts).where(User.email == "target@example.co.ke")) == 5


def test_approving_the_same_record_in_parallel_audits_it_once(db):
    admins = [make_staff(db, "ADMIN")[0] for _ in range(5)]
    record = make_record(db, publication_status="PENDING", is_synthetic=False)
    run_in_parallel(lambda session, index: approve_records(ApproveRecords(record_ids=[record.id]), session.get(Staff, admins[index].id), session), 5)
    db.expire_all()
    assert db.get(ConvictionRecord, record.id).publication_status == "APPROVED"
    entries = db.scalars(select(AuditEntry).where(AuditEntry.action == "RECORD_STATUS_CHANGED")).all()
    assert len(entries) == 1


def test_the_search_limit_holds_under_parallel_lookups_and_searches(db, monkeypatch):
    monkeypatch.setattr(settings, "daily_search_limit", 4)
    user = make_user(db)
    outcomes = run_in_parallel(lambda session, _: spend_search(session.get(User, user.id), session), 20)
    assert outcomes.count("ok") == 4
