import pytest
from fastapi import Request

from app.ratelimit import _COUNTS, _MAX_KEYS, check_limit, client_ip


def test_map_stays_bounded_under_key_spray():
    _COUNTS.clear()
    for i in range(_MAX_KEYS + 5000):
        check_limit("spray:" + str(i), 5, 3600)
    assert len(_COUNTS) <= _MAX_KEYS


def test_forgot_aggregate_limit_per_ip_blocks_distinct_emails(client):
    codes = []
    for i in range(12):
        response = client.post(
            "/forgot", data={"email": "orang%d@example.test" % i}, follow_redirects=False
        )
        codes.append(response.status_code)
    assert codes[:10] == [303] * 10
    assert codes[10:] == [429, 429]


def test_forgot_pair_limit_still_applies(client):
    codes = [
        client.post(
            "/forgot", data={"email": "sama@example.test"}, follow_redirects=False
        ).status_code
        for _ in range(5)
    ]
    assert codes == [303, 303, 303, 429, 429]


def _request(headers=None, client=("203.0.113.9", 40000)) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
    }
    return Request(scope)


def test_client_ip_prefers_cf_connecting_ip():
    assert client_ip(_request({"CF-Connecting-IP": "198.51.100.7"})) == "198.51.100.7"
    assert (
        client_ip(_request({"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "9.9.9.9"}))
        == "198.51.100.7"
    )


def test_client_ip_uses_the_rightmost_xff_hop():
    assert (
        client_ip(_request({"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 8.8.8.8"}))
        == "8.8.8.8"
    )


def test_client_ip_falls_back_to_the_socket_peer():
    assert client_ip(_request()) == "203.0.113.9"


def test_spoofed_leftmost_xff_does_not_change_the_key():
    first = client_ip(_request({"X-Forwarded-For": "6.6.6.6, 9.9.9.9"}))
    second = client_ip(_request({"X-Forwarded-For": "7.7.7.7, 9.9.9.9"}))
    assert first == second == "9.9.9.9"

