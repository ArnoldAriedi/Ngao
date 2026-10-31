import pytest
from pydantic import ValidationError

from app.schemas import StaffLogin


def test_login_needs_a_six_digit_code():
    assert StaffLogin(email="a@b.co", password="x", otp="123456").otp == "123456"
    with pytest.raises(ValidationError):
        StaffLogin(email="a@b.co", password="x", otp="12345")
