import pytest

from app.mailer import MailError, SmtpConfig, build_email, send_email
from tests.fake_smtp import FakeSmtp


@pytest.fixture
def smtp():
    server = FakeSmtp()
    yield server
    server.stop()


def config(smtp, **overrides):
    fields = dict(host="127.0.0.1", port=smtp.port, username="", password="", security="none", sender="alerts@ngao.example")
    return SmtpConfig(**{**fields, **overrides})


def test_message_reaches_the_server_with_the_right_headers(smtp):
    message = build_email("alerts@ngao.example", "reviewer@example.go.ke", "Urgent Ngao report", "Report 17 is due Thu 22:00 UTC.")
    send_email(config(smtp), message)

    sender, recipients, raw = smtp.messages[0]
    assert sender == "alerts@ngao.example" and recipients == ["reviewer@example.go.ke"]
    assert "Subject: Urgent Ngao report" in raw and "Report 17 is due" in raw


def test_credentials_are_sent_when_configured(smtp):
    send_email(config(smtp, username="mailer", password="right-password"), build_email("a@b.co", "c@d.co", "s", "b"))
    assert smtp.logins == [("mailer", "right-password")]


def test_wrong_credentials_fail_loudly_and_send_nothing(smtp):
    with pytest.raises(MailError):
        send_email(config(smtp, username="mailer", password="wrong"), build_email("a@b.co", "c@d.co", "s", "b"))
    assert smtp.messages == []


def test_unreachable_server_is_a_mail_error():
    dead = SmtpConfig("127.0.0.1", 1, "", "", "none", "a@b.co")
    with pytest.raises(MailError):
        send_email(dead, build_email("a@b.co", "c@d.co", "s", "b"))


@pytest.mark.parametrize("recipient,subject", [("a@b.co\r\nBcc: x@y.co", "s"), ("a@b.co", "s\nBcc: x@y.co")])
def test_header_injection_is_refused(recipient, subject):
    with pytest.raises(MailError):
        build_email("alerts@ngao.example", recipient, subject, "body")



class FakeBrevo:
    def __init__(self, status=201):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        self.received, outer = [], self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                outer.received.append({"body": body, "key": self.headers.get("api-key")})
                self.send_response(status)
                self.end_headers()
                self.wfile.write(b'{"messageId": "<1@x>"}' if status == 201 else b'{"message": "Sender not valid"}')

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v3/smtp/email"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def test_brevo_gets_the_message_as_json_with_the_api_key():
    from app.mailer import send_brevo
    brevo = FakeBrevo()
    try:
        send_brevo("key123", "ngao@example.com", "user@example.com", "Ngao code", "Your code is 123456", url=brevo.url)
    finally:
        brevo.stop()
    [call] = brevo.received
    assert call["key"] == "key123"
    assert call["body"] == {"sender": {"name": "Ngao", "email": "ngao@example.com"}, "to": [{"email": "user@example.com"}], "subject": "Ngao code", "textContent": "Your code is 123456"}


def test_brevo_refusing_the_message_is_an_error_that_says_why():
    import pytest
    from app.mailer import MailError, send_brevo
    brevo = FakeBrevo(status=400)
    try:
        with pytest.raises(MailError, match="Sender not valid"):
            send_brevo("key123", "ngao@example.com", "user@example.com", "hi", "hello", url=brevo.url)
    finally:
        brevo.stop()


def test_an_unreachable_brevo_is_an_error():
    import pytest
    from app.mailer import MailError, send_brevo
    with pytest.raises(MailError):
        send_brevo("key123", "ngao@example.com", "user@example.com", "hi", "hello", url="http://127.0.0.1:1/v3/smtp/email")


def test_brevo_rejects_line_breaks_in_the_recipient_or_subject():
    import pytest
    from app.mailer import MailError, send_brevo
    with pytest.raises(MailError):
        send_brevo("key123", "ngao@example.com", "user@example.com\nbcc:evil@example.com", "hi", "hello")
    with pytest.raises(MailError):
        send_brevo("key123", "ngao@example.com", "user@example.com", "hi\nbcc:evil@example.com", "hello")
