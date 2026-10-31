from app.geo import bounding_box, distance_km


def test_same_point_is_zero():
    assert distance_km(-1.2864, 36.8172, -1.2864, 36.8172) == 0


def test_distance_is_symmetric():
    forward = distance_km(-1.2864, 36.8172, -1.3, 36.83)
    backward = distance_km(-1.3, 36.83, -1.2864, 36.8172)
    assert abs(forward - backward) < 1e-9


def test_bounding_box_contains_point_on_the_circle():
    south, north, west, east = bounding_box(-1.2864, 36.8172, 15)
    assert south < -1.2864 - 0.13 and north > -1.2864 + 0.13
    assert west < 36.8172 - 0.13 and east > 36.8172 + 0.13


def test_service_area_is_kenya_with_a_margin_for_border_towns():
    from app.geo import in_service_area

    assert in_service_area(-1.2864, 36.8172)
    assert in_service_area(-5.0, 39.0)
    assert not in_service_area(51.5, -0.12)
    assert not in_service_area(0.0, 179.9)
    assert not in_service_area(0.0, -179.9)
    assert not in_service_area(89.0, 36.8)
