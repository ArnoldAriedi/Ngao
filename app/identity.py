import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from fastapi import HTTPException

from app.config import settings

NATIONAL_ID = re.compile(r"\d{7,8}")
KENYAN_MOBILE = re.compile(r"(?:\+?254|0)([17]\d{8})")


def normalize_phone(raw: str) -> str | None:
    match = KENYAN_MOBILE.fullmatch(re.sub(r"[\s-]", "", raw))
    return f"+254{match.group(1)}" if match else None


log = logging.getLogger("ngao.identity")
DOJAH_URL = "https://api.dojah.io/api/v1/ke/kyc/id"
TIMEOUT_SECONDS = 10


def name_tokens(*parts) -> set[str]:
    return {token for part in parts for token in re.findall(r"[a-z]+", (part or "").lower())}


def names_match(typed: str, first, middle, last) -> bool:
    """The registry's names must appear in what the person typed. At least two of them, or all if it has fewer."""
    registry = name_tokens(first, middle, last)
    return bool(registry) and len(registry & name_tokens(typed)) >= min(2, len(registry))


def dojah_confirm(national_id: str, full_name: str, url: str = DOJAH_URL) -> bool:
    """Look the ID up with Dojah and compare names. The registry record is used for this one comparison and never stored or logged."""
    if not NATIONAL_ID.fullmatch(national_id):
        return False
    headers = {"Authorization": settings.dojah_secret_key, "AppId": settings.dojah_app_id, "Accept": "application/json"}
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode({'id': national_id})}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
            entity = json.loads(reply.read())["entity"]
            parts = (entity.get("first_name"), entity.get("middle_name"), entity.get("last_name"))
    except urllib.error.HTTPError as failure:
        if failure.code == 404:
            return False
        log.error("ID check failed: provider answered %s", failure.code)
        raise HTTPException(503, "ID verification is unavailable right now. Try again shortly.") from None
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, AttributeError):
        log.error("ID check failed: provider unreachable or sent an unreadable reply")
        raise HTTPException(503, "ID verification is unavailable right now. Try again shortly.") from None
    return names_match(full_name, *parts)


def confirm_national_id(national_id: str, full_name: str) -> bool:
    """ID_PROVIDER=dojah checks the registry. ID_PROVIDER=none skips it and only checks the format. Otherwise demo accepts any well-formed ID and production refuses."""
    if settings.id_provider == "dojah":
        return dojah_confirm(national_id, full_name)
    if settings.id_provider == "none":
        return bool(NATIONAL_ID.fullmatch(national_id))
    if not settings.demo_mode:
        raise HTTPException(503, "No ID verification provider is configured")
    return bool(NATIONAL_ID.fullmatch(national_id))
