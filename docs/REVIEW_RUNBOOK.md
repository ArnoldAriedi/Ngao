# Review queue runbook

Who answers correction reports, how fast, and what happens when nobody does.

## What the clock does

| Report type | Due | Claim target | Chased at |
| --- | --- | --- | --- |
| Wrong person, conviction overturned | 72 hours | 24 hours | 24 h to the review inbox, 48 h to the escalation contact |
| Wrong details, other | 14 days | none | only when overdue |

The clock counts hours, not working days. It does not stop for weekends or public holidays.

When an urgent report is claimed, its record is suspended at once. When an urgent report reaches 72 hours unclaimed, the record is suspended automatically. Either way the person concerned stops being shown, so the cost of a slow queue falls on the service and not on someone who may have been wrongly listed. A suspension caused by neglect is a failure to be reviewed, not a success.

## Cover standard

Every day has a **primary** and a **backup**.

- The primary checks the queue every morning and evening, claims new urgent reports within 24 hours, and owns anything they claim until it is closed or handed over in writing.
- The backup stays reachable by phone. They act if an urgent report is still unclaimed at 24 hours, or if the primary does not answer.
- Both must be active staff. Someone who has left, or has been deactivated, stops counting immediately.

Beyond the rota:

- At least 4 trained active staff is the realistic floor. With 4 people, each is on duty about half of all days and primary about one day in four. With 3, each is on duty two days in three, which does not last. `MIN_ACTIVE_REVIEWERS` defaults to 3 so that `queue/health` warns you at the bare minimum, but plan for 4 or more.
- One named escalation contact who answers a phone at night, set as `ESCALATION_EMAIL`.
- The hourly digest is a backstop for the checks above, not a substitute.

### Why holidays need a name against them

A report filed at 17:00 on the Thursday before Easter is due at 17:00 on Sunday. A report filed at 17:00 on Christmas Eve is due at 17:00 on 27 December. Neither has a working day in it. The generator weights weekends and public holidays double so nobody carries them all, and it respects declared leave. Check the holiday file against the current year's official gazette each year. Fixed-date holidays are listed in `docs/kenya_holidays_2026_27.csv`. Holidays that move with the Islamic calendar are not, and must be added by hand once the date is announced.

## Keeping the rota honest

1. Put your team in a CSV like `docs/team.csv`: one row per person, with any leave in the `unavailable` column (ranges like `2026-12-24..2026-12-27`, separated by `;`).
2. Generate the rota, at least a month ahead of any holiday and for 90 days at a time:

```
python -m scripts.generate_rota team.csv --start 2026-10-27 --days 90 --holidays docs/kenya_holidays_2026_27.csv --out /etc/ngao/rota.csv
```

It prints how many primary, backup and holiday-or-weekend shifts each person got, and exits non-zero if any day lacks two people available.

3. Swaps are edited into `rota.csv` before the day, not agreed in chat afterwards.
4. Regenerate whenever someone joins, leaves or books leave. The weekly gap check (below) tells you when you forgot.

`docs/rota_first_90_days_PLACEHOLDER.csv` shows the output for four made-up people. It is deliberately full of `example.go.ke` addresses, so the gap check flags every day until you replace it with your real team.

## Scheduled jobs

Three jobs keep the queue honest. `deploy/ngao.cron` installs all of them.

| Job | Runs | What it does |
| --- | --- | --- |
| `enforce_deadlines` | every 15 minutes | Suspends records whose urgent report passed 72 hours |
| `queue_digest` | every hour | Emails unclaimed and at-risk reports |
| `check_rota` | Mondays 08:00 Nairobi time | Emails the escalation contact if any day in the next 30 lacks two active people |

Each job records a heartbeat. `GET /health/jobs` returns 200 only if every job has run recently and last succeeded, and 503 otherwise, with the state of each job (`OK`, `STALE`, `FAILING`, `NEVER_RAN`). Point an external uptime monitor at it and have it alert a person on a non-200. A job that stops running cannot report its own death, so something outside the server has to watch.

## Confirming alerts really send

1. `python -m scripts.send_test_email` sends a real message to the alert and escalation addresses. Open each inbox and check spam. The script can only prove the provider accepted the message.
2. In a staging copy, set `URGENT_CLAIM_TARGET_HOURS=0`, file an urgent report as a test user, run `python -m scripts.queue_digest`, and confirm the unclaimed-report email arrives. This proves the whole path from queue to inbox.
3. Check `/health/jobs` shows `OK` for all three jobs after they have each run once.
4. Repeat steps 1 and 3 after any change to the mail provider, the server or the cron file.

## Handling a report

1. **Claim it.** For urgent reports this suspends the record.
2. **Read it.** Treat the reporter as someone who may be mistaken or may be the person concerned. Do not tell them about other reports on the same record.
3. **Check it against the source.** Ask the court that heard the case, or the Judiciary's Office of the Chief Registrar for sexual-offence records. Do not decide on the reporter's account alone. Record the court file number or appeal reference you relied on.
4. **Decide.**

| Reason | What to confirm | If confirmed | If not |
| --- | --- | --- | --- |
| Wrong person | The conviction belongs to someone else | Resolve, record `REMOVED` | Reject, record `APPROVED` |
| Conviction overturned | An appeal court order quashing it | Resolve, record `REMOVED` | Reject, record `APPROVED` |
| Wrong details | The offence, dates or area are wrong | Correct the source data, resolve, record `APPROVED` | Reject, record `APPROVED` |
| Other | Depends | Use judgment and write down why | Reject, record `APPROVED` |

Only an administrator can set `REMOVED`. A reviewer who confirms a removal passes it to an administrator with the evidence in the note, and the report stays open until it is done.

5. **Write the note.** The reporter reads it. Say what you checked and what you decided in plain language. Do not include anyone's ID number or details about other people.
6. **Close it.** The reporter is emailed. If the email fails, the reporter can still read the outcome in the app.

## Escalation ladder

| Time since filing | What happens | Who acts |
| --- | --- | --- |
| 24 hours, unclaimed | Alert to the review inbox | Whoever is on duty claims it |
| 48 hours, unclaimed | Alert to the escalation contact | Escalation contact finds a reviewer, by phone if needed |
| 72 hours | Record suspended automatically | Reviewer closes it the next shift. Admin reviews why it was missed |

## Handover

At the end of every shift, post a note listing each open report, who owns it and what it is waiting for. A report with no owner is a report that will be late.

## Monthly review

Read these from the audit log and the queue:

- Median hours from filing to claim, for urgent reports.
- Share of urgent reports closed before the deadline. The target is all of them.
- Records suspended because a deadline passed (`AUTO_SUSPEND_OVERDUE`). The target is zero. Any other number needs an explanation.
- Share of reports accepted. A high share means the data has a quality problem upstream, not a reviewing problem.
- Reports where reporter notification failed.

## Joining and leaving

An administrator creates staff with `python -m scripts.create_staff`, and the new person scans the printed authenticator link on their own phone. On the day someone leaves, an administrator runs `python -m scripts.deactivate_staff their@email`. Their session ends on the next request.

## Sizing

Staff needed on duty per day is roughly (reports per day × minutes per report) ÷ productive minutes per person, with a floor of two. Reports per day is unknown until launch. Start at three trained staff, read `queue/health` daily for the first month, and add people before the claim-late alerts become routine.
