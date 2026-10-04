"""Integration tests for the share-link feature (F4 /app/share.py)."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.share
from app.auth import COOKIE_NAME
from app.config import settings
from app.db import SessionLocal
from app.explore import PAGE_NOT_FOUND_MSG
from app.export import TABLE_KEYS
from app.models import Analysis, AnalysisShare, Dataset, SessionRow, User
from app.security import hash_password, hash_token, new_token, now_epoch, verify_password

try:
    from test_explorer_routes import _build_standard_files, _seed_done
except ImportError:
    from tests.test_explorer_routes import _build_standard_files, _seed_done

PW_DEFAULT = "rahasia-1234"


def _csv(rows: list[list[str]]) -> str:
    return "\r\n".join(",".join(row) for row in rows) + "\r\n"


def _owner_and_analysis(
    client: TestClient,
    email: str = "owner@example.com",
    filename: str = "smoke.csv",
) -> tuple[int, int, int]:
    token = new_token()
    with SessionLocal() as db:
        user = User(
            email=email,
            email_normalized=email.lower().strip(),
            password_hash=hash_password("password-12345"),
            created_at=now_epoch(),
            verified_at=now_epoch(),
        )
        db.add(user)
        db.flush()
        db.add(
            SessionRow(
                user_id=user.id,
                token_hash=hash_token(token),
                created_at=now_epoch(),
                expires_at=now_epoch() + 3600,
            )
        )
        db.commit()
        uid = user.id
    client.cookies.set(COOKIE_NAME, token)

    files = _build_standard_files()
    import raschlab.report as report

    rows = [[*report.PERSON_HEADER_ROW_1, "NAME"], [*report.PERSON_HEADER_ROW_2, "NAME"]]
    for i in range(1, 11):
        row = ["0"] * len(report.PERSON_HEADER_ROW_2)
        row[0] = str(i)
        row[13] = f"SENTINEL-P-{i}"
        row[14], row[15], row[16], row[17] = str(i), "1.20", "misfit", "kept"
        rows.append([*row, f"SENTINEL-N-{i}"])
    files["person_table.csv"] = _csv(rows)
    aid = _seed_done(uid, filename, files)

    with SessionLocal() as db:
        analysis = db.scalar(select(Analysis).where(Analysis.id == aid))
        ds_id = analysis.dataset_id

    return uid, aid, ds_id


def _create_share_link(
    client: TestClient, aid: int, password: str = PW_DEFAULT
) -> tuple[str, str]:
    r = client.post(f"/analyses/{aid}/share", data={"password": password}, follow_redirects=False)
    assert r.status_code == 200, (r.status_code, r.text[:300])
    m = re.search(r"/s/([A-Za-z0-9_\-]+)", r.text)
    assert m, f"Share URL not found in response: {r.text[:300]}"
    token = m.group(1)
    return token, r.text


def test_create_returns_url_once_and_stores_only_hashes(client: TestClient) -> None:
    pw = "rahasia-1234"
    assert len(pw) == 12
    uid, aid, _ = _owner_and_analysis(client, email="owner1@example.com")

    r = client.post(f"/analyses/{aid}/share", data={"password": pw}, follow_redirects=False)
    assert r.status_code == 200
    expected_url_prefix = f"{settings.app_base_url}/s/"
    assert expected_url_prefix in r.text

    m = re.search(r"/s/([A-Za-z0-9_\-]+)", r.text)
    assert m
    raw_token = m.group(1)

    with SessionLocal() as db:
        row = db.scalar(select(AnalysisShare).where(AnalysisShare.analysis_id == aid))
        assert row is not None
        assert row.token_hash == hash_token(raw_token)
        assert verify_password(row.password_hash, pw)
        assert row.password_hash.startswith("$argon2")

        for col in (
            "id",
            "analysis_id",
            "user_id",
            "token_hash",
            "password_hash",
            "created_at",
            "expires_at",
            "revoked_at",
        ):
            val = str(getattr(row, col))
            assert raw_token not in val
            assert pw not in val


def test_second_create_revokes_the_first(client: TestClient) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner2@example.com")

    token1, _ = _create_share_link(client, aid, password="password-1234")
    token2, _ = _create_share_link(client, aid, password="password-5678")

    anon = TestClient(client.app, base_url="https://testserver")
    r1 = anon.get(f"/s/{token1}")
    assert r1.status_code == 404

    r2 = anon.get(f"/s/{token2}")
    assert r2.status_code == 200
    assert "Buka hasil" in r2.text


def test_revoke_and_non_owner(client: TestClient) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner3@example.com")
    token, _ = _create_share_link(client, aid, password="password-1234")

    anon = TestClient(client.app, base_url="https://testserver")
    assert anon.get(f"/s/{token}").status_code == 200

    rev = client.post(f"/analyses/{aid}/share/revoke", follow_redirects=False)
    assert rev.status_code == 303
    assert anon.get(f"/s/{token}").status_code == 404

    client_foreign = TestClient(client.app, base_url="https://testserver")
    _owner_and_analysis(client_foreign, email="foreign3@example.com")
    r_foreign_create = client_foreign.post(f"/analyses/{aid}/share", data={"password": "password-1234"})
    assert r_foreign_create.status_code == 404
    r_foreign_revoke = client_foreign.post(f"/analyses/{aid}/share/revoke")
    assert r_foreign_revoke.status_code == 404

    r_anon_create = anon.post(f"/analyses/{aid}/share", data={"password": "password-1234"})
    assert r_anon_create.status_code == 404
    r_anon_revoke = anon.post(f"/analyses/{aid}/share/revoke")
    assert r_anon_revoke.status_code == 404

    with SessionLocal() as db:
        aid_shares = db.scalars(select(AnalysisShare).where(AnalysisShare.analysis_id == aid)).all()
        assert len(aid_shares) == 1
        assert aid_shares[0].revoked_at is not None


def test_short_password_is_refused(client: TestClient) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner4@example.com")
    short_pw = "short-9c"
    assert len(short_pw) < 10

    r = client.post(f"/analyses/{aid}/share", data={"password": short_pw}, follow_redirects=False)
    assert r.status_code == 200
    assert "Password tautan minimal 10 karakter" in r.text

    with SessionLocal() as db:
        row = db.scalar(select(AnalysisShare).where(AnalysisShare.analysis_id == aid))
        assert row is None


def test_expiry_boundary_and_revocation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner5@example.com")
    pw = "password-1234"
    token, _ = _create_share_link(client, aid, password=pw)

    anon = TestClient(client.app, base_url="https://testserver")

    post_ok = anon.post(f"/s/{token}", data={"password": pw}, follow_redirects=False)
    assert post_ok.status_code == 303
    cookie_val = re.search(r"raschlab_share=([^;]+)", post_ok.headers.get("set-cookie", "")).group(1)

    with SessionLocal() as db:
        row = db.scalar(select(AnalysisShare).where(AnalysisShare.token_hash == hash_token(token)))
        expires_at = row.expires_at

    monkeypatch.setattr(app.share, "now_epoch", lambda: expires_at - 1)
    anon_no_cookie = TestClient(client.app, base_url="https://testserver")
    g_before = anon_no_cookie.get(f"/s/{token}")
    assert g_before.status_code == 200
    assert "Buka hasil" in g_before.text

    monkeypatch.setattr(app.share, "now_epoch", lambda: expires_at)
    anon_at_boundary = TestClient(client.app, base_url="https://testserver")
    assert anon_at_boundary.get(f"/s/{token}").status_code == 404

    monkeypatch.setattr(app.share, "now_epoch", lambda: expires_at + 1)
    g_after = anon_no_cookie.get(f"/s/{token}")
    assert g_after.status_code == 404

    p_after = anon_no_cookie.post(f"/s/{token}", data={"password": pw})
    assert p_after.status_code == 404

    anon_with_cookie = TestClient(client.app, base_url="https://testserver")
    anon_with_cookie.cookies.set("raschlab_share", cookie_val)
    c_after = anon_with_cookie.get(f"/s/{token}")
    assert c_after.status_code == 404


def test_unknown_token_is_404_not_403(client: TestClient) -> None:
    anon = TestClient(client.app, base_url="https://testserver")
    r = anon.get("/s/nonexistent-token-xyz-12345")
    assert r.status_code == 404
    data = json.loads(r.text)
    assert data["detail"] == PAGE_NOT_FOUND_MSG
    assert "SENTINEL" not in r.text
    assert "explorer-data" not in r.text


def test_gate_page_carries_no_data(client: TestClient) -> None:
    secret_fname = "confidential_dataset_xyz.csv"
    uid, aid, _ = _owner_and_analysis(client, email="owner7@example.com", filename=secret_fname)
    token, _ = _create_share_link(client, aid, password="password-1234")

    anon = TestClient(client.app, base_url="https://testserver")
    r = anon.get(f"/s/{token}")
    assert r.status_code == 200
    assert secret_fname not in r.text
    assert "SENTINEL" not in r.text
    assert "explorer-data" not in r.text


def test_wrong_password_renders_gate(client: TestClient) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner8@example.com")
    token, _ = _create_share_link(client, aid, password="password-1234")

    anon = TestClient(client.app, base_url="https://testserver")
    bad = anon.post(f"/s/{token}", data={"password": "wrong-password-guess"})
    assert bad.status_code == 200
    assert "Password salah" in bad.text
    assert "Set-Cookie" not in bad.headers
    assert "raschlab_share" not in str(bad.headers.get("set-cookie", ""))


def test_password_rate_limit(client: TestClient) -> None:
    uid1, aid1, _ = _owner_and_analysis(client, email="owner9a@example.com")
    token1, _ = _create_share_link(client, aid1, password="password-1234")

    uid2, aid2, _ = _owner_and_analysis(client, email="owner9b@example.com")
    token2, _ = _create_share_link(client, aid2, password="password-5678")

    anon = TestClient(client.app, base_url="https://testserver")

    for _ in range(10):
        r = anon.post(f"/s/{token1}", data={"password": "wrong-pw"})
        assert r.status_code == 200

    r11 = anon.post(f"/s/{token1}", data={"password": "wrong-pw"})
    assert r11.status_code == 429
    assert "Retry-After" in r11.headers
    assert int(r11.headers["Retry-After"]) > 0

    r2 = anon.post(f"/s/{token2}", data={"password": "wrong-pw"})
    assert r2.status_code == 200
    assert "Password salah" in r2.text


def test_cookie_flags_and_scope(client: TestClient) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner10@example.com")
    pw = "password-1234"
    token, _ = _create_share_link(client, aid, password=pw)

    anon = TestClient(client.app, base_url="https://testserver")
    ok = anon.post(f"/s/{token}", data={"password": pw}, follow_redirects=False)
    assert ok.status_code == 303
    set_cookie = ok.headers.get("set-cookie", "")

    assert "raschlab_share=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert f"Path=/s/{token}" in set_cookie

    cookie_val = re.search(r"raschlab_share=([^;]+)", set_cookie).group(1)
    with SessionLocal() as db:
        row = db.scalar(select(AnalysisShare).where(AnalysisShare.token_hash == hash_token(token)))
        assert row is not None
        assert cookie_val != row.token_hash


def test_all_views_and_fragments_hide_identity(client: TestClient) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner11@example.com")
    pw = "password-1234"
    token, _ = _create_share_link(client, aid, password=pw)

    anon = TestClient(client.app, base_url="https://testserver")
    ok = anon.post(f"/s/{token}", data={"password": pw}, follow_redirects=False)
    assert ok.status_code == 303

    views = ("wright", "butir", "partisipan", "ringkasan", "opsi", "subsubtes", "tabulasi", "bandingkan")
    assert len(views) == 8
    for view in views:
        v = anon.get(f"/s/{token}?view={view}")
        assert v.status_code == 200, f"view {view} failed: {v.status_code}"
        assert "SENTINEL-P-" not in v.text, f"view {view} leaked SENTINEL-P-"
        assert "SENTINEL-N-" not in v.text, f"view {view} leaked SENTINEL-N-"

    fragments = ("butir", "partisipan", "ringkasan", "opsi", "subsubtes", "tabulasi", "bandingkan")
    assert len(fragments) == 7
    for frag in fragments:
        fr = anon.get(f"/s/{token}?fragment={frag}")
        assert fr.status_code == 200, f"fragment {frag} failed: {fr.status_code}"
        assert "SENTINEL-P-" not in fr.text, f"fragment {frag} leaked SENTINEL-P-"
        assert "SENTINEL-N-" not in fr.text, f"fragment {frag} leaked SENTINEL-N-"

    part = anon.get(f"/s/{token}?view=partisipan")
    assert part.status_code == 200
    assert ">PERSON<" not in part.text
    assert ">NAME<" not in part.text
    assert "RANK" in part.text
    assert part.text.count('class="th-sort"') == 5
    assert 'data-sort="text"' not in part.text

    q_resp = anon.get(f"/s/{token}?view=partisipan&q_person=SENTINEL-P-1")
    assert q_resp.status_code == 200
    assert 'id="partisipan-empty"' in q_resp.text
    assert "Tidak ada baris yang cocok" in q_resp.text
    assert 'data-explorer-table="1"' not in q_resp.text


def test_share_cookie_cannot_reach_owner_routes(client: TestClient) -> None:
    uid, aid, ds_id = _owner_and_analysis(client, email="owner12@example.com")
    pw = "password-1234"
    token, _ = _create_share_link(client, aid, password=pw)

    anon = TestClient(client.app, base_url="https://testserver")
    ok = anon.post(f"/s/{token}", data={"password": pw}, follow_redirects=False)
    cookie_val = re.search(r"raschlab_share=([^;]+)", ok.headers.get("set-cookie", "")).group(1)
    crafted = {"Cookie": f"raschlab_share={cookie_val}"}

    all_table_keys = sorted(set(TABLE_KEYS.keys()) | {"semua", "bandingkan"})
    for key in all_table_keys:
        resp = anon.get(f"/analyses/{aid}/export?table={key}", headers=crafted)
        assert resp.status_code == 404, f"Export key {key} returned {resp.status_code}"

    assert anon.get(f"/analyses/{aid}/export", headers=crafted).status_code == 404
    assert anon.get(f"/analyses/{aid}/explore", headers=crafted).status_code == 404
    assert anon.get("/analyses", headers=crafted).status_code == 404
    assert anon.get("/datasets", headers=crafted).status_code == 404
    assert anon.get(f"/datasets/{ds_id}", headers=crafted).status_code == 404
    assert anon.get("/account", headers=crafted).status_code == 404

    assert anon.get(f"/s/{token}", headers=crafted).status_code == 200
    assert anon.get("/static/app.css", headers=crafted).status_code == 200


def test_cookie_path_scope_keeps_it_off_owner_paths(client: TestClient) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner13@example.com")
    pw = "password-1234"
    token, _ = _create_share_link(client, aid, password=pw)

    anon = TestClient(client.app, base_url="https://testserver")
    ok = anon.post(f"/s/{token}", data={"password": pw}, follow_redirects=False)
    assert ok.status_code == 303

    r_analyses = anon.get("/analyses", follow_redirects=False)
    assert r_analyses.status_code == 303
    assert r_analyses.headers["location"].startswith("/login")

    r_datasets = anon.get("/datasets", follow_redirects=False)
    assert r_datasets.status_code == 303
    assert r_datasets.headers["location"].startswith("/login")

    r_login = anon.get("/login")
    assert r_login.status_code == 200
    assert "SENTINEL" not in r_login.text


def test_owner_plus_share_cookies_still_reach_owner_pages(client: TestClient) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner14@example.com")
    pw = "password-1234"
    token, _ = _create_share_link(client, aid, password=pw)

    with SessionLocal() as db:
        row = db.scalar(select(AnalysisShare).where(AnalysisShare.token_hash == hash_token(token)))
        share_cookie = app.share.share_cookie_value(row)

    client.cookies.set("raschlab_share", share_cookie)

    r = client.get("/analyses")
    assert r.status_code == 200


def test_shared_html_has_no_owner_links(client: TestClient) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner15@example.com")
    pw = "password-1234"
    token, _ = _create_share_link(client, aid, password=pw)

    anon = TestClient(client.app, base_url="https://testserver")
    ok = anon.post(f"/s/{token}", data={"password": pw}, follow_redirects=False)
    assert ok.status_code == 303

    dash = anon.get(f"/s/{token}")
    assert dash.status_code == 200
    part = anon.get(f"/s/{token}?view=partisipan")
    assert part.status_code == 200

    combined_html = dash.text + part.text
    hrefs = re.findall(r'href=["\']([^"\']*)["\']', combined_html)
    actions = re.findall(r'action=["\']([^"\']*)["\']', combined_html)

    banned_prefixes = ("/export", "/datasets", "/analyses", "/account", "/login", "/logout")
    for banned in banned_prefixes:
        for h in hrefs:
            assert banned not in h, f"Found banned href '{h}' on shared page"
        for a in actions:
            assert banned not in a, f"Found banned action '{a}' on shared page"

    assert len(actions) > 0
    for a in actions:
        assert a == "" or a.startswith(f"/s/{token}"), f"Form action '{a}' does not post to share path"


def test_no_token_or_password_in_logs(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    pw = "secret-pass-99"
    uid, aid, _ = _owner_and_analysis(client, email="owner16@example.com")

    token, _ = _create_share_link(client, aid, password=pw)
    anon = TestClient(client.app, base_url="https://testserver")

    anon.post(f"/s/{token}", data={"password": "wrong-secret-99"})
    anon.post(f"/s/{token}", data={"password": pw})
    anon.get(f"/s/{token}")
    client.post(f"/analyses/{aid}/share/revoke")

    log_text = caplog.text
    assert pw not in log_text, "Password leaked in captured logs"
    assert token not in log_text, "Raw token leaked in captured logs"


def test_hardening_headers(client: TestClient) -> None:
    uid, aid, _ = _owner_and_analysis(client, email="owner17@example.com")
    pw = "password-1234"
    token, _ = _create_share_link(client, aid, password=pw)

    anon = TestClient(client.app, base_url="https://testserver")

    gate_resp = anon.get(f"/s/{token}")
    assert gate_resp.status_code == 200
    assert gate_resp.headers.get("referrer-policy") == "no-referrer"
    assert gate_resp.headers.get("cache-control") == "no-store"
    assert gate_resp.headers.get("x-robots-tag") == "noindex"

    auth_post = anon.post(f"/s/{token}", data={"password": pw}, follow_redirects=False)
    assert auth_post.headers.get("referrer-policy") == "no-referrer"
    assert auth_post.headers.get("cache-control") == "no-store"
    assert auth_post.headers.get("x-robots-tag") == "noindex"

    dash_resp = anon.get(f"/s/{token}")
    assert dash_resp.status_code == 200
    assert dash_resp.headers.get("referrer-policy") == "no-referrer"
    assert dash_resp.headers.get("cache-control") == "no-store"
    assert dash_resp.headers.get("x-robots-tag") == "noindex"


def test_owner_person_table_keeps_the_person_sort_control(client: TestClient) -> None:
    """The owner table must still offer a text sort on PERSON (regression guard)."""
    uid, aid, _ = _owner_and_analysis(client, email="owner18@example.com")
    page = client.get(f"/analyses/{aid}/explore?view=partisipan")
    assert page.status_code == 200
    assert ">PERSON<" in page.text or "PERSON</button>" in page.text, "the owner PERSON header cell is gone"
    assert 'data-sort="text"' in page.text, "the owner PERSON sort control lost its text sort type"
    # exactly one text-sort control (PERSON); the numeric ones stay numeric
    assert page.text.count('data-sort="text"') == 1
    assert page.text.count('class="th-sort"') == 6


def test_render_failure_is_hardened_and_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-HTTPException render error must still carry the share hardening headers, and must be logged."""
    uid, aid, _ = _owner_and_analysis(client, email="owner19@example.com")
    token, _ = _create_share_link(client, aid, password="password-1234")

    with SessionLocal() as db:
        row = db.scalar(select(Analysis).where(Analysis.id == aid))
        row.params_json = "{not valid json"
        db.commit()

    anon = TestClient(client.app, base_url="https://testserver")
    anon.post(f"/s/{token}", data={"password": "password-1234"}, follow_redirects=False)

    caplog.set_level(logging.ERROR)
    r = anon.get(f"/s/{token}")
    assert r.status_code == 500, r.status_code
    assert r.headers.get("cache-control") == "no-store"
    assert r.headers.get("referrer-policy") == "no-referrer"
    assert r.headers.get("x-robots-tag") == "noindex"
    assert "Terjadi kesalahan" in r.text
    assert "params_json" in caplog.text or "JSONDecodeError" in caplog.text or "share render failed" in caplog.text

