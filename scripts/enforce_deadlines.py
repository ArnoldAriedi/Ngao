"""Suspend records whose urgent reports passed their deadline. Run every 15 minutes."""
from app.corrections import suspend_overdue
from app.jobs import tracked

JOB = "enforce_deadlines"

if __name__ == "__main__":
    with tracked(JOB) as run:
        run.detail = f"{suspend_overdue(run.db)} suspended"
    print(run.detail)
