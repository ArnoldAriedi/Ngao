import pytest
from pydantic import ValidationError

from app.schemas import CorrectionIn, Resolution

LONG_ENOUGH = "The court file lists a different father's name."


def test_known_reason_with_details_is_accepted():
    assert CorrectionIn(reason="WRONG_PERSON", details=LONG_ENOUGH).reason == "WRONG_PERSON"


def test_unknown_reason_is_rejected():
    with pytest.raises(ValidationError):
        CorrectionIn(reason="DISLIKE", details=LONG_ENOUGH)


def test_thin_details_are_rejected():
    with pytest.raises(ValidationError):
        CorrectionIn(reason="WRONG_PERSON", details="wrong")


def test_resolution_can_suspend_the_record():
    assert Resolution(outcome="RESOLVED", note="Appeal confirmed", record_status="SUSPENDED").record_status == "SUSPENDED"


def test_resolution_rejects_bad_record_status_and_outcome():
    with pytest.raises(ValidationError):
        Resolution(outcome="RESOLVED", note="ok then", record_status="DELETED")
    with pytest.raises(ValidationError):
        Resolution(outcome="MAYBE", note="ok then")
