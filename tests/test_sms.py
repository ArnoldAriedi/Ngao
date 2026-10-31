import pytest

from app.sms import SmsError, send_sms
from tests.fake_sms_gateway import FakeSmsGateway


@pytest.fixture
def gateway():
    server = FakeSmsGateway()
    yield server
    server.stop()


def test_the_message_reaches_the_gateway_as_json_with_the_token(gateway):
    gateway.required_token = "s3cret"
    send_sms(gateway.url, "s3cret", "+254712345678", "Your Ngao phone code is 123456")
    [call] = gateway.received
    assert call["body"] == {"to": "+254712345678", "message": "Your Ngao phone code is 123456"}
    assert call["auth"] == "Bearer s3cret" and call["type"] == "application/json"


def test_no_authorization_header_is_sent_without_a_token(gateway):
    send_sms(gateway.url, "", "+254712345678", "hello")
    assert gateway.received[0]["auth"] is None


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_a_refusal_from_the_gateway_is_an_error(gateway, status):
    gateway.status = status
    with pytest.raises(SmsError):
        send_sms(gateway.url, "", "+254712345678", "hello")


def test_a_wrong_token_is_an_error(gateway):
    gateway.required_token = "right"
    with pytest.raises(SmsError):
        send_sms(gateway.url, "wrong", "+254712345678", "hello")


def test_an_unreachable_gateway_is_an_error():
    with pytest.raises(SmsError):
        send_sms("http://127.0.0.1:1/send", "", "+254712345678", "hello")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/send", "", "javascript:alert(1)"])
def test_only_http_and_https_gateways_are_allowed(url):
    with pytest.raises(SmsError):
        send_sms(url, "", "+254712345678", "hello")



class FakeAfricasTalking:
    def __init__(self, reply, status=201):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        self.received, outer = [], self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                outer.received.append({"form": raw, "key": self.headers.get("apiKey"), "type": self.headers.get("Content-Type")})
                self.send_response(status)
                self.end_headers()
                self.wfile.write(reply.encode())

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/version1/messaging"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def at_reply(code, status):
    return '{"SMSMessageData": {"Message": "x", "Recipients": [{"number": "+254712345678", "statusCode": %d, "status": "%s"}]}}' % (code, status)


def test_africastalking_gets_a_form_post_with_the_api_key_header():
    at = FakeAfricasTalking(at_reply(101, "Success"))
    try:
        send_sms(at.url, "key123", "+254712345678", "Your code is 123456", provider="africastalking", username="myapp", sender_id="NGAO")
    finally:
        at.stop()
    [call] = at.received
    assert call["key"] == "key123" and call["type"] == "application/x-www-form-urlencoded"
    assert "username=myapp" in call["form"] and "to=%2B254712345678" in call["form"] and "from=NGAO" in call["form"]


def test_africastalking_without_a_sender_id_sends_no_from_field():
    at = FakeAfricasTalking(at_reply(101, "Success"))
    try:
        send_sms(at.url, "key123", "+254712345678", "hi", provider="africastalking", username="myapp")
    finally:
        at.stop()
    assert "from=" not in at.received[0]["form"]


@pytest.mark.parametrize("code,status", [(402, "InvalidSenderId"), (403, "InvalidPhoneNumber"), (405, "InsufficientBalance")])
def test_africastalking_refusing_the_recipient_is_an_error_even_on_a_201(code, status):
    at = FakeAfricasTalking(at_reply(code, status))
    try:
        with pytest.raises(SmsError, match=status):
            send_sms(at.url, "key123", "+254712345678", "hi", provider="africastalking", username="myapp")
    finally:
        at.stop()


def test_africastalking_reply_that_is_not_json_is_an_error():
    at = FakeAfricasTalking("The supplied authentication is invalid")
    try:
        with pytest.raises(SmsError):
            send_sms(at.url, "bad", "+254712345678", "hi", provider="africastalking", username="myapp")
    finally:
        at.stop()


def test_africastalking_needs_a_username_and_key():
    with pytest.raises(SmsError):
        send_sms("https://api.africastalking.com/version1/messaging", "", "+254712345678", "hi", provider="africastalking", username="")
