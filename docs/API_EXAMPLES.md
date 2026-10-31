# API examples

Sign up, then confirm both codes:

```
POST /api/v1/auth/register
{"full_name": "Wanjiku Kamau", "email": "w@example.co.ke", "phone": "0712345678", "national_id": "12345678", "password": "a-long-password"}

POST /api/v1/auth/verify
{"email": "w@example.co.ke", "email_code": "482913", "phone_code": "107355"}
```

`register` replies `201` with `{"email": "...", "delivered": {"email": true, "phone": true}}`. If a flag is false, that code could not be sent. The account is saved, and `resend` tries again. In demo mode the reply also carries `demo_codes`.

Both return no data until the codes match. `verify` and `login` return `{"token": "..."}`.

If the codes expire, are guessed wrong too often, or never arrived, ask for new ones. The old codes stop working immediately:

```
POST /api/v1/auth/resend
{"email": "w@example.co.ke", "password": "a-long-password"}
```

`resend` returns the same `delivered` flags.

Check a stored session before showing anything: `GET /api/v1/auth/session` returns `{"ok": true}`, or 401 once the token has expired.

Signing in to an unconfirmed account returns 403, and the web app then calls `resend` for you. Rate-limited calls return 429 with a `Retry-After` header.

Sign in:

```
POST /api/v1/auth/login
{"email": "w@example.co.ke", "password": "a-long-password"}
```

Categories (no sign-in needed):

`GET /api/v1/safety/categories` also returns `max_radius_km`, the search limit the web app uses.

Nearby (needs `Authorization: Bearer <token>`). Coordinates go in the body, not the URL:

```
POST /api/v1/safety/nearby
{"latitude": -1.2864, "longitude": 36.8172, "radius_km": 15, "category": "SEXUAL_ASSAULT"}
```

`radius_km` and `category` are optional. The radius cannot exceed `MAX_SEARCH_RADIUS_KM`, and the point must be in or near Kenya. Looking up one record you already know counts as a search too:

```
POST /api/v1/safety/records/NGA-1A2B3C4D5E/lookup
{"latitude": -1.2864, "longitude": 36.8172}
```

Report a mistake on a record (needs a token; one open report per user per record):

```
POST /api/v1/safety/records/NGA-1A2B3C4D5E/corrections
{"reason": "WRONG_PERSON", "details": "The court file shows a different person with the same name."}
```

Reasons: `WRONG_PERSON`, `CONVICTION_OVERTURNED`, `WRONG_DETAILS`, `OTHER`. `details` must be 20 to 2000 characters.

Check your own reports, their deadlines and outcomes: `GET /api/v1/safety/corrections`. Each report has `record_hidden`, which is true while that report is the reason the record is hidden.

Report statuses: `OPEN`, `IN_REVIEW`, `RESOLVED` (accepted), `REJECTED` (not accepted).

## Staff

Create staff with `python -m scripts.create_staff`, which prints an authenticator-app setup link once.

```
POST /api/v1/staff/login
{"email": "reviewer@example.go.ke", "password": "...", "otp": "123456"}
```

Returns `{"token": "...", "role": "REVIEWER"}`. Send it as `Authorization: Bearer <token>`. Staff tokens last 60 minutes and do not work on user endpoints, and user tokens do not work here.

Reviewers and administrators:

```
GET  /api/v1/admin/corrections                 open queue, soonest deadline first, with an overdue flag
POST /api/v1/admin/corrections/17/claim        starts review; suspends the record for urgent reasons
POST /api/v1/admin/corrections/17/resolve
{"outcome": "RESOLVED", "note": "Appeal judgment confirmed with the registry.", "record_status": "REMOVED"}
```

`outcome` is `RESOLVED` or `REJECTED`. The reporter is emailed. `record_status` is required when the report suspended the record, to say what happens next (`APPROVED` restores it). Reviewers may suspend a record, and may restore one only when their own report suspended it. Every other status change needs an administrator (403).

Queue health, for any staff member:

`GET /api/v1/admin/queue/health` returns open reports by state (`ON_TRACK`, `CLAIM_LATE`, `ESCALATE`, `OVERDUE`), how many need attention, the number of active staff, and `understaffed`.

Health (no sign-in): `GET /health` returns `{"status": "ok", "demo_mode": false, "delivery": {"email": "configured", "sms": "configured"}}`. Each channel is `configured`, `demo` or `missing`.

Job health (no sign-in, for an uptime monitor):

`GET /health/jobs` returns `{"healthy": true, "jobs": {"enforce_deadlines": "OK", ...}}` with status 200, or status 503 if any job is `STALE`, `FAILING` or `NEVER_RAN`.

Administrators only:

```
GET  /api/v1/admin/records/pending
POST /api/v1/admin/records/approve
{"record_ids": [12, 13, 14]}
```

Imported records are `PENDING` until approved here. The reply lists which ids were approved and which were not pending.

```
POST /api/v1/admin/records/1/publication?status=SUSPENDED
GET  /api/v1/admin/audit?action=RECORD_STATUS_CHANGED&limit=100
```

Publication statuses: `PENDING`, `APPROVED`, `SUSPENDED`, `REMOVED`.
