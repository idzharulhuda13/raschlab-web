"""Tests for attaching a delete list (pdfile/idfile) to a run (F16-A).

Every case drives run_for_dataset with a small in-memory dataset and a monkeypatched
app.analysis.run_analyze, so no real engine run happens. The invalid uploads prove that
validation happens before anything is handed to the engine and before an Analysis row exists.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

import app.analysis as analysis_module
from app.analysis import (
    DELETE_LIST_MAX_BYTES,
    OUTPUT_FILES,
    AnalysisError,
    build_matrix_gzip,
    parse_delete_list,
    run_for_dataset,
)
from app.db import SessionLocal
from app.models import Analysis, AnalysisFile, Dataset, User
from app.security import hash_password, now_epoch
from tests.test_f9_ux import _build_test_files


def _make_dataset(db) -> Dataset:
    """Insert a committed dataset with a precomputed matrix so no parsing is needed."""
    now = now_epoch()
    user = User(
        email="delete-list@example.test",
        email_normalized="delete-list@example.test",
        password_hash=hash_password("katasandi-delete-123"),
        created_at=now,
        verified_at=now,
    )
    db.add(user)
    db.commit()

    mapping = {"1": "correct", "0": "incorrect"}
    matrix = build_matrix_gzip(
        "delimited",
        ["P1", "P2"],
        ["I1", "I2"],
        [["1", "0"], ["0", "1"]],
        mapping=mapping,
    )
    dataset = Dataset(
        user_id=user.id,
        filename="sample.csv",
        kind="delimited",
        format="csv",
        status="committed",
        n_persons=2,
        n_items=2,
        item_labels_json=json.dumps(["I1", "I2"]),
        mapping_json=json.dumps(mapping),
        summary_json=json.dumps({}),
        raw_gzip=gzip.compress(b"", mtime=0.0),
        raw_bytes=0,
        created_at=now,
        committed_at=now,
        matrix_gzip=matrix,
    )
    db.add(dataset)
    db.commit()
    return dataset


def _install_fake_engine(monkeypatch) -> list[dict]:
    """Replace run_analyze with a stub that records its call and writes the output tables."""
    calls: list[dict] = []

    def fake_run_analyze(*args, **kwargs) -> None:
        captured = dict(kwargs)
        pdfile_path = kwargs.get("pdfile_path")
        if pdfile_path is not None:
            captured["pdfile_bytes"] = Path(pdfile_path).read_bytes()
            captured["pdfile_name"] = Path(pdfile_path).name
        idfile_path = kwargs.get("idfile_path")
        if idfile_path is not None:
            captured["idfile_bytes"] = Path(idfile_path).read_bytes()
            captured["idfile_name"] = Path(idfile_path).name
        calls.append(captured)

        out_dir = kwargs["out_dir"]
        for name, text in _build_test_files().items():
            Path(out_dir, name).write_bytes(text.encode("utf-8"))

    monkeypatch.setattr(analysis_module, "run_analyze", fake_run_analyze)
    return calls


def _analysis_count(db, dataset_id: int) -> int:
    return db.scalar(
        select(func.count(Analysis.id)).where(Analysis.dataset_id == dataset_id)
    )


def test_valid_pdfile_reaches_engine_and_missing_idfile_is_none(monkeypatch):
    calls = _install_fake_engine(monkeypatch)
    uploaded = b"item1\nitem2\nitem3\n"
    parsed = parse_delete_list("hapus.txt", uploaded)

    with SessionLocal() as db:
        dataset = _make_dataset(db)
        analysis = run_for_dataset(db, dataset, delete_lists={"pdfile": parsed})
        assert analysis.status == "done"

    assert len(calls) == 1
    assert calls[0]["pdfile_name"] == "pdfile_input.TXT"
    assert calls[0]["pdfile_bytes"] == uploaded
    assert calls[0]["idfile_path"] is None


def test_params_json_records_metadata_and_never_the_text(monkeypatch):
    _install_fake_engine(monkeypatch)
    uploaded = b"alpha\nbeta\n"
    parsed = parse_delete_list("hapus.dat", uploaded)

    with SessionLocal() as db:
        dataset = _make_dataset(db)
        analysis = run_for_dataset(db, dataset, delete_lists={"pdfile": parsed})
        assert analysis.status == "done"
        params = json.loads(analysis.params_json)

    assert params["pdfile"] == {
        "name": "hapus.dat",
        "sha256": hashlib.sha256(uploaded).hexdigest(),
        "rows": 2,
        "bytes": len(uploaded),
    }
    assert params["idfile"] is None
    assert set(params["pdfile"]) == {"name", "sha256", "rows", "bytes"}
    assert "text" not in params["pdfile"]
    serialized = json.dumps(params)
    assert "alpha" not in serialized
    assert "beta" not in serialized


def test_input_row_is_stored_and_output_rows_survive(monkeypatch):
    _install_fake_engine(monkeypatch)
    uploaded = b"drop me\n"
    parsed = parse_delete_list("hapus.csv", uploaded)

    with SessionLocal() as db:
        dataset = _make_dataset(db)
        analysis = run_for_dataset(db, dataset, delete_lists={"pdfile": parsed})
        assert analysis.status == "done"

        files = db.scalars(
            select(AnalysisFile).where(AnalysisFile.analysis_id == analysis.id)
        ).all()
        file_map = {f.filename: f for f in files}

        assert "input_pdfile.TXT" in file_map
        stored = file_map["input_pdfile.TXT"]
        assert gzip.decompress(stored.content_gzip) == uploaded
        assert stored.sha256 == hashlib.sha256(uploaded).hexdigest()
        assert stored.bytes == len(uploaded)

        for filename in OUTPUT_FILES:
            assert filename in file_map


def test_exe_extension_is_refused_before_the_engine(monkeypatch):
    calls = _install_fake_engine(monkeypatch)

    with SessionLocal() as db:
        dataset = _make_dataset(db)
        with pytest.raises(AnalysisError) as excinfo:
            parsed = parse_delete_list("list.exe", b"1\n2\n")
            run_for_dataset(db, dataset, delete_lists={"pdfile": parsed})
        assert str(excinfo.value) == "Daftar hapus harus berupa berkas teks (.txt, .csv, atau .dat)."
        assert calls == []
        assert _analysis_count(db, dataset.id) == 0


def test_empty_list_is_refused_before_the_engine(monkeypatch):
    calls = _install_fake_engine(monkeypatch)

    with SessionLocal() as db:
        dataset = _make_dataset(db)
        with pytest.raises(AnalysisError) as excinfo:
            parsed = parse_delete_list("kosong.txt", b"\n   \n\n")
            run_for_dataset(db, dataset, delete_lists={"pdfile": parsed})
        assert str(excinfo.value) == "Daftar hapus kosong."
        assert calls == []
        assert _analysis_count(db, dataset.id) == 0


def test_oversized_list_is_refused(monkeypatch):
    calls = _install_fake_engine(monkeypatch)
    oversized = b"x" * (DELETE_LIST_MAX_BYTES + 1)

    with pytest.raises(AnalysisError) as excinfo:
        parse_delete_list("besar.txt", oversized)
    assert str(excinfo.value) == "Daftar hapus terlalu besar (maksimal 2 MB)."
    assert calls == []


def test_binary_upload_is_refused(monkeypatch):
    """latin-1 decodes every byte, so the binary branch needs its own check, not the decode loop."""
    calls = _install_fake_engine(monkeypatch)
    binary = bytes(range(256)) * 4

    with pytest.raises(AnalysisError) as exc:
        parse_delete_list("hapus.txt", binary)
    assert str(exc.value) == "Daftar hapus harus berupa teks biasa, bukan berkas biner."

    with SessionLocal() as db:
        assert _analysis_count(db, 0) == 0
    assert calls == []


def test_bom_is_stripped_and_does_not_count_as_a_row():
    uploaded = "\ufeff219\n543\n553\n".encode("utf-8")

    parsed = parse_delete_list("hapus.txt", uploaded)

    assert parsed["rows"] == 3
    assert "\ufeff" not in parsed["text"]
    assert parsed["text"].splitlines()[0] == "219"


def test_latin1_list_is_stored_byte_identical(monkeypatch):
    """The audit row must be the uploaded bytes, not a re-encoding of them."""
    _install_fake_engine(monkeypatch)
    uploaded = "219\n\xe9tude\n553\n".encode("latin-1")

    parsed = parse_delete_list("hapus.txt", uploaded)
    assert parsed["rows"] == 3

    with SessionLocal() as db:
        dataset = _make_dataset(db)
        analysis = run_for_dataset(db, dataset, delete_lists={"pdfile": parsed})
        assert analysis.status == "done"
        stored = db.scalars(
            select(AnalysisFile).where(
                AnalysisFile.analysis_id == analysis.id,
                AnalysisFile.filename == "input_pdfile.TXT",
            )
        ).one()

    assert gzip.decompress(stored.content_gzip) == uploaded
    assert stored.sha256 == hashlib.sha256(uploaded).hexdigest()
    assert stored.bytes == len(uploaded)
