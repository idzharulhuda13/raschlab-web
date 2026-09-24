from unittest.mock import MagicMock
import pytest

import app.db
from app.config import settings


def test_get_engine_enables_pre_ping_and_recycle(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure serverless Postgres pooler drops stale connections after idle periods.
    captured_kwargs: dict[str, object] = {}

    def fake_create_engine(*args: object, **kwargs: object) -> MagicMock:
        captured_kwargs.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(app.db, "create_engine", fake_create_engine)
    monkeypatch.setattr(app.db, "_engine", None)
    monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@ep-demo.neon.tech/neondb")

    engine = app.db.get_engine()

    assert engine is not None
    assert captured_kwargs.get("pool_pre_ping") is True
    assert captured_kwargs.get("pool_recycle") == 300
