"""Tiny distributed lock helpers on top of the Django cache (Redis in production).

``cache.add`` is atomic in Redis and LocMem, which is all we need to avoid
running the same task twice.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.core.cache import cache


def acquire(key: str, ttl: int) -> bool:
    return bool(cache.add(f"lock:{key}", 1, ttl))


def release(key: str) -> None:
    cache.delete(f"lock:{key}")


@contextmanager
def lock(key: str, ttl: int) -> Iterator[bool]:
    got = acquire(key, ttl)
    try:
        yield got
    finally:
        if got:
            release(key)
