import base64
import hashlib

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "development-only-change-this-secret"


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://ngao:ngao_dev_password@localhost:5432/ngao"
    migration_database_url: str = ""
    app_secret: str = DEV_SECRET
    totp_encryption_keys: str = ""
    demo_mode: bool = True
    max_search_radius_km: int = 15
    token_ttl_minutes: int = 720
    code_ttl_minutes: int = 10
    daily_search_limit: int = 30
    daily_report_limit: int = 5
    trusted_proxy_hops: int = 0
    staff_token_ttl_minutes: int = 60
    urgent_review_hours: int = 72
    standard_review_days: int = 14
    suspend_on_review_start: bool = True
    suspend_on_deadline: bool = True
    review_alert_email: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_security: str = "starttls"
    mail_from: str = ""
    brevo_api_key: str = ""
    id_provider: str = ""
    dojah_app_id: str = ""
    dojah_secret_key: str = ""
    sms_gateway_url: str = ""
    sms_gateway_token: str = ""
    sms_provider: str = ""
    at_username: str = ""
    at_sender_id: str = ""
    escalation_email: str = ""
    urgent_claim_target_hours: int = 24
    escalation_hours: int = 48
    min_active_reviewers: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def check_settings(self):
        if self.smtp_security not in {"starttls", "ssl", "none"}:
            raise ValueError("SMTP_SECURITY must be starttls, ssl or none")
        if self.smtp_host and not self.mail_from:
            raise ValueError("MAIL_FROM must be set when SMTP_HOST is set")
        if self.brevo_api_key and not self.mail_from:
            raise ValueError("MAIL_FROM must be set when BREVO_API_KEY is set")
        if self.id_provider not in {"", "dojah", "none"}:
            raise ValueError("ID_PROVIDER must be empty, dojah or none")
        if self.id_provider == "dojah" and not (self.dojah_app_id and self.dojah_secret_key):
            raise ValueError("DOJAH_APP_ID and DOJAH_SECRET_KEY must be set when ID_PROVIDER is dojah")
        if self.sms_provider not in {"", "africastalking"}:
            raise ValueError("SMS_PROVIDER must be empty or africastalking")
        if self.sms_provider == "africastalking" and not (self.at_username and self.sms_gateway_token):
            raise ValueError("AT_USERNAME and SMS_GATEWAY_TOKEN must be set when SMS_PROVIDER is africastalking")
        if self.demo_mode:
            return self
        if not (self.smtp_host or self.brevo_api_key):
            raise ValueError("SMTP_HOST or BREVO_API_KEY must be set when DEMO_MODE is false")
        if not self.sms_gateway_url.startswith("https://"):
            raise ValueError("SMS_GATEWAY_URL must be an https URL when DEMO_MODE is false")
        if self.smtp_security == "none":
            raise ValueError("SMTP_SECURITY=none is only allowed in demo mode")
        if self.app_secret == DEV_SECRET:
            raise ValueError("APP_SECRET must be set when DEMO_MODE is false")
        if not self.totp_encryption_keys:
            raise ValueError("TOTP_ENCRYPTION_KEYS must be set when DEMO_MODE is false")
        return self

    @property
    def totp_key_list(self) -> list[str]:
        if self.totp_encryption_keys:
            return [key.strip() for key in self.totp_encryption_keys.split(",") if key.strip()]
        return [base64.urlsafe_b64encode(hashlib.sha256(self.app_secret.encode()).digest()).decode()]


settings = Settings()
