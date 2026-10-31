import base64
import hmac
import hashlib
import secrets
import struct
import time

STEP_SECONDS = 30


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def provisioning_uri(secret: str, email: str) -> str:
    return f"otpauth://totp/Ngao:{email}?secret={secret}&issuer=Ngao"


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 10**6:06d}"


def accepted_step(secret: str, submitted: str, last_step: int, now: float | None = None) -> int | None:
    """Matching time step, or None. Steps at or before last_step are replays."""
    current = int((time.time() if now is None else now) // STEP_SECONDS)
    for step in (current - 1, current, current + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), submitted):
            return step
    return None
