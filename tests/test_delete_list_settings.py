"""Tests for the delete-list upload on the settings screen and the run's record of it (F16-B).

Every POST drives the real route with a monkeypatched app.analysis.run_analyze, so no engine
run happens. The invalid upload proves validation lands before the rate limit and before the
engine, and that no Analysis row is left behind.
"""

from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Analysis
from app.security import now_epoch
from tests.test_analysis_settings import _create_authenticated_user, _upload_and_commit_sample
from tests.test_delete_list_inputs import _install_fake_engine

FORM = {"misfit": "1.50", "mode": "compat", "digits": "2"}

_EMPTY_FILE_BOUNDARY = "----raschlabemptyinput"


def _empty_file_multipart() -> tuple[bytes, str]:
    """A browser-shaped body for a form whose two file inputs carry nothing.

    Browsers send the parts with `filename=""`, which httpx's multipart encoder omits, so the
    body is built by hand: this is the shape the strip rule on upload.filename must handle.
    """
    def part(name: str, body: bytes, filename: str | None = None) -> bytes:
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        return (
            f"--{_EMPTY_FILE_BOUNDARY}\r\n{disposition}\r\n\r\n".encode("utf-8")
            + body
            + b"\r\n"
        )

    body = (
        part("misfit", b"1.50")
        + part("mode", b"compat")
        + part("digits", b"2")
        + part("pdfile", b"", filename="")
        + part("idfile", b"", filename="")
        + f"--{_EMPTY_FILE_BOUNDARY}--\r\n".encode("utf-8")
    )
    return body, f"multipart/form-data; boundary={_EMPTY_FILE_BOUNDARY}"


def _post_analyze(client: TestClient, dataset_id: int, **kwargs):
    return client.post(
        f"/datasets/{dataset_id}/analyze",
        data=FORM,
        follow_redirects=False,
        **kwargs,
    )


def _analysis_id_from(response) -> int:
    return int(response.headers["location"].split("/")[-1].split("?")[0])


def _recorded_params(analysis_id: int) -> dict:
    with SessionLocal() as db:
        analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert analysis is not None
        return json.loads(analysis.params_json)


def _analysis_count(dataset_id: int) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count(Analysis.id)).where(Analysis.dataset_id == dataset_id)
        )


def test_post_with_pdfile_records_metadata_without_the_text(client: TestClient, monkeypatch):
    _install_fake_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    uploaded = b"101\n102\n103\n"

    resp = _post_analyze(client, dataset_id, files={"pdfile": ("hapus.txt", uploaded, "text/plain")})

    assert resp.status_code == 303
    params = _recorded_params(_analysis_id_from(resp))
    assert params["pdfile"] == {
        "name": "hapus.txt",
        "sha256": hashlib.sha256(uploaded).hexdigest(),
        "rows": 3,
        "bytes": len(uploaded),
    }
    assert "text" not in params["pdfile"]


def test_post_with_pdfile_only_leaves_idfile_none(client: TestClient, monkeypatch):
    _install_fake_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = _post_analyze(client, dataset_id, files={"pdfile": ("hapus.csv", b"12\n13\n", "text/csv")})

    assert resp.status_code == 303
    params = _recorded_params(_analysis_id_from(resp))
    assert params["pdfile"]["rows"] == 2
    assert params["idfile"] is None


def test_exe_upload_is_refused_and_creates_no_analysis(client: TestClient, monkeypatch):
    calls = _install_fake_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = _post_analyze(
        client, dataset_id, files={"pdfile": ("x.exe", b"1\n2\n", "application/octet-stream")}
    )

    assert resp.status_code == 422
    assert "Daftar hapus harus berupa berkas teks (.txt, .csv, atau .dat)." in resp.text
    assert _analysis_count(dataset_id) == 0
    assert calls == []


def test_empty_file_inputs_are_recorded_as_none(client: TestClient, monkeypatch):
    calls = _install_fake_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    body, content_type = _empty_file_multipart()
    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        content=body,
        headers={"content-type": content_type},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert _analysis_count(dataset_id) == 1
    params = _recorded_params(_analysis_id_from(resp))
    assert params["pdfile"] is None
    assert params["idfile"] is None
    assert len(calls) == 1
    assert calls[0]["pdfile_path"] is None
    assert calls[0]["idfile_path"] is None


def test_run_page_shows_the_list_it_used(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    sha = hashlib.sha256(b"daftar hapus peserta").hexdigest()
    now = now_epoch()
    with SessionLocal() as db:
        analysis = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status="done",
            params_json=json.dumps(
                {
                    "misfit": 1.5,
                    "mode": "compat",
                    "digits": 2,
                    "pdfile": {
                        "name": "hapus-peserta.txt",
                        "sha256": sha,
                        "rows": 1234,
                        "bytes": 5555,
                    },
                    "idfile": None,
                }
            ),
            engine_ref="test-ref",
            created_at=now,
            expires_at=now + 180 * 86400,
            finished_at=now,
            elapsed_ms=100,
        )
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id

    page = client.get(f"/analyses/{analysis_id}")

    assert page.status_code == 200
    assert "Daftar hapus peserta" in page.text
    assert "hapus-peserta.txt" in page.text
    assert "1.234" in page.text
    assert sha[:8].upper() in page.text


def test_run_page_says_nothing_when_no_list_was_used(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    sha = hashlib.sha256(b"daftar hapus peserta").hexdigest()
    now = now_epoch()
    with SessionLocal() as db:
        analysis = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status="done",
            params_json=json.dumps(
                {"misfit": 1.5, "mode": "compat", "digits": 2, "pdfile": None, "idfile": None}
            ),
            engine_ref="test-ref",
            created_at=now,
            expires_at=now + 180 * 86400,
            finished_at=now,
            elapsed_ms=100,
        )
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id

    page = client.get(f"/analyses/{analysis_id}")

    assert page.status_code == 200
    assert "Daftar hapus peserta" not in page.text
    assert "Daftar hapus butir" not in page.text
    assert "hapus-peserta.txt" not in page.text
    assert "1.234" not in page.text
    assert sha[:8].upper() not in page.text
