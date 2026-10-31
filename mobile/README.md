# Mobile client outline

The repository ships the API and a responsive web app. A native client is a separate project.

Suggested stack: React Native + TypeScript.

Screens:
1. Welcome
2. Create account (name, email, phone, national ID, password)
3. Confirm codes
4. Search with foreground location permission and the nested-shield distance view
5. Record list, filtered by distance band and type
6. Report a mistake, from each record (`POST /api/v1/safety/records/{id}/corrections`), plus a list of your reports (`GET /api/v1/safety/corrections`) with status, review-by date and the reviewer's note

Reuse the shield in `app/static/index.html` (`#mark` and `#almond`) and the flag colours: black `#000000`, red `#BB0000`, green `#006600`, white `#FFFFFF`. Red marks permanent listings, green marks a verified account.

Keep the bearer token in the platform's secure store. Never log coordinates. Staff tools stay in the web console. Never ship staff credentials or the app secret.
