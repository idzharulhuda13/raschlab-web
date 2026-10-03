"""Integration tests for one reading surface (single surface explorer).

Covers:
- Real row counts rendered on new tabs: opsi, subsubtes, tabulasi.
- XLSX downloads for new tabs: opsi, subsubtes, tabulasi, tabulasi_butir.
- Tabulasi per-item table search, sorting, and pagination.
- Honest notes and 404s on analyses seeded without optional table files.
- Absence of back-links to the retired result page on the explorer dashboard.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.export import XLSX_MEDIA_TYPE
from tests.test_explorer_routes import (
    _ITEM_HEADER_ROW0,
    _ITEM_HEADER_ROW1,
    _PERSON_HEADER_ROW0,
    _PERSON_HEADER_ROW1,
    _WRIGHT_HEADER_ROW0,
    _WRIGHT_HEADER_ROW1,
    _create_authenticated_user,
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

_TABULASI_HEADER = [
    "SUBTES",
    "SUBSUBTES",
    "KESUKARAN",
    "TINGGI",
    "NOMOR_TINGGI",
    "RENDAH",
    "NOMOR_RENDAH",
    "JUMLAH",
]

_TABULASI_ITEM_HEADER = [
    "SUBTES",
    "SUBSUBTES",
    "ENTRY",
    "ITEM",
    "KESUKARAN",
    "DAYA_BEDA",
    "DATA_PCT",
    "PTMA_CORR",
]


def _make_option_table() -> list[list[str]]:
    header0 = [
        "ENTRY", "TOTAL", "COUNT", "SCORE", "DATA", "WEIGHT",
        "MEASURE", "S.E.", "IN.MNSQ", "OUT.MNSQ", "PTMEA", "ITEM",
    ]
    header1 = ["", "", "", "", "", "", "", "", "", "", "", ""]
    rows = [header0, header1]
    for i in range(147):
        rows.append([
            "1", "10", "30", "1", "A", "1.0",
            "0.0", "0.2", "1.0", "1.0", "0.4", f"Item{i+1}",
        ])
    return rows


def _make_subsubtes_table() -> list[list[str]]:
    rows = [_SUBSUBTES_HEADER]
    for i in range(7):
        rows.append([
            f"Subsubtes {i+1}", "10", "0", "10",
            "0.10", "0.05", "1.00", "1.20", "0",
        ])
    return rows


def _make_tabulasi_summary_table() -> list[list[str]]:
    rows = [_TABULASI_HEADER]
    for i in range(19):
        rows.append([
            f"Subtes {i+1}", f"Subsubtes {i+1}", "sedang",
            "5", "1", "2", "2", "7",
        ])
    return rows


def _make_tabulasi_item_table(n: int = 370, target_label: str | None = None) -> list[list[str]]:
    rows = [_TABULASI_ITEM_HEADER]
    for i in range(n):
        label = target_label if (target_label and i == 0) else f"Item_{i+1:04d}"
        rows.append([
            "Subtes 1", "Subsubtes 1", str(i + 1), label,
            "sedang", "tinggi", "50", "0.30",
        ])
    return rows


def _build_base_files() -> dict[str, str]:
    item_rows = (
        [_ITEM_HEADER_ROW0, _ITEM_HEADER_ROW1]
        + [_make_item_row(i + 1, f"{(i - 6) * 0.25:.2f}", f"Label{i+1}") for i in range(12)]
    )
    person_rows = [
        _PERSON_HEADER_ROW0,
        _PERSON_HEADER_ROW1,
    ] + [
        [
            str(i + 1), "8", "12", f"{(i - 15) * 0.1:.2f}",
            "0.50", "1.20", "0.80", "1.15", "0.60", "0.48", "0.50",
            "70.0", "68.0", f"Person{i+1}",
        ]
        for i in range(30)
    ]
    wright_rows = [
        _WRIGHT_HEADER_ROW0,
        _WRIGHT_HEADER_ROW1,
        ["0.00", "30", "******************************", "12", "1-12", "************", "1-30", "1-12"],
    ]
    summary_rows = [
        ["SECTION", "STATISTIC", "VALUE"],
        ["", "", ""],
        ["ITEM", "COUNT", "12"],
        ["ITEM", "MEASURE MEAN", "0.00"],
        ["PERSON", "COUNT", "30"],
        ["PERSON", "MEASURE MEAN", "0.15"],
        ["PERSON", "EXTREME INCL COUNT", "30"],
    ]
    return {
        "item_table_15.1.csv": _csv(item_rows),
        "person_table.csv": _csv(person_rows),
        "summary_table.csv": _csv(summary_rows),
        "wright_map_measure.csv": _csv(wright_rows),
        "wright_map_frequency.csv": _csv(wright_rows),
    }


def _build_all_tables_files() -> dict[str, str]:
    files = _build_base_files()
    files["option_table_15.3.csv"] = _csv(_make_option_table())
    files["subsubtes_summary.csv"] = _csv(_make_subsubtes_table())
    files["tabulasi_summary.csv"] = _csv(_make_tabulasi_summary_table())
    files["tabulasi_item.csv"] = _csv(_make_tabulasi_item_table(370))
    return files


def test_new_tabs_render_real_row_counts(client: TestClient) -> None:
    user_id = _create_authenticated_user(client)
    files = _build_all_tables_files()
    aid = _seed_done(user_id, "all_tables.csv", files)

    resp_opsi = client.get(f"/analyses/{aid}/explore?view=opsi")
    assert resp_opsi.status_code == 200
    opsi_section = resp_opsi.text[resp_opsi.text.index('id="opsi"'):]
    opsi_section = opsi_section[:opsi_section.index("</section>")]
    assert opsi_section.count("<tr>") == 149
    assert "Tabel Opsi dan Distraktor (15.3)" in resp_opsi.text

    resp_sub = client.get(f"/analyses/{aid}/explore?view=subsubtes")
    assert resp_sub.status_code == 200
    sub_section = resp_sub.text[resp_sub.text.index('id="subsubtes"'):]
    sub_section = sub_section[:sub_section.index("</section>")]
    assert sub_section.count("<tr>") == 8
    assert "Ringkasan Sub-Subtes" in resp_sub.text

    resp_tab = client.get(f"/analyses/{aid}/explore?view=tabulasi")
    assert resp_tab.status_code == 200
    tab_section = resp_tab.text[resp_tab.text.index('id="tabulasi"'):]
    tab_section = tab_section[:tab_section.index("</section>")]
    assert tab_section.count("<tr") == 391
    assert "Ringkasan Tabulasi" in resp_tab.text
    assert "Tabulasi per Butir" in resp_tab.text


def test_new_tab_downloads_answer(client: TestClient) -> None:
    user_id = _create_authenticated_user(client)
    files = _build_all_tables_files()
    aid = _seed_done(user_id, "downloads.csv", files)

    for table in ("opsi", "subsubtes", "tabulasi", "tabulasi_butir"):
        resp = client.get(f"/analyses/{aid}/export?table={table}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == XLSX_MEDIA_TYPE


def test_tabulasi_per_item_search_sort_and_pager(client: TestClient) -> None:
    user_id = _create_authenticated_user(client)
    target_label = "BUTIR_TARGET_520"
    tab_item_rows = _make_tabulasi_item_table(520, target_label=target_label)

    files = _build_base_files()
    files["tabulasi_summary.csv"] = _csv(_make_tabulasi_summary_table())
    files["tabulasi_item.csv"] = _csv(tab_item_rows)
    aid = _seed_done(user_id, "tab520.csv", files)

    resp = client.get(f"/analyses/{aid}/explore?view=tabulasi")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="tab-search"' in html
    assert html.count('data-explorer-table="1"') == 1
    assert 'aria-sort="none"' in html
    assert 'class="th-sort"' in html
    assert 'data-sort="text"' in html
    assert 'data-sort="number"' in html

    resp_p2 = client.get(f"/analyses/{aid}/explore?view=tabulasi&page_tab=2")
    assert resp_p2.status_code == 200
    assert "Halaman 2 dari 2 (520 baris)" in resp_p2.text
    assert "Menampilkan 20 dari 520 baris." in resp_p2.text

    resp_q = client.get(f"/analyses/{aid}/explore?view=tabulasi&q_tab={target_label}")
    assert resp_q.status_code == 200
    assert 'id="tabulasi-count"' in resp_q.text
    count_line = resp_q.text.split('id="tabulasi-count"')[1].split("</p>")[0]
    assert "Menampilkan 1 dari 1 baris." in count_line
    assert "520" not in count_line

    resp_nomatch = client.get(f"/analyses/{aid}/explore?view=tabulasi&q_tab=zzz_nomatch")
    assert resp_nomatch.status_code == 200
    html_nomatch = resp_nomatch.text
    assert 'id="tabulasi-empty"' in html_nomatch
    assert "Tidak ada baris yang cocok dengan pencarian." in html_nomatch
    assert "Hapus pencarian" in html_nomatch
    assert f"/analyses/{aid}/explore?view=tabulasi" in html_nomatch


def test_old_run_keeps_honest_notes_and_404s(client: TestClient) -> None:
    user_id = _create_authenticated_user(client)
    files = _build_base_files()
    aid = _seed_done(user_id, "old_run.csv", files)

    resp_tab = client.get(f"/analyses/{aid}/explore?view=tabulasi")
    assert resp_tab.status_code == 200
    assert (
        "Analisis ini dijalankan sebelum mesin menulis ringkasan tabulasi, "
        "jadi rinciannya belum tersimpan. Jalankan ulang analisis untuk melihatnya."
    ) in resp_tab.text
    assert "?table=tabulasi" not in resp_tab.text

    resp_sub = client.get(f"/analyses/{aid}/explore?view=subsubtes")
    assert resp_sub.status_code == 200
    assert (
        "Analisis ini dijalankan sebelum mesin menulis ringkasan sub-subtes, "
        "jadi rinciannya belum tersimpan. Jalankan ulang analisis untuk melihatnya."
    ) in resp_sub.text
    assert "?table=subsubtes" not in resp_sub.text

    for table in ("tabulasi", "tabulasi_butir", "subsubtes"):
        resp_exp = client.get(f"/analyses/{aid}/export?table={table}")
        assert resp_exp.status_code == 404


def test_dashboard_has_no_result_page_back_links(client: TestClient) -> None:
    user_id = _create_authenticated_user(client)
    files = _build_base_files()
    aid = _seed_done(user_id, "no_back_links.csv", files)

    resp = client.get(f"/analyses/{aid}/explore")
    assert resp.status_code == 200
    assert "Kembali ke Hasil Analisis" not in resp.text
    assert f'href="/analyses/{aid}"' not in resp.text
