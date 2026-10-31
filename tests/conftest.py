import os

import pytest


def pytest_collection_modifyitems(config, items):
    database_ready = os.environ.get("NGAO_TEST_DATABASE") == "1"
    for item in items:
        if "integration" not in item.path.parts:
            continue
        item.add_marker(pytest.mark.integration)
        if not database_ready:
            item.add_marker(pytest.mark.skip(reason="set NGAO_TEST_DATABASE=1 and point DATABASE_URL at a scratch database"))


@pytest.fixture(autouse=True)
def isolate_from_local_env(monkeypatch):
    """Real SMTP or SMS settings in a developer's .env must never leak into the tests."""
    from app.config import settings
    for name in ("smtp_host", "sms_gateway_url", "sms_gateway_token", "sms_provider", "at_username", "at_sender_id", "brevo_api_key", "id_provider", "dojah_app_id", "dojah_secret_key"):
        monkeypatch.setattr(settings, name, "")
