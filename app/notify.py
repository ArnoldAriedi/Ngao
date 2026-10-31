import logging

from fastapi import HTTPException

from app.config import settings
from app.mailer import MailError, SmtpConfig, build_email, send_brevo, send_email
from app.sms import SmsError, send_sms

log = logging.getLogger("ngao.notify")


def smtp_config() -> SmtpConfig:
    return SmtpConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        security=settings.smtp_security,
        sender=settings.mail_from,
    )


def deliver(channel: str, destination: str, message: str, subject: str = "Ngao") -> None:
    if channel == "email" and settings.brevo_api_key:
        try:
            send_brevo(settings.brevo_api_key, settings.mail_from, destination, subject, message)
        except MailError as failure:
            log.error("email to %s failed: %s", destination, failure)
            raise HTTPException(503, "Email could not be sent") from None
        return
    if channel == "email" and settings.smtp_host:
        try:
            send_email(smtp_config(), build_email(settings.mail_from, destination, subject, message))
        except MailError as failure:
            log.error("email to %s failed: %s", destination, failure)
            raise HTTPException(503, "Email could not be sent") from None
        return
    if channel == "sms" and settings.sms_gateway_url:
        try:
            send_sms(settings.sms_gateway_url, settings.sms_gateway_token, destination, message,
                     provider=settings.sms_provider, username=settings.at_username, sender_id=settings.at_sender_id)
        except SmsError as failure:
            log.error("sms to %s failed: %s", destination, failure)
            raise HTTPException(503, "SMS could not be sent") from None
        return
    if not settings.demo_mode:
        raise HTTPException(503, f"No {channel} delivery provider is configured")
    log.warning("demo %s to %s: %s", channel, destination, message)


def try_deliver(channel: str, destination: str, message: str, subject: str = "Ngao") -> bool:
    try:
        deliver(channel, destination, message, subject)
    except HTTPException as failure:
        log.warning("%s to %s not sent: %s", channel, destination, failure.detail)
        return False
    return True
