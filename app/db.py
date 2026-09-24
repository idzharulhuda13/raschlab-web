from collections.abc import Generator
from typing import Any
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _normalize(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_engine() -> Engine | None:
    global _engine
    if _engine is None and settings.database_url:
        _engine = create_engine(
            _normalize(settings.database_url),
            pool_pre_ping=True,
            pool_recycle=300,
        )
    return _engine


def SessionLocal() -> Session:
    global _session_factory
    engine = get_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is not configured")
    if _session_factory is None:
        _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _session_factory()


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_db() -> tuple[str, str | None]:
    if not settings.database_url:
        return ("unconfigured", None)
    try:
        engine = get_engine()
        if engine is None:
            return ("unconfigured", None)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return ("ok", None)
    except Exception as exc:
        return ("error", str(exc))


def __getattr__(name: str) -> Any:
    if name == "engine":
        return get_engine()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
