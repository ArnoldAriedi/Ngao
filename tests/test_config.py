import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import DEV_SECRET, Settings

KEY = Fernet.generate_key().decode()


def build(**overrides):
    return Settings(_env_file=None, **overrides)


def production(**overrides):
    fields = dict(
        demo_mode=False, app_secret="s" * 40, totp_encryption_keys=KEY, smtp_host="smtp.example.com",
        mail_from="alerts@example.com", smtp_security="starttls", sms_gateway_url="https://sms.example.com/send",
    )
    return build(**{**fields, **overrides})


def test_a_fully_configured_production_setup_is_accepted():
    assert production().demo_mode is False


@pytest.mark.parametrize("change", [
    {"app_secret": DEV_SECRET},
    {"totp_encryption_keys": ""},
    {"smtp_host": ""},
    {"mail_from": ""},
    {"sms_gateway_url": ""},
    {"sms_gateway_url": "http://sms.example.com/send"},
    {"smtp_security": "none"},
    {"smtp_security": "tls"},
])
def test_production_refuses_to_start_with_missing_or_weak_settings(change):
    with pytest.raises(ValidationError):
        production(**change)


def test_demo_mode_needs_nothing_configured():
    settings = build(demo_mode=True, app_secret=DEV_SECRET, totp_encryption_keys="", smtp_host="", sms_gateway_url="")
    assert settings.demo_mode is True


def test_demo_mode_still_rejects_nonsense_mail_settings():
    with pytest.raises(ValidationError):
        build(demo_mode=True, smtp_security="tls")
    with pytest.raises(ValidationError):
        build(demo_mode=True, smtp_host="smtp.example.com", mail_from="")


def test_plain_smtp_is_allowed_only_in_demo_mode():
    assert build(demo_mode=True, smtp_host="127.0.0.1", mail_from="a@b.co", smtp_security="none").smtp_security == "none"


def test_key_list_splits_on_commas_and_ignores_blanks():
    settings = production(totp_encryption_keys=" first ,second,, ")
    assert settings.totp_key_list == ["first", "second"]


def test_demo_fallback_key_is_a_valid_fernet_key_that_depends_on_the_secret():
    first = build(demo_mode=True, app_secret="a" * 40, totp_encryption_keys="").totp_key_list
    again = build(demo_mode=True, app_secret="a" * 40, totp_encryption_keys="").totp_key_list
    other = build(demo_mode=True, app_secret="b" * 40, totp_encryption_keys="").totp_key_list
    assert first == again and first != other
    Fernet(first[0].encode())
