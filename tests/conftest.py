import sys
import types
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.db
from app.config import settings
from app.main import app
from app.models import Base
from app.ratelimit import _COUNTS

try:
    import app.auth
except ImportError:
    from app.emailer import send_email

    auth_mod = types.ModuleType("app.auth")
    auth_mod.send_email = send_email
    sys.modules["app.auth"] = auth_mod
    import app
    app.auth = auth_mod


@pytest.fixture(autouse=True)
def reset_env(monkeypatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(settings, "database_url", "sqlite:///" + str(db_file))
    monkeypatch.setattr(settings, "gate_open", True)
    monkeypatch.setattr(settings, "resend_api_key", "re_test_dummy")
    monkeypatch.setattr(settings, "app_base_url", "https://testserver")

    app.db._engine = None
    app.db._session_factory = None

    engine = app.db.get_engine()
    Base.metadata.create_all(engine)
    _COUNTS.clear()

    yield

    if engine is not None:
        engine.dispose()
    app.db._engine = None
    app.db._session_factory = None


@pytest.fixture
def client(reset_env):
    return TestClient(app, base_url="https://testserver")


_sent_emails: list[tuple[str, str, str]] = []


@pytest.fixture
def sent_emails():
    return _sent_emails


@pytest.fixture(autouse=True)
def capture_emails(monkeypatch):
    _sent_emails.clear()

    def fake_send_email(to: str, subject: str, html: str, *args: Any, **kwargs: Any) -> None:
        _sent_emails.append((to, subject, html))
        return None

    monkeypatch.setattr(app.auth, "send_email", fake_send_email)
