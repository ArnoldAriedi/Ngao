import json
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage

TIMEOUT_SECONDS = 10
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class MailError(Exception):
    pass


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    security: str
    sender: str


def build_email(sender: str, recipient: str, subject: str, body: str) -> EmailMessage:
    if any(ch in recipient + subject for ch in "\r\n"):
        raise MailError("Line breaks are not allowed in the recipient or subject")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    return message


def open_connection(config: SmtpConfig, context: ssl.SSLContext) -> smtplib.SMTP:
    if config.security == "ssl":
        return smtplib.SMTP_SSL(config.host, config.port, timeout=TIMEOUT_SECONDS, context=context)
    return smtplib.SMTP(config.host, config.port, timeout=TIMEOUT_SECONDS)


def send_email(config: SmtpConfig, message: EmailMessage) -> None:
    context = ssl.create_default_context()
    try:
        with open_connection(config, context) as client:
            if config.security == "starttls":
                client.starttls(context=context)
            if config.username:
                client.login(config.username, config.password)
            client.send_message(message)
    except (smtplib.SMTPException, OSError) as failure:
        raise MailError(str(failure)) from None


def send_brevo(api_key: str, sender: str, recipient: str, subject: str, body: str, url: str = BREVO_URL) -> None:
    """Send through Brevo's HTTPS API (port 443), which home and cloud networks rarely block."""
    if any(ch in recipient + subject for ch in "\r\n"):
        raise MailError("Line breaks are not allowed in the recipient or subject")
    payload = {"sender": {"name": "Ngao", "email": sender}, "to": [{"email": recipient}], "subject": subject, "textContent": body}
    headers = {"api-key": api_key, "accept": "application/json", "content-type": "application/json"}
    request = urllib.request.Request(url, json.dumps(payload).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS):
            return
    except urllib.error.HTTPError as failure:
        detail = failure.read()[:200].decode("utf-8", "replace")
        raise MailError(f"Brevo refused the message ({failure.code}): {detail}") from None
    except (urllib.error.URLError, OSError) as failure:
        raise MailError(str(failure)) from None
