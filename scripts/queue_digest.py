"""Email unclaimed and at-risk urgent reports. Run hourly."""
from app.config import settings
from app.corrections import open_report_states
from app.jobs import tracked
from app.notify import try_deliver
from app.queue_health import CLAIM_LATE, ESCALATE, OVERDUE

JOB = "queue_digest"


def describe(open_reports: list, states: set[str]) -> list[str]:
    return [
        f"report {report.id} ({report.reason}), due {report.due_at:%a %d %b %H:%M} UTC"
        for report, state in open_reports
        if state in states
    ]


def send(address: str, subject: str, heading: str, lines: list[str]) -> bool:
    return bool(address) and try_deliver("email", address, heading + "\n" + "\n".join(lines), subject)


def main():
    with tracked(JOB) as run:
        open_reports = open_report_states(run.db)
        claim_late = describe(open_reports, {CLAIM_LATE})
        escalated = describe(open_reports, {ESCALATE, OVERDUE})
        delivered = []
        if claim_late:
            delivered.append(send(settings.review_alert_email, "Unclaimed urgent Ngao reports", "Nobody has claimed these in time:", claim_late))
        if escalated:
            escalate_to = settings.escalation_email or settings.review_alert_email
            delivered.append(send(escalate_to, "Ngao reports at risk of suspension", "These are close to, or past, their deadline:", escalated))
        run.ok = all(delivered)
        run.detail = f"{len(claim_late)} claim-late, {len(escalated)} escalated or overdue, {delivered.count(False)} undelivered"
    print(run.detail)


if __name__ == "__main__":
    main()
