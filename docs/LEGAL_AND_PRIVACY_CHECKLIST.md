# Legal and privacy launch checklist (Kenya)

A planning checklist, not legal advice.

## Data access
- [x] Imports are validated row by row and never published directly. An administrator approves each record, and every import is recorded in the audit log with a file hash.
- [ ] Decide who approves imported records, what they compare each one against, and keep that written procedure.
- [ ] Confirm the exact expiry day with counsel. Today a record stops being listed on the seventh anniversary itself.
- [ ] Confirm your reverse proxy, monitoring and error reporting do not log request bodies, and record your log retention periods.
- [ ] Obtain written authorisation from the Office of the Chief Registrar of the Judiciary to receive Convicted Sexual Offenders Register data and to republish it. The Judiciary's own page lists penalties for misusing register information.
- [ ] Find the lawful source for GBV, trafficking and child-labour convictions. No central register was found.
- [ ] Confirm which fields may be processed and which may be displayed.

## Policy conflicts to settle in writing
- [ ] The statutory register keeps an offender listed until death or a successful appeal. Ngao lists for 7 years, or permanently after two convictions. Decide who owns that difference and whether the Judiciary accepts it.
- [ ] Define "repeat". The code counts total verified convictions (2 or more), across categories.
- [ ] Decide whether the 7-year clock starting at release (when later than judgment) matches the intended policy.

## Law and regulators
- [ ] Review the Data Protection Act, 2019, the Data Protection (General) Regulations, 2021, ODPC registration, and DPIA obligations.
- [ ] Review the Constitution, the Children Act, 2022, victim privacy, witness protection and court reporting restrictions.
- [ ] Ensure child victims and witnesses cannot be identified, directly or by inference.

## Process
- [ ] Define correction, appeal, suspension and removal workflows, including who answers a mistaken-identity complaint.
- [x] User-facing correction request, staff review queue and reporter notification exist.
- [x] Deadlines: 72 hours for wrong-person and overturned-conviction reports, 14 days for the rest. Suspension happens when review starts or the deadline passes. Confirm these numbers and that policy with counsel.
- [x] Runbook, queue chasing at 24 and 48 hours, rota gap check and understaffing warning exist (`docs/REVIEW_RUNBOOK.md`).
- [x] Rota generator with primary and backup roles, fair holiday and weekend spread, and leave handling (`scripts/generate_rota.py`).
- [ ] Name at least 4 trained staff and an escalation contact, put them in a team CSV, and generate the first 90-day rota from it. A sample built from made-up people is in `docs/`.
- [ ] Set `REVIEW_ALERT_EMAIL` and `ESCALATION_EMAIL`.
- [x] Cron file and job heartbeats exist, and `GET /health/jobs` reports whether the jobs are running (`deploy/ngao.cron`).
- [ ] Install the cron file on the server and point an uptime monitor at `/health/jobs`.
- [ ] Re-generate the rota each time someone joins, leaves or books leave, and after each year's holiday list is confirmed.
- [ ] Decide who may be a reviewer versus an administrator, and who approves new staff.
- [x] SMTP email sending exists and is tested against a local mail server (`app/mailer.py`).
- [ ] Configure a real provider and the SPF, DKIM and DMARC records, then run `scripts/send_test_email.py` and confirm the messages arrive and are not in spam.
- [ ] Run the end-to-end alert test from the runbook in staging.
- [x] SMS goes through a configurable HTTP gateway, delivery is reported per channel, and production will not start without it.
- [ ] Contract an SMS provider (or adapter) and confirm real phone codes arrive on Kenyan networks.
- [ ] Integrate an authorised national-ID verification service. Until then the app labels demo mode and refuses to register anyone in production.
- [ ] Test that pending, suspended, removed, acquitted and lapsed records never appear in search.
- [ ] Confirm helpline numbers shown in the app (999/112, 1195, 116) with official sources before launch.

## Security
- [x] Role rules are enforced on the server: reviewers cannot publish, un-remove or remove records, and can restore only a suspension their own report caused.
- [ ] Run the integration suite against PostgreSQL (`make test-integration`, or push to CI) and keep a green result. It has not been executed against a database yet.
- [x] Rate limits on login, sign-up, code confirmation, resend and correction reports, and an atomic daily search quota that also covers record lookups.
- [ ] Run `tests/test_concurrency.py` against a scratch PostgreSQL database and keep the passing result.
- [ ] Set `TRUSTED_PROXY_HOPS` correctly for your hosting setup, and confirm in a test that two different visitors are counted separately.
- [ ] Monitor `429` rates and failed logins. Guessing spread across many addresses is slowed but not stopped.
- [ ] Known gaps not yet built: password reset, sign-out that revokes a session (tokens last 12 hours), and sign-up replies that confirm an account already exists.
- [ ] Replace the demo ID check and demo code delivery.
- [ ] Threat-model harassment, vigilantism, mistaken identity, location triangulation by repeated searches, scraping and insider abuse.
- [x] Staff accounts with password and authenticator-app code, lockout, role separation and an audit trail exist.
- [x] Runtime database role limited to INSERT and SELECT on `audit_entries`, with append-only triggers (`scripts/harden_db.py`).
- [x] Staff authenticator secrets are encrypted, with key rotation (`scripts/rotate_totp_keys.py`).
- [ ] Run `scripts/verify_hardening.py` against the real database and keep its PASS output.
- [ ] Store `TOTP_ENCRYPTION_KEYS` in a secrets manager and keep the database owner login off the app server.
- [ ] Use encryption, backups, a separate database role for the public API, and an independent security review.
