from app.totp import accepted_step, code_at, new_secret

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def test_matches_rfc_6238_vectors():
    assert code_at(RFC_SECRET, 59 // 30) == "287082"
    assert code_at(RFC_SECRET, 1111111109 // 30) == "081804"


def test_adjacent_steps_only():
    now = 1111111109
    step = now // 30
    assert accepted_step(RFC_SECRET, code_at(RFC_SECRET, step), 0, now) == step
    assert accepted_step(RFC_SECRET, code_at(RFC_SECRET, step - 1), 0, now) == step - 1
    assert accepted_step(RFC_SECRET, code_at(RFC_SECRET, step + 5), 0, now) is None


def test_used_code_is_a_replay():
    now = 1111111109
    step = now // 30
    assert accepted_step(RFC_SECRET, code_at(RFC_SECRET, step), step, now) is None


def test_secrets_are_unique_base32():
    first, second = new_secret(), new_secret()
    assert first != second and first.isalnum() and first.upper() == first
