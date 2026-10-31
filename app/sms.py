import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 10
AT_ACCEPTED = {100, 101, 102}  # Processed, Sent, Queued


class SmsError(Exception):
    pass


def africastalking_request(url, api_key, username, sender_id, to, message):
    if not api_key or not username:
        raise SmsError("Africa's Talking needs AT_USERNAME and SMS_GATEWAY_TOKEN (the API key)")
    form = {"username": username, "to": to, "message": message}
    if sender_id:
        form["from"] = sender_id
    headers = {"apiKey": api_key, "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    return urllib.request.Request(url, urllib.parse.urlencode(form).encode(), headers, method="POST")


def check_africastalking(body):
    """Africa's Talking can answer 201 even when it refuses a message, so read each recipient's status."""
    try:
        recipients = json.loads(body)["SMSMessageData"]["Recipients"]
        accepted = [r for r in recipients if r["statusCode"] in AT_ACCEPTED]
        status = recipients[0].get("status", "unknown") if recipients else "no recipients"
    except (ValueError, KeyError, TypeError, AttributeError):
        raise SmsError("Africa's Talking sent a reply Ngao could not read") from None
    if not accepted:
        raise SmsError(f"Africa's Talking did not accept the message: {status}")


def send_sms(gateway_url: str, token: str, to: str, message: str, provider: str = "", username: str = "", sender_id: str = "") -> None:
    """Generic gateway: POST {"to", "message"} as JSON with a bearer token, any 2xx is accepted.
    provider="africastalking": form POST with an apiKey header, and each recipient's status is checked."""
    if not gateway_url.startswith(("http://", "https://")):
        raise SmsError("SMS gateway URL must be http or https")
    if provider == "africastalking":
        request = africastalking_request(gateway_url, token, username, sender_id, to, message)
    else:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(gateway_url, json.dumps({"to": to, "message": message}).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
            body = reply.read()
    except (urllib.error.URLError, OSError) as failure:
        raise SmsError(str(failure)) from None
    if provider == "africastalking":
        check_africastalking(body)
