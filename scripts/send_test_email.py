"""Send a real test email. Defaults to the alert and escalation addresses."""
import argparse
import sys
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.notify import deliver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("addresses", nargs="*")
    args = parser.parse_args()

    recipients = args.addresses or [a for a in (settings.review_alert_email, settings.escalation_email) if a]
    if not recipients:
        raise SystemExit("No address given, and REVIEW_ALERT_EMAIL and ESCALATION_EMAIL are empty.")
    if not (settings.smtp_host or settings.brevo_api_key):
        raise SystemExit("Neither BREVO_API_KEY nor SMTP_HOST is set, so nothing real would be sent.")

    text = f"Test from Ngao sent {datetime.now(timezone.utc):%d %b %Y %H:%M} UTC. If you can read this, alerts to this address work."
    any_failed = False
    for address in recipients:
        try:
            deliver("email", address, text, "Ngao test email")
        except HTTPException as failure:
            any_failed = True
            print(f"FAILED {address}: {failure.detail}")
            continue
        print(f"accepted by provider: {address}")
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
