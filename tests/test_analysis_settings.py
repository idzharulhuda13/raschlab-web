"""Tests for dataset analysis settings (GET and POST)."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.analysis import build_matrix_gzip, write_inputs
from app.auth import COOKIE_NAME
from app.db import SessionLocal
from app.models import Analysis, AnalysisFile, Dataset, SessionRow, User
from app.security import hash_password, hash_token, new_token, now_epoch
from tests.test_f9_ux import _build_test_files

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


def test_settings_get_prefills_defaults(client: TestClient):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    assert 'value="1.50"' in resp.text
    assert re.search(r'<option[^>]*value=["\']compat["\'][^>]*selected', resp.text) or re.search(r'<option[^>]*selected[^>]*value=["\']compat["\']', resp.text)
    assert re.search(r'<option[^>]*value=["\']2["\'][^>]*selected', resp.text) or re.search(r'<option[^>]*selected[^>]*value=["\']2["\']', resp.text)


def test_settings_get_prefills_newest_analysis(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    now = now_epoch()
    with SessionLocal() as db:
        analysis = Analysis(
            dataset_id=dataset_id,
            user_id=user_id,
            status="done",
            params_json=json.dumps({"misfit": 1.2, "mode": "exact", "digits": 4}),
            engine_ref="raschlab-engine-test",
            created_at=now,
            started_at=now,
            finished_at=now,
            expires_at=now + 180 * 86400,
        )
        db.add(analysis)
        db.commit()

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    assert 'value="1.20"' in resp.text
    assert re.search(r'<option[^>]*value=["\']4["\'][^>]*selected', resp.text) or re.search(r'<option[^>]*selected[^>]*value=["\']4["\']', resp.text)


def test_settings_rejects_bad_values(client: TestClient):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp_misfit = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={"misfit": "9", "mode": "compat", "digits": "2"},
    )
    assert resp_misfit.status_code == 422
    assert "Ambang misfit harus berada antara 0,5 dan 5,0." in resp_misfit.text

    resp_mode = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={"misfit": "1.50", "mode": "winsteps", "digits": "2"},
    )
    assert resp_mode.status_code == 422
    assert "Mode kalibrasi harus compat atau exact." in resp_mode.text

    resp_digits = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={"misfit": "1.50", "mode": "compat", "digits": "9"},
    )
    assert resp_digits.status_code == 422
    assert "Desimal harus berada antara 1 dan 4." in resp_digits.text

    with SessionLocal() as db:
        analysis_count = db.scalar(
            select(func.count(Analysis.id)).where(Analysis.dataset_id == dataset_id)
        )
        assert analysis_count == 0


def test_settings_post_stores_params(client: TestClient):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    post_resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={"misfit": "1,20", "mode": "exact", "digits": "4"},
        follow_redirects=False,
    )
    assert post_resp.status_code == 303
    location = post_resp.headers["location"]
    assert location.startswith("/analyses/")
    analysis_id = int(location.split("/")[-1].split("?")[0])

    with SessionLocal() as db:
        analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert analysis is not None
        params = json.loads(analysis.params_json)
        assert params["misfit"] == 1.2
        assert params["mode"] == "exact"
        assert params["digits"] == 4


def test_new_run_leaves_old_analysis_params(client: TestClient):
    import gzip
    import hashlib
    from tests.test_f9_ux import _build_test_files

    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    now = now_epoch()
    with SessionLocal() as db:
        analysis_a = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status="done",
            params_json=json.dumps({"misfit": 1.2, "mode": "compat", "digits": 2}),
            engine_ref="test-ref",
            created_at=now,
            expires_at=now + 180 * 86400,
            finished_at=now,
            elapsed_ms=100,
        )
        db.add(analysis_a)
        db.commit()
        analysis_a_id = analysis_a.id

        for fname, text in _build_test_files().items():
            raw_bytes = text.encode("utf-8")
            af = AnalysisFile(
                analysis_id=analysis_a_id,
                filename=fname,
                content_gzip=gzip.compress(raw_bytes, mtime=0),
                sha256=hashlib.sha256(raw_bytes).hexdigest(),
                bytes=len(raw_bytes),
            )
            db.add(af)
        db.commit()

    resp_b = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={"misfit": "1,50", "mode": "compat", "digits": "2"},
        follow_redirects=False,
    )
    assert resp_b.status_code == 303
    analysis_b_id = int(resp_b.headers["location"].split("/")[-1].split("?")[0])
    assert analysis_a_id != analysis_b_id

    with SessionLocal() as db:
        analysis_a = db.scalar(select(Analysis).where(Analysis.id == analysis_a_id))
        assert analysis_a is not None
        params_a = json.loads(analysis_a.params_json)
        assert params_a["misfit"] == 1.2

    page_a = client.get(f"/analyses/{analysis_a_id}")
    assert page_a.status_code == 200
    assert "1,20" in page_a.text
    assert "1,50" not in page_a.text


def test_uploaded_con_directives_reach_the_generated_con(tmp_path: Path):
    n_items = 4
    item_labels = ["I1", "I2", "I3", "I4"]
    rows = [["1"] * n_items]
    mapping = {"1": "correct"}

    gz_bytes = build_matrix_gzip("delimited", ["P1"], item_labels, rows, mapping=mapping)
    dataset_with_control = Dataset(
        n_items=n_items,
        item_labels_json=json.dumps(item_labels),
        summary_json=json.dumps({"control": {"MISSCORE": "-0.5", "CODES": "ABCD"}}),
    )

    dir_ctrl = tmp_path / "ctrl"
    dir_ctrl.mkdir()
    con_path_ctrl, _ = write_inputs(dir_ctrl, dataset_with_control, gz_bytes)

    con_text = Path(con_path_ctrl).read_text(encoding="utf-8")
    lines = [line.strip() for line in con_text.splitlines() if line.strip()]
    assert "MISSCORE = -0.5" in lines
    codes_idx = lines.index("CODES = ABCD")
    misscore_idx = lines.index("MISSCORE = -0.5")
    data_idx = lines.index("DATA = data.prn")
    assert codes_idx < misscore_idx < data_idx

    dir_no_ctrl_a = tmp_path / "no_ctrl_a"
    dir_no_ctrl_b = tmp_path / "no_ctrl_b"
    dir_no_ctrl_a.mkdir()
    dir_no_ctrl_b.mkdir()

    dataset_without_control_key = Dataset(
        n_items=n_items,
        item_labels_json=json.dumps(item_labels),
        summary_json=json.dumps({"n_persons": 1}),
    )
    dataset_no_summary = Dataset(
        n_items=n_items,
        item_labels_json=json.dumps(item_labels),
        summary_json=None,
    )

    con_path_a, _ = write_inputs(dir_no_ctrl_a, dataset_without_control_key, gz_bytes)
    con_path_b, _ = write_inputs(dir_no_ctrl_b, dataset_no_summary, gz_bytes)

    assert Path(con_path_a).read_bytes() == Path(con_path_b).read_bytes()


def test_misfit_band_reads_both_header_layouts(client: TestClient):
    """The misfit band must appear for the engine's two-row header AND for the legacy single-cell header."""
    item_two_row = (
        "ENTRY,TOTAL,TOTAL,JMLE,MODEL,INFIT,,OUTFIT,,PTMEASUR-AL,,EXACT,MATCH,\n"
        "NUMBER,SCORE,COUNT,MEASURE,S.E.,MNSQ,ZSTD,MNSQ,ZSTD,CORR.,EXP.,OBS%,EXP%,ITEM\n"
        "1,232,289,-0.02,0.15,1.90,3.10,1.00,0.02,0.04,0.03,80.3,80.3,I01\n"
        "2,240,289,0.20,0.15,0.90,0.10,0.95,0.05,0.40,0.35,88.0,86.0,I02\n"
    )
    item_legacy = (
        "ENTRY,SCORE,COUNT,MEASURE,S.E.,INFIT MNSQ,INFIT ZSTD,OUTFIT MNSQ,OUTFIT ZSTD,CORR.,EXP.,OBS%,EXP%\n"
        "NUMBER,SCORE,COUNT,MEASURE,S.E.,MNSQ,ZSTD,MNSQ,ZSTD,CORR.,EXP.,OBS%,EXP%\n"
        "1,232,289,-0.02,0.15,1.90,3.10,1.00,0.02,0.04,0.03,80.3,80.3\n"
        "2,240,289,0.20,0.15,0.90,0.10,0.95,0.05,0.40,0.35,88.0,86.0\n"
    )

    for label, item_csv in (("two-row engine layout", item_two_row), ("legacy single-cell layout", item_legacy)):
        user_id = _create_authenticated_user(client, email=f"layout_{label.split()[0]}@example.test")
        dataset_id = _upload_and_commit_sample(client)
        now = now_epoch()
        with SessionLocal() as db:
            analysis = Analysis(
                user_id=user_id, dataset_id=dataset_id, status="done",
                params_json=json.dumps({"misfit": 1.5, "mode": "compat", "digits": 2}),
                engine_ref="test-ref", created_at=now, expires_at=now + 180 * 86400,
                finished_at=now, elapsed_ms=100,
            )
            db.add(analysis)
            db.commit()
            analysis_id = analysis.id
            for fname, text in _build_test_files().items():
                raw = (item_csv if fname == "item_table_15.1.csv" else text).encode("utf-8")
                db.add(AnalysisFile(
                    analysis_id=analysis_id, filename=fname,
                    content_gzip=gzip.compress(raw, mtime=0),
                    sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                ))
            db.commit()

        page = client.get(f"/analyses/{analysis_id}")
        assert page.status_code == 200, label
        assert "Butir Bermasalah" in page.text, f"misfit band missing for {label}"
        assert "1 dari 2 butir melewati ambang misfit INFIT MNSQ ≥ 1,50" in page.text, f"wrong count for {label}"



def test_control_directive_validation(client: TestClient):
    """Reject the values the engine cannot use, and accept the ones the format document allows."""
    from app.analysis import AnalysisError, validate_control_directives

    ok_cases = [
        ({"CODES": "01"}, 2, "01"),          # binary alphabet is legal, not only A to E
        ({"CODES": "1234"}, 2, "12"),        # rating scale alphabet is legal
        ({"MISSCORE": "-0.5"}, 2, "01"),     # numeric MISSCORE is a score value
        ({"MISSCORE": "E"}, 2, "ABCDE"),     # non-numeric MISSCORE is a character list, per the format document
        ({"KEY1": "ABCD", "CODES": "ABCDE"}, 4, "ABCDE"),
    ]
    for control, n_items, data_codes in ok_cases:
        result = validate_control_directives(control, n_items, data_codes)
        assert isinstance(result, dict), control

    bad_cases = [
        ({"KEY1": "ABZD"}, 4, "ABCDE", "tidak ada di CODES"),
        ({"KEY1": "ABC"}, 4, "ABCDE", "tidak sama dengan jumlah butir"),
        ({"CODES": "A B"}, 2, "AB", "tidak boleh memuat spasi"),
        ({"CODES": "AAB"}, 2, "AB", "karakter berulang"),
        ({"CODES": "AB"}, 2, "ABC", "tidak mencakup kode data"),
        ({"MISSCORE": "Z"}, 2, "ABCDE", "tidak dikenal"),
    ]
    for control, n_items, data_codes, needle in bad_cases:
        try:
            validate_control_directives(control, n_items, data_codes)
        except AnalysisError as exc:
            assert needle in str(exc), (control, str(exc))
        else:
            raise AssertionError(f"not rejected: {control}")


def test_uploaded_con_is_honoured_end_to_end(client: TestClient, tmp_path: Path):
    """Upload a CSV together with a .con file and prove the honoured directives reach analyze.CON."""
    from app.analysis import build_matrix_gzip, write_inputs
    from app.db import SessionLocal
    from app.models import Dataset

    _create_authenticated_user(client)
    n_items = 40  # sample_300x40.csv has 40 items, so a KEY1 must be exactly this long
    key1 = ("ABCD" * 10)[:n_items]
    con_text = (
        "&INST\n"
        f"KEY1 = {key1}\n"
        "CODES = ABCDE\n"
        "MISSCORE = -0.5\n"
        "NAMELEN = 999\n"      # must be ignored: the web derives the layout from the data
        "&END\n"
    )
    raw_csv = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()
    # sample_300x40.csv uses digits 0/1, but the test exercises CODES=ABCDE.
    # Map cell tokens to A/B so the control file's CODES directive covers the data.
    csv_bytes = raw_csv.replace(b",0", b",A").replace(b",1", b",B")
    upload = client.post(
        "/datasets",
        files={
            "data": ("sample_300x40.csv", csv_bytes, "text/csv"),
            "con": ("control.con", con_text.encode("utf-8"), "text/plain"),
        },
        follow_redirects=False,
    )
    assert upload.status_code == 303, upload.text
    dataset_id = int(upload.headers["location"].split("/")[-1].split("?")[0])

    with SessionLocal() as db:
        dataset = db.get(Dataset, dataset_id)
        summary = json.loads(dataset.summary_json or "{}")
        control = summary.get("control") or {}
        assert control.get("KEY1") == key1, control
        assert control.get("CODES") == "ABCDE", control
        assert control.get("MISSCORE") == "-0.5", control
        assert "NAMELEN" not in control, control

        matrix = build_matrix_gzip(
            "delimited", ["P1", "P2"], [f"I{i:02d}" for i in range(1, n_items + 1)],
            [["1"] * n_items, ["0"] * n_items], mapping={"1": "correct", "0": "incorrect"},
        )
        con_path, _ = write_inputs(tmp_path, dataset, matrix)
        con_written = Path(con_path).read_text("utf-8")

    # the test therefore takes a tmp_path parameter: def test_uploaded_con_is_honoured_end_to_end(client, tmp_path)
    assert f"KEY1 = {key1}" in con_written
    assert "CODES = ABCDE" in con_written
    assert "MISSCORE = -0.5" in con_written
    assert "NAMELEN" not in con_written
    # MISSCORE must sit after CODES and before DATA
    assert con_written.index("CODES = ABCDE") < con_written.index("MISSCORE = -0.5")
    assert con_written.index("MISSCORE = -0.5") < con_written.index("DATA =")

    # Rejection case: KEY1 with character Z not in CODES
    bad_key1 = key1[:-1] + "Z"
    bad_con_text = (
        "&INST\n"
        f"KEY1 = {bad_key1}\n"
        "CODES = ABCDE\n"
        "&END\n"
    )
    bad_upload = client.post(
        "/datasets",
        files={
            "data": ("sample_300x40.csv", csv_bytes, "text/csv"),
            "con": ("control.con", bad_con_text.encode("utf-8"), "text/plain"),
        },
        follow_redirects=False,
    )
    assert bad_upload.status_code == 200
    assert "Z" in bad_upload.text


def test_settings_hint_derives_from_the_constants(client: TestClient):
    """The hint copy must quote the real default, so changing the constant moves the text."""
    from app.analysis import MISFIT_THRESHOLD_DEFAULT, PARAMS_DEFAULT, format_threshold

    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    page = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert page.status_code == 200
    assert f"Bawaan {format_threshold(MISFIT_THRESHOLD_DEFAULT)}." in page.text
    assert f"Bawaan {PARAMS_DEFAULT['digits']}." in page.text
    assert "Bawaan compat." in page.text
    assert "Turunkan ke 1,20" not in page.text
