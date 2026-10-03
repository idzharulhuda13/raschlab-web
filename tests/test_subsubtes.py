"""Tests for F18: Ringkasan Sub-Subtes band and subsubtes_summary.csv.

Covers six checks:
1. Engine run stores subsubtes_summary.csv and renders to the page.
2. Band renders stored summary rows with columns, formatting, and export link.
3. Band notes old runs without the summary file.
4. Band notes header-only files where no sub-subtest codes are present.
5. Band sits between Rekap Responden and Tabel Butir (15.1).
6. Unduh semua copy carries no sheet count on result and explore pages.
"""

import csv
import gzip
import io
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AnalysisFile
from tests.test_analysis_routes import FIXTURES_DIR, _create_authenticated_user
from tests.test_explorer_routes import (
    _ITEM_HEADER_ROW0,
    _ITEM_HEADER_ROW1,
    _PERSON_HEADER_ROW0,
    _PERSON_HEADER_ROW1,
    _WRIGHT_HEADER_ROW0,
    _WRIGHT_HEADER_ROW1,
    _csv,
    _make_item_row,
    _seed_done,
)

_SUBSUBTES_HEADER = [
    "SUBSUBTES",
    "ITEMS",
    "ANCHOR_ITEMS",
    "NEW_ITEMS",
    "MEAN_MEASURE",
    "S.SD_MEASURE",
    "MEAN_INFIT",
    "MAX_INFIT",
    "MISFIT_ITEMS",
]
_SUBSUBTES_ROWS = [
    ["Deretan Bilangan", "20", "0", "20", "0.42", "0.15", "1.02", "1.60", "1"],
    ["Logis", "20", "20", "0", "-0.50", "0.10", "0.95", "0.98", "0"],
]
_OLD_RUN_NOTE = (
    "Analisis ini dijalankan sebelum mesin menulis ringkasan sub-subtes, "
    "jadi rinciannya belum tersimpan. Jalankan ulang analisis untuk melihatnya."
)
_HEADER_ONLY_NOTE = (
    "Data ini tidak memuat kode sub-subtes pada label butir, jadi ringkasan per "
    "sub-subtes kosong. Analisis tetap lengkap; tabel ini terisi otomatis bila "
    "label butir memuat kode sub-subtes."
)


def _band_section(html: str) -> str:
    start = html.index('id="subsubtes"')
    end = html.index("</section>", start)
    return html[start:end]


def _stored_files(with_subsubtes: str | None) -> dict[str, str]:
    files = {
        "item_table_15.1.csv": _csv([_ITEM_HEADER_ROW0, _ITEM_HEADER_ROW1, _make_item_row(1, "0.00", "I1")]),
        "option_table_15.3.csv": _csv([["ENTRY", "DATA"], ["", ""]]),
        "person_table.csv": _csv([_PERSON_HEADER_ROW0, _PERSON_HEADER_ROW1]),
        "summary_table.csv": _csv([["SECTION", "STATISTIC", "VALUE"], ["PERSON", "COUNT", "30"]]),
        "wright_map_measure.csv": _csv([_WRIGHT_HEADER_ROW0, _WRIGHT_HEADER_ROW1]),
        "wright_map_frequency.csv": _csv([_WRIGHT_HEADER_ROW0, _WRIGHT_HEADER_ROW1]),
    }
    if with_subsubtes is not None:
        files["subsubtes_summary.csv"] = with_subsubtes
    return files


def _seed_run(client: TestClient, email: str, with_subsubtes: str | None) -> int:
    user_id = _create_authenticated_user(client, email=email)
    return _seed_done(user_id, "tbs_ringkas.csv", _stored_files(with_subsubtes))


def test_engine_run_stores_subsubtes_summary(client: TestClient) -> None:
    raw = (FIXTURES_DIR / "sample_300x40.csv").read_bytes().decode()
    lines = raw.splitlines()
    header_cells = lines[0].split(",")

    new_header = [header_cells[0]]
    for i in range(1, 21):
        new_header.append(f"{i:02d}tbskd26a{i:02d}")
    for i in range(21, 41):
        new_header.append(f"{i:02d}tbspl25a{i:02d}")
    new_text = "\n".join([",".join(new_header)] + lines[1:]) + "\n"

    _create_authenticated_user(client, email="subsubtes_engine@example.test")
    resp = client.post(
        "/datasets",
        files={"data": ("tbs_sintetis.csv", new_text.encode(), "text/csv")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    dataset_id = int(location.split("/")[-1].split("?")[0])

    resp = client.post(
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
    assert resp.status_code == 303

    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={"misfit": "1.50", "mode": "compat", "digits": "2", "person_order": "misfit"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    analysis_id = int(location.split("/")[-1].split("?")[0])

    with SessionLocal() as db:
        row = db.scalar(
            select(AnalysisFile).where(
                AnalysisFile.analysis_id == analysis_id,
                AnalysisFile.filename == "subsubtes_summary.csv",
            )
        )
    assert row is not None
    text = gzip.decompress(row.content_gzip).decode()
    parsed = list(csv.reader(io.StringIO(text)))

    assert parsed[0] == _SUBSUBTES_HEADER
    assert len(parsed) == 3
    assert parsed[1][:4] == ["Deretan Bilangan", "20", "0", "20"]
    assert parsed[2][:4] == ["Logis", "20", "20", "0"]
    assert all(float(parsed[1][i]) == float(parsed[1][i]) for i in (4, 5, 6, 7))

    resp = client.get(f"/analyses/{analysis_id}/explore?view=subsubtes")
    section = _band_section(resp.text)
    assert "Deretan Bilangan" in section
    assert "Logis" in section


def test_band_renders_stored_summary_rows(client: TestClient) -> None:
    analysis_id = _seed_run(
        client,
        email="rendered_rows@example.test",
        with_subsubtes=_csv([_SUBSUBTES_HEADER] + _SUBSUBTES_ROWS),
    )
    resp = client.get(f"/analyses/{analysis_id}/explore?view=subsubtes")
    section = _band_section(resp.text)

    assert "Ringkasan Sub-Subtes" in section
    assert "Ringkasan 2 sub-subtes, sesuai urutan kemunculan pada butir." in section

    last_idx = -1
    for col in _SUBSUBTES_HEADER:
        idx = section.index(col)
        assert idx > last_idx
        last_idx = idx

    assert "0,42" in section
    assert "-0,50" in section
    assert f'href="/analyses/{analysis_id}/export?table=subsubtes"' in section
    assert 'aria-label="Unduh Excel ringkasan sub-subtes"' in section
    assert "\u2014" not in resp.text


def test_band_notes_an_old_run_without_the_file(client: TestClient) -> None:
    analysis_id = _seed_run(client, email="old_run@example.test", with_subsubtes=None)
    resp = client.get(f"/analyses/{analysis_id}/explore?view=subsubtes")
    section = _band_section(resp.text)

    assert _OLD_RUN_NOTE in section
    assert "<table" not in section
    assert "?table=subsubtes" not in section


def test_band_header_only_means_no_subsubtes_in_this_data(client: TestClient) -> None:
    analysis_id = _seed_run(
        client,
        email="header_only@example.test",
        with_subsubtes=_csv([_SUBSUBTES_HEADER]),
    )
    resp = client.get(f"/analyses/{analysis_id}/explore?view=subsubtes")
    section = _band_section(resp.text)

    assert _HEADER_ONLY_NOTE in section
    assert _OLD_RUN_NOTE not in section
    assert "<table" not in section
    assert "?table=subsubtes" in section


def test_band_sits_between_rekap_and_tabel_butir(client: TestClient) -> None:
    analysis_id = _seed_run(
        client,
        email="band_order@example.test",
        with_subsubtes=_csv([_SUBSUBTES_HEADER] + _SUBSUBTES_ROWS),
    )
    resp = client.get(f"/analyses/{analysis_id}/explore")
    text = resp.text

    assert text.index('id="tab-ringkasan"') < text.index('id="tab-subsubtes"')


def test_unduh_semua_copy_carries_no_sheet_count(client: TestClient) -> None:
    analysis_id = _seed_run(
        client,
        email="unduh_semua@example.test",
        with_subsubtes=_csv([_SUBSUBTES_HEADER] + _SUBSUBTES_ROWS),
    )
    for url in (f"/analyses/{analysis_id}", f"/analyses/{analysis_id}/explore?view=wright"):
        resp = client.get(url)
        text = resp.text
        assert "6 sheet" not in text
        assert "Unduh semua (satu berkas, semua sheet)" in text
        assert "satu berkas, semua sheet" in text
