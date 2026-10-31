import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "app" / "static" / "index.html"
CATEGORIES = [
    ("GENDER_BASED_VIOLENCE", "Gender-based violence"), ("SEXUAL_ASSAULT", "Sexual assault"),
    ("CHILD_SEXUAL_OFFENCE", "Child sexual offences"), ("CHILD_TRAFFICKING", "Child trafficking"),
    ("CHILD_LABOUR", "Child labour"),
]
REASONS = [
    ("WRONG_PERSON", "This is not the person convicted"), ("CONVICTION_OVERTURNED", "The conviction was overturned on appeal"),
    ("WRONG_DETAILS", "The offence, dates or area are wrong"), ("OTHER", "Something else"),
]


def record(reference, category, label, distance, listed_until="2031-01-12", count=1, area="Demo area"):
    return {
        "public_record_id": reference, "offense_category": category, "offense_label": label,
        "convictions_count": count, "judgment_date": "2024-01-12", "release_date": None,
        "sentence_description": "Fictional sentence", "county": "Nairobi County", "area_label": area,
        "distance_km": distance, "listed_until": listed_until, "last_verified_at": None, "synthetic": True,
    }


def default_records():
    return [
        record("D-1", "CHILD_SEXUAL_OFFENCE", "Defilement (fictional)", 2),
        record("D-2", "SEXUAL_ASSAULT", "Sexual assault (fictional)", 4),
        record("D-3", "CHILD_LABOUR", "Hazardous child labour (fictional)", 7),
        record("D-4", "CHILD_SEXUAL_OFFENCE", "Repeat defilement (fictional)", 11, None, 2),
        record("D-5", "GENDER_BASED_VIOLENCE", "Repeat domestic violence (fictional)", 14, None, 2),
    ]


class MockApi:
    def __init__(self):
        self.reset()
        self.server = HTTPServer(("127.0.0.1", 0), self.handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reset(self):
        self.max_radius = 15
        self.demo_mode = True
        self.delivered = {"email": True, "phone": True}
        self.statuses = {}
        self.details = {}
        self.records = default_records()
        self.my_reports = []
        self.requests = []
        self.resends = []

    def requests_to(self, fragment, method="POST"):
        return [item for item in self.requests if fragment in item["path"] and item["method"] == method]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def handler(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body, content_type="application/json"):
                payload = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(payload)

            def forced(self, key, success_status, success_body):
                status = api.statuses.get(key, success_status)
                if status == success_status:
                    return self.reply(status, success_body)
                return self.reply(status, {"detail": api.details.get(key, "Something failed")})

            def do_GET(self):
                if self.path == "/":
                    return self.reply(200, PAGE.read_bytes(), "text/html")
                if self.path != "/":
                    api.requests.append({"method": "GET", "path": self.path, "body": None})
                if self.path.startswith("/api/v1/auth/session"):
                    return self.forced("session", 200, {"ok": True})
                if self.path.startswith("/api/v1/safety/categories"):
                    body = {
                        "max_radius_km": api.max_radius,
                        "demo_mode": api.demo_mode,
                        "categories": [{"code": c, "label": l} for c, l in CATEGORIES],
                        "correction_reasons": [{"code": c, "label": l} for c, l in REASONS],
                    }
                    return self.forced("categories", 200, body)
                if self.path.startswith("/api/v1/safety/corrections"):
                    return self.reply(200, api.my_reports)
                self.reply(404, {"detail": "not found"})

            def do_POST(self):
                size = int(self.headers.get("Content-Length", 0))
                sent = json.loads(self.rfile.read(size) or b"{}")
                api.requests.append({"method": "POST", "path": self.path, "body": sent})
                email = sent.get("email", "")
                if self.path.endswith("/register"):
                    codes = {"email": "482913", "phone": "107355"}
                    return self.forced("register", 201, {"email": email.lower(), "demo_codes": codes, "delivered": api.delivered})
                if self.path.endswith("/verify"):
                    return self.forced("verify", 200, {"token": "test-token"})
                if self.path.endswith("/resend"):
                    api.resends.append(sent)
                    return self.reply(200, {"email": email, "demo_codes": {"email": "111222", "phone": "333444"}, "delivered": api.delivered})
                if self.path.endswith("/login"):
                    if email == "unconfirmed@example.co.ke":
                        return self.reply(403, {"detail": "Finish confirming your codes first. Choose Send new codes"})
                    if email == "wrong@example.co.ke":
                        return self.reply(401, {"detail": "Wrong email or password"})
                    return self.reply(200, {"token": "test-token"})
                if self.path.endswith("/nearby"):
                    inside = [r for r in api.records if r["distance_km"] <= sent.get("radius_km", 15)]
                    if sent.get("category"):
                        inside = [r for r in inside if r["offense_category"] == sent["category"]]
                    return self.forced("nearby", 200, inside)
                if self.path.endswith("/corrections"):
                    return self.forced("report", 201, {"reference": 17, "status": "OPEN", "review_by": "2026-10-29T09:00:00Z"})
                self.reply(404, {"detail": "not found"})

        return Handler
