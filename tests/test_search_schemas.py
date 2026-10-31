import pytest
from pydantic import ValidationError

from app.config import settings
from app.schemas import ApproveRecords, Point, SearchRequest


@pytest.mark.parametrize("latitude,longitude", [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_out_of_range_coordinates_are_refused(latitude, longitude):
    with pytest.raises(ValidationError):
        Point(latitude=latitude, longitude=longitude)


def test_radius_defaults_to_the_configured_maximum_and_cannot_exceed_it():
    assert SearchRequest(latitude=-1.2, longitude=36.8).radius_km == settings.max_search_radius_km
    with pytest.raises(ValidationError):
        SearchRequest(latitude=-1.2, longitude=36.8, radius_km=settings.max_search_radius_km + 1)
    with pytest.raises(ValidationError):
        SearchRequest(latitude=-1.2, longitude=36.8, radius_km=0)


def test_approval_batches_are_bounded():
    assert ApproveRecords(record_ids=[1, 2]).record_ids == [1, 2]
    with pytest.raises(ValidationError):
        ApproveRecords(record_ids=[])
    with pytest.raises(ValidationError):
        ApproveRecords(record_ids=list(range(201)))
