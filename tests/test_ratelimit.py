import pytest

from app.ratelimit import _COUNTS, _MAX_KEYS, check_limit


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
