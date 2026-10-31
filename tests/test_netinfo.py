from app.netinfo import pick_client_ip


def test_header_ignored_without_trusted_proxy():
    assert pick_client_ip("198.51.100.7", "10.0.0.5", 0) == "10.0.0.5"


def test_one_proxy_last_address_is_client():
    assert pick_client_ip("203.0.113.9", "10.0.0.5", 1) == "203.0.113.9"


def test_spoofed_earlier_address_ignored():
    assert pick_client_ip("1.2.3.4, 203.0.113.9", "10.0.0.5", 1) == "203.0.113.9"


def test_two_proxies_skip_the_inner_one():
    assert pick_client_ip("203.0.113.9, 10.1.1.1", "10.0.0.5", 2) == "203.0.113.9"


def test_short_header_falls_back_to_peer():
    assert pick_client_ip("", "10.0.0.5", 1) == "10.0.0.5"
    assert pick_client_ip("203.0.113.9", "10.0.0.5", 2) == "10.0.0.5"
