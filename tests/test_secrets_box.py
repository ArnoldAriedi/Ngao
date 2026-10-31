import pytest
from cryptography.fernet import Fernet

from app.secrets_box import SecretBox

PLAIN = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def key():
    return Fernet.generate_key().decode()


def test_round_trip_and_ciphertext_hides_the_secret():
    box = SecretBox([key()])
    sealed = box.seal(PLAIN)
    assert PLAIN not in sealed
    assert box.unseal(sealed) == PLAIN


def test_same_secret_seals_differently_each_time():
    box = SecretBox([key()])
    assert box.seal(PLAIN) != box.seal(PLAIN)


def test_wrong_key_cannot_read_it():
    sealed = SecretBox([key()]).seal(PLAIN)
    with pytest.raises(ValueError):
        SecretBox([key()]).unseal(sealed)


def test_rotation_moves_secrets_to_the_new_key_and_retires_the_old():
    old, new = key(), key()
    sealed_under_old = SecretBox([old]).seal(PLAIN)

    rotating = SecretBox([new, old])
    assert rotating.unseal(sealed_under_old) == PLAIN
    resealed = rotating.reseal(sealed_under_old)

    assert SecretBox([new]).unseal(resealed) == PLAIN
    with pytest.raises(ValueError):
        SecretBox([old]).unseal(resealed)


def test_legacy_plaintext_is_upgraded():
    box = SecretBox([key()])
    assert box.unseal(box.reseal(PLAIN)) == PLAIN


def test_no_keys_is_an_error():
    with pytest.raises(ValueError):
        SecretBox([])
