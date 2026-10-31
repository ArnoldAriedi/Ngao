from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.corrections import report_mistake, suspend_overdue
from app.models import AuditEntry, ConvictionRecord, CorrectionRequest, User
from app.schemas import CorrectionIn
from sqlalchemy.exc import IntegrityError
from tests.integration.helpers import (
    make_record, make_report, make_staff, make_user, run_in_parallel, search, staff_headers, user_headers,
)

FILE = "/api/v1/safety/records/{}/corrections"
DETAILS = "The court file shows a different person with the same name."


def file_report(client, user, record, reason="WRONG_PERSON", details=DETAILS):
    return client.post(FILE.format(record.public_record_id), json={"reason": reason, "details": details}, headers=user_headers(user))


def hours_from_now(iso_text):
    moment = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    return (moment - datetime.now(timezone.utc)).total_seconds() / 3600


def reload(db, model, key):
    db.expire_all()
    return db.get(model, key)


def audit_actions(db):
    return [entry.action for entry in db.scalars(select(AuditEntry).order_by(AuditEntry.id))]


def test_an_urgent_report_is_due_in_72_hours(client, db):
    response = file_report(client, make_user(db), make_record(db))
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "OPEN" and isinstance(body["reference"], int)
    assert 71.9 < hours_from_now(body["review_by"]) < 72.1


def test_a_routine_report_is_due_in_14_days(client, db):
    response = file_report(client, make_user(db), make_record(db), reason="WRONG_DETAILS")
    assert 14 * 24 - 0.1 < hours_from_now(response.json()["review_by"]) < 14 * 24 + 0.1


@pytest.mark.parametrize("change", [{"reason": "DISLIKE"}, {"details": "too short"}, {"details": "x" * 2001}, {"reason": ""}])
def test_bad_reports_are_refused(client, db, change):
    body = {"reason": "WRONG_PERSON", "details": DETAILS, **change}
    record = make_record(db)
    response = client.post(FILE.format(record.public_record_id), json=body, headers=user_headers(make_user(db)))
    assert response.status_code == 422


def test_reports_need_a_signed_in_user(client, db):
    record = make_record(db)
    assert client.post(FILE.format(record.public_record_id), json={"reason": "OTHER", "details": DETAILS}).status_code == 401


def test_only_listed_records_can_be_reported(client, db):
    user = make_user(db)
    hidden = make_record(db, publication_status="SUSPENDED")
    assert file_report(client, user, hidden).status_code == 404
    unknown = SimpleNamespace(public_record_id="NGA-NOSUCHREC")
    response = file_report(client, user, unknown)
    assert response.status_code == 404 and response.json()["detail"] == "Record not found"


def test_one_open_report_per_person_per_record(client, db):
    user, record = make_user(db), make_record(db)
    assert file_report(client, user, record).status_code == 201
    again = file_report(client, user, record)
    assert again.status_code == 409 and again.json()["detail"] == "You already have an open report for this record"
    assert file_report(client, make_user(db), record).status_code == 201


def test_reports_are_capped_per_person_per_day(client, db, monkeypatch):
    monkeypatch.setattr(settings, "daily_report_limit", 2)
    user = make_user(db)
    statuses = [file_report(client, user, make_record(db)).status_code for _ in range(3)]
    assert statuses == [201, 201, 429]


def test_an_urgent_report_alerts_the_review_inbox_but_a_routine_one_does_not(client, db, outbox, monkeypatch):
    monkeypatch.setattr(settings, "review_alert_email", "alerts@example.go.ke")
    user = make_user(db)
    file_report(client, user, make_record(db), reason="WRONG_DETAILS")
    assert [m for m in outbox if m.to == "alerts@example.go.ke"] == []
    file_report(client, user, make_record(db), reason="CONVICTION_OVERTURNED")
    alert = [m for m in outbox if m.to == "alerts@example.go.ke"]
    assert len(alert) == 1 and alert[0].subject == "Urgent Ngao report"


def test_people_see_only_their_own_reports_with_deadlines_while_open(client, db):
    mine, other = make_user(db), make_user(db)
    record = make_record(db)
    open_report = make_report(db, record, mine)
    closed = make_report(db, make_record(db), mine, status="RESOLVED", resolution_note="Checked with the registry.", hours_old=5)
    make_report(db, record, other)
    reports = client.get("/api/v1/safety/corrections", headers=user_headers(mine)).json()
    by_reference = {r["reference"]: r for r in reports}
    assert set(by_reference) == {open_report.id, closed.id}
    assert by_reference[open_report.id]["review_by"] is not None
    assert by_reference[closed.id]["review_by"] is None and by_reference[closed.id]["resolution_note"] == "Checked with the registry."


def test_the_review_queue_is_for_staff_only(client, db):
    assert client.get("/api/v1/admin/corrections").status_code == 401
    assert client.get("/api/v1/admin/corrections", headers=user_headers(make_user(db))).status_code == 401


def test_the_queue_is_ordered_by_deadline_flags_overdue_and_hides_who_reported(client, db):
    staff, _ = make_staff(db)
    late = make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=80)
    soon = make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=60)
    routine = make_report(db, make_record(db), make_user(db), "OTHER", hours_old=1)
    make_report(db, make_record(db), make_user(db), status="RESOLVED")
    queue = client.get("/api/v1/admin/corrections", headers=staff_headers(staff)).json()
    assert [item["id"] for item in queue] == [late.id, soon.id, routine.id]
    assert [item["overdue"] for item in queue] == [True, False, False]
    assert not {"user_id", "reporter_user_id"} & set(queue[0])


def test_the_queue_can_show_closed_reports(client, db):
    staff, _ = make_staff(db)
    closed = make_report(db, make_record(db), make_user(db), status="RESOLVED")
    shown = client.get("/api/v1/admin/corrections?status=RESOLVED", headers=staff_headers(staff)).json()
    assert [item["id"] for item in shown] == [closed.id]


def test_claiming_an_urgent_report_suspends_the_record_and_it_disappears_from_search(client, db):
    staff, _ = make_staff(db)
    reader, record = make_user(db), make_record(db)
    report = make_report(db, record, make_user(db))
    response = client.post(f"/api/v1/admin/corrections/{report.id}/claim", headers=staff_headers(staff))
    assert response.status_code == 200
    assert response.json() == {"id": report.id, "status": "IN_REVIEW", "record_suspended": True}

    assert reload(db, ConvictionRecord, record.id).publication_status == "SUSPENDED"
    claimed = reload(db, CorrectionRequest, report.id)
    assert claimed.claimed_by_id == staff.id and claimed.auto_suspended is True
    assert search(client, reader).json() == []
    assert audit_actions(db) == ["REPORT_CLAIMED", "AUTO_SUSPEND_ON_REVIEW"]


def test_claiming_a_routine_report_leaves_the_record_visible(client, db):
    staff, _ = make_staff(db)
    record = make_record(db)
    report = make_report(db, record, make_user(db), "WRONG_DETAILS")
    response = client.post(f"/api/v1/admin/corrections/{report.id}/claim", headers=staff_headers(staff))
    assert response.json()["record_suspended"] is False
    assert reload(db, ConvictionRecord, record.id).publication_status == "APPROVED"


def test_suspension_on_review_start_can_be_switched_off(client, db, monkeypatch):
    monkeypatch.setattr(settings, "suspend_on_review_start", False)
    staff, _ = make_staff(db)
    record = make_record(db)
    report = make_report(db, record, make_user(db))
    client.post(f"/api/v1/admin/corrections/{report.id}/claim", headers=staff_headers(staff))
    assert reload(db, ConvictionRecord, record.id).publication_status == "APPROVED"


def test_a_report_can_only_be_claimed_once(client, db):
    first, _ = make_staff(db)
    second, _ = make_staff(db)
    report = make_report(db, make_record(db), make_user(db))
    assert client.post(f"/api/v1/admin/corrections/{report.id}/claim", headers=staff_headers(first)).status_code == 200
    again = client.post(f"/api/v1/admin/corrections/{report.id}/claim", headers=staff_headers(second))
    assert again.status_code == 409 and again.json()["detail"] == "Report is already claimed or closed"
    assert reload(db, CorrectionRequest, report.id).claimed_by_id == first.id


def test_claiming_a_missing_report_is_a_404(client, db):
    staff, _ = make_staff(db)
    response = client.post("/api/v1/admin/corrections/999999/claim", headers=staff_headers(staff))
    assert response.status_code == 404 and response.json()["detail"] == "Report not found"


def claim(client, staff, report):
    return client.post(f"/api/v1/admin/corrections/{report.id}/claim", headers=staff_headers(staff))


def resolve(client, staff, report, **body):
    payload = {"outcome": "RESOLVED", "note": "Checked against the court file.", **body}
    return client.post(f"/api/v1/admin/corrections/{report.id}/resolve", json=payload, headers=staff_headers(staff))


def test_a_report_that_suspended_a_record_must_say_what_happens_to_it(client, db):
    staff, _ = make_staff(db)
    report = make_report(db, make_record(db), make_user(db))
    claim(client, staff, report)
    response = resolve(client, staff, report)
    assert response.status_code == 422
    assert response.json()["detail"] == "This report suspended the record. Choose what happens to it with record_status"
    assert reload(db, CorrectionRequest, report.id).status == "IN_REVIEW"


def test_a_reviewer_can_restore_a_record_and_the_reporter_is_told(client, db, outbox):
    staff, _ = make_staff(db)
    reporter, record = make_user(db), make_record(db)
    report = make_report(db, record, reporter)
    claim(client, staff, report)
    response = resolve(client, staff, report, outcome="REJECTED", record_status="APPROVED")
    assert response.status_code == 200
    assert response.json() == {"id": report.id, "status": "REJECTED", "reporter_notified": True}

    assert reload(db, ConvictionRecord, record.id).publication_status == "APPROVED"
    assert len(search(client, make_user(db)).json()) == 1
    notice = [m for m in outbox if m.to == reporter.email][-1]
    assert notice.subject == f"Update on your Ngao report {report.id}" and "not accepted" in notice.message
    assert reload(db, CorrectionRequest, report.id).notified_at is not None


def test_an_accepted_report_says_accepted(client, db, outbox):
    staff, _ = make_staff(db)
    reporter = make_user(db)
    report = make_report(db, make_record(db), reporter, "WRONG_DETAILS")
    assert resolve(client, staff, report).status_code == 200
    assert "accepted" in [m for m in outbox if m.to == reporter.email][-1].message


def test_only_an_administrator_can_remove_a_record(client, db):
    reviewer, _ = make_staff(db, "REVIEWER")
    record = make_record(db)
    report = make_report(db, record, make_user(db))
    claim(client, reviewer, report)
    refused = resolve(client, reviewer, report, record_status="REMOVED")
    assert refused.status_code == 403 and refused.json()["detail"] == "That status change needs an administrator"
    assert reload(db, CorrectionRequest, report.id).status == "IN_REVIEW"
    assert reload(db, ConvictionRecord, record.id).publication_status == "SUSPENDED"

    admin, _ = make_staff(db, "ADMIN")
    assert resolve(client, admin, report, record_status="REMOVED").status_code == 200
    assert reload(db, ConvictionRecord, record.id).publication_status == "REMOVED"
    detail = [e.detail for e in db.scalars(select(AuditEntry).where(AuditEntry.action == "RECORD_STATUS_CHANGED"))]
    assert detail == [f"SUSPENDED -> REMOVED; report {report.id}"]


def test_a_routine_report_closes_without_touching_the_record(client, db):
    staff, _ = make_staff(db)
    record = make_record(db)
    report = make_report(db, record, make_user(db), "OTHER")
    assert resolve(client, staff, report).status_code == 200
    assert reload(db, ConvictionRecord, record.id).publication_status == "APPROVED"
    assert audit_actions(db) == ["REPORT_RESOLVED"]


@pytest.mark.parametrize("change", [{"note": "ok"}, {"outcome": "MAYBE"}, {"record_status": "DELETED"}])
def test_bad_resolutions_are_refused(client, db, change):
    staff, _ = make_staff(db)
    report = make_report(db, make_record(db), make_user(db), "OTHER")
    assert resolve(client, staff, report, **change).status_code == 422


def test_a_report_cannot_be_closed_twice_or_found_when_missing(client, db):
    staff, _ = make_staff(db)
    report = make_report(db, make_record(db), make_user(db), "OTHER")
    assert resolve(client, staff, report).status_code == 200
    again = resolve(client, staff, report)
    assert again.status_code == 409 and again.json()["detail"] == "Report is already closed"
    ghost = SimpleNamespace(id=999999)
    assert resolve(client, staff, ghost).status_code == 404


def test_a_failed_notification_does_not_block_closing_the_report(client, db, monkeypatch):
    monkeypatch.setattr("app.corrections.try_deliver", lambda *args, **kwargs: False)
    staff, _ = make_staff(db)
    report = make_report(db, make_record(db), make_user(db), "OTHER")
    response = resolve(client, staff, report)
    assert response.status_code == 200 and response.json()["reporter_notified"] is False
    assert reload(db, CorrectionRequest, report.id).notified_at is None


def test_after_a_report_closes_the_person_can_report_again(client, db):
    staff, _ = make_staff(db)
    user, record = make_user(db), make_record(db)
    first = file_report(client, user, record, reason="OTHER")
    assert file_report(client, user, record, reason="OTHER").status_code == 409
    resolve(client, staff, SimpleNamespace(id=first.json()["reference"]))
    assert file_report(client, user, record, reason="OTHER").status_code == 201


def test_queue_health_counts_each_state_and_flags_what_needs_attention(client, db):
    staff, _ = make_staff(db)
    user = make_user(db)
    make_report(db, make_record(db), user, "WRONG_PERSON", hours_old=10)
    make_report(db, make_record(db), user, "WRONG_PERSON", hours_old=30)
    make_report(db, make_record(db), user, "WRONG_PERSON", hours_old=50)
    make_report(db, make_record(db), user, "WRONG_PERSON", hours_old=80)
    make_report(db, make_record(db), user, "WRONG_PERSON", hours_old=60, status="IN_REVIEW")
    make_report(db, make_record(db), user, "OTHER", hours_old=20 * 24)
    body = client.get("/api/v1/admin/queue/health", headers=staff_headers(staff)).json()
    assert body["by_state"] == {"ON_TRACK": 2, "CLAIM_LATE": 1, "ESCALATE": 1, "OVERDUE": 2}
    assert body["open_reports"] == 6 and body["needs_attention"] == 4


def test_queue_health_warns_when_too_few_staff_are_active(client, db, monkeypatch):
    monkeypatch.setattr(settings, "min_active_reviewers", 3)
    staff, _ = make_staff(db)
    make_staff(db)
    assert client.get("/api/v1/admin/queue/health", headers=staff_headers(staff)).json()["understaffed"] is True
    make_staff(db)
    make_staff(db, is_active=False)
    body = client.get("/api/v1/admin/queue/health", headers=staff_headers(staff)).json()
    assert body["understaffed"] is False and body["active_staff"] == 3


def test_the_sweep_suspends_an_overdue_unclaimed_urgent_report_once(db):
    record = make_record(db)
    report = make_report(db, record, make_user(db), "WRONG_PERSON", hours_old=80)
    assert suspend_overdue(db) == 1
    assert reload(db, ConvictionRecord, record.id).publication_status == "SUSPENDED"
    assert reload(db, CorrectionRequest, report.id).auto_suspended is True
    entry = db.scalar(select(AuditEntry))
    assert entry.action == "AUTO_SUSPEND_OVERDUE" and entry.staff_id is None
    assert suspend_overdue(db) == 0
    assert audit_actions(db) == ["AUTO_SUSPEND_OVERDUE"]


def test_the_sweep_ignores_reports_that_are_not_urgent_and_overdue(db):
    make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=10)
    make_report(db, make_record(db), make_user(db), "WRONG_DETAILS", hours_old=80)
    make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=80, status="RESOLVED")
    assert suspend_overdue(db) == 0


def test_the_sweep_catches_a_claimed_report_that_ran_out_of_time(db, monkeypatch):
    monkeypatch.setattr(settings, "suspend_on_review_start", False)
    staff, _ = make_staff(db)
    record = make_record(db)
    report = make_report(db, record, make_user(db), "WRONG_PERSON", hours_old=80, status="IN_REVIEW", claimed_by_id=staff.id)
    assert suspend_overdue(db) == 1
    assert reload(db, ConvictionRecord, record.id).publication_status == "SUSPENDED"


def test_the_sweep_leaves_a_record_an_administrator_already_suspended(db):
    record = make_record(db, publication_status="SUSPENDED")
    report = make_report(db, record, make_user(db), "WRONG_PERSON", hours_old=80)
    assert suspend_overdue(db) == 0
    assert reload(db, CorrectionRequest, report.id).auto_suspended is False


def test_the_sweep_does_nothing_when_switched_off(db, monkeypatch):
    monkeypatch.setattr(settings, "suspend_on_deadline", False)
    make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=80)
    assert suspend_overdue(db) == 0


def test_two_reviewers_claiming_at_once_produce_one_winner(db):
    staff = [make_staff(db)[0] for _ in range(6)]
    record = make_record(db)
    report = make_report(db, record, make_user(db))
    from app.corrections import claim as claim_report
    from app.models import Staff

    outcomes = run_in_parallel(lambda session, index: claim_report(report.id, session.get(Staff, staff[index].id), session), 6)
    assert outcomes.count("ok") == 1 and outcomes.count(409) == 5
    assert reload(db, CorrectionRequest, report.id).status == "IN_REVIEW"
    assert reload(db, ConvictionRecord, record.id).publication_status == "SUSPENDED"


def test_two_reviewers_resolving_at_once_produce_one_winner(db):
    from app.corrections import resolve as resolve_report
    from app.models import Staff
    from app.schemas import Resolution

    staff = [make_staff(db)[0] for _ in range(6)]
    report = make_report(db, make_record(db), make_user(db), "OTHER")
    body = Resolution(outcome="RESOLVED", note="Checked against the court file.")
    outcomes = run_in_parallel(lambda session, index: resolve_report(report.id, body, session.get(Staff, staff[index].id), session), 6)
    assert outcomes.count("ok") == 1 and outcomes.count(409) == 5


def test_parallel_sweeps_suspend_once_and_write_one_audit_entry(db):
    record = make_record(db)
    make_report(db, record, make_user(db), "WRONG_PERSON", hours_old=80)
    run_in_parallel(lambda session, _: suspend_overdue(session), 6)
    assert reload(db, ConvictionRecord, record.id).publication_status == "SUSPENDED"
    assert audit_actions(db).count("AUTO_SUSPEND_OVERDUE") == 1


def test_a_reviewer_cannot_bring_back_a_record_an_administrator_removed(client, db):
    reviewer, _ = make_staff(db, "REVIEWER")
    record = make_record(db, publication_status="REMOVED")
    report = make_report(db, record, make_user(db), "WRONG_DETAILS")
    refused = resolve(client, reviewer, report, record_status="APPROVED")
    assert refused.status_code == 403
    assert reload(db, ConvictionRecord, record.id).publication_status == "REMOVED"
    assert reload(db, CorrectionRequest, report.id).status == "OPEN"


def test_a_reviewer_cannot_publish_a_record_that_was_pulled_back_for_review(client, db):
    reviewer, _ = make_staff(db, "REVIEWER")
    record = make_record(db, publication_status="PENDING")
    report = make_report(db, record, make_user(db), "WRONG_DETAILS")
    assert resolve(client, reviewer, report, record_status="APPROVED").status_code == 403
    assert reload(db, ConvictionRecord, record.id).publication_status == "PENDING"


def test_a_reviewer_cannot_undo_a_suspension_an_administrator_chose(client, db):
    reviewer, _ = make_staff(db, "REVIEWER")
    admin, _ = make_staff(db, "ADMIN")
    record = make_record(db, publication_status="SUSPENDED")
    report = make_report(db, record, make_user(db), "WRONG_DETAILS")
    assert resolve(client, reviewer, report, record_status="APPROVED").status_code == 403
    assert resolve(client, admin, report, record_status="APPROVED").status_code == 200
    assert reload(db, ConvictionRecord, record.id).publication_status == "APPROVED"


def test_a_reviewer_can_suspend_through_a_routine_report(client, db):
    reviewer, _ = make_staff(db, "REVIEWER")
    record = make_record(db)
    report = make_report(db, record, make_user(db), "WRONG_DETAILS")
    assert resolve(client, reviewer, report, record_status="SUSPENDED").status_code == 200
    assert reload(db, ConvictionRecord, record.id).publication_status == "SUSPENDED"


def test_an_administrator_can_publish_a_pending_record_through_a_report(client, db):
    admin, _ = make_staff(db, "ADMIN")
    record = make_record(db, publication_status="PENDING")
    report = make_report(db, record, make_user(db), "WRONG_DETAILS")
    assert resolve(client, admin, report, record_status="APPROVED").status_code == 200


def test_reviewers_can_see_the_records_real_state_and_reporters_see_when_it_is_hidden(client, db):
    staff, _ = make_staff(db)
    reporter, record = make_user(db), make_record(db)
    report = make_report(db, record, reporter)

    def queue():
        return client.get("/api/v1/admin/corrections", headers=staff_headers(staff)).json()[0]

    def mine():
        return client.get("/api/v1/safety/corrections", headers=user_headers(reporter)).json()[0]

    assert queue()["record_status"] == "APPROVED" and mine()["record_hidden"] is False
    claim(client, staff, report)
    assert queue()["record_status"] == "SUSPENDED" and queue()["record_suspended_by_report"] is True
    assert mine()["record_hidden"] is True
    resolve(client, staff, report, record_status="APPROVED")
    assert mine()["record_hidden"] is False


def test_unsuccessful_attempts_do_not_use_up_the_reporting_allowance(client, db, monkeypatch):
    monkeypatch.setattr(settings, "daily_report_limit", 2)
    user, first, second, third = make_user(db), make_record(db), make_record(db), make_record(db)
    assert file_report(client, user, first).status_code == 201
    for _ in range(5):
        assert file_report(client, user, first).status_code == 409
        assert file_report(client, user, SimpleNamespace(public_record_id="NGA-NOSUCHREC")).status_code == 404
    assert file_report(client, user, second).status_code == 201
    assert file_report(client, user, third).status_code == 429


def test_the_database_itself_refuses_a_second_open_report_from_the_same_person(db):
    user, record = make_user(db), make_record(db)
    make_report(db, record, user)
    with pytest.raises(IntegrityError):
        make_report(db, record, user)
    db.rollback()
    make_report(db, record, make_user(db))


def test_once_a_report_is_closed_the_same_person_may_open_another_at_the_database_level(db):
    user, record = make_user(db), make_record(db)
    make_report(db, record, user, status="RESOLVED")
    make_report(db, record, user)
    make_report(db, record, user, status="REJECTED")


def test_parallel_duplicate_reports_from_one_person_produce_exactly_one(db, monkeypatch):
    monkeypatch.setattr(settings, "daily_report_limit", 100)
    user, record = make_user(db), make_record(db)
    body = CorrectionIn(reason="WRONG_PERSON", details=DETAILS)
    outcomes = run_in_parallel(lambda session, _: report_mistake(record.public_record_id, body, session.get(User, user.id), None, session), 6)
    assert outcomes.count("ok") == 1 and set(outcomes) <= {"ok", 409}
    db.expire_all()
    assert db.query(CorrectionRequest).filter_by(user_id=user.id, record_id=record.id).count() == 1
