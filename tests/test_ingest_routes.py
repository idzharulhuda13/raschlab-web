import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import COOKIE_NAME
from app.config import settings
from app.db import SessionLocal
from app.models import Dataset, SessionRow, User
from app.security import hash_password, hash_token, new_token, now_epoch
from app.storage import MAX_UPLOAD_BYTES, decompress

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _create_authenticated_user(client: TestClient, email: str = "researcher@example.test") -> int:
    with SessionLocal() as db:
        now = now_epoch()
        user = User(
            email=email,
            email_normalized=email.lower().strip(),
            password_hash=hash_password("katasandi-ingest-123"),
            created_at=now,
            verified_at=now,
        )
        db.add(user)
        db.commit()
        user_id = user.id

        token = new_token()
        session_row = SessionRow(
            user_id=user_id,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=now + 86400 * 30,
        )
        db.add(session_row)
        db.commit()

    client.cookies.set(COOKIE_NAME, token)
    return user_id


def test_gate_closed_redirects_datasets(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "gate_open", False)
    response = client.get("/datasets", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_anonymous_get_datasets_redirects_to_login(client: TestClient):
    response = client.get("/datasets", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_upload_csv_preview_and_decompressed_bytes_roundtrip(client: TestClient):
    user_id = _create_authenticated_user(client)
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()

    response = client.post(
        "/datasets",
        files={"data": ("sample_300x40.csv", csv_bytes, "text/csv")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/datasets/")
    dataset_id = int(location.split("/")[-1])

    detail_response = client.get(location)
    assert detail_response.status_code == 200
    html = detail_response.text
    assert "300 resp x 40 butir" in html
    assert "413" in html

    with SessionLocal() as db:
        row = db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one()
        assert row.user_id == user_id
        assert row.n_persons == 300
        assert row.n_items == 40
        assert row.status == "staged"
        assert row.committed_at is None
        assert decompress(row.raw_gzip) == csv_bytes


def test_commit_with_unassigned_token_is_blocked(client: TestClient):
    _create_authenticated_user(client)
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()

    upload_resp = client.post(
        "/datasets",
        files={"data": ("sample_300x40.csv", csv_bytes, "text/csv")},
        follow_redirects=False,
    )
    dataset_id = int(upload_resp.headers["location"].split("/")[-1])

    # Omit tokens 'NA' and '' so they remain unassigned
    commit_resp = client.post(
        f"/datasets/{dataset_id}/commit",
        data={"t0": "1", "m0": "correct", "t1": "0", "m1": "incorrect"},
        follow_redirects=False,
    )
    assert commit_resp.status_code == 422
    assert "Ada token yang belum dipetakan" in commit_resp.text

    with SessionLocal() as db:
        row = db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one()
        assert row.status == "staged"
        assert row.committed_at is None


def test_commit_with_complete_mapping_flips_to_ready(client: TestClient):
    _create_authenticated_user(client)
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()

    upload_resp = client.post(
        "/datasets",
        files={"data": ("sample_300x40.csv", csv_bytes, "text/csv")},
        follow_redirects=False,
    )
    dataset_id = int(upload_resp.headers["location"].split("/")[-1])

    commit_resp = client.post(
        f"/datasets/{dataset_id}/commit",
        data={
            "t0": "1",
            "m0": "correct",
            "t1": "0",
            "m1": "incorrect",
            "t2": "NA",
            "m2": "missing",
            "t3": "",
            "m3": "missing",
        },
        follow_redirects=False,
    )
    assert commit_resp.status_code == 303
    assert commit_resp.headers["location"] == f"/datasets/{dataset_id}"

    with SessionLocal() as db:
        row = db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one()
        assert row.status == "ready"
        assert row.committed_at is not None
        assert row.committed_at > 0


def test_winsteps_pair_upload_shows_expected_dimensions(client: TestClient):
    _create_authenticated_user(client)
    prn_bytes = (FIXTURES_DIR / "sample_winsteps.prn").read_bytes()
    con_bytes = (FIXTURES_DIR / "sample_winsteps.CON").read_bytes()

    response = client.post(
        "/datasets",
        files={
            "data": ("sample_winsteps.prn", prn_bytes, "text/plain"),
            "con": ("sample_winsteps.CON", con_bytes, "text/plain"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    dataset_id = int(location.split("/")[-1])

    detail_response = client.get(location)
    assert detail_response.status_code == 200
    assert "60 resp x 20 butir" in detail_response.text

    with SessionLocal() as db:
        row = db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one()
        assert row.n_persons == 60
        assert row.n_items == 20
        assert row.kind == "winsteps"
        assert row.format == "prn"


def test_discard_dataset_removes_row_from_database(client: TestClient):
    _create_authenticated_user(client)
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()

    upload_resp = client.post(
        "/datasets",
        files={"data": ("sample_300x40.csv", csv_bytes, "text/csv")},
        follow_redirects=False,
    )
    dataset_id = int(upload_resp.headers["location"].split("/")[-1])

    discard_resp = client.post(f"/datasets/{dataset_id}/discard", follow_redirects=False)
    assert discard_resp.status_code == 303
    assert discard_resp.headers["location"] == "/datasets"

    with SessionLocal() as db:
        row = db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one_or_none()
        assert row is None


def test_second_user_accessing_dataset_returns_404(client: TestClient):
    _create_authenticated_user(client, email="user1@example.test")
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()

    upload_resp = client.post(
        "/datasets",
        files={"data": ("sample_300x40.csv", csv_bytes, "text/csv")},
        follow_redirects=False,
    )
    dataset_id = int(upload_resp.headers["location"].split("/")[-1])

    _create_authenticated_user(client, email="user2@example.test")
    detail_resp = client.get(f"/datasets/{dataset_id}")
    assert detail_resp.status_code == 404


def test_oversize_upload_renders_error_and_writes_zero_rows(client: TestClient):
    _create_authenticated_user(client)
    oversize_bytes = b"0" * (MAX_UPLOAD_BYTES + 1)

    response = client.post(
        "/datasets",
        files={"data": ("oversize.csv", oversize_bytes, "text/csv")},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Ukuran berkas melebihi batas maksimal 16 MB." in response.text

    with SessionLocal() as db:
        count = db.execute(select(func.count(Dataset.id))).scalar()
        assert count == 0


def test_read_upload_bounded_stops_reading_after_limit():
    from app.ingest import CHUNK_SIZE, _read_upload_bounded
    from app.storage import StorageError

    class FakeUpload:
        def __init__(self, total_bytes: int):
            self.total_bytes = total_bytes
            self.bytes_asked = 0
            self.bytes_read = 0

        async def read(self, n: int = -1) -> bytes:
            if self.bytes_read >= self.total_bytes:
                return b""
            chunk_len = min(n if n > 0 else self.total_bytes, self.total_bytes - self.bytes_read)
            self.bytes_asked += n
            self.bytes_read += chunk_len
            return b"x" * chunk_len

    async def _run():
        limit = 2 * 1024 * 1024
        fake = FakeUpload(total_bytes=10 * 1024 * 1024)
        with pytest.raises(StorageError) as exc_info:
            await _read_upload_bounded(fake, max_bytes=limit)
        assert "Ukuran berkas melebihi batas maksimal" in str(exc_info.value)
        assert fake.bytes_read <= limit + CHUNK_SIZE
        assert fake.bytes_asked <= limit + CHUNK_SIZE

    asyncio.run(_run())


def test_oversize_con_upload_renders_error_and_writes_zero_rows(client: TestClient):
    _create_authenticated_user(client)
    prn_bytes = (FIXTURES_DIR / "sample_winsteps.prn").read_bytes()
    oversize_bytes = b"0" * (MAX_UPLOAD_BYTES + 1)

    response = client.post(
        "/datasets",
        files={
            "data": ("sample.prn", prn_bytes, "text/plain"),
            "con": ("oversize.CON", oversize_bytes, "text/plain"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Ukuran berkas melebihi batas maksimal 16 MB." in response.text

    with SessionLocal() as db:
        count = db.execute(select(func.count(Dataset.id))).scalar()
        assert count == 0


def test_csv_upload_with_all_empty_respondent_stores_missing_person_count(client: TestClient):
    _create_authenticated_user(client)
    csv_bytes = b"id,I01,I02,I03\nP0001,1,0,1\nP0002,,,\nP0003,0,1,0\n"

    response = client.post(
        "/datasets",
        files={"data": ("empty_resp.csv", csv_bytes, "text/csv")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    dataset_id = int(response.headers["location"].split("/")[-1])

    with SessionLocal() as db:
        row = db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one()
        summary = json.loads(row.summary_json)
        assert summary.get("all_missing_persons_count") == 1


def test_winsteps_commit_with_extra_missing_updates_summary(client: TestClient):
    _create_authenticated_user(client)
    prn_bytes = (FIXTURES_DIR / "sample_winsteps.prn").read_bytes()
    con_bytes = (FIXTURES_DIR / "sample_winsteps.CON").read_bytes()

    upload_resp = client.post(
        "/datasets",
        files={
            "data": ("sample_winsteps.prn", prn_bytes, "text/plain"),
            "con": ("sample_winsteps.CON", con_bytes, "text/plain"),
        },
        follow_redirects=False,
    )
    dataset_id = int(upload_resp.headers["location"].split("/")[-1])

    with SessionLocal() as db:
        staged = db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one()
        staged_summary = json.loads(staged.summary_json)
        assert staged_summary["total_missing"] == 52

    commit_resp = client.post(
        f"/datasets/{dataset_id}/commit",
        data={
            "key": "A" * 20,
            "codes": "AB",
            "extra_missing": "A",
        },
        follow_redirects=False,
    )
    assert commit_resp.status_code == 303

    with SessionLocal() as db:
        committed = db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one()
        assert committed.status == "ready"
        summary = json.loads(committed.summary_json)
        assert summary["total_missing"] == 52 + 574
        assert sum(summary["missing_per_item"]) == 52 + 574

