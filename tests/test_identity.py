import pytest
from pydantic import ValidationError

from app.schemas import Registration
from app.identity import normalize_phone


@pytest.mark.parametrize("raw", ["0712 345 678", "+254712345678", "254-712-345-678", "0112345678"])
def test_kenyan_mobiles_normalise(raw):
    assert normalize_phone(raw).startswith("+254")
    assert len(normalize_phone(raw)) == 13


@pytest.mark.parametrize("raw", ["0612345678", "12345", "+1 202 555 0100", ""])
def test_other_numbers_are_rejected(raw):
    assert normalize_phone(raw) is None


def valid(**overrides):
    fields = dict(full_name="Test Person", email="a@b.co", phone="0712345678", national_id="12345678", password="long-enough-pw")
    return Registration(**{**fields, **overrides})


def test_registration_accepts_seven_and_eight_digit_ids():
    assert valid(national_id="1234567").national_id == "1234567"
    assert valid().phone == "+254712345678"


@pytest.mark.parametrize("bad_id", ["123456", "123456789", "12345ab8"])
def test_registration_rejects_malformed_ids(bad_id):
    with pytest.raises(ValidationError):
        valid(national_id=bad_id)


def test_demo_mode_accepts_a_well_formed_id_and_rejects_a_malformed_one(monkeypatch):
    from app.config import settings
    from app.identity import confirm_national_id

    monkeypatch.setattr(settings, "demo_mode", True)
    assert confirm_national_id("12345678", "Wanjiku Kamau") is True
    assert confirm_national_id("123", "Wanjiku Kamau") is False


def test_production_refuses_to_pretend_an_id_was_checked(monkeypatch):
    from fastapi import HTTPException

    from app.config import settings
    from app.identity import confirm_national_id

    monkeypatch.setattr(settings, "demo_mode", False)
    with pytest.raises(HTTPException) as refused:
        confirm_national_id("12345678", "Wanjiku Kamau")
    assert refused.value.status_code == 503



class FakeDojah:
    def __init__(self, status=200, reply=None):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        self.received, outer = [], self
        body = json.dumps(reply if reply is not None else {"entity": {"first_name": "Amina", "middle_name": "Wanjiru", "last_name": "Otieno"}})

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.received.append({"path": self.path, "auth": self.headers.get("Authorization"), "app": self.headers.get("AppId")})
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body.encode())

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/v1/ke/kyc/id"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def check_with_dojah(monkeypatch, typed_name, status=200, reply=None, national_id="12345678"):
    from app.config import settings
    from app.identity import dojah_confirm
    monkeypatch.setattr(settings, "dojah_secret_key", "secret-key")
    monkeypatch.setattr(settings, "dojah_app_id", "app-id")
    server = FakeDojah(status, reply)
    try:
        return dojah_confirm(national_id, typed_name, url=server.url), server.received
    finally:
        server.stop()


def test_dojah_is_asked_with_the_raw_secret_and_app_id(monkeypatch):
    ok, received = check_with_dojah(monkeypatch, "Amina Otieno")
    assert ok is True
    assert received[0]["path"].endswith("?id=12345678") and received[0]["auth"] == "secret-key" and received[0]["app"] == "app-id"


def test_names_are_matched_loosely_but_a_stranger_is_refused(monkeypatch):
    for typed, expected in [("Otieno Amina Wanjiru", True), ("amina otieno", True), ("Amina Wanjiru Otieno", True), ("Amina Kamau", False), ("John Otieno", False), ("Otieno", False)]:
        assert check_with_dojah(monkeypatch, typed)[0] is expected, typed


def test_an_id_with_no_record_is_not_verified(monkeypatch):
    assert check_with_dojah(monkeypatch, "Amina Otieno", status=404)[0] is False


def test_a_malformed_id_is_refused_without_calling_the_provider(monkeypatch):
    ok, received = check_with_dojah(monkeypatch, "Amina Otieno", national_id="12ab")
    assert ok is False and received == []


def test_provider_trouble_is_a_503_not_a_wrong_id(monkeypatch):
    import pytest
    from fastapi import HTTPException
    for status in (401, 402, 424, 429, 500):
        with pytest.raises(HTTPException) as caught:
            check_with_dojah(monkeypatch, "Amina Otieno", status=status)
        assert caught.value.status_code == 503, status
    for reply in ({"nope": 1}, {"entity": None}, {"entity": "x"}):
        with pytest.raises(HTTPException):
            check_with_dojah(monkeypatch, "Amina Otieno", reply=reply)


def test_an_unreachable_provider_is_a_503(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.config import settings
    from app.identity import dojah_confirm
    monkeypatch.setattr(settings, "dojah_secret_key", "k")
    monkeypatch.setattr(settings, "dojah_app_id", "a")
    with pytest.raises(HTTPException):
        dojah_confirm("12345678", "Amina Otieno", url="http://127.0.0.1:1/api/v1/ke/kyc/id")


def test_the_dojah_setting_switches_the_real_check_on(monkeypatch):
    from app import identity
    from app.config import settings
    monkeypatch.setattr(settings, "id_provider", "dojah")
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(identity, "dojah_confirm", lambda national_id, full_name: national_id == "11111111")
    assert identity.confirm_national_id("11111111", "A B") is True
    assert identity.confirm_national_id("22222222", "A B") is False



def test_id_provider_none_skips_the_registry_but_still_checks_the_format(monkeypatch):
    from app import identity
    from app.config import settings
    monkeypatch.setattr(settings, "id_provider", "none")
    monkeypatch.setattr(settings, "demo_mode", False)
    assert identity.confirm_national_id("12345678", "Any Name") is True
    assert identity.confirm_national_id("1234567", "Any Name") is True
    assert identity.confirm_national_id("12ab", "Any Name") is False
