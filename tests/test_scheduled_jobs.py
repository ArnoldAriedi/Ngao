import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.job_health import MAX_AGE, job_state

ROOT = Path(__file__).resolve().parent.parent
CRON_LINE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+ngao\s+.*-m scripts\.(\w+)")
LONGEST_GAP = {
    "enforce_deadlines": timedelta(minutes=15),
    "queue_digest": timedelta(hours=1),
    "check_rota": timedelta(days=7),
}


def scheduled_jobs():
    lines = (ROOT / "deploy" / "ngao.cron").read_text().splitlines()
    return {match.group(6): match.groups()[:5] for line in lines if (match := CRON_LINE.match(line))}


def test_cron_runs_exactly_the_jobs_the_health_check_watches():
    assert set(scheduled_jobs()) == set(MAX_AGE)


def test_every_scheduled_script_exists_and_records_a_heartbeat():
    for job in scheduled_jobs():
        source = (ROOT / "scripts" / f"{job}.py").read_text()
        assert "tracked(" in source, f"{job} never records a heartbeat"
        assert f'"{job}"' in source, f"{job} records under a different name"


def test_each_job_runs_often_enough_to_stay_inside_its_freshness_window():
    for job, gap in LONGEST_GAP.items():
        assert gap < MAX_AGE[job]


def test_state_machine():
    now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    limit = timedelta(minutes=45)
    assert job_state(None, None, now, limit) == "NEVER_RAN"
    assert job_state(now - timedelta(minutes=10), True, now, limit) == "OK"
    assert job_state(now - timedelta(minutes=10), False, now, limit) == "FAILING"
    assert job_state(now - timedelta(minutes=46), True, now, limit) == "STALE"
