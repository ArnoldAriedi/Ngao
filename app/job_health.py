from datetime import datetime, timedelta

MAX_AGE = {
    "enforce_deadlines": timedelta(minutes=45),
    "queue_digest": timedelta(hours=3),
    "check_rota": timedelta(days=8),
}


def job_state(last_ran_at: datetime | None, last_ok: bool | None, now: datetime, max_age: timedelta) -> str:
    if last_ran_at is None:
        return "NEVER_RAN"
    if now - last_ran_at > max_age:
        return "STALE"
    return "OK" if last_ok else "FAILING"
