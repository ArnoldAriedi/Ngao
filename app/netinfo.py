def pick_client_ip(forwarded_for: str, peer: str, trusted_hops: int) -> str:
    """Client is the Nth address from the right. 0 trusts no proxy."""
    if trusted_hops <= 0:
        return peer
    addresses = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    return addresses[-trusted_hops] if len(addresses) >= trusted_hops else peer
