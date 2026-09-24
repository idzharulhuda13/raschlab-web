"""Unit and independent cross-check tests for dataset parsers.

Verifies wide tabular (CSV) and Winsteps (.CON + .prn) parsing paths against
exact combinatorial goldens (PLAN.md D7) and independent pandas extraction pipelines.
"""

import os
from pathlib import Path
import sys

import pandas as pd
import pytest

from app.parsers import (
    count_all_missing_persons,
    distinct_tokens,
    missing_per_item,
    parse_control,
    parse_delimited,
    parse_prn,
    validate_mapping,
)
from app.storage import MAX_CELLS, MAX_UPLOAD_BYTES, StorageError

FIXTURES_DIR = Path(__file__).parent / "fixtures"

GOLDEN_CSV_MISSING: list[int] = [
    11, 10, 10, 10, 11, 10, 10, 10, 10, 11,
    10, 10, 10, 11, 11, 10, 10, 10, 11, 11,
    10, 10, 10, 11, 11, 10, 10, 10, 11, 11,
    10, 10, 10, 11, 10, 10, 10, 10, 11, 10,
]

GOLDEN_PRN_MISSING: list[int] = [
    3, 3, 2, 3, 2, 3, 2, 3, 3, 2,
    3, 2, 3, 2, 3, 3, 2, 3, 2, 3,
]


def test_csv_parse_shape_and_golden_missing():
    csv_path = FIXTURES_DIR / "sample_300x40.csv"
    raw = csv_path.read_bytes()
    parsed = parse_delimited(raw)

    assert len(parsed.person_labels) == 300
    assert len(parsed.item_labels) == 40
    assert len(parsed.rows) == 300
    assert all(len(row) == 40 for row in parsed.rows)
    assert parsed.person_labels[0] == "P0001"
    assert parsed.person_labels[-1] == "P0300"
    assert parsed.item_labels[0] == "I01"
    assert parsed.item_labels[-1] == "I40"

    ours = missing_per_item(parsed)
    assert ours == GOLDEN_CSV_MISSING
    assert sum(ours) == 413


def test_prn_parse_shape_and_golden_missing():
    con_path = FIXTURES_DIR / "sample_winsteps.CON"
    prn_path = FIXTURES_DIR / "sample_winsteps.prn"

    ctrl = parse_control(con_path.read_bytes())
    parsed = parse_prn(prn_path.read_bytes(), ctrl)

    assert len(parsed.person_labels) == 60
    assert len(parsed.rows) == 60
    assert all(len(row) == 20 for row in parsed.rows)
    assert parsed.person_labels[0] == "P0001"
    assert parsed.person_labels[-1] == "P0060"

    ours = missing_per_item(parsed, codes=ctrl.get("CODES"))
    assert ours == GOLDEN_PRN_MISSING
    assert sum(ours) == 52


def test_csv_pandas_cross_check():
    csv_path = FIXTURES_DIR / "sample_300x40.csv"
    raw = csv_path.read_bytes()
    parsed = parse_delimited(raw)
    ours = missing_per_item(parsed)

    df = pd.read_csv(csv_path, dtype=str)
    df_items = df.drop(df.columns[0], axis=1)
    pandas_missing = df_items.isna().sum().tolist()

    assert pandas_missing == ours
    assert pandas_missing == GOLDEN_CSV_MISSING
    assert ours == GOLDEN_CSV_MISSING


def test_prn_pandas_cross_check():
    con_path = FIXTURES_DIR / "sample_winsteps.CON"
    prn_path = FIXTURES_DIR / "sample_winsteps.prn"

    ctrl = parse_control(con_path.read_bytes())
    parsed = parse_prn(prn_path.read_bytes(), ctrl)
    ours = missing_per_item(parsed, codes=ctrl.get("CODES"))

    colspecs = [(10 + c, 11 + c) for c in range(20)]
    df_prn = pd.read_fwf(prn_path, colspecs=colspecs, header=None)
    codes = set(str(ctrl["CODES"]))

    pandas_missing = [
        int((~df_prn[col].fillna("").astype(str).str.strip().isin(codes)).sum())
        for col in df_prn.columns
    ]

    assert pandas_missing == ours
    assert pandas_missing == GOLDEN_PRN_MISSING
    assert ours == GOLDEN_PRN_MISSING


def test_delimiter_sniffing_semicolon():
    raw_semicolon = (
        b"id;item_a;item_b;item_c\n"
        b"P0001;1;0;1\n"
        b"P0002;0;1;0\n"
        b"P0003;1;1;NA\n"
    )
    parsed = parse_delimited(raw_semicolon)
    assert parsed.person_labels == ["P0001", "P0002", "P0003"]
    assert parsed.item_labels == ["item_a", "item_b", "item_c"]
    assert parsed.rows == [
        ["1", "0", "1"],
        ["0", "1", "0"],
        ["1", "1", "NA"],
    ]


def test_control_key1_length_mismatch_rejected():
    con_mismatch = (
        b"&INST\n"
        b"ITEM1=1\n"
        b"NI=10\n"
        b"NAMLEN=5\n"
        b"KEY1=ABCDE\n"
        b"&END\n"
    )
    with pytest.raises(ValueError, match=r"KEY1 length \(5\) does not match NI \(10\)"):
        parse_control(con_mismatch)


def test_over_cap_upload_raises_storage_error():
    oversize_payload = b"x" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(StorageError, match=r"exceeds MAX_UPLOAD_BYTES"):
        parse_delimited(oversize_payload)

    n_items = 999
    rows = MAX_CELLS // n_items + 1
    header = ("id," + ",".join(f"c{i}" for i in range(n_items)) + "\n").encode()
    row = ("P" + ",1" * n_items + "\n").encode()
    oversize_cells = header + row * rows
    assert len(oversize_cells) < MAX_UPLOAD_BYTES
    with pytest.raises(StorageError, match=r"exceeds MAX_CELLS limit"):
        parse_delimited(oversize_cells)


def test_validate_mapping_returns_unassigned_tokens():
    tokens = ["0", "1", "NA", "99", "INVALID", ""]
    mapping = {
        "0": "incorrect",
        "1": "correct",
        "na": "missing",
        "": "missing",
    }
    unassigned = validate_mapping(tokens, mapping)
    assert unassigned == ["99", "INVALID"]


@pytest.mark.skipif(
    not os.path.isdir("/root/projects/raschlab"),
    reason="Engine repo /root/projects/raschlab not present",
)
def test_control_parser_parity_with_engine():
    engine_dir = "/root/projects/raschlab"
    sys.path.insert(0, engine_dir)
    try:
        from raschlab.control import parse_control as engine_parse_control

        con_path = FIXTURES_DIR / "sample_winsteps.CON"
        our_ctrl = parse_control(con_path.read_bytes())
        engine_ctrl = engine_parse_control(str(con_path))

        for key in ("ITEM1", "NI", "NAMLEN", "KEY1", "CODES"):
            assert our_ctrl[key] == engine_ctrl[key]
    finally:
        if engine_dir in sys.path:
            sys.path.remove(engine_dir)


def test_prn_extra_missing_increases_total_missing():
    con_path = FIXTURES_DIR / "sample_winsteps.CON"
    prn_path = FIXTURES_DIR / "sample_winsteps.prn"

    ctrl = parse_control(con_path.read_bytes())
    parsed = parse_prn(prn_path.read_bytes(), ctrl)

    missing_default = missing_per_item(parsed, codes=ctrl.get("CODES"))
    missing_empty_extra = missing_per_item(parsed, codes=ctrl.get("CODES"), extra_missing="")
    assert sum(missing_default) == sum(missing_empty_extra)
    assert sum(missing_default) == 52

    missing_with_a = missing_per_item(parsed, codes=ctrl.get("CODES"), extra_missing="A")
    total_a = sum(row.count("A") for row in parsed.rows)
    assert total_a == 574
    assert sum(missing_with_a) == 52 + 574
    assert sum(missing_with_a) - sum(missing_default) == 574


def test_delimiter_sniffing_quoted_delimiters():
    raw_quoted_semicolons = (
        b'"Nama;Kelas;Sekolah;Kota;Provinsi;Negara",I01,I02,I03\n'
        b'"Budi;1;SMA;JKT;DKI;ID",1,0,1\n'
        b'"Siti;2;SMP;BDG;JBR;ID",0,1,1\n'
    )
    parsed = parse_delimited(raw_quoted_semicolons)
    assert parsed.item_labels == ["Nama;Kelas;Sekolah;Kota;Provinsi;Negara", "I01", "I02", "I03"]
    assert len(parsed.rows[0]) == 4

    raw_quoted_commas = (
        b'id,I01,I02,I03\n'
        b'"Budi, Jr.",1,0,1\n'
        b'"Siti, PhD",0,1,1\n'
    )
    parsed_comma = parse_delimited(raw_quoted_commas)
    assert parsed_comma.person_labels == ["Budi, Jr.", "Siti, PhD"]
    assert parsed_comma.item_labels == ["I01", "I02", "I03"]
    assert parsed_comma.rows == [["1", "0", "1"], ["0", "1", "1"]]


def test_count_all_missing_persons():
    raw_csv = (
        b"id,I01,I02,I03\n"
        b"P0001,1,0,1\n"
        b"P0002,,,\n"
        b"P0003,0,1,0\n"
    )
    parsed = parse_delimited(raw_csv)
    mapping = {"": "missing", "0": "incorrect", "1": "correct"}
    assert count_all_missing_persons(parsed, mapping=mapping) == 1


def test_indonesian_person_label_headers_and_normalization():
    for header_name in ["Responden", "responden*", "responden_id"]:
        csv_text = f"{header_name},I01,I02,I03\nP0001,1,0,1\nP0002,0,1,1\nP0003,1,1,0\n"
        parsed = parse_delimited(csv_text.encode("utf-8"))
        assert parsed.item_labels == ["I01", "I02", "I03"]
        assert parsed.person_labels == ["P0001", "P0002", "P0003"]
        tokens = distinct_tokens(parsed)
        for pid in ["P0001", "P0002", "P0003"]:
            assert pid not in tokens
        assert set(tokens.keys()) == {"0", "1"}

