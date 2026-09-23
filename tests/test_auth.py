import re
from fastapi.testclient import TestClient
from sqlalchemy import select

import tests.conftest
import app.auth as auth_module
from app.db import SessionLocal
from app.emailer import EmailSendError
from app.main import app as fastapi_app
from app.models import EmailToken, SessionRow, User
from app.security import now_epoch

import app.db as db_module

setattr(fastapi_app, "auth", auth_module)
setattr(fastapi_app, "db", db_module)

import sys
for k, v in list(sys.modules.items()):
    if v and getattr(v, "__file__", None) and "conftest.py" in str(v.__file__):
        setattr(v, "app", fastapi_app)

PASSWORD = "katasandi-tes-123"


def _extract_verify_path(html: str) -> str:
    match = re.search(r"(/verify\?token=[^\s\"'<>]+)", html)
    assert match is not None, f"Could not find verify link in html: {html}"
    return match.group(1)


def _extract_token(html: str) -> str:
    match = re.search(r"/verify\?token=([^\s\"'<>]+)", html)
    assert match is not None, f"Could not find verify token in html: {html}"
    return match.group(1)


def test_register_creates_user_with_argon2id_hash(client, sent_emails):
    response = client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/register?msg=")
    assert "sent" in response.headers["location"]

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "a@example.test")).scalar_one()
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash

        tokens = db.execute(select(EmailToken).where(EmailToken.user_id == user.id)).scalars().all()
        assert len(tokens) == 1
        assert tokens[0].purpose == "verify"

    assert len(sent_emails) == 1
    to, subject, html = sent_emails[0]
    assert "/verify?token=" in html


def test_register_rejects_short_password(client):
    response = client.post(
        "/register",
        data={"email": "a@example.test", "password": "abc"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Password minimal 10 karakter." in response.text

    with SessionLocal() as db:
        users = db.execute(select(User)).scalars().all()
        assert len(users) == 0


def test_register_rejects_invalid_email(client):
    response = client.post(
        "/register",
        data={"email": "notanemail", "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Email tidak valid." in response.text

    with SessionLocal() as db:
        users = db.execute(select(User)).scalars().all()
        assert len(users) == 0


def test_register_duplicate_verified_email(client):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "a@example.test")).scalar_one()
        user.verified_at = now_epoch()
        db.commit()

    response = client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Email sudah terdaftar. Silakan masuk atau reset password." in response.text

    with SessionLocal() as db:
        users = db.execute(select(User)).scalars().all()
        assert len(users) == 1


def test_register_duplicate_unverified_reissues_token(client, sent_emails):
    r1 = client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert r1.status_code == 303
    assert len(sent_emails) == 1
    token1 = _extract_token(sent_emails[0][2])

    r2 = client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert r2.status_code == 303
    assert "msg=sent" in r2.headers["location"]
    assert len(sent_emails) == 2
    token2 = _extract_token(sent_emails[1][2])

    r_old = client.get(f"/verify?token={token1}", follow_redirects=False)
    assert r_old.status_code == 303
    assert r_old.headers["location"] == "/login?msg=verify_failed"

    r_new = client.get(f"/verify?token={token2}", follow_redirects=False)
    assert r_new.status_code == 303
    assert r_new.headers["location"] == "/login?msg=verified"


def test_register_send_failure(client, monkeypatch):
    def fail_send(*args, **kwargs):
        raise EmailSendError("Failed to send verification email")

    monkeypatch.setattr(auth_module, "send_email", fail_send)

    response = client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/register?msg=send_failed"

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "a@example.test")).scalar_one_or_none()
        assert user is not None
        assert user.verified_at is None


def test_verify_valid(client, sent_emails):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert len(sent_emails) == 1
    verify_path = _extract_verify_path(sent_emails[0][2])

    response = client.get(verify_path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?msg=verified"

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "a@example.test")).scalar_one()
        assert user.verified_at is not None
        token = db.execute(select(EmailToken).where(EmailToken.user_id == user.id)).scalar_one()
        assert token.used_at is not None


def test_verify_single_use(client, sent_emails):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert len(sent_emails) == 1
    verify_path = _extract_verify_path(sent_emails[0][2])

    r1 = client.get(verify_path, follow_redirects=False)
    assert r1.status_code == 303
    assert r1.headers["location"] == "/login?msg=verified"

    r2 = client.get(verify_path, follow_redirects=False)
    assert r2.status_code == 303
    assert r2.headers["location"] == "/login?msg=verify_failed"


def test_verify_expired(client, sent_emails):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert len(sent_emails) == 1
    verify_path = _extract_verify_path(sent_emails[0][2])

    with SessionLocal() as db:
        token = db.execute(select(EmailToken)).scalar_one()
        token.expires_at = now_epoch() - 1
        db.commit()

    response = client.get(verify_path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?msg=verify_failed"


def test_login_success_and_cookie_flags(client, sent_emails):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    verify_path = _extract_verify_path(sent_emails[0][2])
    client.get(verify_path, follow_redirects=False)

    response = client.post(
        "/login",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/account"

    set_cookie = response.headers.get("set-cookie", "")
    assert "raschlab_sid" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" in set_cookie

    r_account = client.get("/account")
    assert r_account.status_code == 200
    assert "a@example.test" in r_account.text


def test_login_wrong_password(client):
    response = client.post(
        "/login",
        data={"email": "a@example.test", "password": "wrong-password"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Email atau password salah." in response.text


def test_login_unverified_blocked(client):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )

    response = client.post(
        "/login",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Email belum diverifikasi." in response.text
    assert 'action="/resend"' in response.text


def test_login_rate_limit(client):
    email = "ratelimit@example.test"
    for _ in range(5):
        r = client.post(
            "/login",
            data={"email": email, "password": "wrong-password"},
            follow_redirects=False,
        )
        assert r.status_code == 200

    r6 = client.post(
        "/login",
        data={"email": email, "password": "wrong-password"},
        follow_redirects=False,
    )
    assert r6.status_code == 429
    assert "Retry-After" in r6.headers
    assert "Terlalu banyak percobaan. Coba lagi nanti." in r6.text


def test_logout_revokes(client, sent_emails):
    client.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    verify_path = _extract_verify_path(sent_emails[0][2])
    client.get(verify_path, follow_redirects=False)

    client.post(
        "/login",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    old_cookie = client.cookies.get("raschlab_sid")
    assert old_cookie is not None

    r_logout = client.post("/logout", follow_redirects=False)
    assert r_logout.status_code == 303
    assert r_logout.headers["location"] == "/"

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "a@example.test")).scalar_one()
        sessions = db.execute(select(SessionRow).where(SessionRow.user_id == user.id)).scalars().all()
        assert len(sessions) == 0

    client.cookies.set("raschlab_sid", old_cookie)
    r_acc = client.get("/account", follow_redirects=False)
    assert r_acc.status_code == 303
    assert r_acc.headers["location"] == "/login"


def test_isolation_two_accounts(sent_emails):
    client_a = TestClient(fastapi_app, base_url="https://testserver")
    client_b = TestClient(fastapi_app, base_url="https://testserver")

    client_a.post(
        "/register",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    token_a = _extract_token(sent_emails[0][2])
    client_a.get(f"/verify?token={token_a}", follow_redirects=False)
    client_a.post(
        "/login",
        data={"email": "a@example.test", "password": PASSWORD},
        follow_redirects=False,
    )

    client_b.post(
        "/register",
        data={"email": "b@example.test", "password": PASSWORD},
        follow_redirects=False,
    )
    token_b = _extract_token(sent_emails[1][2])
    client_b.get(f"/verify?token={token_b}", follow_redirects=False)
    client_b.post(
        "/login",
        data={"email": "b@example.test", "password": PASSWORD},
        follow_redirects=False,
    )

    resp_a = client_a.get("/account")
    assert resp_a.status_code == 200
    assert "a@example.test" in resp_a.text
    assert "b@example.test" not in resp_a.text

    resp_b = client_b.get("/account")
    assert resp_b.status_code == 200
    assert "b@example.test" in resp_b.text
    assert "a@example.test" not in resp_b.text


def test_account_requires_login(client):
    response = client.get("/account", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
