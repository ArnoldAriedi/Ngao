import runpy
import sys
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs import record_run, tracked
from app.models import ConvictionRecord, JobRun, utcnow
from scripts import check_rota, queue_digest
from tests.integration.helpers import make_record, make_report, make_staff, make_user

JOBS = ("enforce_deadlines", "queue_digest", "check_rota")


def runs(db, job=None):
    db.expire_all()
    query = select(JobRun).order_by(JobRun.id)
    if job:
        query = query.where(JobRun.job == job)
    return list(db.scalars(query))


def record_all(db, ok=True, minutes_ago=5):
    for job in JOBS:
        db.add(JobRun(job=job, ok=ok, ran_at=utcnow() - timedelta(minutes=minutes_ago)))
    db.commit()


def test_a_run_leaves_a_heartbeat(db):
    record_run(db, "queue_digest", True, "2 claim-late")
    [heartbeat] = runs(db)
    assert (heartbeat.job, heartbeat.ok, heartbeat.detail) == ("queue_digest", True, "2 claim-late")


def test_old_heartbeats_are_pruned_per_job(db):
    db.add(JobRun(job="queue_digest", ok=True, ran_at=utcnow() - timedelta(days=31)))
    db.add(JobRun(job="check_rota", ok=True, ran_at=utcnow() - timedelta(days=31)))
    db.commit()
    record_run(db, "queue_digest", True)
    assert [(r.job) for r in runs(db)] == ["check_rota", "queue_digest"]


def test_tracked_records_success_with_the_detail_the_job_set(db):
    with tracked("check_rota") as run:
        run.detail = "0 uncovered days"
    [heartbeat] = runs(db)
    assert heartbeat.ok is True and heartbeat.detail == "0 uncovered days"


def test_tracked_records_a_failure_and_still_raises(db):
    with pytest.raises(RuntimeError):
        with tracked("check_rota"):
            raise RuntimeError("disk on fire")
    [heartbeat] = runs(db)
    assert heartbeat.ok is False and "disk on fire" in heartbeat.detail


def test_a_job_can_report_its_own_failure_without_raising(db):
    with tracked("queue_digest") as run:
        run.ok = False
    assert runs(db)[0].ok is False


def test_health_is_red_until_every_job_has_run(client, db):
    response = client.get("/health/jobs")
    assert response.status_code == 503
    assert response.json() == {"healthy": False, "jobs": {job: "NEVER_RAN" for job in JOBS}}


def test_health_is_green_when_every_job_ran_recently_and_succeeded(client, db):
    record_all(db)
    response = client.get("/health/jobs")
    assert response.status_code == 200 and response.json()["healthy"] is True
    assert set(response.json()["jobs"].values()) == {"OK"}


def test_one_stale_job_turns_health_red(client, db):
    record_all(db)
    db.add(JobRun(job="enforce_deadlines", ok=True, ran_at=utcnow() - timedelta(hours=2)))
    db.query(JobRun).filter(JobRun.job == "enforce_deadlines", JobRun.ran_at > utcnow() - timedelta(hours=1)).delete()
    db.commit()
    response = client.get("/health/jobs")
    assert response.status_code == 503 and response.json()["jobs"]["enforce_deadlines"] == "STALE"


def test_a_failing_latest_run_turns_health_red_and_a_later_success_clears_it(client, db):
    record_all(db, minutes_ago=30)
    db.add(JobRun(job="queue_digest", ok=False, ran_at=utcnow() - timedelta(minutes=10)))
    db.commit()
    assert client.get("/health/jobs").json()["jobs"]["queue_digest"] == "FAILING"
    db.add(JobRun(job="queue_digest", ok=True, ran_at=utcnow() - timedelta(minutes=1)))
    db.commit()
    assert client.get("/health/jobs").status_code == 200


def test_the_deadline_script_suspends_and_leaves_a_heartbeat(db, capsys):
    record = make_record(db)
    make_report(db, record, make_user(db), "WRONG_PERSON", hours_old=80)
    runpy.run_module("scripts.enforce_deadlines", run_name="__main__")
    db.expire_all()
    assert db.get(ConvictionRecord, record.id).publication_status == "SUSPENDED"
    [heartbeat] = runs(db, "enforce_deadlines")
    assert heartbeat.ok is True and heartbeat.detail == "1 suspended"
    assert "1 suspended" in capsys.readouterr().out


@pytest.fixture
def emails(monkeypatch):
    sent = []

    def capture(channel, address, message, subject="Ngao"):
        sent.append((address, subject, message))
        return True

    monkeypatch.setattr("scripts.queue_digest.try_deliver", capture)
    monkeypatch.setattr(settings, "review_alert_email", "inbox@example.go.ke")
    monkeypatch.setattr(settings, "escalation_email", "oncall@example.go.ke")
    return sent


def test_the_digest_nags_the_inbox_about_unclaimed_urgent_reports(db, emails):
    report = make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=25)
    queue_digest.main()
    assert len(emails) == 1
    address, subject, message = emails[0]
    assert address == "inbox@example.go.ke" and subject == "Unclaimed urgent Ngao reports" and f"report {report.id}" in message
    assert runs(db, "queue_digest")[0].ok is True


def test_the_digest_escalates_to_the_on_call_contact_at_48_hours(db, emails):
    make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=50)
    queue_digest.main()
    assert [(address, subject) for address, subject, _ in emails] == [("oncall@example.go.ke", "Ngao reports at risk of suspension")]


def test_the_digest_is_silent_when_nothing_is_late(db, emails):
    make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=5)
    make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=60, status="IN_REVIEW")
    queue_digest.main()
    assert emails == [] and runs(db, "queue_digest")[0].ok is True


def test_the_digest_marks_itself_failing_when_the_email_cannot_be_sent(db, emails, monkeypatch):
    monkeypatch.setattr("scripts.queue_digest.try_deliver", lambda *args, **kwargs: False)
    make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=25)
    queue_digest.main()
    heartbeat = runs(db, "queue_digest")[0]
    assert heartbeat.ok is False and "1 undelivered" in heartbeat.detail


def test_the_digest_marks_itself_failing_when_nobody_is_configured_to_hear_it(db, emails, monkeypatch):
    monkeypatch.setattr(settings, "review_alert_email", "")
    make_report(db, make_record(db), make_user(db), "WRONG_PERSON", hours_old=25)
    queue_digest.main()
    assert runs(db, "queue_digest")[0].ok is False and emails == []


def rota_file(tmp_path, *shifts):
    path = tmp_path / "rota.csv"
    path.write_text("date,email,role\n" + "".join(f"{day},{email},PRIMARY\n" for day, email in shifts))
    return path


def run_rota_check(monkeypatch, path, days=2):
    monkeypatch.setattr(sys, "argv", ["check_rota", str(path), "--days", str(days), "--minimum", "2"])
    check_rota.main()


def test_a_full_rota_passes_and_says_so(db, monkeypatch, tmp_path, capsys):
    first, _ = make_staff(db)
    second, _ = make_staff(db)
    today = utcnow().date()
    shifts = [(today + timedelta(days=d), who.email) for d in range(2) for who in (first, second)]
    run_rota_check(monkeypatch, rota_file(tmp_path, *shifts))
    assert "2+ active staff on duty every day" in capsys.readouterr().out
    assert runs(db, "check_rota")[0].detail == "0 uncovered days"


def test_a_gap_exits_non_zero_names_the_day_and_emails_the_on_call_contact(db, monkeypatch, tmp_path, capsys):
    sent = []
    monkeypatch.setattr("scripts.check_rota.try_deliver", lambda channel, address, message, subject: sent.append((address, subject, message)) or True)
    monkeypatch.setattr(settings, "escalation_email", "oncall@example.go.ke")
    only, _ = make_staff(db)
    today = utcnow().date()
    with pytest.raises(SystemExit) as stopped:
        run_rota_check(monkeypatch, rota_file(tmp_path, (today, only.email)), days=1)
    assert stopped.value.code == 1
    assert sent[0][0] == "oncall@example.go.ke" and sent[0][1] == "Ngao review rota has gaps" and "1 on duty, need 2" in sent[0][2]
    assert runs(db, "check_rota")[0].ok is True


def test_a_gap_with_nobody_to_tell_is_a_failing_run(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "escalation_email", "")
    with pytest.raises(SystemExit):
        run_rota_check(monkeypatch, rota_file(tmp_path), days=1)
    assert runs(db, "check_rota")[0].ok is False


def test_people_who_left_do_not_count_towards_cover(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "escalation_email", "")
    present, _ = make_staff(db)
    gone, _ = make_staff(db, is_active=False)
    today = utcnow().date()
    with pytest.raises(SystemExit):
        run_rota_check(monkeypatch, rota_file(tmp_path, (today, present.email), (today, gone.email)), days=1)
    assert runs(db, "check_rota")[0].detail == "1 uncovered days"
