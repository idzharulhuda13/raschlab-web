import re
import sys
from sqlalchemy import select

import tests.conftest
import app.auth as auth_module
import app.config
import app.db as db_module
from app.config import settings
from app.db import SessionLocal
from app.main import app as fastapi_app
from app.models import EmailToken, SessionRow, User
from app.security import now_epoch

setattr(fastapi_app, "auth", auth_module)
setattr(fastapi_app, "db", db_module)

for k, v in list(sys.modules.items()):
    if v and getattr(v, "__file__", None) and "conftest.py" in str(v.__file__):
        setattr(v, "app", fastapi_app)

PASSWORD = "katasandi-tes-123"


def _extract_token(html: str, param: str) -> str:
    match = re.search(rf"/{param}\?token=([^\s\"'<>]+)", html)
    assert match is not None, f"Could not find token for {param} in html: {html}"
    return match.group(1)


def test_forgot_unknown_email_always_sent(client, sent_emails):
    response = client.post(
        "/forgot",
        data={"email": "nobody@example.test"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/forgot?msg=sent"
    assert len(sent_emails) == 0


def test_forgot_existing_email_issues_link(client, sent_emails):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    response = client.post(
        "/forgot",
        data={"email": "a@example.test"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/forgot?msg=sent"

    reset_emails = [e for e in sent_emails if "/reset?token=" in e[2]]
    assert len(reset_emails) == 1

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "a@example.test")).scalar_one()
        tokens = db.execute(
            select(EmailToken).where(
                EmailToken.user_id == user.id,
                EmailToken.purpose == "reset",
            )
        ).scalars().all()
        assert len(tokens) == 1
        assert tokens[0].used_at is None


def test_reset_happy_path_revokes_sessions(client, sent_emails):
    # register + verify
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    verify_token = _extract_token(sent_emails[0][2], "verify")
    client.get(f"/verify?token={verify_token}", follow_redirects=False)

    # login (session row exists)
    resp_login = client.post(
        "/login",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert resp_login.status_code == 303
    pre_reset_cookie = client.cookies.get("raschlab_sid")
    assert pre_reset_cookie is not None

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "a@example.test")).scalar_one()
        sessions = db.execute(
            select(SessionRow).where(SessionRow.user_id == user.id)
        ).scalars().all()
        assert len(sessions) == 1

    # POST /forgot to get reset token
    client.post(
        "/forgot",
        data={"email": "a@example.test"},
        follow_redirects=False,
    )
    reset_token = _extract_token(sent_emails[-1][2], "reset")

    # POST /reset token from email password baru-sandi-99 -> 303 /login?msg=reset_done
    resp_reset = client.post(
        "/reset",
        data={"token": reset_token, "password": "baru-sandi-99"},
        follow_redirects=False,
    )
    assert resp_reset.status_code == 303
    assert resp_reset.headers["location"] == "/login?msg=reset_done"

    # old password login -> 200 with "Email atau password salah."
    resp_old = client.post(
        "/login",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert resp_old.status_code == 200
    assert "Email atau password salah." in resp_old.text

    # new password login -> 303
    resp_new = client.post(
        "/login",
        data={"email": "a@example.test", "password": "baru-sandi-99"},
        follow_redirects=False,
    )
    assert resp_new.status_code == 303

    # the pre-reset session cookie GET /account -> 303 /login
    client.cookies.set("raschlab_sid", pre_reset_cookie)
    resp_acc = client.get("/account", follow_redirects=False)
    assert resp_acc.status_code == 303
    assert resp_acc.headers["location"] == "/login"


def test_reset_token_single_use(client, sent_emails):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    client.post(
        "/forgot",
        data={"email": "a@example.test"},
        follow_redirects=False,
    )
    reset_token = _extract_token(sent_emails[-1][2], "reset")

    r1 = client.post(
        "/reset",
        data={"token": reset_token, "password": "baru-sandi-99"},
        follow_redirects=False,
    )
    assert r1.status_code == 303
    assert r1.headers["location"] == "/login?msg=reset_done"

    r2 = client.post(
        "/reset",
        data={"token": reset_token, "password": "baru-sandi-99"},
        follow_redirects=False,
    )
    assert r2.status_code == 303
    assert r2.headers["location"] == "/forgot?msg=token_bad"


def test_reset_expired_token(client, sent_emails):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    client.post(
        "/forgot",
        data={"email": "a@example.test"},
        follow_redirects=False,
    )
    reset_token = _extract_token(sent_emails[-1][2], "reset")

    with SessionLocal() as db:
        token_row = db.execute(
            select(EmailToken).where(EmailToken.purpose == "reset")
        ).scalar_one()
        token_row.expires_at = now_epoch() - 1
        db.commit()

    resp = client.get(f"/reset?token={reset_token}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/forgot?msg=token_bad"


def test_reset_weak_password_does_not_consume(client, sent_emails):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    client.post(
        "/forgot",
        data={"email": "a@example.test"},
        follow_redirects=False,
    )
    reset_token = _extract_token(sent_emails[-1][2], "reset")

    resp_weak = client.post(
        "/reset",
        data={"token": reset_token, "password": "abc"},
        follow_redirects=False,
    )
    assert resp_weak.status_code == 200
    assert "Password minimal 10 karakter." in resp_weak.text

    with SessionLocal() as db:
        token_row = db.execute(
            select(EmailToken).where(EmailToken.purpose == "reset")
        ).scalar_one()
        assert token_row.used_at is None

    resp_valid = client.post(
        "/reset",
        data={"token": reset_token, "password": "baru-sandi-99"},
        follow_redirects=False,
    )
    assert resp_valid.status_code == 303
    assert resp_valid.headers["location"] == "/login?msg=reset_done"


def test_resend_reissues(client, sent_emails):
    # register unverified
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    old_token = _extract_token(sent_emails[0][2], "verify")

    with SessionLocal() as db:
        tokens_before = db.execute(
            select(EmailToken).where(EmailToken.purpose == "verify")
        ).scalars().all()
        assert len(tokens_before) == 1

    # POST /resend email=... -> 303 /login?msg=resent and a NEW verify token row
    resp_resend = client.post(
        "/resend",
        data={"email": "a@example.test"},
        follow_redirects=False,
    )
    assert resp_resend.status_code == 303
    assert resp_resend.headers["location"] == "/login?msg=resent"

    with SessionLocal() as db:
        tokens_after = db.execute(
            select(EmailToken).where(EmailToken.purpose == "verify")
        ).scalars().all()
        assert len(tokens_after) == 2

    # old token no longer verifies
    resp_old = client.get(f"/verify?token={old_token}", follow_redirects=False)
    assert resp_old.status_code == 303
    assert resp_old.headers["location"] == "/login?msg=verify_failed"


def test_gate_closed_redirects_register_and_login(client, monkeypatch):
    monkeypatch.setattr(app.config.settings, "gate_open", False)

    r_reg = client.get("/register", follow_redirects=False)
    assert r_reg.status_code == 303
    assert r_reg.headers["location"] == "/"

    r_login = client.get("/login", follow_redirects=False)
    assert r_login.status_code == 303
    assert r_login.headers["location"] == "/"

    r_verify = client.get("/verify?token=x", follow_redirects=False)
    assert r_verify.status_code == 303
    assert r_verify.headers["location"] == "/login?msg=verify_failed"


def test_f0_health_contract_intact_under_f1(client, monkeypatch):
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert set(r_health.json().keys()) == {"status", "version", "commit"}

    monkeypatch.setattr(app.db.settings, "database_url", None)
    app.db._engine = None

    r_db = client.get("/health/db")
    assert r_db.status_code == 200
    assert r_db.json() == {"db": "unconfigured"}


def test_no_em_dash_in_any_auth_page(client):
    r_register = client.get("/register")
    assert r_register.status_code == 200
    assert "—" not in r_register.text

    r_login = client.get("/login")
    assert r_login.status_code == 200
    assert "—" not in r_login.text
