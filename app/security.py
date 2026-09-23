import hashlib
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError, VerificationError

__all__ = [
    "hash_password",
    "verify_password",
    "password_policy",
    "new_token",
    "hash_token",
    "now_epoch",
]

_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return bool(_hasher.verify(password_hash, password))
    except (VerificationError, InvalidHashError, Argon2Error):
        return False


def password_policy(password: str) -> bool:
    return 10 <= len(password) <= 128


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def now_epoch() -> int:
    return int(time.time())
