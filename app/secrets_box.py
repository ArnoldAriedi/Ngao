import re

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

PLAIN_SECRET = re.compile(r"[A-Z2-7]{32}")


class SecretBox:
    """First key encrypts, any key decrypts. That is how keys rotate."""

    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("At least one encryption key is required")
        self._fernet = MultiFernet([Fernet(key.encode()) for key in keys])

    def seal(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def unseal(self, sealed: str) -> str:
        try:
            return self._fernet.decrypt(sealed.encode()).decode()
        except InvalidToken:
            raise ValueError("Stored secret cannot be decrypted with the configured keys") from None

    def reseal(self, stored: str) -> str:
        """Re-encrypt under the first key. Also upgrades legacy plaintext."""
        if PLAIN_SECRET.fullmatch(stored):
            return self.seal(stored)
        return self._fernet.rotate(stored.encode()).decode()
