import pytest

from app.permissions import transition_allowed

STATUSES = ["PENDING", "APPROVED", "SUSPENDED", "REMOVED"]


def test_admins_may_make_any_change():
    assert all(transition_allowed("ADMIN", a, b, False) for a in STATUSES for b in STATUSES)


def test_reviewers_may_suspend_a_published_record():
    assert transition_allowed("REVIEWER", "APPROVED", "SUSPENDED", False)


def test_reviewers_may_only_restore_a_suspension_their_own_report_caused():
    assert transition_allowed("REVIEWER", "SUSPENDED", "APPROVED", True)
    assert not transition_allowed("REVIEWER", "SUSPENDED", "APPROVED", False)


@pytest.mark.parametrize("current,target", [
    ("REMOVED", "APPROVED"), ("REMOVED", "SUSPENDED"), ("PENDING", "APPROVED"), ("PENDING", "SUSPENDED"),
    ("APPROVED", "REMOVED"), ("APPROVED", "PENDING"), ("SUSPENDED", "REMOVED"), ("SUSPENDED", "PENDING"),
])
def test_reviewers_cannot_publish_unremove_or_remove_even_when_a_suspension_is_theirs(current, target):
    assert not transition_allowed("REVIEWER", current, target, True)


def test_staying_put_is_always_allowed():
    assert all(transition_allowed("REVIEWER", status, status, False) for status in STATUSES)


def test_an_unknown_role_gets_no_extra_power():
    assert not transition_allowed("INTERN", "REMOVED", "APPROVED", True)
