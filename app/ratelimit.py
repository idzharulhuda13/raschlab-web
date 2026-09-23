import time
from fastapi import Request

_COUNTS: dict[str, tuple[int, float]] = {}


def check_limit(key: str, limit: int, window_s: int) -> tuple[bool, int]:
    now = time.time()
    if len(_COUNTS) > 10000:
        for k in [k for k, (_, s) in _COUNTS.items() if now - s >= window_s]:
            _COUNTS.pop(k, None)
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
