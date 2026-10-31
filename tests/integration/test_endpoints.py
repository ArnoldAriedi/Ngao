from app.config import settings


def test_the_home_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200 and "<title>Ngao</title>" in response.text


def test_health_in_demo_mode_says_delivery_is_simulated(client):
    body = client.get("/health").json()
    assert body == {"status": "ok", "demo_mode": True, "delivery": {"email": "demo", "sms": "demo"}}


def test_health_reports_configured_providers(client, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "sms_gateway_url", "https://sms.example.com/send")
    assert client.get("/health").json()["delivery"] == {"email": "configured", "sms": "configured"}


def test_health_in_production_mode_flags_missing_providers(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    assert client.get("/health").json()["delivery"] == {"email": "missing", "sms": "missing"}


def test_the_settings_the_page_needs_come_from_the_server(client):
    body = client.get("/api/v1/safety/categories").json()
    assert [c["code"] for c in body["categories"]] == [
        "GENDER_BASED_VIOLENCE", "SEXUAL_ASSAULT", "CHILD_SEXUAL_OFFENCE", "CHILD_TRAFFICKING", "CHILD_LABOUR",
    ]
    assert [r["code"] for r in body["correction_reasons"]] == ["WRONG_PERSON", "CONVICTION_OVERTURNED", "WRONG_DETAILS", "OTHER"]
    assert body["max_radius_km"] == settings.max_search_radius_km and body["demo_mode"] is True


def test_the_settings_endpoint_needs_no_sign_in(client):
    assert client.get("/api/v1/safety/categories").status_code == 200
