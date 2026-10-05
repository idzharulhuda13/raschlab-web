import time
from fastapi import Request

_COUNTS: dict[str, tuple[int, float]] = {}
_MAX_KEYS = 20000
# No window in this app is longer than an hour, so an entry older than that is dead for
# every caller and can be dropped without giving anyone a fresh quota.
_MAX_WINDOW_S = 3600


def _purge_expired(now: float) -> None:
    """Drop entries that are dead for every window in use; never drop a live one.

    Calling this with a single caller's window would delete entries another caller still
    counts on, which is exactly the reset this module must not allow.
    """
    for k in [k for k, (_, s) in _COUNTS.items() if now - s >= _MAX_WINDOW_S]:
        _COUNTS.pop(k, None)


def check_limit(key: str, limit: int, window_s: int) -> tuple[bool, int]:
    now = time.time()
    if len(_COUNTS) >= _MAX_KEYS:
        _purge_expired(now)
    entry = _COUNTS.get(key)
    if entry is not None and now - entry[1] >= window_s:
        del _COUNTS[key]
        entry = None
    if entry is None and len(_COUNTS) >= _MAX_KEYS:
        # The map is full of live keys, which means someone is spraying distinct keys.
        # Refuse the newcomer instead of evicting the oldest live key: evicting it would
        # hand that key a fresh quota and let the spray reset what it is escaping.
        return False, window_s
    count, start = entry if entry is not None else (0, now)
    retry_after = max(0, int(start + window_s - now))
    if count < limit:
        _COUNTS[key] = (count + 1, start)
        return True, retry_after
    return False, retry_after


def client_ip(request: Request) -> str:
    """Resolve the caller from a hop the platform appended, never from a client header.

    Nothing in front of this service sets CF-Connecting-IP, so that header carries no
    authority and is ignored outright. The leftmost X-Forwarded-For entry is client
    supplied for the same reason. The platform front end appends the address it saw, so
    the rightmost X-Forwarded-For entry is the one to trust; with no forwarding header at
    all the socket peer is the only truth.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        hops = [hop.strip() for hop in xff.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return (request.client.host if request.client else None) or "unknown"
