import pytest
from fastapi import HTTPException

from app.config import settings
from app.notify import deliver, try_deliver
from tests.fake_sms_gateway import FakeSmsGateway
from tests.fake_smtp import FakeSmtp


@pytest.fixture
def mail(monkeypatch):
    server = FakeSmtp()
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", server.port)
    monkeypatch.setattr(settings, "smtp_security", "none")
    monkeypatch.setattr(settings, "smtp_username", "")
    monkeypatch.setattr(settings, "mail_from", "alerts@ngao.example")
    yield server
    server.stop()


@pytest.fixture
def sms(monkeypatch):
    server = FakeSmsGateway()
    monkeypatch.setattr(settings, "sms_gateway_url", server.url)
    monkeypatch.setattr(settings, "sms_gateway_token", "gateway-token")
    yield server
    server.stop()


def test_email_goes_through_the_configured_smtp_server(mail):
    deliver("email", "reviewer@example.go.ke", "Report 17 is due.", "Urgent Ngao report")
    sender, recipients, raw = mail.messages[0]
    assert sender == "alerts@ngao.example" and recipients == ["reviewer@example.go.ke"]
    assert "Subject: Urgent Ngao report" in raw and "Report 17 is due." in raw


def test_an_smtp_failure_is_a_503_and_try_deliver_says_false(mail, monkeypatch):
    monkeypatch.setattr(settings, "smtp_port", 1)
    with pytest.raises(HTTPException) as refused:
        deliver("email", "a@b.co", "hello")
    assert refused.value.status_code == 503 and refused.value.detail == "Email could not be sent"
    assert try_deliver("email", "a@b.co", "hello") is False


def test_an_address_with_a_line_break_is_refused_not_sent(mail):
    with pytest.raises(HTTPException):
        deliver("email", "a@b.co\r\nBcc: someone@else.co", "hello")
    assert mail.messages == []


def test_sms_goes_through_the_configured_gateway(sms):
    deliver("sms", "+254712345678", "Your Ngao phone code is 123456")
    [call] = sms.received
    assert call["body"] == {"to": "+254712345678", "message": "Your Ngao phone code is 123456"}
    assert call["auth"] == "Bearer gateway-token"


def test_a_failing_sms_gateway_is_a_503_and_try_deliver_says_false(sms):
    sms.status = 500
    with pytest.raises(HTTPException) as refused:
        deliver("sms", "+254712345678", "hello")
    assert refused.value.status_code == 503 and refused.value.detail == "SMS could not be sent"
    assert try_deliver("sms", "+254712345678", "hello") is False


def test_try_deliver_says_true_when_the_message_went(mail, sms):
    assert try_deliver("email", "a@b.co", "hello") is True
    assert try_deliver("sms", "+254712345678", "hello") is True


def test_demo_mode_without_providers_only_logs(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "sms_gateway_url", "")
    deliver("email", "a@b.co", "hello")
    deliver("sms", "+254712345678", "hello")


@pytest.mark.parametrize("channel", ["email", "sms"])
def test_production_without_a_provider_refuses_rather_than_pretending(monkeypatch, channel):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "sms_gateway_url", "")
    with pytest.raises(HTTPException) as refused:
        deliver(channel, "a@b.co", "hello")
    assert refused.value.status_code == 503 and refused.value.detail == f"No {channel} delivery provider is configured"
    assert try_deliver(channel, "a@b.co", "hello") is False


def test_each_channel_uses_its_own_provider(mail, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "sms_gateway_url", "")
    deliver("email", "a@b.co", "hello")
    with pytest.raises(HTTPException):
        deliver("sms", "+254712345678", "hello")
