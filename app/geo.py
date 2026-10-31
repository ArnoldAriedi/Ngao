from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0088
KM_PER_LAT_DEGREE = 110.5
KENYA_LATITUDE = (-4.8, 5.2)
KENYA_LONGITUDE = (33.8, 42.0)
SEARCH_MARGIN_DEGREES = 0.5


def in_service_area(latitude: float, longitude: float) -> bool:
    """Kenya plus a margin for border towns. Keeps bounding_box clear of the date line and the poles."""
    margin = SEARCH_MARGIN_DEGREES
    return (
        KENYA_LATITUDE[0] - margin <= latitude <= KENYA_LATITUDE[1] + margin
        and KENYA_LONGITUDE[0] - margin <= longitude <= KENYA_LONGITUDE[1] + margin
    )


def distance_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    d_lat = radians(lat_b - lat_a)
    d_lon = radians(lon_b - lon_a)
    chord = sin(d_lat / 2) ** 2 + cos(radians(lat_a)) * cos(radians(lat_b)) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, chord)))


def bounding_box(latitude: float, longitude: float, radius_km: float):
    """SQL prefilter. Always a superset of the circle."""
    lat_span = radius_km / KM_PER_LAT_DEGREE
    lon_span = lat_span / max(cos(radians(latitude)), 0.01)
    return latitude - lat_span, latitude + lat_span, longitude - lon_span, longitude + lon_span
