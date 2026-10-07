from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.analysis
from app.auth import COOKIE_NAME
from app.db import SessionLocal
from app.models import Analysis, Dataset, SessionRow, User
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


class RecordedCall:
    def __init__(self, kwargs: dict[str, Any]):
        self.kwargs = kwargs
        pdfile_path = kwargs.get("pdfile_path")
        idfile_path = kwargs.get("idfile_path")
        anchors_path = kwargs.get("anchors_path")
        self.pdfile_bytes = (
            Path(pdfile_path).read_bytes()
            if pdfile_path and os.path.exists(pdfile_path)
            else None
        )
        self.idfile_bytes = (
            Path(idfile_path).read_bytes()
            if idfile_path and os.path.exists(idfile_path)
            else None
        )
        self.anchors_bytes = (
            Path(anchors_path).read_bytes()
            if anchors_path and os.path.exists(anchors_path)
            else None
        )

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        return self.kwargs[item]


class EngineRecorder(list):
    @property
    def empty(self) -> bool:
        return len(self) == 0


@pytest.fixture
def recorder(monkeypatch):
    calls = EngineRecorder()
    real_run_analyze = app.analysis.run_analyze

    def spy_run_analyze(*args: Any, **kwargs: Any):
        calls.append(RecordedCall(kwargs))
        return real_run_analyze(*args, **kwargs)

    monkeypatch.setattr(app.analysis, "run_analyze", spy_run_analyze)
    with contextlib.suppress(Exception):
        import raschlab.cli

        monkeypatch.setattr(raschlab.cli, "run_analyze", spy_run_analyze)
    return calls


def test_settings_page_renders_the_picker(client: TestClient):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    html = resp.text

    # Three rows with summaries and open buttons
    assert 'data-kind="persons"' in html
    assert 'data-kind="items"' in html
    assert 'data-kind="anchors"' in html
    assert '<span class="pick-summary" data-summary="persons">Belum ada</span>' in html
    assert '<span class="pick-summary" data-summary="items">Belum ada</span>' in html
    assert '<span class="pick-summary" data-summary="anchors">Belum ada</span>' in html
    assert re.search(r'class="btn btn--quiet pick-open"[^>]*data-kind="persons"[^>]*aria-haspopup="dialog"', html)
    assert re.search(r'class="btn btn--quiet pick-open"[^>]*data-kind="items"[^>]*aria-haspopup="dialog"', html)
    assert re.search(r'class="btn btn--quiet pick-open"[^>]*data-kind="anchors"[^>]*aria-haspopup="dialog"', html)

    # Dialog shell with empty results
    assert 'id="picker-dialog"' in html
    assert 'id="picker-title"' in html
    assert 'id="picker-search"' in html
    assert 'id="picker-results"' in html
    assert re.search(r'id="picker-results">\s*</div>', html)
    assert 'id="picker-more"' in html
    assert 'id="picker-status"' in html
    assert 'id="picker-chosen"' in html
    assert 'id="picker-file"' in html

    # File inputs inside dialog
    dialog_match = re.search(r'<dialog id="picker-dialog"[^>]*>(.*?)</dialog>', html, re.DOTALL)
    assert dialog_match is not None
    dialog_content = dialog_match.group(1)
    assert 'name="pdfile"' in dialog_content
    assert 'name="idfile"' in dialog_content
    assert 'name="anchors"' in dialog_content

    # Old markup removed and script tag kept
    assert 'id="pd-picker"' not in html
    assert 'id="pd-picker-data"' not in html
    assert 'id="pd-filter"' not in html
    assert 'name="pd_pick"' not in html
    assert 'name="id_pick"' not in html
    assert 'name="anchor_pos"' not in html
    assert 'name="anchor_value"' not in html
    assert "/static/settings-picker.js" in html


def test_picker_run_reaches_the_engine_and_records_metadata(client: TestClient, recorder):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "pd_pick": ["3", "7"],
            "id_pick": ["5"],
            "anchor_pos": ["1"],
            "anchor_value": ["0.5"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    analysis_id = int(resp.headers["location"].split("/")[-1].split("?")[0])

    with SessionLocal() as db:
        analysis = db.get(Analysis, analysis_id)
        assert analysis is not None
        assert analysis.status == "done"
        params = json.loads(analysis.params_json)
        assert params["pdfile"] == {
            "name": "peserta-dipilih.txt",
            "rows": 2,
            "bytes": 4,
            "sha256": hashlib.sha256(b"3\n7\n").hexdigest(),
        }
        assert params["idfile"]["rows"] == 1
        assert params["idfile"]["sha256"] == hashlib.sha256(b"5\n").hexdigest()
        assert params["anchors"] == {
            "name": "jangkar-dipilih.txt",
            "requested": 1,
            "anchors": {"1": 0.5},
            "by_position": 1,
            "by_label": 0,
            "used": 1,
        }

    assert len(recorder) == 1
    assert recorder[0].pdfile_bytes == b"3\n7\n"
    assert recorder[0].idfile_bytes == b"5\n"
    assert recorder[0].anchors_bytes == b"1 0.5\n"


def test_upload_wins_over_the_picker(client: TestClient, recorder):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    upload_bytes = b"101\n102\n"
    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "pd_pick": ["3"],
            "id_pick": ["5"],
        },
        files={
            "pdfile": ("hapus.txt", upload_bytes, "text/plain"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    analysis_id = int(resp.headers["location"].split("/")[-1].split("?")[0])

    with SessionLocal() as db:
        analysis = db.get(Analysis, analysis_id)
        assert analysis is not None
        params = json.loads(analysis.params_json)
        assert params["pdfile"]["name"] == "hapus.txt"
        assert params["pdfile"]["sha256"] == hashlib.sha256(upload_bytes).hexdigest()
        assert params["idfile"]["name"] == "butir-dipilih.txt"
        assert params["idfile"]["sha256"] == hashlib.sha256(b"5\n").hexdigest()

    assert len(recorder) == 1
    assert recorder[0].pdfile_bytes == upload_bytes
    assert recorder[0].idfile_bytes == b"5\n"


def test_picker_beats_the_inherited_anchors(client: TestClient, recorder):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp1 = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "anchor_pos": ["1"],
            "anchor_value": ["0.5"],
        },
        follow_redirects=False,
    )
    assert resp1.status_code == 303
    analysis_1_id = int(resp1.headers["location"].split("/")[-1].split("?")[0])

    resp2 = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "inherit_anchors": str(analysis_1_id),
            "anchor_pos": ["2"],
            "anchor_value": ["-1.25"],
        },
        follow_redirects=False,
    )
    assert resp2.status_code == 303
    analysis_2_id = int(resp2.headers["location"].split("/")[-1].split("?")[0])

    with SessionLocal() as db:
        analysis2 = db.get(Analysis, analysis_2_id)
        assert analysis2 is not None
        params2 = json.loads(analysis2.params_json)
        assert params2["anchors"]["name"] == "jangkar-dipilih.txt"
        assert params2["anchors"]["anchors"] == {"2": -1.25}

    assert len(recorder) == 2
    assert recorder[1].anchors_bytes == b"2 -1.25\n"


def test_picker_rejects_an_out_of_range_person_position(client: TestClient, recorder):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={"pd_pick": ["9999"]},
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert "di luar rentang 1 sampai 300" in resp.text

    with SessionLocal() as db:
        count = db.scalar(select(func.count(Analysis.id)).where(Analysis.dataset_id == dataset_id))
        assert count == 0

    assert len(recorder) == 0


def test_picker_rejects_a_non_numeric_anchor_value(client: TestClient, recorder):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "anchor_pos": ["1"],
            "anchor_value": ["abc"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert "bukan angka" in resp.text

    with SessionLocal() as db:
        count = db.scalar(select(func.count(Analysis.id)).where(Analysis.dataset_id == dataset_id))
        assert count == 0

    assert len(recorder) == 0


def test_picker_rejects_mismatched_anchor_lists(client: TestClient, recorder):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "anchor_pos": ["1", "2"],
            "anchor_value": ["0.5"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert "Jumlah posisi butir dan nilai jangkar tidak cocok" in resp.text

    with SessionLocal() as db:
        count = db.scalar(select(func.count(Analysis.id)).where(Analysis.dataset_id == dataset_id))
        assert count == 0

    assert len(recorder) == 0


def test_rejected_settings_post_preserves_picker_selections_and_anchor_values(client: TestClient):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "misfit": "-1",
            "pd_pick": ["3", "7"],
            "id_pick": ["5"],
            "anchor_pos": ["1"],
            "anchor_value": ["0.5"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    html = resp.text

    assert '<input type="hidden" name="pd_pick" value="3">' in html
    assert '<input type="hidden" name="pd_pick" value="7">' in html
    assert html.count('name="pd_pick"') == 2
    assert '<input type="hidden" name="id_pick" value="5">' in html
    assert html.count('name="id_pick"') == 1
    assert '<input type="hidden" name="anchor_pos" value="1">' in html
    assert '<input type="hidden" name="anchor_value" value="0.5">' in html
    assert html.count('name="anchor_pos"') == 1
    assert html.count('name="anchor_value"') == 1

    assert '<span class="pick-summary" data-summary="persons">2 dipilih</span>' in html
    assert '<span class="pick-summary" data-summary="items">1 dipilih</span>' in html
    assert '<span class="pick-summary" data-summary="anchors">1 dipilih</span>' in html


def test_rejected_bad_anchor_value_survives_in_input(client: TestClient):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "anchor_pos": ["1"],
            "anchor_value": ["abc"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert '<input type="hidden" name="anchor_pos" value="1">' in resp.text
    assert '<input type="hidden" name="anchor_value" value="abc">' in resp.text


def test_picker_and_upload_produce_identical_engine_input(client: TestClient, recorder):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp_a = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "pd_pick": ["3", "7"],
            "id_pick": ["5"],
            "anchor_pos": ["1", "2"],
            "anchor_value": ["0.5", "-1.25"],
        },
        follow_redirects=False,
    )
    assert resp_a.status_code == 303
    aid_a = int(resp_a.headers["location"].split("/")[-1].split("?")[0])

    resp_b = client.post(
        f"/datasets/{dataset_id}/analyze",
        files={
            "pdfile": ("peserta-dipilih.txt", b"3\n7\n", "text/plain"),
            "idfile": ("butir-dipilih.txt", b"5\n", "text/plain"),
            "anchors": ("jangkar-dipilih.txt", b"1 0.5\n2 -1.25\n", "text/plain"),
        },
        follow_redirects=False,
    )
    assert resp_b.status_code == 303
    aid_b = int(resp_b.headers["location"].split("/")[-1].split("?")[0])

    assert len(recorder) == 2
    assert recorder[0].pdfile_bytes == recorder[1].pdfile_bytes
    assert recorder[0].idfile_bytes == recorder[1].idfile_bytes
    assert recorder[0].anchors_bytes == recorder[1].anchors_bytes

    with SessionLocal() as db:
        analysis_a = db.get(Analysis, aid_a)
        analysis_b = db.get(Analysis, aid_b)
        assert analysis_a is not None and analysis_b is not None
        assert analysis_a.status == "done"
        assert analysis_b.status == "done"
        params_a = json.loads(analysis_a.params_json)
        params_b = json.loads(analysis_b.params_json)
        assert params_a["pdfile"] == params_b["pdfile"]
        assert params_a["idfile"] == params_b["idfile"]
        assert params_a["anchors"] == params_b["anchors"]


def test_settings_page_stays_inside_the_byte_budget(client: TestClient):
    from tests.test_render_budget import _large_csv, _upload

    dataset_id = _upload(client, "large.csv", _large_csv(), "budget_picker@example.test")
    with SessionLocal() as db:
        key = json.loads(
            db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one().mapping_json
        )["key"]

    commit = client.post(
        f"/datasets/{dataset_id}/commit",
        data={"key": key},
        follow_redirects=False,
    )
    assert commit.status_code == 303

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    assert len(resp.content) < 2_000_000
