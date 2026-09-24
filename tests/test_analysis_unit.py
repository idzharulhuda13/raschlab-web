"""Unit tests for analysis orchestration, container building, encoding, and pagination.

Covers:
- Delimited response encoding (deterministic letter assignments, codes, keys, labels).
- Fail-closed validation (unassigned tokens, >4 incorrect tokens, invalid codes/keys, empty matrix).
- Winsteps blanking and extra-missing handling.
- Deterministic gzip container construction and roundtrip decompress.
- PRN roundtrip through raschlab.reader.read_matrix.
- Input file generation (analyze.CON parsed by raschlab.control.parse_control, items.lbl lines).
- String numeric localization (id_num) against the frozen contract cases.
- Pagination clamping and boundary slicing.
- Retention lifecycle sweep (expired row/file purge, near-expiry email notices via captured helper).
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from typing import Any

import pytest
from sqlalchemy import select

from app import auth
from app.analysis import (
    AnalysisError,
    build_matrix_gzip,
    id_num,
    paginate,
    retention_sweep,
    write_inputs,
)
from app.db import SessionLocal
from app.models import Analysis, AnalysisFile, Dataset, User
import raschlab.control
import raschlab.reader


# -----------------------------------------------------------------------------
# Delimited encoding cases
# -----------------------------------------------------------------------------

def test_delimited_encoding_deterministic_letters_and_codes_abc():
    """Two distinct incorrect tokens map to B and C deterministically, yielding codes='ABC'."""
    person_labels = ["Siswa01", "Siswa02", "Siswa03"]
    item_labels = ["Soal 1", "Soal 2", "Soal 3"]
    # Two distinct incorrect tokens: "0" and "9", appearing in different cell positions
    rows = [
        ["1", "0", "1"],
        ["9", "1", ""],
        ["1", "9", "0"],
    ]
    mapping = {
        "1": "correct",
        "0": "incorrect",
        "9": "incorrect",
        "": "missing",
    }

    gz_bytes = build_matrix_gzip("delimited", person_labels, item_labels, rows, mapping=mapping)
    container = json.loads(gzip.decompress(gz_bytes).decode("utf-8"))

    # Sorted distinct incorrect tokens are ["0", "9"], so "0" -> 'B', "9" -> 'C'
    assert container["v"] == 1
    assert container["codes"] == "ABC"
    assert container["key"] == "AAA"
    assert container["namlen"] == 7  # len("Siswa01") == 7

    lines = container["prn"].split("\n")
    assert len(lines) == 3
    # Row 1: "1" (A), "0" (B), "1" (A)
    assert lines[0] == "Siswa01ABA"
    # Row 2: "9" (C), "1" (A), "" (space)
    assert lines[1] == "Siswa02CA "
    # Row 3: "1" (A), "9" (C), "0" (B)
    assert lines[2] == "Siswa03ACB"


def test_delimited_encoding_deterministic_letter_assignment_order():
    """Letter assignment order depends on sorted distinct tokens, not row occurrence order."""
    person_labels = ["P1", "P2"]
    item_labels = ["I1", "I2"]
    mapping = {"1": "correct", "W": "incorrect", "B": "incorrect", "K": "incorrect", "": "missing"}

    # In rows_1, 'W' appears before 'B'
    rows_1 = [["W", "B"], ["1", "K"]]
    gz_1 = build_matrix_gzip("delimited", person_labels, item_labels, rows_1, mapping=mapping)
    c1 = json.loads(gzip.decompress(gz_1).decode("utf-8"))

    # In rows_2, 'B' appears before 'W'
    rows_2 = [["B", "W"], ["K", "1"]]
    gz_2 = build_matrix_gzip("delimited", person_labels, item_labels, rows_2, mapping=mapping)
    c2 = json.loads(gzip.decompress(gz_2).decode("utf-8"))

    # In both cases, sorted distinct tokens are B, K, W -> B->'B', K->'C', W->'D'
    assert c1["codes"] == "ABCD"
    assert c2["codes"] == "ABCD"

    # In c1: row 1 ('W', 'B') -> 'D', 'B'
    assert c1["prn"].split("\n")[0] == "P1DB"
    # In c2: row 1 ('B', 'W') -> 'B', 'D'
    assert c2["prn"].split("\n")[0] == "P1BD"


def test_delimited_encoding_empty_person_label_fallback():
    """Empty or missing person labels fall back to P0001, P0002, etc."""
    person_labels = ["", "  ", None]
    item_labels = ["Q1", "Q2"]
    rows = [["1", "0"], ["0", "1"], ["1", "1"]]
    mapping = {"1": "correct", "0": "incorrect"}

    gz_bytes = build_matrix_gzip("delimited", person_labels, item_labels, rows, mapping=mapping)
    container = json.loads(gzip.decompress(gz_bytes).decode("utf-8"))

    lines = container["prn"].split("\n")
    assert lines[0].startswith("P0001")
    assert lines[1].startswith("P0002")
    assert lines[2].startswith("P0003")


# -----------------------------------------------------------------------------
# Fail-closed cases
# -----------------------------------------------------------------------------

def test_fail_closed_unassigned_token():
    """Unassigned token raises AnalysisError with Indonesian copy identifying the token."""
    person_labels = ["P1"]
    item_labels = ["I1", "I2"]
    rows = [["1", "UNKNOWN_TOKEN"]]
    mapping = {"1": "correct"}

    with pytest.raises(AnalysisError, match="Ada token yang belum dipetakan: UNKNOWN_TOKEN"):
        build_matrix_gzip("delimited", person_labels, item_labels, rows, mapping=mapping)


def test_fail_closed_five_distinct_incorrect_tokens():
    """More than 4 distinct incorrect tokens exceeds B-E pool and raises AnalysisError."""
    person_labels = ["P1"]
    item_labels = ["I1", "I2", "I3", "I4", "I5", "I6"]
    rows = [["1", "2", "3", "4", "5", "6"]]
    mapping = {
        "1": "correct",
        "2": "incorrect",
        "3": "incorrect",
        "4": "incorrect",
        "5": "incorrect",
        "6": "incorrect",
    }

    with pytest.raises(AnalysisError, match="melebihi batas maksimal 4"):
        build_matrix_gzip("delimited", person_labels, item_labels, rows, mapping=mapping)


def test_fail_closed_winsteps_codes_outside_a_to_e():
    """Winsteps codes directive with characters outside A-E raises AnalysisError."""
    person_labels = ["P1"]
    item_labels = ["I1", "I2"]
    rows = ["12"]
    control = {"NI": 2, "KEY1": "12", "CODES": "12345"}

    with pytest.raises(AnalysisError, match="di luar huruf A-E; mesin hanya menerima A-E"):
        build_matrix_gzip("winsteps", person_labels, item_labels, rows, control=control)


def test_fail_closed_winsteps_key_not_in_codes():
    """Winsteps key character not present in CODES raises AnalysisError."""
    person_labels = ["P1"]
    item_labels = ["I1", "I2", "I3"]
    rows = ["ABC"]
    control = {"NI": 3, "KEY1": "ABD", "CODES": "ABC"}

    with pytest.raises(AnalysisError, match="tidak ada dalam kode respon"):
        build_matrix_gzip("winsteps", person_labels, item_labels, rows, control=control)


def test_fail_closed_empty_matrix():
    """Empty rows or all-blank response matrices fail closed."""
    # Delimited empty rows
    with pytest.raises(AnalysisError, match="Tidak ada baris data respon"):
        build_matrix_gzip("delimited", [], ["I1"], [], mapping={"1": "correct"})

    # Delimited all missing cells
    with pytest.raises(AnalysisError, match="semua sel kosong"):
        build_matrix_gzip(
            "delimited",
            ["P1"],
            ["I1", "I2"],
            [["", ""]],
            mapping={"": "missing"},
        )

    # Winsteps empty rows
    with pytest.raises(AnalysisError, match="Berkas PRN tidak memuat data baris"):
        build_matrix_gzip("winsteps", [], ["I1"], [], control={"NI": 1, "KEY1": "A", "CODES": "A"})

    # Winsteps all missing / blanks
    with pytest.raises(AnalysisError, match="semua sel kosong"):
        build_matrix_gzip(
            "winsteps",
            ["P1"],
            ["I1", "I2"],
            ["  "],
            control={"NI": 2, "KEY1": "AA", "CODES": "AB"},
        )


# -----------------------------------------------------------------------------
# Winsteps blanking
# -----------------------------------------------------------------------------

def test_winsteps_blanking():
    """Characters not in valid codes or marked extra-missing are blanked with spaces."""
    person_labels = ["Subj1", "Subj2"]
    item_labels = ["I1", "I2", "I3", "I4"]
    # Row 1 has 'A', 'B', 'C' (extra-missing), '9' (not in codes)
    # Row 2 has 'B', ' ', 'A', 'X' (not in codes)
    rows = ["ABC9", "B AX"]
    mapping = {"key": "AAAA", "codes": "ABC", "extra_missing": "C"}

    gz_bytes = build_matrix_gzip("winsteps", person_labels, item_labels, rows, mapping=mapping)
    container = json.loads(gzip.decompress(gz_bytes).decode("utf-8"))

    lines = container["prn"].split("\n")
    # 'A' and 'B' are valid. 'C' is in extra_missing -> blanked. '9' not in codes -> blanked.
    assert lines[0] == "Subj1AB  "
    # 'B' valid, ' ' blank, 'A' valid, 'X' not in codes -> blanked.
    assert lines[1] == "Subj2B A "


# -----------------------------------------------------------------------------
# Container roundtrip and gzip determinism
# -----------------------------------------------------------------------------

def test_container_roundtrip_and_gzip_determinism():
    """Repeated calls with identical inputs produce bitwise-identical gzip payloads."""
    person_labels = ["P1", "P2"]
    item_labels = ["ItemA", "ItemB"]
    rows = [["1", "0"], ["1", "1"]]
    mapping = {"1": "correct", "0": "incorrect"}

    call_1 = build_matrix_gzip("delimited", person_labels, item_labels, rows, mapping=mapping)
    call_2 = build_matrix_gzip("delimited", person_labels, item_labels, rows, mapping=mapping)

    assert call_1 == call_2
    assert len(call_1) > 0

    decomp = json.loads(gzip.decompress(call_1).decode("utf-8"))
    assert decomp["v"] == 1
    assert decomp["namlen"] == 2
    assert decomp["key"] == "AA"
    assert decomp["codes"] == "AB"
    assert decomp["prn"] == "P1AB\nP2AA"


# -----------------------------------------------------------------------------
# PRN roundtrip through raschlab.reader.read_matrix
# -----------------------------------------------------------------------------

def test_prn_roundtrip_through_raschlab_reader(tmp_path):
    """Container PRN data roundtrips through engine's raschlab.reader.read_matrix."""
    person_labels = ["Responden01", "Responden02", "Responden03"]
    item_labels = ["Item 1", "Item 2", "Item 3", "Item 4"]
    rows = [
        ["1", "0", "", "1"],
        ["1", "1", "1", "0"],
        ["0", "", "1", "1"],
    ]
    mapping = {"1": "correct", "0": "incorrect", "": "missing"}

    gz_bytes = build_matrix_gzip("delimited", person_labels, item_labels, rows, mapping=mapping)
    dataset = Dataset(
        id=1,
        user_id=1,
        filename="test.csv",
        kind="delimited",
        format="csv",
        status="ready",
        n_persons=3,
        n_items=4,
        item_labels_json=json.dumps(item_labels),
        mapping_json=json.dumps(mapping),
        summary_json="{}",
        raw_gzip=b"",
        raw_bytes=0,
        created_at=0,
    )

    con_path, prn_path = write_inputs(tmp_path, dataset, gz_bytes)

    ctrl = raschlab.control.parse_control(con_path)
    labels, read_rows = raschlab.reader.read_matrix(
        prn_path,
        item1=ctrl["ITEM1"],
        ni=ctrl["NI"],
        namlen=ctrl["NAMLEN"],
    )

    assert labels == ["Responden01", "Responden02", "Responden03"]
    # Row 1: "1" -> A, "0" -> B, "" -> space, "1" -> A => "AB A"
    # Row 2: "1" -> A, "1" -> A, "1" -> A, "0" -> B => "AAAB"
    # Row 3: "0" -> B, "" -> space, "1" -> A, "1" -> A => "B AA"
    assert read_rows == ["AB A", "AAAB", "B AA"]


# -----------------------------------------------------------------------------
# write_inputs producing valid CON and items.lbl
# -----------------------------------------------------------------------------

def test_write_inputs_con_and_items_lbl(tmp_path):
    """write_inputs writes CON accepted by parse_control with NI==len(KEY1) and items.lbl count."""
    n_items = 5
    item_labels = [
        "Soal Pilihan Ganda 1",
        "Soal\r\nDengan Baris Baru",
        "Soal Nomor 3",
        "Soal Nomor 4",
        "Soal Nomor 5",
    ]
    rows = [["1"] * n_items]
    mapping = {"1": "correct"}

    gz_bytes = build_matrix_gzip("delimited", ["P1"], item_labels, rows, mapping=mapping)
    dataset = Dataset(
        n_items=n_items,
        item_labels_json=json.dumps(item_labels),
    )

    con_path, prn_path = write_inputs(tmp_path, dataset, gz_bytes)

    assert os.path.isfile(con_path)
    assert os.path.isfile(prn_path)

    # Validate analyze.CON via engine's parse_control
    ctrl = raschlab.control.parse_control(con_path)
    assert ctrl["NI"] == n_items
    assert len(ctrl["KEY1"]) == ctrl["NI"]
    assert ctrl["KEY1"] == "AAAAA"
    assert ctrl["CODES"] == "A"
    assert ctrl["NAMLEN"] == 2
    assert ctrl["ITEM1"] == 3
    assert ctrl["DATA"] == "data.prn"
    assert ctrl["ILABEL"] == "items.lbl"

    # Validate items.lbl line count and newline sanitization
    lbl_path = os.path.join(tmp_path, "items.lbl")
    assert os.path.isfile(lbl_path)
    with open(lbl_path, "r", encoding="utf-8") as f:
        lbl_content = f.read()

    lbl_lines = lbl_content.splitlines()
    assert len(lbl_lines) == n_items
    assert "\r" not in lbl_content
    # Newlines inside labels must have been replaced with spaces
    assert lbl_lines[1] == "Soal Dengan Baris Baru"


# -----------------------------------------------------------------------------
# id_num against the case list
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw_input, expected",
    [
        ("0.65", "0,65"),
        ("-1.23", "-1,23"),
        ("1234", "1.234"),
        ("1000000.5", "1.000.000,5"),
        ("P0001", "P0001"),
        (None, ""),
        ("", ""),
        ("0", "0"),
        ("-0.05", "-0,05"),
        ("+1234567", "+1.234.567"),
        ("100", "100"),
        ("1000", "1.000"),
        ("10000", "10.000"),
        ("100000", "100.000"),
        ("1000000", "1.000.000"),
        ("Item 1", "Item 1"),
        ("INF", "INF"),
    ],
)
def test_id_num_cases(raw_input: Any, expected: str):
    """String numeric formatting matches the frozen contract without float coercion."""
    assert id_num(raw_input) == expected


# -----------------------------------------------------------------------------
# paginate clamping
# -----------------------------------------------------------------------------

def test_paginate_clamping():
    """paginate clamps page numbers, computes bounds, and slices lists properly."""
    data = list(range(1250))  # 1250 rows with default 500 per page -> 3 pages

    # Page 1
    p1 = paginate(data, 1, per_page=500)
    assert p1.page == 1
    assert p1.total_pages == 3
    assert p1.total_rows == 1250
    assert len(p1) == 500
    assert p1.rows[0] == 0
    assert p1.rows[-1] == 499
    assert not p1.has_prev
    assert p1.has_next
    assert p1.prev_page == 1
    assert p1.next_page == 2

    # Page 2
    p2 = paginate(data, 2, per_page=500)
    assert p2.page == 2
    assert len(p2) == 500
    assert p2.rows[0] == 500
    assert p2.rows[-1] == 999
    assert p2.has_prev
    assert p2.has_next

    # Page 3 (partial page)
    p3 = paginate(data, 3, per_page=500)
    assert p3.page == 3
    assert len(p3) == 250
    assert p3.rows[0] == 1000
    assert p3.rows[-1] == 1249
    assert p3.has_prev
    assert not p3.has_next
    assert p3.next_page == 3

    # Clamping below 1
    p_neg = paginate(data, -5, per_page=500)
    assert p_neg.page == 1
    p_zero = paginate(data, 0, per_page=500)
    assert p_zero.page == 1

    # Clamping above total_pages
    p_over = paginate(data, 999, per_page=500)
    assert p_over.page == 3

    # Invalid / non-integer input
    p_str = paginate(data, "invalid", per_page=500)
    assert p_str.page == 1
    p_none = paginate(data, None, per_page=500)
    assert p_none.page == 1

    # Empty rows list
    p_empty = paginate([], 1, per_page=500)
    assert p_empty.page == 1
    assert p_empty.total_pages == 1
    assert p_empty.total_rows == 0
    assert len(p_empty) == 0

    # Key/dict/attribute access
    assert p1["page"] == 1
    assert p1.get("total_pages") == 3


# -----------------------------------------------------------------------------
# retention_sweep on SQLite session
# -----------------------------------------------------------------------------

def test_retention_sweep_lifecycle(sent_emails):
    """retention_sweep purges expired records and sends emails for near-expiry analyses."""
    now = 1_700_000_000

    with SessionLocal() as db:
        user = User(
            email="researcher@campus.test",
            email_normalized="researcher@campus.test",
            password_hash="fake-hash",
            created_at=now,
            verified_at=now,
        )
        db.add(user)
        db.commit()

        dataset = Dataset(
            user_id=user.id,
            filename="instrumen_ujian.csv",
            kind="delimited",
            format="csv",
            status="ready",
            n_persons=10,
            n_items=5,
            item_labels_json="[]",
            mapping_json="{}",
            summary_json="{}",
            raw_gzip=b"test",
            raw_bytes=4,
            created_at=now,
        )
        db.add(dataset)
        db.commit()

        # 1. Expired analysis: expires_at <= now
        a_expired = Analysis(
            user_id=user.id,
            dataset_id=dataset.id,
            status="done",
            params_json="{}",
            engine_ref="8e8ac67",
            created_at=now - 180 * 86400,
            expires_at=now - 100,
        )
        db.add(a_expired)
        db.commit()

        af_expired = AnalysisFile(
            analysis_id=a_expired.id,
            filename="item_table_15.1.csv",
            content_gzip=gzip.compress(b"data"),
            sha256="abc",
            bytes=4,
        )
        db.add(af_expired)
        db.commit()
        expired_id = a_expired.id
        expired_file_id = af_expired.id

        # 2. Near-expiry analysis: within 14 days, status done, notice_sent_at is None
        a_near = Analysis(
            user_id=user.id,
            dataset_id=dataset.id,
            status="done",
            params_json="{}",
            engine_ref="8e8ac67",
            created_at=now - 170 * 86400,
            expires_at=now + 5 * 86400,
            notice_sent_at=None,
        )
        db.add(a_near)

        # 3. Far-from-expiry analysis: > 14 days
        a_safe = Analysis(
            user_id=user.id,
            dataset_id=dataset.id,
            status="done",
            params_json="{}",
            engine_ref="8e8ac67",
            created_at=now,
            expires_at=now + 100 * 86400,
            notice_sent_at=None,
        )
        db.add(a_safe)

        # 4. Near-expiry analysis that already received notice
        a_already_notified = Analysis(
            user_id=user.id,
            dataset_id=dataset.id,
            status="done",
            params_json="{}",
            engine_ref="8e8ac67",
            created_at=now - 170 * 86400,
            expires_at=now + 5 * 86400,
            notice_sent_at=now - 86400,
        )
        db.add(a_already_notified)
        db.commit()

        near_id = a_near.id
        safe_id = a_safe.id
        already_notified_id = a_already_notified.id

        # Run sweep
        result = retention_sweep(db, now=now)

        assert result["deleted"] == 1
        assert result["notified"] == 1

        # Assert expired analysis and its files are gone
        assert db.scalar(select(Analysis).where(Analysis.id == expired_id)) is None
        assert db.scalar(select(AnalysisFile).where(AnalysisFile.id == expired_file_id)) is None

        # Assert near-expiry analysis has notice_sent_at recorded
        db_near = db.scalar(select(Analysis).where(Analysis.id == near_id))
        assert db_near is not None
        assert db_near.notice_sent_at == now

        # Assert safe analysis is untouched
        db_safe = db.scalar(select(Analysis).where(Analysis.id == safe_id))
        assert db_safe is not None
        assert db_safe.notice_sent_at is None

        # Assert already-notified analysis unchanged
        db_already = db.scalar(select(Analysis).where(Analysis.id == already_notified_id))
        assert db_already is not None
        assert db_already.notice_sent_at == now - 86400

        # Assert captured email received notification
        assert len(sent_emails) == 1
        to_email, subject, html = sent_emails[0]
        assert to_email == "researcher@campus.test"
        assert "Pemberitahuan Masa Simpan" in subject
        assert "instrumen_ujian.csv" in html


def test_retention_sweep_email_failure_resilience(monkeypatch):
    """When email sending fails, notice_sent_at is left NULL to allow retry without crashing."""
    now = 1_700_000_000

    def failing_send_email(*args, **kwargs):
        raise RuntimeError("SMTP connection timeout")

    monkeypatch.setattr(auth, "send_email", failing_send_email)

    with SessionLocal() as db:
        user = User(
            email="fail@campus.test",
            email_normalized="fail@campus.test",
            password_hash="fake-hash",
            created_at=now,
            verified_at=now,
        )
        db.add(user)
        db.commit()

        dataset = Dataset(
            user_id=user.id,
            filename="data_fail.csv",
            kind="delimited",
            format="csv",
            status="ready",
            n_persons=5,
            n_items=2,
            item_labels_json="[]",
            mapping_json="{}",
            summary_json="{}",
            raw_gzip=b"x",
            raw_bytes=1,
            created_at=now,
        )
        db.add(dataset)
        db.commit()

        analysis = Analysis(
            user_id=user.id,
            dataset_id=dataset.id,
            status="done",
            params_json="{}",
            engine_ref="8e8ac67",
            created_at=now,
            expires_at=now + 3 * 86400,
            notice_sent_at=None,
        )
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id

        result = retention_sweep(db, now=now)
        assert result["notified"] == 0

        db_analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert db_analysis is not None
        assert db_analysis.notice_sent_at is None


def test_retention_sweep_send_email_signature_contract(monkeypatch):
    """Ensure retention_sweep passes every required parameter of app.emailer.send_email."""
    import inspect
    from app.emailer import send_email as real_send_email

    params = inspect.signature(real_send_email).parameters
    required_params = {
        name
        for name, param in params.items()
        if param.default is inspect.Parameter.empty
    }

    recorded_kwargs: dict[str, Any] = {}

    def recorder(*args: Any, **kwargs: Any) -> None:
        recorded_kwargs.update(kwargs)

    monkeypatch.setattr(auth, "send_email", recorder)

    now = 1_700_000_000
    with SessionLocal() as db:
        user = User(
            email="researcher@campus.test",
            email_normalized="researcher@campus.test",
            password_hash="fake-hash",
            created_at=now,
            verified_at=now,
        )
        db.add(user)
        db.commit()

        dataset = Dataset(
            user_id=user.id,
            filename="survey.csv",
            kind="delimited",
            format="csv",
            status="ready",
            n_persons=5,
            n_items=2,
            item_labels_json="[]",
            mapping_json="{}",
            summary_json="{}",
            raw_gzip=b"x",
            raw_bytes=1,
            created_at=now,
        )
        db.add(dataset)
        db.commit()

        analysis = Analysis(
            user_id=user.id,
            dataset_id=dataset.id,
            status="done",
            params_json="{}",
            engine_ref="8e8ac67",
            created_at=now - 170 * 86400,
            expires_at=now + 5 * 86400,
            notice_sent_at=None,
        )
        db.add(analysis)
        db.commit()

        result = retention_sweep(db, now=now)
        assert result["notified"] == 1, f"Expected 1 notification sent, got {result['notified']}"

        missing = required_params - set(recorded_kwargs.keys())
        assert not missing, (
            f"auth.send_email kwargs {set(recorded_kwargs.keys())} do not cover all required "
            f"parameters of app.emailer.send_email: missing {missing}"
        )

