"""Compressed raw bytes storage abstraction.

The raw uploaded bytes are the single source of truth for all dataset
derivatives and downstream parsers. All raw-byte read/write operations stay
confined to this module so replacing Postgres bytea persistence with an
external object store (e.g., GCS) is a pluggable swap that avoids touching
ingestion routes or parsing logic (PLAN.md D1).
"""

import gzip

__all__ = [
    "MAX_UPLOAD_BYTES",
    "MAX_CELLS",
    "StorageError",
    "compress",
    "decompress",
]

# 16 MiB per-file upload cap keeps Neon storage within bounds and prevents memory exhaustion.
MAX_UPLOAD_BYTES: int = 16 * 1024 * 1024

# 6,000,000 cells ceiling: the instance is 2 GiB at concurrency 1, and the measured peak for
# a 45.833-person matrix is 0,31 GiB at 0,69 M cells, 0,70 GiB at 2,29 M, 0,71 GiB at 2,52 M,
# 0,83 GiB at 2,98 M and 0,94 GiB at 3,90 M. Memory, not time, sets the ceiling: the engine
# needs 11 s at 3,9 M cells against a 120 s request timeout. 6 M lands near 1,4 GiB, leaving
# ~30% headroom. Raising this again means raising the instance memory in deploy_ui.sh first.
MAX_CELLS: int = 6_000_000


class StorageError(Exception):
    """Raised when raw payload size violates configured storage caps."""


def compress(raw: bytes) -> bytes:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise StorageError(
            f"Payload size {len(raw)} bytes exceeds MAX_UPLOAD_BYTES ({MAX_UPLOAD_BYTES} bytes)"
        )
    # mtime=0 ensures deterministic byte output for identical raw inputs.
    return gzip.compress(raw, mtime=0.0)


def decompress(blob: bytes) -> bytes:
    if len(blob) > MAX_UPLOAD_BYTES:
        raise StorageError(
            f"Stored blob size {len(blob)} bytes exceeds MAX_UPLOAD_BYTES ({MAX_UPLOAD_BYTES} bytes)"
        )
    raw = gzip.decompress(blob)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise StorageError(
            f"Decompressed payload size {len(raw)} bytes exceeds MAX_UPLOAD_BYTES ({MAX_UPLOAD_BYTES} bytes)"
        )
    return raw