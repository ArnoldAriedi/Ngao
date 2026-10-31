# Ngao

Ngao (Swahili for shield) shows verified users the court-recorded convictions within 15 km of them for:

| Code | Covers |
| --- | --- |
| `GENDER_BASED_VIOLENCE` | GBV and domestic violence |
| `SEXUAL_ASSAULT` | Rape, sexual assault and related offences |
| `CHILD_SEXUAL_OFFENCE` | Defilement and other sexual offences against children |
| `CHILD_TRAFFICKING` | Trafficking of children |
| `CHILD_LABOUR` | Employing children in exploitative or hazardous work |

The design uses the Maasai shield from the Kenyan flag: the mark, the flag-stripe frame, and the search view, where the 15 km radius is drawn as three nested shields (0-5, 5-10, 10-15 km).

## Rules the code enforces

- **Accounts.** Sign-up needs an email, a Kenyan mobile number and a national ID. The ID is checked, then a code goes to the email and another to the phone. Search is refused until all three are confirmed. One account per email, phone and ID. The ID is stored only as an HMAC hash.
- **Retention** (`app/retention.py`). A record is listed for 7 years from the later of judgment date and release date. It stops being listed on the seventh anniversary itself, so a conviction on 14 March 2019 is last shown on 13 March 2026. Two or more convictions make the listing permanent. Records are filtered at query time, so nothing needs a cleanup job.
- **Only convictions.** The importer skips any row whose outcome is not `CONVICTED`. Staff can suspend or, for administrators, remove a record (for example after a successful appeal).
- **Minimal public fields.** No name, ID number, photo or street address is returned. Coordinates are rounded to 2 decimals (about 1 km) on import, and distances are rounded up to whole kilometres. A name or photo field is a deliberate decision for the data owner, not a default.
- **Corrections.** Every listed record has a "Report a mistake" form. Reports go to a staff review queue. The reporter gets a review-by date, an email when the report is closed, and can read the outcome under "Your reports".
- **Review deadlines.** Wrong-person and overturned-conviction reports are due in 72 hours (`URGENT_REVIEW_HOURS`). Everything else is due in 14 days (`STANDARD_REVIEW_DAYS`).
- **Suspension policy.** Filing a report never hides a record, so nobody can suppress a listing by filing one. An urgent report suspends its record in two cases. A reviewer starts work on it (`SUSPEND_ON_REVIEW_START`), or nobody has started by the deadline (`SUSPEND_ON_DEADLINE`). Overdue reports are enforced on every search, and `scripts/enforce_deadlines.py` can also run from cron. A record suspended this way stays hidden until a reviewer closes the report and states what happens to it. Several reports on one record do not suspend it, because that rule invites brigading.
- **Staff.** Staff have their own accounts with a password and an authenticator-app code. Reviewers can claim and close reports and suspend or restore records. Only administrators can remove records, change publication status directly, or read the audit log. Five wrong attempts lock an account for 15 minutes, and a code cannot be reused.
- **Audit trail.** Staff logins (including failures), claims, resolutions, every record status change and every automatic suspension are written to `audit_entries`, in the same transaction as the action. The database enforces that it is append-only (see Production database setup).
- **Staffing.** `docs/REVIEW_RUNBOOK.md` sets the cover standard, rota process, escalation ladder and monthly review. The software backs it up: `scripts/queue_digest.py` chases unclaimed urgent reports at 24 and 48 hours, `scripts/check_rota.py` finds days with too few people on duty, and `GET /api/v1/admin/queue/health` shows what needs attention and whether you are understaffed.
- **Scraping.** `DAILY_SEARCH_LIMIT` (default 30) caps searches per account per day. Looking up a single record counts as a search too, because each lookup reveals a distance from a chosen point.

## Data

Ngao ships with fictional demo records. If you used an earlier zip, drop its dev database and re-run `init_db`, because the correction and staff tables changed. It cannot fetch real ones by itself.

- The Judiciary's Convicted Sexual Offenders Electronic Register, kept by the Chief Registrar under the Sexual Offences Act, is the official source for `SEXUAL_ASSAULT` and `CHILD_SEXUAL_OFFENCE`. Access is by request. Public disclosure needs the Judiciary's written authorisation.
- No central register was found for GBV, trafficking or child-labour convictions. Those need an agreement with the Judiciary or the ODPP.

Once you have an authorised export, match its columns to `docs/register_export_template.csv` and run:

```bash
python -m scripts.import_register export.csv
```

The importer validates every row before it writes anything. It checks dates, conviction counts, text lengths, that coordinates fall inside Kenya (which catches swapped latitude and longitude), and duplicate source references. Rejected rows are listed with their line numbers in `export.rejected.csv`. If any row is rejected, nothing is imported unless you pass `--skip-invalid`. Rows whose outcome is not `CONVICTED` are skipped.

Imported records are never published directly. They arrive `PENDING`, and an administrator reviews them against the source and approves them (`GET /api/v1/admin/records/pending`, then `POST /api/v1/admin/records/approve`). Each approval is audited. If a later import changes the published details of an approved record, it goes back to `PENDING` until it is approved again. Records an administrator suspended or removed stay that way. Every import writes an audit entry with the file name, a hash of the file and the counts, so you can show which export a record came from.

Public record IDs are random and fixed at first import, so rotating `APP_SECRET` cannot change them. Records are matched across imports by source and source reference.

With `DEMO_MODE=true` only fictional records are served. With `DEMO_MODE=false` only imported records are served.

## Run locally

```bash
cp .env.example .env
docker compose up -d db
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.init_db
python -m scripts.seed_demo
python -m scripts.create_staff you@example.go.ke "Your Name" --role ADMIN
uvicorn app.main:app --reload
pytest
```

Open http://127.0.0.1:8000. In demo mode the verification codes are shown on screen and logged.

## Who can change what

| Change | Reviewer | Administrator |
| --- | --- | --- |
| Suspend a published record | yes | yes |
| Restore a record that their own report suspended | yes | yes |
| Restore a record an administrator suspended | no | yes |
| Publish a pending record, or bring back a removed one | no | yes |
| Remove a record | no | yes |
| Approve imports, read the audit log, change status directly | no | yes |

The rule lives in `app/permissions.py` and is enforced on the server, so it holds whatever the interface does. A record's real state is visible to reviewers in the queue (`record_status`), and a reporter sees when their report is the reason a record is hidden. Hiding is always temporary and audited, and removal needs an administrator.

## Where searches work

Searches are accepted only from in and near Kenya (the country's bounding box plus half a degree for border towns), which keeps the distance maths clear of the date line. Outside it the API answers 422 with a clear reason. To widen the area, change `app/geo.py`.

## Location privacy

Search coordinates are sent in the body of a POST request, never in the URL, so they do not appear in access logs, browser history or the `Referer` header. Ngao does not store or log them. That promise covers the app only. Make sure your reverse proxy, firewall, monitoring and error-reporting tools are not set to record request bodies, and write down how long any logs you do keep are retained.

## Abuse limits

| What | Limit |
| --- | --- |
| Searches and record lookups | 30 per account per day (`DAILY_SEARCH_LIMIT`) |
| Correction reports | 5 per account per day (`DAILY_REPORT_LIMIT`) |
| Failed logins | 5 per address and account per 15 minutes, 30 per address |
| Sign-ups | 5 per address per hour, and 3 per email or phone number per hour |
| Confirming codes | 5 wrong guesses per set of codes, 20 requests per address per 15 minutes |
| Sending new codes | 3 per account per hour. Old codes stop working at once |

How it holds up:

- The search quota, claiming a report, closing a report and a record's automatic suspension are each a single atomic database statement, so parallel requests cannot all slip through.
- Failed logins are counted per address and account together, so an attacker cannot lock a real person out from somewhere else. The cost is that someone guessing from many different addresses is only slowed by the password hashing and the 10-character minimum. Watch for that pattern.
- If the app sits behind a reverse proxy or load balancer, set `TRUSTED_PROXY_HOPS` to the number of proxies you control, or every visitor will look like one address. Leave it at 0 if there is no proxy. Never set it higher than the number you control, because the header can be forged.
- An account that was never confirmed can get new codes by signing in, or from the "Send new codes" button.
- A search that fails on the server still uses one of the day's searches. Invalid requests are refused before the quota is touched, and a correction report only uses its allowance once it is known to be valid. The database also refuses a second open report from the same person on the same record, so two simultaneous requests cannot both get in.
- Limits are kept in the database (`throttle_events`), so they work across several app servers without extra infrastructure.

`tests/test_concurrency.py` fires parallel requests at the quota, the claim step and duplicate sign-ups. It needs a scratch PostgreSQL database and is skipped otherwise. See the top of the file for how to run it.

## Production database setup

Use two database logins. The owner creates tables and stays off the app server. The runtime role is what the app connects as.

```bash
MIGRATION_DATABASE_URL=postgresql+psycopg://owner:...@db/ngao python -m scripts.init_db
APP_DB_PASSWORD="$(openssl rand -base64 32)" python -m scripts.harden_db
# set DATABASE_URL to postgresql+psycopg://ngao_app:<that password>@db/ngao
python -m scripts.verify_hardening
```

`harden_db` gives `ngao_app` the minimum it needs. It can read and add audit rows, and nothing else on that table. Triggers also block UPDATE, DELETE and TRUNCATE on `audit_entries` for every login, the owner included. `verify_hardening` tries all three as both logins and fails loudly if any works, or if the runtime role is a superuser. Run it after every deploy, and re-run `harden_db` after any schema change. The check adds one audit row each time.

What this does not stop: someone with the owner login can still disable the triggers. Keep that login off the app server and out of its environment.

## Email

Any provider that offers SMTP works. Set `SMTP_HOST`, `SMTP_PORT` (587 for `starttls`, 465 for `ssl`), `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SECURITY` and `MAIL_FROM`. `MAIL_FROM` must be an address on a domain you control. Email carries sign-up codes, report outcomes sent to reporters, and every staff alert.

```bash
python -m scripts.send_test_email                     # to REVIEW_ALERT_EMAIL and ESCALATION_EMAIL
python -m scripts.send_test_email someone@gmail.com   # or to any address
```

Set up SPF, DKIM and DMARC for the sending domain. Your provider shows the exact DNS records. Without them, alerts are likely to land in spam or be rejected, and nobody will know. After setting it up, send a test to at least one Gmail and one other address and check the spam folder.

Phone codes go to an HTTP SMS gateway you configure. Set `SMS_GATEWAY_URL` (https is required in production) and optionally `SMS_GATEWAY_TOKEN`. Ngao sends `POST {"to": "+2547...", "message": "..."}` as JSON with `Authorization: Bearer <token>`, and treats any 2xx reply as accepted. That fits an in-house gateway, or a provider whose API takes this shape. For a provider with a different API you need a small adapter in front of it. Ngao does not ship a ready-made integration for any named provider, and the sender is tested only against a local stand-in server, so run a real message through your chosen provider before launch.

With `DEMO_MODE=false` the app refuses to start without `SMTP_HOST`, a `MAIL_FROM` and an https `SMS_GATEWAY_URL`. `GET /health` shows whether each channel is `configured`, `demo` or `missing`. If one code cannot be delivered, sign-up still saves the account, tells the user which code failed, and lets them ask again. They cannot finish confirming until both codes can be delivered.

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
playwright install chromium
make check             # lint, and cross-check every test against the app (no database needed)
make test              # unit tests (no database or browser needed)
make test-integration  # starts a scratch PostgreSQL on port 5433 and runs the server-side suite
make test-ui           # drives the real page in Chromium against a stand-in API
```

| Layer | Cases | What it proves |
| --- | --- | --- |
| Unit | ~140 | Distance and expiry rules, permissions, two-factor codes, encryption, rota, import validation, mail and SMS sending against local stand-in servers, configuration rules |
| Integration | ~210 | Real HTTP requests against PostgreSQL: sign-up and confirmation, lockouts and rate limits, search and retention, the corrections workflow and roles, staff login, the importer, scheduled jobs, and parallel-request races |
| Browser | 44 | The real page: journey, escaping of hostile data, request bodies, errors, accessibility, mobile layout |

The integration suite wipes every table in the database named by `DATABASE_URL`, so it refuses to run unless that URL contains `test`. The database-hardening test also needs `NGAO_TEST_OWNER_URL`, `NGAO_TEST_APP_URL` and `NGAO_TEST_APP_PASSWORD`, and CI sets all three. `.github/workflows/tests.yml` runs everything on each push.

Do not rely on this suite until it has run green on a real PostgreSQL. It was written and statically cross-checked without being executed against one. `tests/tools/verify_tests.py` compares every test with the real routes, methods, error messages, model fields, settings and fixtures, and it caught every mistake deliberately planted to test it. That is a strong guard against typos and drift, but it proves nothing about behaviour.

## Scheduled jobs and staffing

`deploy/ngao.cron` runs the three jobs, `docs/REVIEW_RUNBOOK.md` explains them, and `GET /health/jobs` reports whether they are running. Install:

```bash
sudo install -d -o ngao /var/log/ngao /etc/ngao
sudo cp deploy/ngao.cron /etc/cron.d/ngao
```

Put the app's settings in `/etc/ngao/env` (readable only by the `ngao` user) and your rota in `/etc/ngao/rota.csv`. Build the rota with `python -m scripts.generate_rota` as described in the runbook. Then point an uptime monitor at `/health/jobs`.

## Encryption keys

Staff authenticator secrets are encrypted before they reach the database. The key lives in `TOTP_ENCRYPTION_KEYS`, never in the database, so a stolen database dump cannot be used to forge staff codes.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the output in your secrets manager and inject it into the app as `TOTP_ENCRYPTION_KEYS`. To rotate, put the new key first and the old key after it, separated by a comma, run `python -m scripts.rotate_totp_keys`, then remove the old key. The same script upgrades any secrets stored in plaintext by an earlier version. Before running it on an old database, rename the column: `ALTER TABLE staff RENAME COLUMN totp_secret TO totp_secret_sealed; ALTER TABLE staff ALTER COLUMN totp_secret_sealed TYPE varchar(255);`. A compromised app server can still read the key, so this protects the database, not the app.

## Before this touches real data

- `app/identity.py`: `confirm_national_id` accepts any well-formed ID in demo mode and refuses to run otherwise. Connect a real registry check.
- `app/notify.py` is wired to SMTP and the SMS gateway. Configure both and send real test messages.
- Set `DEMO_MODE=false` and a long `APP_SECRET`. The app refuses to start in production mode with the default secret.
- Complete "Production database setup" and "Encryption keys" above. The app refuses to start in production mode without `TOTP_ENCRYPTION_KEYS`.
- Install `deploy/ngao.cron`, set `REVIEW_ALERT_EMAIL` and `ESCALATION_EMAIL`, configure SMTP and its DNS records, generate the rota from your real team, and run the confirmation steps in the runbook.
- Contract an SMS provider and confirm real codes arrive. Registration cannot complete without working SMS.
- Work through `docs/LEGAL_AND_PRIVACY_CHECKLIST.md`.
