from datetime import date, timedelta

import pytest

from app.config import settings
from app.retention import plus_years
from app.schemas import PublicRecord
from tests.integration.helpers import (
    km_north, make_record, make_report, make_user, run_in_parallel, search, user_headers,
)

NEARBY = "/api/v1/safety/nearby"
LOOKUP = "/api/v1/safety/records/{}/lookup"


def years_ago(years: int) -> date:
    return date.today() - timedelta(days=365 * years + years // 4)


def point(km=0):
    latitude, longitude = km_north(km)
    return {"latitude": latitude, "longitude": longitude}


def test_results_come_back_nearest_first_with_distances_rounded_up(client, db):
    user = make_user(db)
    far, near, middle = make_record(db, km=12.5), make_record(db, km=2.5), make_record(db, km=7.2)
    body = search(client, user).json()
    assert [r["public_record_id"] for r in body] == [near.public_record_id, middle.public_record_id, far.public_record_id]
    assert [r["distance_km"] for r in body] == [3, 8, 13]


def test_a_record_just_inside_the_edge_is_found_and_one_beyond_it_is_not(client, db):
    user = make_user(db)
    inside, outside = make_record(db, km=14.5), make_record(db, km=15.5)
    found = [r["public_record_id"] for r in search(client, user).json()]
    assert found == [inside.public_record_id] and outside.public_record_id not in found


def test_a_smaller_radius_narrows_the_results(client, db):
    user = make_user(db)
    make_record(db, km=2.5)
    make_record(db, km=7.2)
    assert len(search(client, user, radius_km=5).json()) == 1


def test_a_very_close_record_is_reported_as_at_least_one_kilometre(client, db):
    user = make_user(db)
    make_record(db, km=0.1)
    assert search(client, user).json()[0]["distance_km"] == 1


def test_only_public_fields_are_returned_and_never_where_exactly_or_who(client, db):
    user = make_user(db)
    make_record(db)
    item = search(client, user).json()[0]
    assert set(item) == set(PublicRecord.model_fields)
    assert not {"id", "latitude", "longitude", "source_reference", "source_name", "review_note"} & set(item)


def test_category_filter_returns_only_that_category(client, db):
    user = make_user(db)
    make_record(db, offense_category="CHILD_TRAFFICKING")
    make_record(db, offense_category="SEXUAL_ASSAULT")
    found = search(client, user, category="CHILD_TRAFFICKING").json()
    assert [r["offense_category"] for r in found] == ["CHILD_TRAFFICKING"]


def test_unknown_category_is_refused(client, db):
    response = search(client, make_user(db), category="KIDNAPPING")
    assert response.status_code == 400 and response.json()["detail"] == "Unsupported category"


@pytest.mark.parametrize("status", ["PENDING", "SUSPENDED", "REMOVED"])
def test_unpublished_records_are_never_shown(client, db, status):
    make_record(db, publication_status=status)
    assert search(client, make_user(db)).json() == []


def test_demo_mode_serves_only_fictional_records(client, db):
    make_record(db, is_synthetic=False)
    fiction = make_record(db, is_synthetic=True)
    found = search(client, make_user(db)).json()
    assert [r["public_record_id"] for r in found] == [fiction.public_record_id]


def test_production_mode_serves_only_real_records(client, db, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    make_record(db, is_synthetic=True)
    real = make_record(db, is_synthetic=False)
    found = search(client, make_user(db)).json()
    assert [r["public_record_id"] for r in found] == [real.public_record_id]


def test_a_single_conviction_lapses_after_seven_years(client, db):
    user = make_user(db)
    make_record(db, judgment_date=years_ago(10))
    current = make_record(db, judgment_date=years_ago(1))
    found = search(client, user).json()
    assert [r["public_record_id"] for r in found] == [current.public_record_id]
    assert found[0]["listed_until"] == plus_years(current.judgment_date, 7).isoformat()


def test_a_repeat_offender_stays_listed_permanently(client, db):
    make_record(db, judgment_date=years_ago(25), convictions_count=2)
    found = search(client, make_user(db)).json()
    assert len(found) == 1 and found[0]["listed_until"] is None and found[0]["convictions_count"] == 2


def test_the_seven_years_run_from_release_when_that_is_later(client, db):
    make_record(db, judgment_date=years_ago(9), release_date=years_ago(2))
    assert len(search(client, make_user(db)).json()) == 1


@pytest.mark.parametrize("body", [
    {"latitude": 91, "longitude": 36.8}, {"latitude": -91, "longitude": 36.8},
    {"latitude": -1.2, "longitude": 181}, {"latitude": -1.2, "longitude": -181},
    {"latitude": -1.2, "longitude": 36.8, "radius_km": 0}, {"latitude": -1.2, "longitude": 36.8, "radius_km": -3},
    {"latitude": -1.2}, {},
])
def test_invalid_search_bodies_are_refused(client, db, body):
    response = client.post(NEARBY, json=body, headers=user_headers(make_user(db)))
    assert response.status_code == 422


def test_the_radius_cannot_exceed_the_configured_maximum(client, db):
    response = search(client, make_user(db), radius_km=settings.max_search_radius_km + 1)
    assert response.status_code == 422


def test_coordinates_in_the_url_are_not_accepted_at_all(client, db):
    response = client.get(f"{NEARBY}?latitude=-1.28&longitude=36.8", headers=user_headers(make_user(db)))
    assert response.status_code == 405


def test_the_daily_limit_is_enforced_and_says_so(client, db, monkeypatch):
    monkeypatch.setattr(settings, "daily_search_limit", 2)
    user = make_user(db)
    assert [search(client, user).status_code for _ in range(2)] == [200, 200]
    blocked = search(client, user)
    assert blocked.status_code == 429 and blocked.json()["detail"] == "Daily search limit reached. Try again tomorrow"


def test_the_limit_is_per_person(client, db, monkeypatch):
    monkeypatch.setattr(settings, "daily_search_limit", 1)
    first, second = make_user(db), make_user(db)
    search(client, first)
    assert search(client, first).status_code == 429
    assert search(client, second).status_code == 200


def test_the_allowance_resets_on_a_new_day(client, db, monkeypatch):
    monkeypatch.setattr(settings, "daily_search_limit", 1)
    user = make_user(db)
    search(client, user)
    assert search(client, user).status_code == 429
    user.search_day = date.today() - timedelta(days=1)
    db.commit()
    assert search(client, user).status_code == 200
    db.refresh(user)
    assert user.searches_today == 1 and user.search_day == date.today()


def test_refused_requests_do_not_use_up_the_allowance(client, db, monkeypatch):
    monkeypatch.setattr(settings, "daily_search_limit", 2)
    user = make_user(db)
    for _ in range(5):
        assert search(client, user, category="KIDNAPPING").status_code == 400
        assert search(client, user, latitude=999).status_code == 422
    assert [search(client, user).status_code for _ in range(2)] == [200, 200]


def test_looking_up_one_record_costs_a_search_too(client, db, monkeypatch):
    monkeypatch.setattr(settings, "daily_search_limit", 2)
    user, record = make_user(db), make_record(db)
    assert search(client, user).status_code == 200
    assert client.post(LOOKUP.format(record.public_record_id), json=point(), headers=user_headers(user)).status_code == 200
    assert search(client, user).status_code == 429
    assert client.post(LOOKUP.format(record.public_record_id), json=point(), headers=user_headers(user)).status_code == 429


def test_lookup_returns_the_public_view_with_distance(client, db):
    user, record = make_user(db), make_record(db, km=4.2)
    response = client.post(LOOKUP.format(record.public_record_id), json=point(), headers=user_headers(user))
    assert response.status_code == 200
    assert set(response.json()) == set(PublicRecord.model_fields) and response.json()["distance_km"] == 5


def test_lookup_hides_records_that_are_far_unpublished_lapsed_or_unknown(client, db):
    user = make_user(db)
    far = make_record(db, km=30)
    pending = make_record(db, publication_status="PENDING")
    lapsed = make_record(db, judgment_date=years_ago(10))
    for public_id in (far.public_record_id, pending.public_record_id, lapsed.public_record_id, "NGA-NOSUCHREC"):
        response = client.post(LOOKUP.format(public_id), json=point(), headers=user_headers(user))
        assert response.status_code == 404 and response.json()["detail"] == "Record not found"


def test_lookup_validates_coordinates_like_search_does(client, db):
    user, record = make_user(db), make_record(db)
    response = client.post(LOOKUP.format(record.public_record_id), json={"latitude": 123, "longitude": 36.8}, headers=user_headers(user))
    assert response.status_code == 422


def test_an_overdue_urgent_report_hides_the_record_before_results_are_built(client, db):
    user, record = make_user(db), make_record(db)
    make_report(db, record, make_user(db), "WRONG_PERSON", hours_old=80)
    assert search(client, user).json() == []
    db.refresh(record)
    assert record.publication_status == "SUSPENDED"


def test_the_overdue_rule_can_be_switched_off(client, db, monkeypatch):
    monkeypatch.setattr(settings, "suspend_on_deadline", False)
    user, record = make_user(db), make_record(db)
    make_report(db, record, make_user(db), "WRONG_PERSON", hours_old=80)
    assert len(search(client, user).json()) == 1


def test_a_young_or_non_urgent_report_does_not_hide_anything(client, db):
    user = make_user(db)
    fresh, slow = make_record(db), make_record(db, km=3.5)
    make_report(db, fresh, make_user(db), "WRONG_PERSON", hours_old=10)
    make_report(db, slow, make_user(db), "WRONG_DETAILS", hours_old=80)
    assert len(search(client, user).json()) == 2


def test_parallel_searches_never_exceed_the_daily_limit(db, monkeypatch):
    from app.main import spend_search
    from app.models import User

    monkeypatch.setattr(settings, "daily_search_limit", 5)
    user = make_user(db)

    outcomes = run_in_parallel(lambda session, _: spend_search(session.get(User, user.id), session), 15)
    assert outcomes.count("ok") == 5 and outcomes.count(429) == 10


@pytest.mark.parametrize("latitude,longitude", [(51.5, -0.12), (0.0, 179.9), (0.0, -179.9), (89.0, 36.8), (-34.0, 18.4)])
def test_searches_from_outside_kenya_and_its_margin_are_refused_with_a_reason(client, db, latitude, longitude):
    response = client.post(NEARBY, json={"latitude": latitude, "longitude": longitude}, headers=user_headers(make_user(db)))
    assert response.status_code == 422
    assert "Searches are only available in and near Kenya" in response.json()["detail"][0]["msg"]


def test_a_border_town_just_outside_kenya_can_still_search(client, db):
    response = client.post(NEARBY, json={"latitude": -5.0, "longitude": 39.5}, headers=user_headers(make_user(db)))
    assert response.status_code == 200


def test_lookup_has_the_same_service_area(client, db):
    record = make_record(db)
    response = client.post(LOOKUP.format(record.public_record_id), json={"latitude": 51.5, "longitude": -0.12}, headers=user_headers(make_user(db)))
    assert response.status_code == 422
