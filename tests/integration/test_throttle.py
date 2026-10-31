from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models import ThrottleEvent, utcnow
from app.throttle import blocked, client_ip, guard, key_for, record, recent

HOUR = timedelta(hours=1)


def test_the_limit_is_the_number_allowed_and_the_next_one_is_refused(db):
    key = key_for("test", "a")
    for _ in range(3):
        guard(db, key, 3, HOUR)
    with pytest.raises(HTTPException) as refused:
        guard(db, key, 3, HOUR)
    assert refused.value.status_code == 429 and refused.value.headers["Retry-After"] == "3600"


def test_keys_do_not_affect_each_other(db):
    for _ in range(3):
        guard(db, key_for("test", "a"), 3, HOUR)
    guard(db, key_for("test", "b"), 3, HOUR)


def test_events_outside_the_window_are_not_counted(db):
    key = key_for("test", "old")
    db.add_all([ThrottleEvent(key=key, at=utcnow() - timedelta(hours=2)) for _ in range(10)])
    db.commit()
    assert recent(db, key, HOUR) == 0
    guard(db, key, 1, HOUR)


def test_blocked_means_at_the_limit_not_over_it(db):
    key = key_for("test", "blocked")
    for _ in range(2):
        record(db, key)
    db.commit()
    assert blocked(db, key, 3, HOUR) is False
    record(db, key)
    db.commit()
    assert blocked(db, key, 3, HOUR) is True


def test_stored_keys_are_hashes_so_no_address_or_number_is_kept(db):
    guard(db, key_for("code-email", "wanjiku@example.co.ke"), 3, HOUR)
    guard(db, key_for("code-phone", "+254712345678"), 3, HOUR)
    stored = list(db.scalars(select(ThrottleEvent.key)))
    assert len(stored) == 2 and all(len(key) == 64 and key.isalnum() for key in stored)
    assert not any("wanjiku" in key or "254712" in key for key in stored)


def request_from(peer, forwarded=""):
    return SimpleNamespace(headers={"x-forwarded-for": forwarded} if forwarded else {}, client=SimpleNamespace(host=peer))


def test_the_forwarded_header_is_ignored_unless_proxies_are_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert client_ip(request_from("10.0.0.5", "203.0.113.9")) == "10.0.0.5"


def test_with_one_trusted_proxy_the_real_client_is_used_and_spoofing_is_not(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    assert client_ip(request_from("10.0.0.5", "6.6.6.6, 203.0.113.9")) == "203.0.113.9"


def test_a_request_with_no_client_address_still_gets_a_key(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert client_ip(SimpleNamespace(headers={}, client=None)) == "unknown"
