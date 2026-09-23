import time
from fastapi import Request

_COUNTS: dict[str, tuple[int, float]] = {}
_MAX_KEYS = 20000


def _evict(now: float, window_s: int) -> None:
    """Keep the map bounded: drop expired keys first, then the oldest ones.

    A key created by a spray of distinct values is fresh for its whole window, so
    purging expired keys alone never shrinks the map under attack.
    """
    for k in [k for k, (_, s) in _COUNTS.items() if now - s >= window_s]:
        _COUNTS.pop(k, None)
    overflow = len(_COUNTS) - _MAX_KEYS + 1
    if overflow > 0:
        oldest = sorted(_COUNTS, key=lambda k: _COUNTS[k][1])[:overflow]
        for k in oldest:
            _COUNTS.pop(k, None)


def check_limit(key: str, limit: int, window_s: int) -> tuple[bool, int]:
    now = time.time()
    if len(_COUNTS) >= _MAX_KEYS:
        _evict(now, window_s)
    if key in _COUNTS and now - _COUNTS[key][1] >= window_s:
        del _COUNTS[key]
    count, start = _COUNTS.get(key, (0, now))
    retry_after = max(0, int(start + window_s - now))
    if count < limit:
        _COUNTS[key] = (count + 1, start)
        return True, retry_after
    return False, retry_after


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else None) or "unknown"
