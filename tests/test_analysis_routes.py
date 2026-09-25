"""Integration tests for analysis routes and execution lifecycle.

Covers:
- Upload + commit sample -> POST analyze -> 303 -> GET result page 200.
- Result page rendering: table headers, misfit order label, decimal comma in measure cells, id_num-formatted thousands.
- Database state: status == 'done', elapsed_ms > 0, 6 analysis_files rows, engine header prefixes, sha256 validation, 180-day retention window.
- Multi-user isolation: foreign user receives 404 for analysis read and run.
- Engine failure handling: SystemExit(2) during analysis yields status == 'failed', zero files, and misfit alert with Indonesian error message.
- Loading state: running row presentation and duplicate run prevention.
- Stale analysis recovery: running row older than 900 seconds automatically flips to failed on read.
- Dataset detail view: presence of latest_analysis link when analysis is complete.
- Legacy dataset backfill: analysis execution transparently generates and stores matrix_gzip when missing.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.analysis import OUTPUT_FILES, STALE_RUN_S, id_num
from app.auth import COOKIE_NAME
from app.config import settings
from app.db import SessionLocal
from app.models import Analysis, AnalysisFile, Dataset, SessionRow, User
from app.security import hash_password, hash_token, new_token, now_epoch

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _create_authenticated_user(client: TestClient, email: str = "researcher@example.test") -> int:
    with SessionLocal() as db:
        now = now_epoch()
        user = User(
            email=email,
            email_normalized=email.lower().strip(),
            password_hash=hash_password("katasandi-analysis-123"),
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


def _upload_and_commit_sample(client: TestClient, fixture_name: str = "sample_300x40.csv") -> int:
    csv_bytes = (FIXTURES_DIR / fixture_name).read_bytes()
    upload_resp = client.post(
        "/datasets",
        files={"data": (fixture_name, csv_bytes, "text/csv")},
        follow_redirects=False,
    )
    assert upload_resp.status_code == 303
    dataset_id = int(upload_resp.headers["location"].split("/")[-1].split("?")[0])

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
    return dataset_id


def test_analyze_flow_and_result_page_contract(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    post_resp = client.post(f"/datasets/{dataset_id}/analyze", follow_redirects=False)
    assert post_resp.status_code == 303
    location = post_resp.headers["location"]
    assert location.startswith("/analyses/")
    analysis_id = int(location.split("/")[-1].split("?")[0])

    get_resp = client.get(location)
    assert get_resp.status_code == 200
    html = get_resp.text

    assert "Tabel Butir (15.1)" in html
    assert "misfit (outfit MNSQ menurun)" in html
    assert "Urutan Responden:" in html
    assert '<td class="num-col mono">-0,02</td>' in html

    # Verify id_num formatting on thousands via elapsed_ms >= 1000
    with SessionLocal() as db:
        analysis_record = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert analysis_record is not None
        analysis_record.elapsed_ms = 1250
        db.commit()

    resp_thousands = client.get(location)
    assert resp_thousands.status_code == 200
    assert "1.250 ms" in resp_thousands.text

    # Database assertions
    with SessionLocal() as db:
        analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert analysis is not None
        assert analysis.status == "done"
        assert analysis.elapsed_ms is not None and analysis.elapsed_ms > 0
        assert analysis.user_id == user_id
        assert analysis.dataset_id == dataset_id
        assert analysis.expires_at - analysis.created_at == 180 * 86400

        files = list(
            db.scalars(
                select(AnalysisFile).where(AnalysisFile.analysis_id == analysis_id)
            ).all()
        )
        assert len(files) == 6
        file_map = {f.filename: f for f in files}
        assert set(file_map.keys()) == set(OUTPUT_FILES)

        expected_headers = {
            "item_table_15.1.csv": b"ENTRY,TOTAL,TOTAL,JMLE,MODEL,INFIT",
            "person_table.csv": b"ENTRY,TOTAL,TOTAL,JMLE,MODEL,INFIT",
            "option_table_15.3.csv": b"ENTRY,DATA,SCORE,DATA",
            "summary_table.csv": b"SECTION,STATISTIC,VALUE",
            "wright_map_measure.csv": b"MEASURE,NR_PERSON",
            "wright_map_frequency.csv": b"MEASURE,NR_PERSON",
        }

        for filename, expected_header in expected_headers.items():
            af = file_map[filename]
            raw_decompressed = gzip.decompress(af.content_gzip)
            assert len(raw_decompressed) == af.bytes
            assert hashlib.sha256(raw_decompressed).hexdigest() == af.sha256
            assert raw_decompressed.startswith(expected_header)


def test_analysis_user_isolation_blocks_foreign_read_and_run(client: TestClient):
    user_a_id = _create_authenticated_user(client, email="usera@example.test")
    dataset_id = _upload_and_commit_sample(client)

    post_resp = client.post(f"/datasets/{dataset_id}/analyze", follow_redirects=False)
    assert post_resp.status_code == 303
    analysis_id = int(post_resp.headers["location"].split("/")[-1].split("?")[0])

    user_b_id = _create_authenticated_user(client, email="userb@example.test")
    assert user_b_id != user_a_id

    read_resp = client.get(f"/analyses/{analysis_id}")
    assert read_resp.status_code == 404

    run_resp = client.post(f"/datasets/{dataset_id}/analyze", follow_redirects=False)
    assert run_resp.status_code == 404


def test_analysis_engine_failure_produces_failed_status_and_misfit_alert(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    def _failing_run_analyze(*args: Any, **kwargs: Any) -> None:
        raise SystemExit(2)

    monkeypatch.setattr("app.analysis.run_analyze", _failing_run_analyze)

    post_resp = client.post(f"/datasets/{dataset_id}/analyze", follow_redirects=False)
    assert post_resp.status_code == 303
    analysis_id = int(post_resp.headers["location"].split("/")[-1].split("?")[0])

    with SessionLocal() as db:
        analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert analysis is not None
        assert analysis.status == "failed"
        assert analysis.error is not None
        assert "Analisis gagal dijalankan mesin:" in analysis.error

        files_count = db.scalar(
            select(func.count(AnalysisFile.id)).where(AnalysisFile.analysis_id == analysis_id)
        )
        assert files_count == 0

    page_resp = client.get(f"/analyses/{analysis_id}")
    assert page_resp.status_code == 200
    html = page_resp.text
    assert "alert alert--misfit" in html
    assert "Analisis Gagal" in html
    assert "Analisis gagal dijalankan mesin:" in html
    assert "Jalankan Ulang" in html


def test_analysis_loading_state_rendering_and_in_flight_redirect(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    now = now_epoch()
    with SessionLocal() as db:
        running_analysis = Analysis(
            dataset_id=dataset_id,
            user_id=user_id,
            status="running",
            params_json=json.dumps({"mode": "compat"}),
            engine_ref="raschlab-engine-test",
            created_at=now,
            started_at=now,
            expires_at=now + 180 * 86400,
        )
        db.add(running_analysis)
        db.commit()
        analysis_id = running_analysis.id

    page_resp = client.get(f"/analyses/{analysis_id}")
    assert page_resp.status_code == 200
    html = page_resp.text
    assert "Memproses" in html
    assert "Analisis sedang diproses..." in html

    post_resp = client.post(f"/datasets/{dataset_id}/analyze", follow_redirects=False)
    assert post_resp.status_code == 303
    assert post_resp.headers["location"].startswith(f"/analyses/{analysis_id}")


def test_analysis_stale_running_row_flips_to_failed(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    now = now_epoch()
    stale_time = now - 950
    with SessionLocal() as db:
        stale_analysis = Analysis(
            dataset_id=dataset_id,
            user_id=user_id,
            status="running",
            params_json=json.dumps({"mode": "compat"}),
            engine_ref="raschlab-engine-test",
            created_at=stale_time,
            started_at=stale_time,
            expires_at=stale_time + 180 * 86400,
        )
        db.add(stale_analysis)
        db.commit()
        analysis_id = stale_analysis.id

    page_resp = client.get(f"/analyses/{analysis_id}")
    assert page_resp.status_code == 200
    html = page_resp.text
    assert "alert alert--misfit" in html
    assert "Analisis terhenti saat berjalan. Jalankan ulang." in html

    with SessionLocal() as db:
        row = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert row is not None
        assert row.status == "failed"
        assert row.error == "Analisis terhenti saat berjalan. Jalankan ulang."
        assert row.finished_at is not None


def test_dataset_detail_shows_latest_analysis_link(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    detail_before = client.get(f"/datasets/{dataset_id}")
    assert detail_before.status_code == 200
    assert "Belum ada analisis untuk berkas ini." in detail_before.text

    post_resp = client.post(f"/datasets/{dataset_id}/analyze", follow_redirects=False)
    assert post_resp.status_code == 303
    analysis_id = int(post_resp.headers["location"].split("/")[-1].split("?")[0])

    detail_after = client.get(f"/datasets/{dataset_id}")
    assert detail_after.status_code == 200
    assert f'href="/analyses/{analysis_id}"' in detail_after.text
    assert "Lihat hasil analisis terakhir" in detail_after.text


def test_legacy_dataset_backfill_matrix_gzip_on_analyze(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    with SessionLocal() as db:
        ds = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
        assert ds is not None
        ds.matrix_gzip = None
        db.commit()

    with SessionLocal() as db:
        ds = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
        assert ds is not None
        assert ds.matrix_gzip is None

    post_resp = client.post(f"/datasets/{dataset_id}/analyze", follow_redirects=False)
    assert post_resp.status_code == 303
    analysis_id = int(post_resp.headers["location"].split("/")[-1].split("?")[0])

    with SessionLocal() as db:
        ds = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
        assert ds is not None
        assert ds.matrix_gzip is not None
        assert len(ds.matrix_gzip) > 0

        container = json.loads(gzip.decompress(ds.matrix_gzip).decode("utf-8"))
        assert container["v"] == 1
        assert "prn" in container
        assert container["namlen"] > 0

        analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert analysis is not None
        assert analysis.status == "done"


def test_anonymous_access_redirects_or_returns_404(client: TestClient):
    post_resp = client.post("/datasets/1/analyze", follow_redirects=False)
    assert post_resp.status_code == 303
    assert post_resp.headers["location"] == "/login"

    get_resp = client.get("/analyses/1")
    assert get_resp.status_code == 404


def test_gate_closed_blocks_analysis_routes(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "gate_open", False)

    post_resp = client.post("/datasets/1/analyze", follow_redirects=False)
    assert post_resp.status_code == 303
    assert post_resp.headers["location"] == "/"

    get_resp = client.get("/analyses/1")
    assert get_resp.status_code == 404
