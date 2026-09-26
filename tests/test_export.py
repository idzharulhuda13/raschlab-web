"""Tests for the Excel export feature (/analyses/{id}/export)."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from typing import Optional

from fastapi.testclient import TestClient
import openpyxl
import pytest

from app.analysis import build_matrix_gzip, write_inputs
from app.auth import COOKIE_NAME
from app.db import SessionLocal
from app.explore import build_compare_pairs
from app.export import (
    COMPARE_HEADER,
    COMPARE_NUMERIC,
    EXPORT_MAX_CELLS,
    EXPORT_MAX_ROWS,
    EXPORT_RATE_MSG,
    EXPORT_TABLE_NOT_FOUND_MSG,
    HEADER_ROWS,
    SHEET_TITLES,
    TABLE_KEYS,
    TABLE_NUMERIC,
    XLSX_MEDIA_TYPE,
    build_xlsx,
)
from app.models import Analysis, AnalysisFile, Dataset, SessionRow, User
from app.parsers import parse_delimited
from app.ratelimit import _COUNTS
from app.security import hash_password, hash_token, new_token, now_epoch

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

_ITEM_HEADER_ROW0 = ["ENTRY", "TOTAL", "TOTAL", "JMLE", "MODEL", "INFIT", "INFIT", "OUTFIT", "OUTFIT", "PTMEASUR-AL", "EXP.", "EXACT", "EXACT", "ITEM"]
_ITEM_HEADER_ROW1 = ["", "SCORE", "COUNT", "MEASURE", "S.E.", "MNSQ", "ZSTD", "MNSQ", "ZSTD", "CORR.", "", "OBS%", "EXPECTED%", ""]

_PERSON_HEADER_ROW0 = ["ENTRY", "TOTAL", "TOTAL", "JMLE", "MODEL", "INFIT", "INFIT", "OUTFIT", "OUTFIT", "PTMEASUR-AL", "EXP.", "EXACT", "EXACT", "PERSON"]
_PERSON_HEADER_ROW1 = ["", "SCORE", "COUNT", "MEASURE", "S.E.", "MNSQ", "ZSTD", "MNSQ", "ZSTD", "CORR.", "", "OBS%", "EXPECTED%", ""]


# ---------------------------------------------------------------------------
# Low-level helpers copied verbatim from tests/test_explorer_routes.py
# ---------------------------------------------------------------------------

def _csv(rows: list[list[str]]) -> str:
    """Produce CSV text exactly as the engine writes it: commas, CRLF, trailing CRLF."""
    return "\r\n".join(",".join(cell for cell in row) for row in rows) + "\r\n"


def _seed_done(
    user_id: int,
    filename: str,
    files: dict[str, str],
    status: str = "done",
    created_at: Optional[int] = None,
    n_persons: int = 30,
    n_items: int = 12,
) -> int:
    """Seed Dataset + Analysis + AnalysisFile rows without running the engine.

    Returns the analysis id.
    """
    now = created_at if created_at is not None else now_epoch()
    with SessionLocal() as db:
        raw_text = b"dummy,csv,content"
        raw_gz = gzip.compress(raw_text, mtime=0)
        item_labels = [f"Item{i+1}" for i in range(n_items)]
        dataset = Dataset(
            user_id=user_id,
            filename=filename,
            kind="delimited",
            format="csv",
            status="ready",
            n_persons=n_persons,
            n_items=n_items,
            item_labels_json=json.dumps(item_labels),
            mapping_json=json.dumps({"1": "correct", "0": "incorrect"}),
            summary_json=json.dumps({}),
            raw_gzip=raw_gz,
            raw_bytes=len(raw_text),
            created_at=now,
            committed_at=now,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

        analysis = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status=status,
            params_json=json.dumps({"mode": "compat", "digits": 2}),
            engine_ref="test-ref",
            created_at=now,
            expires_at=now + 180 * 86400,
            finished_at=now if status == "done" else None,
            elapsed_ms=1234 if status == "done" else None,
        )
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id

        for fname, text in files.items():
            raw_bytes = text.encode("utf-8")
            af = AnalysisFile(
                analysis_id=analysis_id,
                filename=fname,
                content_gzip=gzip.compress(raw_bytes, mtime=0),
                sha256=hashlib.sha256(raw_bytes).hexdigest(),
                bytes=len(raw_bytes),
            )
            db.add(af)
        db.commit()

    return analysis_id


def _create_user_with_token(client: TestClient, email: str = "researcher@example.test") -> tuple[int, str]:
    with SessionLocal() as db:
        now = now_epoch()
        user = User(
            email=email,
            email_normalized=email.lower().strip(),
            password_hash=hash_password("katasandi-export-123"),
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
    return user_id, token


# ---------------------------------------------------------------------------
# The Seven Tests
# ---------------------------------------------------------------------------

def test_cell_parity_with_engine_workbook(tmp_path):
    fixture_path = FIXTURES_DIR / "sample_300x40.csv"
    csv_bytes = fixture_path.read_bytes()

    parsed = parse_delimited(csv_bytes)
    mapping = {"1": "correct", "0": "incorrect", "NA": "missing", "": "missing"}
    matrix_gzip = build_matrix_gzip(
        kind="delimited",
        person_labels=parsed.person_labels,
        item_labels=parsed.item_labels,
        rows=parsed.rows,
        mapping=mapping,
    )
    dataset = Dataset(
        n_items=len(parsed.item_labels),
        item_labels_json=json.dumps(parsed.item_labels),
    )
    con_path, data_path = write_inputs(tmp_path, dataset, matrix_gzip)

    out_dir = tmp_path / "cli_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "raschlab",
        "analyze",
        "--con",
        str(con_path),
        "--data",
        str(data_path),
        "--out",
        str(out_dir),
        "--format",
        "both",
    ]
    subprocess.run(cmd, check=True)

    engine_wb_path = out_dir / "analysis_report.xlsx"
    assert engine_wb_path.is_file(), f"Engine workbook not found at {engine_wb_path}"
    engine_wb = openpyxl.load_workbook(engine_wb_path, data_only=False)

    engine_sheet_map = {
        "butir": "15.1",
        "opsi": "15.3",
        "responden": "person",
        "ringkasan": "summary",
        "wright": "wright_measure",
        "frekuensi": "wright_frequency",
    }

    stored_keys = ["butir", "opsi", "responden", "ringkasan", "wright", "frekuensi"]
    for key in stored_keys:
        engine_sheet_name = engine_sheet_map[key]
        if engine_sheet_name not in engine_wb.sheetnames:
            pytest.fail(
                f"Engine workbook missing sheet '{engine_sheet_name}' for key '{key}'. "
                f"Workbook contains sheets: {engine_wb.sheetnames}"
            )
        engine_ws = engine_wb[engine_sheet_name]

        csv_path = out_dir / TABLE_KEYS[key]
        assert csv_path.is_file(), f"CLI CSV output file not found: {csv_path}"
        with open(csv_path, "r", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        numeric = TABLE_NUMERIC.get(key)
        xlsx_bytes = build_xlsx(SHEET_TITLES[key], rows, HEADER_ROWS[key], numeric)
        our_wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=False)
        our_ws = our_wb[SHEET_TITLES[key]]

        if key == "frekuensi":
            for r in range(1, our_ws.max_row + 1):
                r_idx = r - 1
                for c in range(1, our_ws.max_column + 1):
                    c_idx = c - 1
                    cell_our = our_ws.cell(row=r, column=c)
                    raw_text = rows[r_idx][c_idx] if r_idx < len(rows) and c_idx < len(rows[r_idx]) else ""
                    coord = f"R{r}C{c} ({cell_our.coordinate})"

                    if cell_our.value is None:
                        assert raw_text == "", (
                            f"[{key}] expected empty field at {coord}, got {raw_text!r}"
                        )
                    else:
                        assert (str(cell_our.value) == raw_text) or (
                            isinstance(cell_our.value, (int, float)) and float(raw_text) == float(cell_our.value)
                        ), (
                            f"[{key}] cell value mismatch at {coord}: {cell_our.value!r} != {raw_text!r}"
                        )

                    if r > HEADER_ROWS[key]:
                        if c_idx in (0, 1, 2, 5):
                            assert isinstance(cell_our.value, (int, float)), (
                                f"[{key}] expected number at {coord}, got {type(cell_our.value)}"
                            )
                        else:
                            assert cell_our.value is None or isinstance(cell_our.value, str), (
                                f"[{key}] expected str or None at {coord}, got {type(cell_our.value)}"
                            )
                    else:
                        assert cell_our.value is None or isinstance(cell_our.value, str), (
                            f"[{key}] header expected str or None at {coord}, got {type(cell_our.value)}"
                        )
            continue

        assert our_ws.max_row == engine_ws.max_row, (
            f"[{key}] row count mismatch: {our_ws.max_row} != {engine_ws.max_row}"
        )
        assert our_ws.max_column == engine_ws.max_column, (
            f"[{key}] column count mismatch: {our_ws.max_column} != {engine_ws.max_column}"
        )

        for r in range(1, our_ws.max_row + 1):
            for c in range(1, our_ws.max_column + 1):
                cell_our = our_ws.cell(row=r, column=c)
                cell_eng = engine_ws.cell(row=r, column=c)
                coord = f"R{r}C{c} ({cell_our.coordinate})"

                assert cell_our.value == cell_eng.value, (
                    f"[{key}] cell value mismatch at {coord}: {cell_our.value!r} != {cell_eng.value!r}"
                )
                assert type(cell_our.value) is type(cell_eng.value), (
                    f"[{key}] cell type mismatch at {coord}: {type(cell_our.value)} != {type(cell_eng.value)}"
                )
                assert cell_our.number_format == cell_eng.number_format, (
                    f"[{key}] cell number_format mismatch at {coord}: {cell_our.number_format!r} != {cell_eng.number_format!r}"
                )


def test_all_rows_not_the_500_row_page(client):
    header_rows_count = HEADER_ROWS["responden"]
    data_rows = [
        [str(i), "15", "30", "0.50", "0.20", "1.00", "0.0", "1.00", "0.0", "0.45", "0.40", "70.0", "65.0", f"Person_{i:03d}"]
        for i in range(1, 701)
    ]
    all_person_rows = [_PERSON_HEADER_ROW0, _PERSON_HEADER_ROW1] + data_rows
    person_csv = _csv(all_person_rows)

    csv_lines = [line for line in person_csv.split("\r\n") if line.strip()]
    csv_data_count = len(csv_lines) - header_rows_count
    assert csv_data_count == 700, f"CSV fixture data row count is {csv_data_count}, expected 700"

    user_id, token = _create_user_with_token(client, email="user_700@example.test")
    client.cookies.set(COOKIE_NAME, token)
    files = {"person_table.csv": person_csv}
    analysis_id = _seed_done(user_id=user_id, filename="data_700.csv", files=files, n_persons=700)

    resp = client.get(f"/analyses/{analysis_id}/export?table=responden")
    assert resp.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(resp.content), data_only=False)
    ws = wb["responden"]

    assert ws.max_row > 500, f"Expected more than 500 rows, got {ws.max_row}"
    assert ws.max_row == 700 + header_rows_count, (
        f"Expected max_row to equal 700 + {header_rows_count}, got {ws.max_row}"
    )


def test_guard_matrix(client, monkeypatch):
    user1_id, token1 = _create_user_with_token(client, email="guard1@example.test")
    client.cookies.set(COOKIE_NAME, token1)

    item_rows = [
        _ITEM_HEADER_ROW0,
        _ITEM_HEADER_ROW1,
        ["1", "10", "20", "0.10", "0.20", "1.00", "0.0", "1.00", "0.0", "0.50", "0.45", "75.0", "70.0", "Item1"],
    ]
    files = {"item_table_15.1.csv": _csv(item_rows)}
    analysis_id = _seed_done(user_id=user1_id, filename="data_guard.csv", files=files)

    # 1. Anonymous request returns 404
    client.cookies.clear()
    resp_anon = client.get(f"/analyses/{analysis_id}/export?table=butir")
    assert resp_anon.status_code == 404

    # Restore session for user1
    client.cookies.set(COOKIE_NAME, token1)

    # 2. Gate closed by monkeypatching app.auth._gate_closed to return True returns 404
    monkeypatch.setattr("app.auth._gate_closed", lambda: True)
    monkeypatch.setattr("app.export._gate_closed", lambda: True)
    resp_gate = client.get(f"/analyses/{analysis_id}/export?table=butir")
    assert resp_gate.status_code == 404
    monkeypatch.setattr("app.auth._gate_closed", lambda: False)
    monkeypatch.setattr("app.export._gate_closed", lambda: False)

    # 3. An analysis owned by another user returns 404
    user2_id, token2 = _create_user_with_token(client, email="guard2_other@example.test")
    client.cookies.set(COOKIE_NAME, token2)
    resp_foreign = client.get(f"/analyses/{analysis_id}/export?table=butir")
    assert resp_foreign.status_code == 404

    # Switch back to user1
    client.cookies.set(COOKIE_NAME, token1)

    # 4. A seeded analysis with status "running" returns 303 with location /analyses/{id}
    running_id = _seed_done(user_id=user1_id, filename="data_running.csv", files=files, status="running")
    resp_running = client.get(f"/analyses/{running_id}/export?table=butir", follow_redirects=False)
    assert resp_running.status_code == 303
    assert resp_running.headers["location"] == f"/analyses/{running_id}"

    # 5. table=bogus returns 404
    resp_bogus = client.get(f"/analyses/{analysis_id}/export?table=bogus")
    assert resp_bogus.status_code == 404

    # 6. A seed whose files dict omits item_table_15.1.csv and is asked for table=butir returns 404
    omit_id = _seed_done(user_id=user1_id, filename="data_omit.csv", files={})
    resp_omit = client.get(f"/analyses/{omit_id}/export?table=butir")
    assert resp_omit.status_code == 404


def test_identifier_columns_stay_text():
    rows = [
        ["ENTRY", "MEASURE", "PERSON"],
        ["NUMBER", "MEASURE", "PERSON"],
        ["1", "-1.25", "007"],
        ["2", "0.50", "3251501001500027"],
    ]
    xlsx_bytes = build_xlsx("test_sheet", rows, header_rows=2, numeric=None)
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=False)
    ws = wb["test_sheet"]

    p1 = ws.cell(row=3, column=3)
    p2 = ws.cell(row=4, column=3)
    assert isinstance(p1.value, str) and p1.value == "007"
    assert isinstance(p2.value, str) and p2.value == "3251501001500027"

    m1 = ws.cell(row=3, column=2)
    m2 = ws.cell(row=4, column=2)
    assert isinstance(m1.value, float) and m1.value == -1.25
    assert m1.number_format == "0.00"
    assert isinstance(m2.value, float) and m2.value == 0.50
    assert m2.number_format == "0.00"

    e1 = ws.cell(row=3, column=1)
    e2 = ws.cell(row=4, column=1)
    assert isinstance(e1.value, int) and e1.value == 1
    assert e1.number_format == "0"
    assert isinstance(e2.value, int) and e2.value == 2
    assert e2.number_format == "0"


def test_response_headers(client):
    user_id, token = _create_user_with_token(client, email="headers@example.test")
    client.cookies.set(COOKIE_NAME, token)
    files = {
        "person_table.csv": _csv([
            _PERSON_HEADER_ROW0,
            _PERSON_HEADER_ROW1,
            ["1", "10", "12", "0.50", "0.20", "1.00", "0.0", "1.00", "0.0", "0.40", "0.35", "70.0", "65.0", "Person_1"],
        ])
    }
    analysis_id = _seed_done(user_id=user_id, filename="data_headers.csv", files=files, n_persons=1)

    resp = client.get(f"/analyses/{analysis_id}/export?table=responden")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == XLSX_MEDIA_TYPE

    expected_filename = f"raschlab-{analysis_id}-responden.xlsx"
    cd = resp.headers["content-disposition"]
    assert f'filename="{expected_filename}"' in cd
    assert f"filename*=UTF-8''{expected_filename}" in cd
    assert resp.headers["cache-control"] == "no-store"


def test_bandingkan_matches_compare_pairs(client):
    user_id, token = _create_user_with_token(client, email="compare@example.test")
    client.cookies.set(COOKIE_NAME, token)

    items_from = [
        _ITEM_HEADER_ROW0,
        _ITEM_HEADER_ROW1,
        ["1", "15", "30", "0.10", "0.20", "1.00", "0.0", "1.00", "0.0", "0.50", "0.45", "75.0", "70.0", "Item1"],
        ["2", "18", "30", "-0.30", "0.21", "0.98", "-0.1", "0.95", "-0.2", "0.52", "0.46", "80.0", "72.0", "Item2"],
    ]
    items_to = [
        _ITEM_HEADER_ROW0,
        _ITEM_HEADER_ROW1,
        ["1", "14", "30", "0.25", "0.20", "1.02", "0.1", "1.01", "0.1", "0.48", "0.45", "72.0", "70.0", "Item1"],
        ["2", "20", "30", "-0.15", "0.22", "0.96", "-0.2", "0.92", "-0.3", "0.55", "0.46", "82.0", "72.0", "Item2"],
    ]
    id1 = _seed_done(user_id=user_id, filename="data_cmp1.csv", files={"item_table_15.1.csv": _csv(items_from)})
    id2 = _seed_done(user_id=user_id, filename="data_cmp2.csv", files={"item_table_15.1.csv": _csv(items_to)})

    resp = client.get(f"/analyses/{id1}/export?table=bandingkan&from={id1}&to={id2}")
    assert resp.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(resp.content), data_only=False)
    ws = wb["bandingkan"]

    row1 = [cell.value for cell in ws[1]]
    assert row1 == COMPARE_HEADER

    pairs = build_compare_pairs(items_from, items_to)["pairs"]
    assert len(pairs) > 0
    assert ws.max_row == len(pairs) + 1

    for idx, pair in enumerate(pairs, start=2):
        row_cells = [cell.value for cell in ws[idx]]
        assert int(row_cells[0]) == int(pair[0])
        assert str(row_cells[1]) == str(pair[1])
        assert float(row_cells[2]) == float(pair[2])
        assert float(row_cells[3]) == float(pair[3])
        assert float(row_cells[4]) == float(pair[4])


def test_export_caps_and_rate_limit(client, monkeypatch):
    user_id, token = _create_user_with_token(client, email="ratelimit@example.test")
    client.cookies.set(COOKIE_NAME, token)

    person_rows = [
        _PERSON_HEADER_ROW0,
        _PERSON_HEADER_ROW1,
        ["1", "10", "12", "0.50", "0.20", "1.00", "0.0", "1.00", "0.0", "0.40", "0.35", "70.0", "65.0", "Person_1"],
        ["2", "11", "12", "0.60", "0.21", "0.95", "-0.1", "0.98", "-0.1", "0.42", "0.36", "75.0", "68.0", "Person_2"],
    ]
    real_rows = len(person_rows)
    real_cells = sum(len(r) for r in person_rows)
    files = {"person_table.csv": _csv(person_rows)}
    analysis_id = _seed_done(user_id=user_id, filename="data_cap.csv", files=files, n_persons=2)

    # (a) monkeypatch app.export.EXPORT_MAX_CELLS to a small number such as 10
    monkeypatch.setattr("app.export.EXPORT_MAX_CELLS", 10)
    resp_413 = client.get(f"/analyses/{analysis_id}/export?table=responden")
    assert resp_413.status_code == 413
    assert str(real_rows) in resp_413.text
    assert str(real_cells) in resp_413.text

    # (b) with the cap restored, call the route 31 times for one seeded analysis
    monkeypatch.setattr("app.export.EXPORT_MAX_CELLS", EXPORT_MAX_CELLS)
    _COUNTS.clear()

    resp_31 = None
    for i in range(31):
        resp = client.get(f"/analyses/{analysis_id}/export?table=responden")
        if i < 30:
            assert resp.status_code == 200, f"Call {i+1} failed with status {resp.status_code}"
        else:
            resp_31 = resp

    assert resp_31 is not None
    assert resp_31.status_code == 429
    retry_after = resp_31.headers.get("retry-after") or resp_31.headers.get("Retry-After")
    assert retry_after is not None, "Missing Retry-After header on 429 response"
    retry_int = int(retry_after)
    assert retry_int >= 0


def test_export_row_cap(client, monkeypatch):
    user_id, token = _create_user_with_token(client, email="rowcap@example.test")
    client.cookies.set(COOKIE_NAME, token)

    person_rows = [
        ["1", "10", "12", "0.50", "0.20", "1.00", "0.0", "1.00", "0.0", "0.40", "0.35", "70.0", "65.0", f"Person_{i}"]
        for i in range(1, 6)
    ]
    real_rows = len(person_rows)
    real_cells = sum(len(r) for r in person_rows)
    files = {"person_table.csv": _csv(person_rows)}
    analysis_id = _seed_done(user_id=user_id, filename="data_row_cap.csv", files=files, n_persons=5)

    monkeypatch.setattr("app.export.EXPORT_MAX_ROWS", 3)
    resp_413 = client.get(f"/analyses/{analysis_id}/export?table=responden")
    assert resp_413.status_code == 413
    assert str(real_rows) in resp_413.text
    assert "5" in resp_413.text
    assert str(real_cells) in resp_413.text

    with pytest.raises(Exception):
        openpyxl.load_workbook(io.BytesIO(resp_413.content))

    monkeypatch.setattr("app.export.EXPORT_MAX_ROWS", EXPORT_MAX_ROWS)
    resp_200 = client.get(f"/analyses/{analysis_id}/export?table=responden")
    assert resp_200.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp_200.content))
    assert wb is not None


def test_export_frekuensi_route(client):
    user_id, token = _create_user_with_token(client, email="frekuensi@example.test")
    client.cookies.set(COOKIE_NAME, token)

    freq_csv = (
        "MEASURE,NR_PERSON,NR_PERSON_PRESENT,PERSON_HIST,PERSON_FREQ_HIST,NR_ITEM,ITEMS,ITEM_HIST,PERSON_ENTRIES,ITEM_ENTRIES\r\n"
        ",,,,,,,,PERSON_ENTRIES,ITEM_ENTRIES\r\n"
        "1.75,0,0,,,0,,,,\r\n"
        "1.5,84,84,####################################################################################,###############,0,,,1 3 5 10 12 17 19 24 26 28 33 35 40 42 47 49 56 58 63 65 70 72 79 81 86 88 93 95 102 104 109 111 116 118 125 127 132 134 139 141 146 148 150 155 157 162 164 169 171 173 178 180 185 187 192 194 201 203 208 210 215 217 224 226 231 233 238 240 247 249 254 256 261 263 270 272 277 279 284 286 291 293 295 300,\r\n"
        "1.25,216,216,########################################################################################################################################################################################################################,###############,0,,,2 4 6 7 8 9 11 13 14 15 16 18 20 21 22 23 25 27 29 30 31 32 34 36 37 38 39 41 43 44 45 46 48 50 51 52 53 54 55 57 59 60 61 62 64 66 67 68 69 71 73 74 75 76 77 78 80 82 83 84 85 87 89 90 91 92 94 96 97 98 99 100 101 103 105 106 107 108 110 112 113 114 115 117 119 120 121 122 123 124 126 128 129 130 131 133 135 136 137 138 140 142 143 144 145 147 149 151 152 153 154 156 158 159 160 161 163 165 166 167 168 170 172 174 175 176 177 179 181 182 183 184 186 188 189 190 191 193 195 196 197 198 199 200 202 204 205 206 207 209 211 212 213 214 216 218 219 220 221 222 223 225 227 228 229 230 232 234 235 236 237 239 241 242 243 244 245 246 248 250 251 252 253 255 257 258 259 260 262 264 265 266 267 268 269 271 273 274 275 276 278 280 281 282 283 285 287 288 289 290 292 294 296 297 298 299,\r\n"
        "1.0,0,0,,,0,,,,\r\n"
        "0.75,0,0,,,0,,,,\r\n"
        "0.5,0,0,,,0,,,,\r\n"
        "0.25,0,0,,,0,,,,\r\n"
        "0.0,0,0,,,40,I01 I02 I03 I04 I05 I06 I07 I08 I09 I10 I11 I12 I13 I14 I15 I16 I17 I18 I19 I20 I21 I22 I23 I24 I25 I26 I27 I28 I29 I30 I31 I32 I33 I34 I35 I36 I37 I38 I39 I40,##################################,,1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40\r\n"
        "-0.25,0,0,,,0,,,,\r\n"
    )
    files = {"wright_map_frequency.csv": freq_csv}
    analysis_id = _seed_done(user_id=user_id, filename="data_frekuensi.csv", files=files)

    resp = client.get(f"/analyses/{analysis_id}/export?table=frekuensi")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == XLSX_MEDIA_TYPE

    wb = openpyxl.load_workbook(io.BytesIO(resp.content), data_only=False)
    assert wb.sheetnames == ["frekuensi"]
    ws = wb["frekuensi"]

    csv_rows = list(csv.reader(io.StringIO(freq_csv.strip())))
    assert ws.max_row == len(csv_rows)

    nr_person_cell = ws.cell(row=10, column=2)
    items_cell = ws.cell(row=10, column=7)
    assert isinstance(nr_person_cell.value, int)
    assert isinstance(items_cell.value, str)

