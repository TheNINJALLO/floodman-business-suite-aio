from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from .config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=1800,
        future=True,
    )


@contextmanager
def transaction() -> Iterator[Connection]:
    with get_engine().begin() as connection:
        yield connection


def database_ready() -> bool:
    """Return true only when the fresh v3 baseline exists.

    v3 intentionally has no runtime migration container. PostgreSQL creates the
    complete schema from docker-entrypoint-initdb.d when the new volume is first
    initialized, and every application waits for this marker.
    """
    try:
        with get_engine().connect() as connection:
            version = connection.execute(
                text("SELECT baseline_version FROM floodman_schema_info WHERE singleton=true")
            ).scalar_one_or_none()
        return version == "3.0.0"
    except Exception:
        return False
